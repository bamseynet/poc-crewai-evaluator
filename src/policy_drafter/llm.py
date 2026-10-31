"""Choose the LLMs for a run: the offline fake, or Bedrock through CrewAI's LiteLLM integration."""

from dataclasses import dataclass

from crewai import LLM
from crewai.llms.base_llm import BaseLLM

from policy_drafter.config import Settings
from policy_drafter.fake_llm import FakeLLM

# Adaptive thinking draws on the same budget as the visible answer.
_MAX_OUTPUT_TOKENS = 16_000


@dataclass(frozen=True)
class LLMs:
    """The model tiers. Judgement gets the strongest model, high-volume writing a cheaper one."""

    evaluator: BaseLLM
    worker: BaseLLM


def build_llms(settings: Settings) -> LLMs:
    if settings.llm_mode == "fake":
        delay = settings.fake_llm_delay_ms / 1000
        return LLMs(evaluator=FakeLLM(delay_seconds=delay), worker=FakeLLM(delay_seconds=delay))
    return LLMs(
        evaluator=_bedrock_llm(settings.bedrock_model_id, settings.aws_region),
        worker=_bedrock_llm(settings.bedrock_worker_model_id, settings.aws_region),
    )


def _bedrock_llm(model_id: str, region: str) -> LLM:
    # `is_litellm=True` selects CrewAI's LiteLLM integration rather than its native Bedrock class.
    # `temperature` is deliberately left unset, because current Claude models do not need it.
    return LLM(
        model=f"bedrock/{model_id}",
        is_litellm=True,
        stream=True,
        max_tokens=_MAX_OUTPUT_TOKENS,
        aws_region_name=region,
    )
