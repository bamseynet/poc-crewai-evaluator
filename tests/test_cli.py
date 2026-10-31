"""The command-line entry point."""

from pathlib import Path

import pytest

from policy_drafter.cli import main


def test_runs_the_loop_and_writes_the_final_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "fake")
    output = tmp_path / "policy.md"

    code = main(["Draft a data retention policy", "--rubric", "tone", "--output", str(output)])

    printed = capsys.readouterr().out
    assert code == 0
    assert "Iteration 1" in printed
    assert "Stop reason: passed" in printed
    assert "Draft a data retention policy" in output.read_text()


def test_exits_non_zero_when_the_quality_bar_is_not_met(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LLM_MODE", "fake")

    code = main(
        ["Draft a policy", "--rubric", "tone", "--max-iterations", "1", "--threshold", "10"]
    )

    assert code == 1
    assert "Stop reason: max_iterations" in capsys.readouterr().out


def test_rejects_invalid_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "fake")

    with pytest.raises(SystemExit):
        main(["Draft a policy", "--rubric", "does_not_exist"])


def test_unwritable_output_path_is_rejected_before_any_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "fake")

    with pytest.raises(SystemExit):
        main(["Draft a policy", "--output", str(tmp_path / "missing" / "out.md")])
