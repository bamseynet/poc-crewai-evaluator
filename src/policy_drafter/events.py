"""Typed progress events. A CLI, a test or an SSE endpoint can all consume the same stream."""

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from policy_drafter.models import StopReason
from policy_drafter.rubrics import Rubric
from policy_drafter.scoring import Evaluation

Phase = Literal["research", "draft", "evaluate"]


class RunStarted(BaseModel):
    type: Literal["run_started"] = "run_started"
    request: str
    rubric: Rubric
    max_iterations: int
    threshold: float | None


class IterationStarted(BaseModel):
    type: Literal["iteration_started"] = "iteration_started"
    iteration: int


class PhaseStarted(BaseModel):
    type: Literal["phase_started"] = "phase_started"
    iteration: int
    phase: Phase


class TokenEmitted(BaseModel):
    type: Literal["token"] = "token"
    iteration: int
    phase: Phase
    text: str


class ResearchCompleted(BaseModel):
    type: Literal["research_completed"] = "research_completed"
    iteration: int
    research: str


class DraftCompleted(BaseModel):
    type: Literal["draft_completed"] = "draft_completed"
    iteration: int
    draft: str


class EvaluationRetried(BaseModel):
    type: Literal["evaluation_retried"] = "evaluation_retried"
    iteration: int
    warnings: list[str]


class EvaluationCompleted(BaseModel):
    type: Literal["evaluation_completed"] = "evaluation_completed"
    iteration: int
    evaluation: Evaluation


class RunFinished(BaseModel):
    type: Literal["run_finished"] = "run_finished"
    stop_reason: StopReason
    iterations: int
    final_iteration: int | None
    final_draft: str | None
    error: str | None = None


ProgressEvent = Annotated[
    RunStarted
    | IterationStarted
    | PhaseStarted
    | TokenEmitted
    | ResearchCompleted
    | DraftCompleted
    | EvaluationRetried
    | EvaluationCompleted
    | RunFinished,
    Field(discriminator="type"),
]
EventSink = Callable[[ProgressEvent], None]


def ignore_event(_event: ProgressEvent) -> None:
    """The default sink."""
