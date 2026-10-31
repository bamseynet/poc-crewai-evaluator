"""A deterministic stand-in for Bedrock, so anyone can run the loop with no AWS account.

It is more than a canned reply. The fake drafter writes a section for each item of feedback it
finds in its prompt, and the fake evaluator raises a criterion's score only when the draft contains
such a section. The demo therefore converges only if feedback really travels from the evaluator
to the drafter, which is the property the pattern depends on.
"""

import json
import re
import time
import zlib
from typing import Any

from crewai.llms.base_llm import BaseLLM, llm_call_context

from policy_drafter.prompts import DRAFTER_ROLE, EVALUATOR_ROLE, RESEARCHER_ROLE

_RUBRIC_LINE = re.compile(r"^- `(\w+)` \((.+?)\): (.+)$", re.MULTILINE)
_FEEDBACK_LINE = re.compile(r"^- \[(\w+)\] (.+?) \(.+?\): (.+)$", re.MULTILINE)

_MAX_SCORE = 9.5
_POINTS_PER_REVISION = 2.5
# Picked per criterion by checksum, so that criteria pass at different iterations.
_STARTING_SCORES = (3.0, 4.5, 6.0, 7.5)

_FIRST_DRAFT = """\
# Policy draft

> Request: {request}
>
> This text comes from the offline fake LLM. Set `LLM_MODE=bedrock` to use real models.

## 1. Purpose

This policy sets out how the organisation manages the activity described in the request.

## 2. Scope

This policy applies to all employees and contractors.

## 3. Requirements

Employees must use approved tools and must protect company and customer data."""


class FakeLLM(BaseLLM):
    delay_seconds: float = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**{"model": "fake", **kwargs})

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        role = from_agent.role if from_agent is not None else ""
        prompt = "\n".join(message["content"] for message in messages)
        reply = self.reply_for(role, prompt)
        with llm_call_context():
            for word in re.findall(r"\S+\s*|\s+", reply):
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
                self._emit_stream_chunk_event(word, from_task=from_task, from_agent=from_agent)
        return reply

    def get_input_tokens_count(
        self, messages: Any, tools: Any = None, response_model: Any = None
    ) -> int:
        return len(str(messages)) // 4

    def reply_for(self, role: str, prompt: str) -> str:
        if role == RESEARCHER_ROLE:
            return _research(prompt)
        if role == DRAFTER_ROLE:
            return _draft(prompt)
        if role == EVALUATOR_ROLE:
            return _evaluate(prompt)
        raise ValueError(f"FakeLLM has no behaviour for role {role!r}")


def _research(prompt: str) -> str:
    gaps = [name for _, name, _ in _FEEDBACK_LINE.findall(_section(prompt, "evaluator_feedback"))]
    notes = [
        "## Research notes",
        "",
        "- Sector regulators are likely to expect documented ownership and review. [VERIFY]",
        "- Data protection law is likely to apply to any personal data involved. [VERIFY]",
    ]
    notes += [f"- The drafter should strengthen: {gap}." for gap in gaps]
    return "\n".join(notes)


def _draft(prompt: str) -> str:
    previous = _section(prompt, "previous_draft")
    if not previous or previous.startswith("None."):
        return _FIRST_DRAFT.format(request=_section(prompt, "request"))

    sections = [previous]
    for criterion_id, name, feedback in _FEEDBACK_LINE.findall(
        _section(prompt, "evaluator_feedback")
    ):
        sections.append(
            f"## {name}\n\n"
            f"Reviewer note on `{criterion_id}`: this section responds to the feedback below.\n\n"
            f"> {feedback}"
        )
    return "\n\n".join(sections)


def _evaluate(prompt: str) -> str:
    draft = _section(prompt, "draft")
    criteria = []
    for criterion_id, name, description in _RUBRIC_LINE.findall(_section(prompt, "rubric")):
        revisions = draft.count(f"Reviewer note on `{criterion_id}`")
        start = _STARTING_SCORES[zlib.crc32(criterion_id.encode()) % len(_STARTING_SCORES)]
        criteria.append(
            {
                "id": criterion_id,
                "score": min(start + revisions * _POINTS_PER_REVISION, _MAX_SCORE),
                "feedback": f"Add more specifics on {name.lower()}. Expected: {description}",
            }
        )
    return json.dumps({"criteria": criteria})


def _section(prompt: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.DOTALL)
    return match.group(1).strip() if match else ""
