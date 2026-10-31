"""Agent roles and the prompts they work from. This module is plain text and has no CrewAI code.

Prompts are rendered with `str.format` rather than `Crew.kickoff(inputs=...)`, because CrewAI
substitutes placeholders one after another: a request or model reply that happened to contain
`{feedback}` would have it replaced by the real feedback.
"""

from policy_drafter.rubrics import Rubric
from policy_drafter.scoring import Evaluation

RESEARCHER_ROLE = "Regulatory Researcher"
DRAFTER_ROLE = "Policy Drafter"
EVALUATOR_ROLE = "Compliance Evaluator"

NO_FEEDBACK = "None. This is the first draft."
NO_PREVIOUS_DRAFT = "None. This is the first draft."

RESEARCH_TASK = """\
Prepare research notes that a policy drafter will rely on.

<request>
{request}
</request>

The draft will be judged against this rubric:

<rubric>
{rubric}
</rubric>

An evaluator's feedback on the previous draft, if there is one:

<evaluator_feedback>
{feedback}
</evaluator_feedback>

Identify the laws, regulations, standards and control expectations that are likely to apply, and
the points the policy must therefore cover. If there is feedback, concentrate on what the drafter
needs to resolve it. You have no internet access: mark anything you are not certain of with
[VERIFY] rather than guessing, and never invent a citation."""

DRAFT_TASK = """\
Write the complete policy document in Markdown.

<request>
{request}
</request>

It will be judged against this rubric:

<rubric>
{rubric}
</rubric>

Your previous draft, if there is one:

<previous_draft>
{previous_draft}
</previous_draft>

An evaluator's feedback on that draft, if there is any:

<evaluator_feedback>
{feedback}
</evaluator_feedback>

If there is feedback, revise your previous draft so that it resolves every point, keep what was
not criticised, and output the whole document rather than only the changes. Use the research notes
provided as context, and keep any [VERIFY] markers on claims you cannot confirm."""

EVALUATION_TASK = """\
Score this draft policy against each rubric criterion, independently and strictly.

<request>
{request}
</request>

<rubric>
{rubric}
</rubric>

<draft>
{draft}
</draft>

Score each criterion from 0 to 10, where 0 means absent, 5 means present but not good enough to
publish, 7 means a competent policy team would accept it, and 10 means it could not be improved.
Judge only the text in front of you. For any score below 10, give specific feedback: quote or
point to the relevant part of the draft and say exactly what would raise the score.

Respond with only a JSON object in this form, with no other text and no code fence:

{{"criteria": [{{"id": "<criterion id>", "score": <number>, "feedback": "<your feedback>"}}]}}"""


def render_rubric(rubric: Rubric) -> str:
    """The rubric as prompts see it. Pass marks are left out so they cannot anchor the scores."""
    return "\n".join(
        f"- `{criterion.id}` ({criterion.name}): {criterion.description}"
        for criterion in rubric.criteria
    )


def render_feedback(evaluation: Evaluation) -> str:
    """What the drafter is told to fix: the failing criteria only."""
    lines = []
    for score in evaluation.failing:
        scored = f"{score.score:g}" if score.score is not None else "not scored"
        lines.append(
            f"- [{score.criterion_id}] {score.name} ({scored}, needs {score.threshold:g}): "
            f"{score.feedback}"
        )
    return "\n".join(lines) or NO_FEEDBACK
