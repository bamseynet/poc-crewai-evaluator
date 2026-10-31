"""Settings come from the environment and default to the offline fake."""

import pytest
from pydantic import ValidationError

from policy_drafter.config import Settings
from policy_drafter.fake_llm import FakeLLM
from policy_drafter.llm import build_llms


def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_MODE", "BEDROCK_MODEL_ID", "BEDROCK_WORKER_MODEL_ID", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_the_fake_llm_so_no_aws_is_needed() -> None:
    llms = build_llms(settings())

    assert isinstance(llms.evaluator, FakeLLM)
    assert isinstance(llms.worker, FakeLLM)


def test_model_ids_and_region_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "bedrock")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-opus-5-5")
    monkeypatch.setenv("BEDROCK_WORKER_MODEL_ID", "eu.anthropic.claude-haiku-5-5")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    llms = build_llms(settings())

    assert llms.evaluator.model == "bedrock/eu.anthropic.claude-opus-5-5"
    assert llms.worker.model == "bedrock/eu.anthropic.claude-haiku-5-5"


def test_rejects_an_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "openai")

    with pytest.raises(ValidationError):
        settings()


def test_retention_must_cover_the_concurrent_runs() -> None:
    with pytest.raises(ValueError, match="MAX_RETAINED_RUNS"):
        Settings(max_concurrent_runs=4, max_retained_runs=2)
