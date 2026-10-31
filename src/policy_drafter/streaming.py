"""Forward CrewAI's LLM stream chunks to whichever run produced them.

CrewAI's event bus is process-wide, and a server may run several flows at once. Chunk events are
dispatched synchronously on the calling thread, so a ContextVar reliably identifies the run.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.llm_events import LLMStreamChunkEvent

TokenSink = Callable[[str, str | None], None]

_current_sink: ContextVar[TokenSink | None] = ContextVar("policy_drafter_token_sink", default=None)


@crewai_event_bus.on(LLMStreamChunkEvent)
def _forward_chunk(_source: Any, event: LLMStreamChunkEvent) -> None:
    sink = _current_sink.get()
    if sink is not None and event.chunk and event.tool_call is None:
        sink(event.chunk, event.agent_role)


@contextmanager
def stream_tokens_to(sink: TokenSink) -> Iterator[None]:
    """Send the tokens of LLM calls made inside this block to `sink(text, agent_role)`."""
    token = _current_sink.set(sink)
    try:
        yield
    finally:
        _current_sink.reset(token)
