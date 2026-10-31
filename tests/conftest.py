"""Shared fixtures. Every test runs real CrewAI Flows and Crews against an offline fake LLM."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from crewai.llms.base_llm import BaseLLM, llm_call_context
from pydantic import PrivateAttr

from policy_drafter.prompts import DRAFTER_ROLE, EVALUATOR_ROLE, RESEARCHER_ROLE
from policy_drafter.rubrics import load_rubric

Reply = str | Exception | Callable[[str], str]


@dataclass
class Call:
    role: str
    prompt: str


class ScriptedLLM(BaseLLM):
    """Replays scripted replies per agent role and records every prompt it receives."""

    _scripts: dict[str, list[Reply]] = PrivateAttr(default_factory=dict)
    _calls: list[Call] = PrivateAttr(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        researcher: Sequence[Reply] = (),
        drafter: Sequence[Reply] = (),
        evaluator: Sequence[Reply] = (),
    ) -> "ScriptedLLM":
        llm = cls(model="scripted")
        llm._scripts = {
            RESEARCHER_ROLE: list(researcher),
            DRAFTER_ROLE: list(drafter),
            EVALUATOR_ROLE: list(evaluator),
        }
        return llm

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
        assert from_agent is not None
        role = from_agent.role
        prompt = "\n".join(message["content"] for message in messages)
        self._calls.append(Call(role, prompt))

        script = self._scripts[role]
        # The last reply repeats, so tests only script what they care about.
        reply = script.pop(0) if len(script) > 1 else script[0] if script else f"{role} reply"
        if isinstance(reply, Exception):
            raise reply
        text = reply(prompt) if callable(reply) else reply
        with llm_call_context():
            for word in text.split(" "):
                self._emit_stream_chunk_event(
                    word + " ", from_task=from_task, from_agent=from_agent
                )
        return text

    def prompts_for(self, role: str) -> list[str]:
        return [call.prompt for call in self._calls if call.role == role]


def scores_json(
    rubric_id: str, score: float, feedback: str = "Needs work.", **overrides: Any
) -> str:
    """Evaluator output scoring every criterion `score`, except those named in overrides."""
    entries = []
    for criterion in load_rubric(rubric_id).criteria:
        override = overrides.get(criterion.id, score)
        value, text = override if isinstance(override, tuple) else (override, feedback)
        entries.append({"id": criterion.id, "score": value, "feedback": text})
    return json.dumps({"criteria": entries})
