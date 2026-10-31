"""The run registry: fan-out to SSE subscribers and shutdown behaviour."""

import asyncio

from policy_drafter.events import IterationStarted
from policy_drafter.llm import LLMs
from policy_drafter.runs import Run, RunManager
from tests.conftest import ScriptedLLM


def test_publishing_survives_a_subscriber_whose_event_loop_has_closed() -> None:
    run = Run("r1")
    loop = asyncio.new_event_loop()
    run._subscribers.add((loop, asyncio.Event()))
    loop.close()

    run.publish(IterationStarted(iteration=1))
    run.finish()

    assert run.finished
    assert len(run.events_after(0)) == 1


def test_shutdown_ends_the_streams_of_runs_still_in_flight() -> None:
    llm = ScriptedLLM.build()
    manager = RunManager(lambda: LLMs(evaluator=llm, worker=llm), max_concurrent=1, max_retained=5)
    run = Run("r2")
    manager._runs[run.id] = run

    manager.shutdown()

    assert run.finished
