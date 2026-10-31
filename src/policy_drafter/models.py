"""The data that moves through the loop."""

from enum import StrEnum
from typing import Annotated

from crewai.flow.flow import FlowState
from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from policy_drafter.rubrics import load_rubric
from policy_drafter.scoring import Evaluation

DEFAULT_MAX_ITERATIONS = 4
MAX_ITERATIONS_LIMIT = 8
"""Hard ceiling on revisions. Every iteration costs real money, whatever a caller asks for."""


class StopReason(StrEnum):
    PASSED = "passed"
    MAX_ITERATIONS = "max_iterations"
    EVALUATOR_ERROR = "evaluator_error"
    ERROR = "error"


def _known_rubric(rubric_id: str) -> str:
    load_rubric(rubric_id)
    return rubric_id


class RunConfig(BaseModel):
    """A validated request to run the loop."""

    request: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    rubric_id: Annotated[str, AfterValidator(_known_rubric)]
    max_iterations: int = Field(default=DEFAULT_MAX_ITERATIONS, ge=1, le=MAX_ITERATIONS_LIMIT)
    threshold: float | None = Field(default=None, ge=0, le=10)


class IterationRecord(BaseModel):
    number: int
    research: str
    draft: str
    evaluation: Evaluation


class DraftingState(FlowState):
    """Flow state. Everything the loop needs to decide what happens next is held here."""

    request: str = ""
    rubric_id: str = ""
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    threshold: float | None = None

    iteration: int = 0
    research: str = ""
    draft: str = ""
    iterations: list[IterationRecord] = Field(default_factory=list)

    stop_reason: StopReason | None = None
    final_iteration: int | None = None
    final_draft: str | None = None
    error: str | None = None
