"""Run the loop on worker threads and replay its events to any number of subscribers.

Flows are synchronous and long-running, while the API is async, so each run gets a worker thread
and an append-only event log. Subscribers read from the log, so a client that reconnects can resume
from the last event it saw. Everything is in memory, so restarting the server loses all runs.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from policy_drafter.events import ProgressEvent, RunFinished, TokenEmitted
from policy_drafter.flow import run_drafting
from policy_drafter.llm import LLMs
from policy_drafter.models import RunConfig, StopReason

logger = logging.getLogger(__name__)


class TooManyRunsError(Exception):
    """The concurrency limit has been reached."""


class Run:
    def __init__(self, run_id: str) -> None:
        self.id = run_id
        self._lock = threading.Lock()
        self._log: list[tuple[int, ProgressEvent]] = []
        self._last_seq = 0
        self._finished = False
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def publish(self, event: ProgressEvent) -> None:
        with self._lock:
            self._last_seq += 1
            # Completed events carry the full text, so the tokens that led up to them are only
            # useful to a client watching live. Dropping them keeps the log small.
            if not isinstance(event, TokenEmitted):
                self._log = [e for e in self._log if not isinstance(e[1], TokenEmitted)]
            self._log.append((self._last_seq, event))
        self._wake_subscribers()

    def finish(self) -> None:
        with self._lock:
            self._finished = True
        self._wake_subscribers()

    def events_after(self, seq: int) -> list[tuple[int, ProgressEvent]]:
        with self._lock:
            return [entry for entry in self._log if entry[0] > seq]

    async def follow(self, after: int = 0) -> AsyncIterator[tuple[int, ProgressEvent]]:
        """Yield events after `after`, waiting for new ones until the run has finished."""
        subscriber = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._subscribers.add(subscriber)
        try:
            cursor = after
            while True:
                subscriber[1].clear()
                # Read `finished` first: an event published between these two reads is then
                # still picked up, and the stream cannot end before its last event.
                finished = self.finished
                for seq, event in self.events_after(cursor):
                    cursor = seq
                    yield seq, event
                if finished:
                    return
                await subscriber[1].wait()
        finally:
            with self._lock:
                self._subscribers.discard(subscriber)

    def _wake_subscribers(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, wake in subscribers:
            loop.call_soon_threadsafe(wake.set)


class RunManager:
    """Starts runs, limits how many are active and forgets the oldest finished ones."""

    def __init__(
        self, llm_factory: Callable[[], LLMs], *, max_concurrent: int, max_retained: int
    ) -> None:
        self._llm_factory = llm_factory
        self._max_concurrent = max_concurrent
        self._max_retained = max_retained
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._executor = ThreadPoolExecutor(max_concurrent, thread_name_prefix="drafting")

    def start(self, config: RunConfig) -> Run:
        run = Run(uuid4().hex)
        with self._lock:
            active = sum(not existing.finished for existing in self._runs.values())
            if active >= self._max_concurrent:
                raise TooManyRunsError
            self._runs[run.id] = run
            self._evict_finished()
        self._executor.submit(self._execute, run, config)
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _execute(self, run: Run, config: RunConfig) -> None:
        try:
            run_drafting(config, self._llm_factory(), on_event=run.publish)
        # run_drafting records its own failures, so this only catches problems setting up a run.
        # A subscriber must always see a final event, or its stream would never end.
        except Exception as error:
            logger.exception("Could not start run %s", run.id)
            run.publish(
                RunFinished(
                    stop_reason=StopReason.ERROR,
                    iterations=0,
                    final_iteration=None,
                    final_draft=None,
                    error=f"{type(error).__name__}: {error}",
                )
            )
        finally:
            run.finish()

    def _evict_finished(self) -> None:
        excess = len(self._runs) - self._max_retained
        for run_id in [r.id for r in self._runs.values() if r.finished][: max(excess, 0)]:
            del self._runs[run_id]
