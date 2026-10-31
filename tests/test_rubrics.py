"""Rubrics are the contract between the user, the writer and the evaluator."""

import pytest

from policy_drafter.rubrics import (
    Rubric,
    RubricError,
    list_rubrics,
    load_rubric,
    parse_rubric,
)

VALID = """
id: sample
name: Sample
description: A sample rubric
threshold: 6
criteria:
  - id: first_item
    name: First
    description: The first criterion
  - id: second_item
    name: Second
    description: The second criterion
    threshold: 9
"""


def test_parses_a_valid_rubric() -> None:
    rubric = parse_rubric(VALID)

    assert isinstance(rubric, Rubric)
    assert rubric.id == "sample"
    assert [c.id for c in rubric.criteria] == ["first_item", "second_item"]


def test_criterion_threshold_overrides_the_rubric_default() -> None:
    rubric = parse_rubric(VALID)

    assert rubric.threshold_for(rubric.criteria[0]) == 6
    assert rubric.threshold_for(rubric.criteria[1]) == 9


def test_threshold_override_replaces_every_criterion_threshold() -> None:
    rubric = parse_rubric(VALID)

    assert rubric.threshold_for(rubric.criteria[0], override=8) == 8
    assert rubric.threshold_for(rubric.criteria[1], override=8) == 8


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("id: [unterminated", id="invalid-yaml"),
        pytest.param("- just\n- a\n- list\n", id="not-a-mapping"),
        pytest.param("id: x\nname: X\ndescription: d\ncriteria: []\n", id="no-criteria"),
        pytest.param(
            "id: x\nname: X\ndescription: d\nthreshold: 11\n"
            "criteria:\n  - {id: a, name: A, description: d}\n",
            id="threshold-above-scale",
        ),
        pytest.param(
            "id: x\nname: X\ndescription: d\n"
            "criteria:\n  - {id: a, name: A, description: d, threshold: -1}\n",
            id="criterion-threshold-below-scale",
        ),
        pytest.param(
            "id: x\nname: X\ndescription: d\n"
            "criteria:\n  - {id: a, name: A, description: d}\n"
            "  - {id: a, name: B, description: d}\n",
            id="duplicate-criterion-id",
        ),
        pytest.param(
            "id: x\nname: X\ndescription: d\n"
            "criteria:\n  - {id: Not A Slug, name: A, description: d}\n",
            id="criterion-id-not-a-slug",
        ),
        pytest.param(
            "id: x\nname: X\ndescription: d\ncriteria:\n  - {id: a, name: A}\n",
            id="criterion-without-description",
        ),
    ],
)
def test_rejects_invalid_rubrics(text: str) -> None:
    with pytest.raises(RubricError):
        parse_rubric(text)


def test_bundles_the_four_requested_rubrics() -> None:
    assert {r.id for r in list_rubrics()} == {
        "completeness",
        "regulatory_coverage",
        "clarity",
        "tone",
    }


@pytest.mark.parametrize("rubric_id", ["completeness", "regulatory_coverage", "clarity", "tone"])
def test_loads_each_bundled_rubric_by_id(rubric_id: str) -> None:
    rubric = load_rubric(rubric_id)

    assert rubric.id == rubric_id
    assert len(rubric.criteria) >= 3


@pytest.mark.parametrize("rubric_id", ["nope", "../secrets", "/etc/passwd", ""])
def test_unknown_or_unsafe_rubric_ids_are_rejected(rubric_id: str) -> None:
    with pytest.raises(RubricError):
        load_rubric(rubric_id)
