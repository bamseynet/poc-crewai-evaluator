"""The evaluator-optimizer loop, expressed as a CrewAI Flow.

    begin ──▶ write_draft ──▶ evaluate_draft ──▶ route_on_scores ── "stop" ──▶ finish
                   ▲                                    │
                   └──────────── "revise" ──────────────┘

Read this file top to bottom to see the pattern: the writer crew optimizes, the evaluator crew
judges, and plain Python decides, using the scores, whether to go round again. No model ever
decides when the loop ends.
"""

import logging
import re
import threading
from collections.abc import Sequence
from typing import Final, Literal

from crewai.flow.flow import Flow, listen, or_, router, start
from crewai.tasks.task_output import TaskOutput
from pydantic import Field, InstanceOf, PrivateAttr

from policy_drafter.crews import build_evaluator_crew, build_writer_crew, kickoff
from policy_drafter.events import (
    DraftCompleted,
    EvaluationCompleted,
    EvaluationRetried,
    EventSink,
    IterationStarted,
    Phase,
    PhaseStarted,
    ProgressEvent,
    ResearchCompleted,
    RunFinished,
    RunStarted,
    TokenEmitted,
    ignore_event,
)
from policy_drafter.llm import LLMs
from policy_drafter.models import DraftingState, IterationRecord, RunConfig, StopReason
from policy_drafter.prompts import DRAFTER_ROLE, EVALUATOR_ROLE, RESEARCHER_ROLE
from policy_drafter.rubrics import load_rubric
from policy_drafter.scoring import Evaluation, parse_evaluation
from policy_drafter.streaming import stream_tokens_to

logger = logging.getLogger(__name__)

_REVISE: Final = "revise"
_STOP: Final = "stop"
_EVALUATOR_ATTEMPTS = 2
_MAX_ERROR_CHARS = 500
_PHASE_BY_ROLE: dict[str, Phase] = {
    RESEARCHER_ROLE: "research",
    DRAFTER_ROLE: "draft",
    EVALUATOR_ROLE: "evaluate",
}
_WRAPPING_FENCE = re.compile(r"^(`{3,})([a-zA-Z]*)[ \t]*\n(.*)\n\1$", re.DOTALL)


def stop_reason_for(
    evaluation: Evaluation, iteration: int, max_iterations: int
) -> StopReason | None:
    """The loop's exit condition. Returns None to keep revising."""
    if not evaluation.parse_ok:
        return StopReason.EVALUATOR_ERROR
    if evaluation.all_passed:
        return StopReason.PASSED
    if iteration >= max_iterations:
        return StopReason.MAX_ITERATIONS
    return None


def select_final(iterations: Sequence[IterationRecord]) -> IterationRecord | None:
    """The draft to hand over: most criteria passed, then highest mean, then most recent."""
    if not iterations:
        return None
    return max(
        iterations,
        key=lambda record: (
            len(record.evaluation.scores) - len(record.evaluation.failing),
            record.evaluation.mean_score,
            record.number,
        ),
    )


class DraftingFlow(Flow[DraftingState]):
    llms: InstanceOf[LLMs] = Field(exclude=True)
    on_event: EventSink = Field(default=ignore_event, exclude=True)
    suppress_flow_events: bool = True

    # Flows otherwise create a long-term memory store, which this pattern has no use for: the
    # state below is the only memory between iterations.
    _skip_auto_memory: bool = PrivateAttr(default=True)
    _concluded: bool = PrivateAttr(default=False)
    # Tokens arrive on CrewAI's streaming thread and everything else on the flow's.
    _emit_lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)

    @start()
    def begin(self) -> None:
        self._emit(
            RunStarted(
                request=self.state.request,
                rubric=load_rubric(self.state.rubric_id),
                max_iterations=self.state.max_iterations,
                threshold=self.state.threshold,
            )
        )

    @listen(or_(begin, _REVISE))
    def write_draft(self) -> None:
        """The optimizer. On a revision, the evaluator's feedback goes into the prompts."""
        state = self.state
        state.iteration += 1
        self._emit(IterationStarted(iteration=state.iteration))
        self._emit(PhaseStarted(iteration=state.iteration, phase="research"))

        previous = state.iterations[-1] if state.iterations else None
        result = kickoff(
            build_writer_crew(
                self.llms,
                request=state.request,
                rubric=load_rubric(state.rubric_id),
                previous=previous.evaluation if previous else None,
                previous_draft=previous.draft if previous else None,
                on_research_done=self._on_research_done,
            )
        )

        state.research = result.tasks_output[0].raw
        state.draft = _clean_draft(result.raw)
        if not state.draft:
            raise ValueError("The drafter returned an empty draft.")
        self._emit(DraftCompleted(iteration=state.iteration, draft=state.draft))

    @listen(write_draft)
    def evaluate_draft(self) -> None:
        """The evaluator. It sees only the current draft, never the history or the pass mark."""
        state = self.state
        rubric = load_rubric(state.rubric_id)
        self._emit(PhaseStarted(iteration=state.iteration, phase="evaluate"))

        evaluation: Evaluation | None = None
        for attempt in range(1, _EVALUATOR_ATTEMPTS + 1):
            try:
                result = kickoff(
                    build_evaluator_crew(
                        self.llms, request=state.request, rubric=rubric, draft=state.draft
                    )
                )
            except Exception as error:
                logger.exception("Evaluator call failed (attempt %d)", attempt)
                if attempt == _EVALUATOR_ATTEMPTS:
                    if evaluation is None:
                        raise
                    break  # keep the reading already in hand
                self._emit(
                    EvaluationRetried(
                        iteration=state.iteration,
                        warnings=[f"Evaluator call failed: {type(error).__name__}"],
                    )
                )
                continue
            latest = parse_evaluation(result.raw, rubric, state.threshold)
            # A retry must never replace a better reading with a worse one.
            if evaluation is None or _scored(latest) > _scored(evaluation):
                evaluation = latest
            if _scored(evaluation) == len(evaluation.scores):
                break
            if attempt < _EVALUATOR_ATTEMPTS:
                self._emit(
                    EvaluationRetried(iteration=state.iteration, warnings=evaluation.warnings)
                )

        if evaluation is None:
            raise RuntimeError("the evaluator was never run")
        state.iterations.append(
            IterationRecord(
                number=state.iteration,
                research=state.research,
                draft=state.draft,
                evaluation=evaluation,
            )
        )
        self._emit(EvaluationCompleted(iteration=state.iteration, evaluation=evaluation))

    @router(evaluate_draft)
    def route_on_scores(self) -> Literal["revise", "stop"]:
        """The control decision. This is ordinary code and it is unit-testable."""
        state = self.state
        evaluation = state.iterations[-1].evaluation
        state.stop_reason = stop_reason_for(evaluation, state.iteration, state.max_iterations)
        return _REVISE if state.stop_reason is None else _STOP

    @listen(_STOP)
    def finish(self) -> None:
        self._conclude()

    def fail(self, error: Exception) -> None:
        """Record a failure as a stop reason, so that callers can treat every run the same way."""
        logger.exception("Drafting run failed", exc_info=error)
        if self._concluded:
            # The outcome was already recorded and announced; a late failure (such as a broken
            # event sink) must not emit a second terminal event or rewrite the stop reason.
            return
        self.state.stop_reason = StopReason.ERROR
        self.state.error = f"{type(error).__name__}: {error}"[:_MAX_ERROR_CHARS]
        try:
            self._conclude()
        # The sink may be what failed (a closed stream); the outcome is already on the state.
        except Exception:
            logger.exception("Could not announce the end of the run")

    def emit_token(self, text: str, agent_role: str | None) -> None:
        phase = _PHASE_BY_ROLE.get(agent_role or "")
        if phase is not None:
            self._emit(TokenEmitted(iteration=self.state.iteration, phase=phase, text=text))

    def _conclude(self) -> None:
        state = self.state
        self._concluded = True
        final = select_final(state.iterations)
        state.final_iteration = final.number if final else None
        state.final_draft = final.draft if final else (state.draft or None)
        if final is None and state.final_draft:
            state.final_iteration = state.iteration
        self._emit(
            RunFinished(
                stop_reason=state.stop_reason or StopReason.ERROR,
                iterations=len(state.iterations),
                final_iteration=state.final_iteration,
                final_draft=state.final_draft,
                error=state.error,
            )
        )

    def _on_research_done(self, output: TaskOutput) -> None:
        iteration = self.state.iteration
        self._emit(ResearchCompleted(iteration=iteration, research=output.raw))
        self._emit(PhaseStarted(iteration=iteration, phase="draft"))

    def _emit(self, event: ProgressEvent) -> None:
        with self._emit_lock:
            self.on_event(event)


def _scored(evaluation: Evaluation) -> int:
    return sum(1 for score in evaluation.scores if score.score is not None)


def _clean_draft(raw: str) -> str:
    """Remove the code fence that models sometimes wrap a Markdown document in."""
    text = raw.replace("\r\n", "\n").strip()
    match = _WRAPPING_FENCE.match(text)
    if match is None:
        return text
    _, language, body = match.groups()
    # A fence tagged markdown is a wrapper whatever it contains. An untagged one is only a
    # wrapper when no code block sits inside, as a document may open and close with its own.
    if language.lower() in {"markdown", "md"} or (not language and "\n```" not in body):
        return body.strip()
    return text


def run_drafting(
    config: RunConfig, llms: LLMs, on_event: EventSink = ignore_event
) -> DraftingState:
    """Run the loop to completion. Failures end up in the returned state and are not raised."""
    flow = DraftingFlow(llms=llms, on_event=on_event)
    with stream_tokens_to(flow.emit_token):
        try:
            flow.kickoff(inputs=config.model_dump())
        # This is the boundary of a run: whatever goes wrong inside it, from Bedrock throttling
        # to a CrewAI error, the caller gets a recorded outcome rather than an exception.
        except Exception as error:
            flow.fail(error)
        else:
            if not flow._concluded:  # the run ended without reaching `finish`
                flow.fail(RuntimeError("the run ended without reaching a conclusion"))
    state: DraftingState = flow.state
    return state
