"""The agents. Crews own the roles, while the Flow owns the loop.

Each call builds a new Crew, so nothing leaks between iterations except what the Flow deliberately
passes in.
"""

import warnings
from collections.abc import Callable
from typing import cast

from crewai import Agent, Crew, CrewOutput, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.llms.base_llm import BaseLLM
from crewai.tasks.task_output import TaskOutput

from policy_drafter.llm import LLMs
from policy_drafter.prompts import (
    DRAFT_TASK,
    DRAFTER_ROLE,
    EVALUATION_TASK,
    EVALUATOR_ROLE,
    NO_FEEDBACK,
    NO_PREVIOUS_DRAFT,
    RESEARCH_TASK,
    RESEARCHER_ROLE,
    render_feedback,
    render_rubric,
)
from policy_drafter.rubrics import Rubric
from policy_drafter.scoring import Evaluation

# CrewAI warns that callbacks cannot be checkpointed. This project does not use checkpoints.
warnings.filterwarnings("ignore", message=r"A \w+ callback cannot be saved in a checkpoint")


def build_writer_crew(
    llms: LLMs,
    *,
    request: str,
    rubric: Rubric,
    previous: Evaluation | None,
    previous_draft: str | None,
    on_research_done: Callable[[TaskOutput], None],
) -> Crew:
    """Researcher then drafter, both on the cheaper worker tier."""
    prompt_values = {
        "request": request,
        "rubric": render_rubric(rubric),
        "feedback": render_feedback(previous) if previous else NO_FEEDBACK,
        "previous_draft": previous_draft or NO_PREVIOUS_DRAFT,
    }
    researcher = _agent(
        RESEARCHER_ROLE,
        goal="Find what the requested policy must cover to satisfy its regulators and auditors.",
        backstory="A compliance analyst who is careful to separate what is known from what is not.",
        llm=llms.worker,
    )
    drafter = _agent(
        DRAFTER_ROLE,
        goal="Write a policy that people can follow and auditors can test, acting on all feedback.",
        backstory="A senior policy writer at a regulated enterprise who responds well to review.",
        llm=llms.worker,
    )
    research = Task(
        description=RESEARCH_TASK.format(**prompt_values),
        expected_output="Concise research notes in Markdown.",
        agent=researcher,
        callback=on_research_done,
    )
    draft = Task(
        description=DRAFT_TASK.format(**prompt_values),
        expected_output="Only the complete policy in Markdown, with no preamble and no code fence.",
        agent=drafter,
        context=[research],
    )
    return _crew([researcher, drafter], [research, draft])


def build_evaluator_crew(llms: LLMs, *, request: str, rubric: Rubric, draft: str) -> Crew:
    """A single agent on the strongest tier, with no knowledge of earlier iterations."""
    evaluator = _agent(
        EVALUATOR_ROLE,
        goal="Judge drafts accurately so that only publishable policies pass.",
        backstory="A sceptical internal auditor who gives specific, actionable criticism.",
        llm=llms.evaluator,
    )
    evaluation = Task(
        description=EVALUATION_TASK.format(
            request=request, rubric=render_rubric(rubric), draft=draft
        ),
        expected_output="Only a JSON object with a score and feedback for every criterion.",
        agent=evaluator,
    )
    return _crew([evaluator], [evaluation])


def kickoff(crew: Crew) -> CrewOutput:
    """Run a crew. These crews never set `stream=True`, so the result is always a CrewOutput."""
    return cast(CrewOutput, crew.kickoff())


def _agent(role: str, *, goal: str, backstory: str, llm: BaseLLM) -> Agent:
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=llm,
        allow_delegation=False,
        max_iter=3,
        verbose=False,
    )


def _crew(agents: list[BaseAgent], tasks: list[Task]) -> Crew:
    return Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        memory=False,
        cache=False,
        verbose=False,
    )
