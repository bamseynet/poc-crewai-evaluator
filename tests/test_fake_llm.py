"""The fake LLM behind `make dev`. Its drafts only improve if the feedback actually reaches it."""

import json

from policy_drafter.config import Settings
from policy_drafter.fake_llm import FakeLLM
from policy_drafter.flow import run_drafting
from policy_drafter.llm import LLMs, build_llms
from policy_drafter.models import RunConfig, StopReason
from policy_drafter.prompts import DRAFTER_ROLE
from policy_drafter.rubrics import list_rubrics

REQUEST = "Draft an acceptable-use policy for AI tools for a 500-person fintech"


def fake_llms() -> LLMs:
    return build_llms(Settings(llm_mode="fake", _env_file=None))  # type: ignore[call-arg]


def test_every_bundled_rubric_converges_within_the_default_budget() -> None:
    for rubric in list_rubrics():
        state = run_drafting(RunConfig(request=REQUEST, rubric_id=rubric.id), fake_llms())

        assert state.stop_reason is StopReason.PASSED, rubric.id
        assert len(state.iterations) >= 2, f"{rubric.id} should need at least one revision"


def test_scores_never_regress_and_drafts_change_between_iterations() -> None:
    state = run_drafting(RunConfig(request=REQUEST, rubric_id="regulatory_coverage"), fake_llms())

    drafts = [record.draft for record in state.iterations]
    assert len(set(drafts)) == len(drafts)
    for earlier, later in zip(state.iterations, state.iterations[1:], strict=False):
        for before, after in zip(earlier.evaluation.scores, later.evaluation.scores, strict=True):
            assert (after.score or 0) >= (before.score or 0)


def test_revisions_reword_existing_text_as_well_as_adding_to_it() -> None:
    """Otherwise the UI's diff would only ever show additions in the demo."""
    state = run_drafting(RunConfig(request=REQUEST, rubric_id="regulatory_coverage"), fake_llms())

    first, second, *_ = [record.draft.splitlines() for record in state.iterations]
    assert set(first) - set(second)


def test_impossible_threshold_reaches_max_iterations() -> None:
    state = run_drafting(
        RunConfig(request=REQUEST, rubric_id="clarity", max_iterations=2, threshold=10),
        fake_llms(),
    )

    assert state.stop_reason is StopReason.MAX_ITERATIONS
    assert len(state.iterations) == 2


def test_drafts_mention_the_request() -> None:
    state = run_drafting(RunConfig(request=REQUEST, rubric_id="tone"), fake_llms())

    assert REQUEST in (state.final_draft or "")


def test_evaluator_output_is_valid_json_with_every_criterion() -> None:
    llm = FakeLLM()
    prompt = (
        "<rubric>\n- `one` (One): first\n- `two` (Two): second\n</rubric>\n"
        "<draft>\nSome text.\n</draft>"
    )

    reply = llm.reply_for("Compliance Evaluator", prompt)

    assert [entry["id"] for entry in json.loads(reply)["criteria"]] == ["one", "two"]


def test_the_fake_drafter_only_improves_when_given_feedback() -> None:
    """Guards the demo itself: its convergence depends on the feedback in the prompt."""
    llm = FakeLLM()
    without = (
        "<previous_draft>\nOld.\n</previous_draft>\n"
        "<evaluator_feedback>\nNone.\n</evaluator_feedback>"
    )
    with_feedback = without.replace("None.", "- [scope] Scope (3, needs 7): Be specific.")

    assert "Reviewer note" not in llm.reply_for(DRAFTER_ROLE, without)
    assert "Reviewer note on `scope`" in llm.reply_for(DRAFTER_ROLE, with_feedback)
