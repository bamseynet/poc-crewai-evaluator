"""The evaluator-optimizer loop, exercised end to end with a scripted LLM."""

import threading

import pytest
from pydantic import ValidationError

from policy_drafter.events import ProgressEvent, TokenEmitted
from policy_drafter.flow import run_drafting
from policy_drafter.llm import LLMs
from policy_drafter.models import MAX_ITERATIONS_LIMIT, RunConfig, StopReason
from policy_drafter.prompts import DRAFTER_ROLE, EVALUATOR_ROLE, RESEARCHER_ROLE
from tests.conftest import ScriptedLLM, scores_json

RUBRIC = "clarity"
PASS = scores_json(RUBRIC, 9, "Good.")
FAIL = scores_json(RUBRIC, 4)


def config(max_iterations: int = 3, threshold: float | None = None, request: str | None = None):  # type: ignore[no-untyped-def]
    return RunConfig(
        request=request or "Draft an acceptable-use policy for AI tools for a 500-person fintech",
        rubric_id=RUBRIC,
        max_iterations=max_iterations,
        threshold=threshold,
    )


def run(llm: ScriptedLLM, *args, events: list[ProgressEvent] | None = None, **kwargs):  # type: ignore[no-untyped-def]
    sink = events.append if events is not None else lambda _event: None
    return run_drafting(config(*args, **kwargs), LLMs(evaluator=llm, worker=llm), on_event=sink)


# --- Termination -----------------------------------------------------------------------------


def test_terminates_as_soon_as_every_criterion_passes() -> None:
    llm = ScriptedLLM.build(drafter=["Draft one."], evaluator=[PASS])

    state = run(llm, max_iterations=5)

    assert state.stop_reason is StopReason.PASSED
    assert [record.number for record in state.iterations] == [1]
    assert len(llm.prompts_for(DRAFTER_ROLE)) == 1
    assert len(llm.prompts_for(EVALUATOR_ROLE)) == 1
    assert state.final_draft == "Draft one."
    assert state.final_iteration == 1


def test_revises_until_the_evaluator_passes_then_stops() -> None:
    llm = ScriptedLLM.build(drafter=["One.", "Two.", "Three."], evaluator=[FAIL, FAIL, PASS])

    state = run(llm, max_iterations=8)

    assert state.stop_reason is StopReason.PASSED
    assert [record.draft for record in state.iterations] == ["One.", "Two.", "Three."]
    assert len(llm.prompts_for(EVALUATOR_ROLE)) == 3
    assert state.final_draft == "Three."
    assert state.final_iteration == 3


def test_terminates_at_max_iterations_when_never_passing() -> None:
    llm = ScriptedLLM.build(evaluator=[FAIL])

    state = run(llm, max_iterations=3)

    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert len(state.iterations) == 3
    assert len(llm.prompts_for(DRAFTER_ROLE)) == 3
    assert len(llm.prompts_for(EVALUATOR_ROLE)) == 3


def test_a_single_iteration_budget_is_respected() -> None:
    llm = ScriptedLLM.build(evaluator=[FAIL])

    state = run(llm, max_iterations=1)

    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert len(state.iterations) == 1


def test_one_failing_criterion_is_enough_to_keep_revising() -> None:
    almost = scores_json(RUBRIC, 9, plain_language=(6.9, "Too much jargon."))
    llm = ScriptedLLM.build(evaluator=[almost, PASS])

    state = run(llm, max_iterations=3)

    assert state.stop_reason is StopReason.PASSED
    assert len(state.iterations) == 2


def test_run_threshold_override_changes_the_exit_condition() -> None:
    llm = ScriptedLLM.build(evaluator=[PASS])

    state = run(llm, max_iterations=2, threshold=9.5)

    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert len(state.iterations) == 2


# --- Bounds ----------------------------------------------------------------------------------


@pytest.mark.parametrize("max_iterations", [0, -1, MAX_ITERATIONS_LIMIT + 1, 1000])
def test_iteration_budget_is_bounded(max_iterations: int) -> None:
    with pytest.raises(ValidationError):
        config(max_iterations=max_iterations)


def test_threshold_must_be_on_the_scale() -> None:
    with pytest.raises(ValidationError):
        config(threshold=10.5)


@pytest.mark.parametrize("request_text", ["", "   ", "x" * 5_000])
def test_request_length_is_validated(request_text: str) -> None:
    with pytest.raises(ValidationError):
        RunConfig(request=request_text, rubric_id=RUBRIC)


def test_unknown_rubric_is_rejected_before_any_llm_call() -> None:
    with pytest.raises(ValidationError):
        RunConfig(request="A valid request", rubric_id="nope")


# --- Feedback is fed into the next draft -----------------------------------------------------


def test_evaluator_feedback_reaches_the_next_drafter_prompt() -> None:
    feedback = "UNIQUE-FEEDBACK: name who approves exceptions."
    evaluation = scores_json(RUBRIC, 9, actionable_requirements=(3, feedback))
    llm = ScriptedLLM.build(drafter=["First draft."], evaluator=[evaluation, PASS])

    run(llm, max_iterations=2)

    first, second = llm.prompts_for(DRAFTER_ROLE)
    assert feedback not in first
    assert feedback in second


def test_next_drafter_prompt_contains_the_previous_draft() -> None:
    llm = ScriptedLLM.build(drafter=["PREVIOUS-DRAFT-TEXT", "Better."], evaluator=[FAIL, PASS])

    run(llm, max_iterations=2)

    first, second = llm.prompts_for(DRAFTER_ROLE)
    assert "PREVIOUS-DRAFT-TEXT" not in first
    assert "PREVIOUS-DRAFT-TEXT" in second


def test_only_failing_criteria_are_fed_back() -> None:
    evaluation = scores_json(
        RUBRIC,
        9,
        plain_language=(9, "PASSING-NOTE"),
        normative_language=(2, "FAILING-NOTE"),
    )
    llm = ScriptedLLM.build(evaluator=[evaluation, PASS])

    run(llm, max_iterations=2)

    second = llm.prompts_for(DRAFTER_ROLE)[1]
    assert "FAILING-NOTE" in second
    assert "PASSING-NOTE" not in second


def test_only_the_latest_feedback_is_used() -> None:
    llm = ScriptedLLM.build(
        evaluator=[
            scores_json(RUBRIC, 2, "FEEDBACK-ROUND-ONE"),
            scores_json(RUBRIC, 2, "FEEDBACK-ROUND-TWO"),
            PASS,
        ],
    )

    run(llm, max_iterations=3)

    third = llm.prompts_for(DRAFTER_ROLE)[2]
    assert "FEEDBACK-ROUND-TWO" in third
    assert "FEEDBACK-ROUND-ONE" not in third


def test_feedback_also_guides_the_researcher() -> None:
    evaluation = scores_json(RUBRIC, 9, plain_language=(3, "RESEARCH-THIS-GAP"))
    llm = ScriptedLLM.build(evaluator=[evaluation, PASS])

    run(llm, max_iterations=2)

    first, second = llm.prompts_for(RESEARCHER_ROLE)
    assert "RESEARCH-THIS-GAP" not in first
    assert "RESEARCH-THIS-GAP" in second


def test_research_notes_reach_the_drafter() -> None:
    llm = ScriptedLLM.build(researcher=["RESEARCH-NOTES-MARKER"], evaluator=[PASS])

    run(llm)

    assert "RESEARCH-NOTES-MARKER" in llm.prompts_for(DRAFTER_ROLE)[0]


def test_user_supplied_braces_do_not_break_prompt_templating() -> None:
    braces = "Cover {request} and {feedback} and {unknown} and }{ literally"
    evaluation = scores_json(RUBRIC, 2, "Feedback with {previous_draft} and {research}")
    llm = ScriptedLLM.build(drafter=["Draft with {request} inside."], evaluator=[evaluation, PASS])

    state = run(llm, max_iterations=2, request=braces)

    assert state.stop_reason is StopReason.PASSED
    second = llm.prompts_for(DRAFTER_ROLE)[1]
    assert braces in second
    assert "Feedback with {previous_draft} and {research}" in second
    assert "Draft with {request} inside." in second


# --- What the evaluator sees -----------------------------------------------------------------


def test_evaluator_sees_the_draft_and_rubric_but_not_the_pass_mark_or_history() -> None:
    llm = ScriptedLLM.build(
        drafter=["DRAFT-MARKER-ONE", "DRAFT-MARKER-TWO"],
        evaluator=[scores_json(RUBRIC, 2, "EARLIER-FEEDBACK"), PASS],
    )

    run(llm, max_iterations=2)

    first, second = llm.prompts_for(EVALUATOR_ROLE)
    assert "DRAFT-MARKER-ONE" in first
    assert "normative_language" in first
    assert "threshold" not in first.lower()
    assert "DRAFT-MARKER-TWO" in second
    assert "DRAFT-MARKER-ONE" not in second
    assert "EARLIER-FEEDBACK" not in second


def test_each_role_uses_the_configured_model_tier() -> None:
    evaluator = ScriptedLLM.build(evaluator=[PASS])
    worker = ScriptedLLM.build()

    run_drafting(config(), LLMs(evaluator=evaluator, worker=worker))

    assert {call.role for call in evaluator._calls} == {EVALUATOR_ROLE}
    assert {call.role for call in worker._calls} == {RESEARCHER_ROLE, DRAFTER_ROLE}


# --- Malformed evaluator output --------------------------------------------------------------


def test_unparseable_evaluation_is_retried_once_without_a_new_draft() -> None:
    llm = ScriptedLLM.build(evaluator=["I'd rather not.", PASS])

    state = run(llm)

    assert state.stop_reason is StopReason.PASSED
    assert len(llm.prompts_for(EVALUATOR_ROLE)) == 2
    assert len(llm.prompts_for(DRAFTER_ROLE)) == 1


def test_persistently_unparseable_evaluation_stops_honestly() -> None:
    llm = ScriptedLLM.build(evaluator=["not json at all"])

    state = run(llm, max_iterations=4)

    assert state.stop_reason is StopReason.EVALUATOR_ERROR
    assert len(state.iterations) == 1
    assert len(llm.prompts_for(EVALUATOR_ROLE)) == 2
    assert not state.iterations[0].evaluation.all_passed


def test_partial_evaluation_fails_closed_and_keeps_revising() -> None:
    partial = '{"criteria": [{"id": "plain_language", "score": 10, "feedback": "ok"}]}'
    llm = ScriptedLLM.build(evaluator=[partial, partial, PASS])

    state = run(llm, max_iterations=3)

    assert state.stop_reason is StopReason.PASSED
    assert len(state.iterations) == 2
    assert "normative_language" in state.iterations[0].evaluation.warnings[0]


# --- The final draft -------------------------------------------------------------------------


def test_at_max_iterations_the_best_scoring_draft_wins_over_the_last() -> None:
    llm = ScriptedLLM.build(
        drafter=["Weak.", "Best.", "Regressed."],
        evaluator=[scores_json(RUBRIC, 3), scores_json(RUBRIC, 6), scores_json(RUBRIC, 5)],
    )

    state = run(llm, max_iterations=3)

    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert state.final_iteration == 2
    assert state.final_draft == "Best."


def test_passing_more_criteria_beats_a_higher_mean() -> None:
    llm = ScriptedLLM.build(
        drafter=["More passes.", "Higher mean."],
        evaluator=[
            scores_json(RUBRIC, 2, plain_language=(9, "ok"), normative_language=(9, "ok")),
            scores_json(RUBRIC, 6.9),
        ],
    )

    state = run(llm, max_iterations=2)

    assert state.final_draft == "More passes."


def test_tied_drafts_prefer_the_latest() -> None:
    llm = ScriptedLLM.build(drafter=["Older.", "Newer."], evaluator=[FAIL])

    state = run(llm, max_iterations=2)

    assert state.final_draft == "Newer."


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("```markdown\n# Policy\n\nBody.\n```", id="markdown-fence"),
        pytest.param("```\n# Policy\n\nBody.\n```\n", id="bare-fence"),
        pytest.param("\n\n# Policy\n\nBody.\n\n", id="whitespace"),
    ],
)
def test_draft_wrapping_is_removed(reply: str) -> None:
    llm = ScriptedLLM.build(drafter=[reply], evaluator=[PASS])

    assert run(llm).final_draft == "# Policy\n\nBody."


# --- Progress events -------------------------------------------------------------------------


def test_events_describe_the_loop_in_order() -> None:
    llm = ScriptedLLM.build(drafter=["One.", "Two."], evaluator=[FAIL, PASS])
    events: list[ProgressEvent] = []

    run(llm, max_iterations=3, events=events)

    lifecycle = [
        (
            event.type,
            getattr(event, "iteration", None),
            getattr(event, "phase", None),
        )
        for event in events
        if event.type != "token"
    ]
    assert lifecycle == [
        ("run_started", None, None),
        ("iteration_started", 1, None),
        ("phase_started", 1, "research"),
        ("research_completed", 1, None),
        ("phase_started", 1, "draft"),
        ("draft_completed", 1, None),
        ("phase_started", 1, "evaluate"),
        ("evaluation_completed", 1, None),
        ("iteration_started", 2, None),
        ("phase_started", 2, "research"),
        ("research_completed", 2, None),
        ("phase_started", 2, "draft"),
        ("draft_completed", 2, None),
        ("phase_started", 2, "evaluate"),
        ("evaluation_completed", 2, None),
        ("run_finished", None, None),
    ]


def test_run_finished_event_records_the_stop_reason_and_final_draft() -> None:
    llm = ScriptedLLM.build(drafter=["The draft."], evaluator=[PASS])
    events: list[ProgressEvent] = []

    run(llm, events=events)

    finished = events[-1]
    assert finished.type == "run_finished"
    assert finished.stop_reason is StopReason.PASSED
    assert finished.final_draft == "The draft."
    assert finished.final_iteration == 1


def test_tokens_stream_with_their_iteration_and_phase() -> None:
    llm = ScriptedLLM.build(
        researcher=["notes here"], drafter=["draft words"], evaluator=[FAIL, PASS]
    )
    events: list[ProgressEvent] = []

    run(llm, max_iterations=2, events=events)

    tokens = [event for event in events if isinstance(event, TokenEmitted)]
    text = {
        (iteration, phase): "".join(
            t.text for t in tokens if (t.iteration, t.phase) == (iteration, phase)
        )
        for iteration, phase in {(t.iteration, t.phase) for t in tokens}
    }
    assert text[(1, "research")].strip() == "notes here"
    assert text[(1, "draft")].strip() == "draft words"
    assert (1, "evaluate") in text
    assert (2, "draft") in text


def test_concurrent_runs_do_not_receive_each_others_tokens() -> None:
    def scripted(marker: str) -> ScriptedLLM:
        return ScriptedLLM.build(researcher=[marker], drafter=[marker], evaluator=[PASS])

    results: dict[str, list[ProgressEvent]] = {"AAA": [], "BBB": []}

    def worker(marker: str) -> None:
        llm = scripted(marker)
        run_drafting(config(), LLMs(evaluator=llm, worker=llm), on_event=results[marker].append)

    threads = [threading.Thread(target=worker, args=(marker,)) for marker in results]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for marker, events in results.items():
        tokens = [e.text for e in events if isinstance(e, TokenEmitted) and e.phase != "evaluate"]
        assert tokens
        other = "BBB" if marker == "AAA" else "AAA"
        assert not any(other in text for text in tokens)


# --- Failures --------------------------------------------------------------------------------


def test_llm_failure_is_recorded_as_a_stop_reason_rather_than_raised() -> None:
    llm = ScriptedLLM.build(drafter=[RuntimeError("Bedrock is throttling")])
    events: list[ProgressEvent] = []

    state = run(llm, events=events)

    assert state.stop_reason is StopReason.ERROR
    assert "Bedrock is throttling" in (state.error or "")
    assert events[-1].type == "run_finished"
    assert events[-1].stop_reason is StopReason.ERROR


def test_failure_after_a_scored_draft_keeps_the_best_draft_so_far() -> None:
    llm = ScriptedLLM.build(
        drafter=["Usable.", RuntimeError("Connection lost")],
        evaluator=[FAIL],
    )

    state = run(llm, max_iterations=3)

    assert state.stop_reason is StopReason.ERROR
    assert state.final_draft == "Usable."
    assert state.final_iteration == 1


def test_a_sink_that_fails_after_the_run_finished_does_not_rewrite_the_outcome() -> None:
    llm = ScriptedLLM.build(drafter=["Draft one."], evaluator=[PASS])
    seen: list[ProgressEvent] = []

    def flaky_sink(event: ProgressEvent) -> None:
        seen.append(event)
        if event.type == "run_finished":
            raise ConnectionError("client went away")

    state = run_drafting(config(), LLMs(evaluator=llm, worker=llm), on_event=flaky_sink)

    assert state.stop_reason is StopReason.PASSED
    assert [event.type for event in seen].count("run_finished") == 1


def test_a_mostly_unparseable_evaluation_is_retried_before_it_drives_a_revision() -> None:
    partial = '{"criteria": [{"id": "plain_language", "score": 3, "feedback": "x"}]}'
    llm = ScriptedLLM.build(evaluator=[partial, PASS])
    events: list[ProgressEvent] = []

    state = run(llm, max_iterations=3, events=events)

    assert state.stop_reason is StopReason.PASSED
    assert len(state.iterations) == 1
    assert any(event.type == "evaluation_retried" for event in events)


def test_a_failure_while_evaluating_the_first_draft_still_returns_that_draft() -> None:
    llm = ScriptedLLM.build(drafter=["Only draft."], evaluator=[RuntimeError("throttled")])

    state = run(llm)

    assert state.stop_reason is StopReason.ERROR
    assert state.final_draft == "Only draft."


def test_a_sink_that_always_fails_does_not_make_run_drafting_raise() -> None:
    llm = ScriptedLLM.build(drafter=["Draft one."], evaluator=[PASS])

    def broken(_event: ProgressEvent) -> None:
        raise BrokenPipeError("client went away")

    state = run_drafting(config(), LLMs(evaluator=llm, worker=llm), on_event=broken)

    assert state.stop_reason is StopReason.ERROR
