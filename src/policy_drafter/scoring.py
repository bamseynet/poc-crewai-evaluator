"""Turn raw evaluator text into per-criterion scores.

The loop's exit condition depends on this parser, so it has two rules:

* It never raises, whatever the model returns.
* It fails closed. A criterion without a usable score does not pass, so a malformed response
  can trigger a revision but can never approve a policy.
"""

import json
import math
import re
from collections.abc import Iterator
from typing import Any

import json_repair
from pydantic import BaseModel, computed_field

from policy_drafter.rubrics import Criterion, Rubric

_FENCE = re.compile(r"```[a-zA-Z]*\s*(.*?)```", re.DOTALL)
_FRACTION = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)$", re.IGNORECASE)
_PERCENT = re.compile(r"^(-?\d+(?:\.\d+)?)\s*%$")
_PLAIN = re.compile(r"^(?:score\s*[:=]?\s*)?(-?\d+(?:\.\d+)?)$", re.IGNORECASE)

_CONTAINER_KEYS = ("criteria", "scores", "evaluation", "evaluations", "results", "rubric")
_ID_KEYS = ("id", "criterion_id", "criterion", "name", "key")
_SCORE_KEYS = ("score", "rating", "value", "points")
_FEEDBACK_KEYS = ("feedback", "comment", "comments", "rationale", "reason", "notes")

_MAX_DEPTH = 4
_MAX_FEEDBACK_CHARS = 4_000
_MAX_SCORE = 10.0


class CriterionScore(BaseModel):
    criterion_id: str
    name: str
    score: float | None
    threshold: float
    passed: bool
    feedback: str


class Evaluation(BaseModel):
    scores: list[CriterionScore]
    parse_ok: bool
    warnings: list[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_passed(self) -> bool:
        return self.parse_ok and all(score.passed for score in self.scores)

    @property
    def mean_score(self) -> float:
        return sum(score.score or 0 for score in self.scores) / len(self.scores)

    @property
    def failing(self) -> list[CriterionScore]:
        return [score for score in self.scores if not score.passed]


def parse_evaluation(raw: object, rubric: Rubric, threshold: float | None = None) -> Evaluation:
    """Parse evaluator output against a rubric. Never raises."""
    payload = _load_json(raw) if isinstance(raw, str) else None
    warnings: list[str] = []

    lookup: dict[str, Criterion] = {}
    for criterion in rubric.criteria:
        lookup[_normalise(criterion.name)] = criterion
        lookup[_normalise(criterion.id)] = criterion

    found: dict[str, tuple[float | None, str]] = {}
    for key, value, feedback in _entries(payload):
        matched = lookup.get(_normalise(key))
        if matched is None:
            warnings.append(f"Ignored unknown criterion {key!r}.")
            continue
        score = _coerce_score(value)
        previous = found.get(matched.id)
        # When the evaluator scores a criterion twice, believe the less flattering score.
        if previous is None or previous[0] is None or (score is not None and score < previous[0]):
            found[matched.id] = (score, feedback)

    scores = [
        _score_for(criterion, rubric.threshold_for(criterion, threshold), found.get(criterion.id))
        for criterion in rubric.criteria
    ]
    warnings.extend(
        f"No usable score for criterion {score.criterion_id!r}."
        for score in scores
        if score.score is None
    )
    return Evaluation(
        scores=scores,
        parse_ok=any(score.score is not None for score in scores),
        warnings=warnings,
    )


def _score_for(
    criterion: Criterion, threshold: float, found: tuple[float | None, str] | None
) -> CriterionScore:
    score, feedback = found if found is not None else (None, "")
    passed = score is not None and score >= threshold
    if score is None:
        feedback = (
            f"The evaluator did not return a usable score for {criterion.name}. "
            f"Make sure the draft clearly meets this criterion: {criterion.description}"
        )
    elif not feedback and not passed:
        feedback = (
            f"{criterion.name} did not reach the required score. "
            f"Improve the draft against this criterion: {criterion.description}"
        )
    return CriterionScore(
        criterion_id=criterion.id,
        name=criterion.name,
        score=score,
        threshold=threshold,
        passed=passed,
        feedback=feedback,
    )


def _load_json(text: str) -> Any:
    """Find the most plausible JSON value in free text, or return None."""
    fenced = _FENCE.search(text)
    body = (fenced.group(1) if fenced else text).strip()
    opening = [position for position in (body.find("{"), body.find("[")) if position != -1]
    if not opening:
        return _parse_strict(body)

    start = min(opening)
    end = max(body.rfind("}"), body.rfind("]")) + 1
    for candidate in (body, body[start:end]):
        parsed = _parse_strict(candidate)
        if parsed is not None:
            return parsed
    # Truncated output has no closing bracket and trailing prose confuses the repair, so try
    # both spans and keep whichever recovers more criteria.
    repaired = (_parse_lenient(body[start:end]), _parse_lenient(body[start:]))
    return max(repaired, key=lambda parsed: sum(1 for _ in _entries(parsed)))


def _parse_strict(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _parse_lenient(text: str) -> Any:
    try:
        return json_repair.loads(text)
    # json_repair is a best-effort third-party parser fed with arbitrary model output. Any
    # failure here means the same thing: this text cannot be recovered.
    except Exception:
        return None


def _entries(payload: Any, depth: int = 0) -> Iterator[tuple[str, Any, str]]:
    """Yield (criterion key, raw score, feedback) from any reasonable JSON shape."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and (key := _first(item, _ID_KEYS)) is not None:
                yield str(key), _first(item, _SCORE_KEYS), _feedback(item)
        return
    if not isinstance(payload, dict):
        return

    for container in _CONTAINER_KEYS:
        if isinstance(payload.get(container), list | dict):
            yield from _entries(payload[container], depth + 1)
            return

    for key, value in payload.items():
        if isinstance(value, dict):
            yield str(key), _first(value, _SCORE_KEYS), _feedback(value)
        elif not isinstance(value, list):
            yield str(key), value, ""


def _coerce_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return _clamp(float(value))
    return _score_from_text(value.strip()) if isinstance(value, str) else None


def _score_from_text(text: str) -> float | None:
    if match := _FRACTION.match(text):
        scale = float(match.group(2))
        return _clamp(float(match.group(1)) / scale * _MAX_SCORE) if scale > 0 else None
    if match := _PERCENT.match(text):
        return _clamp(float(match.group(1)) / _MAX_SCORE)
    if match := _PLAIN.match(text):
        return _clamp(float(match.group(1)))
    return None


def _clamp(score: float) -> float | None:
    if not math.isfinite(score):
        return None
    return round(min(max(score, 0.0), _MAX_SCORE), 2)


def _feedback(item: dict[str, Any]) -> str:
    value = _first(item, _FEEDBACK_KEYS)
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(part) for part in value)
    return str(value).strip()[:_MAX_FEEDBACK_CHARS]


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((item[key] for key in keys if item.get(key) is not None), None)


def _normalise(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
