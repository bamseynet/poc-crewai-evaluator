"""Load the YAML rubrics that define what a good draft means.

A rubric is plain data, so a compliance team can change the quality bar without touching the
agents. Scores are always on a 0-10 scale.
"""

from functools import lru_cache
from importlib import resources
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Score = Annotated[float, Field(ge=0, le=10)]


class RubricError(ValueError):
    """A rubric is missing or does not match the schema."""


class Criterion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    threshold: Score | None = None


class Rubric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    threshold: Score = 7
    criteria: tuple[Criterion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _criterion_ids_are_unique(self) -> "Rubric":
        ids = [criterion.id for criterion in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate criterion ids in rubric {self.id!r}")
        return self

    def threshold_for(self, criterion: Criterion, override: float | None = None) -> float:
        """The pass mark for a criterion: run override, then criterion, then rubric default."""
        if override is not None:
            return override
        return criterion.threshold if criterion.threshold is not None else self.threshold


def parse_rubric(text: str) -> Rubric:
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RubricError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RubricError("a rubric must be a YAML mapping")
    try:
        return Rubric.model_validate(data)
    except ValidationError as exc:
        raise RubricError(f"invalid rubric: {exc}") from exc


def _read_bundled() -> list[Rubric]:
    files = resources.files("policy_drafter") / "rubric_files"
    return [
        parse_rubric(path.read_text(encoding="utf-8"))
        for path in files.iterdir()
        if path.name.endswith(".yaml")
    ]


@lru_cache(maxsize=1)
def _bundled_rubrics() -> dict[str, Rubric]:
    loaded: dict[str, Rubric] = {}
    for rubric in sorted(_read_bundled(), key=lambda r: r.name):
        if rubric.id in loaded:
            raise RubricError(f"duplicate rubric id: {rubric.id!r}")
        loaded[rubric.id] = rubric
    return loaded


def list_rubrics() -> list[Rubric]:
    return list(_bundled_rubrics().values())


def load_rubric(rubric_id: str) -> Rubric:
    # Looking the id up in the loaded set, rather than building a path from it, means an
    # untrusted id can never reach the filesystem.
    try:
        return _bundled_rubrics()[rubric_id]
    except KeyError:
        raise RubricError(f"unknown rubric: {rubric_id!r}") from None
