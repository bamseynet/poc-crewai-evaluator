"""Runtime settings, read from the environment or a local .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cross-Region inference profile ids from the Amazon Bedrock model cards:
# https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html
DEFAULT_MODEL_ID = "us.anthropic.claude-opus-5-5"
DEFAULT_WORKER_MODEL_ID = "us.anthropic.claude-sonnet-5-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_mode: Literal["fake", "bedrock"] = "fake"
    bedrock_model_id: str = DEFAULT_MODEL_ID
    bedrock_worker_model_id: str = DEFAULT_WORKER_MODEL_ID
    aws_region: str = "us-east-1"
    fake_llm_delay_ms: int = Field(default=0, ge=0, le=1000)

    # When set, the API requires `Authorization: Bearer <token>` to start or watch a run.
    api_access_token: SecretStr | None = None
    max_concurrent_runs: int = Field(default=2, ge=1)
    max_retained_runs: int = Field(default=50, ge=1)
    # The built web UI, for deployments that serve it from the API container.
    web_dist: Path | None = None
