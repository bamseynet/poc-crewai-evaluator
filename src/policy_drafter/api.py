"""The HTTP API. Start with `uvicorn policy_drafter.api:create_app --factory`."""

import logging
import secrets
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from policy_drafter import models
from policy_drafter.config import Settings
from policy_drafter.llm import LLMs, build_llms
from policy_drafter.models import RunConfig
from policy_drafter.rubrics import list_rubrics
from policy_drafter.runs import Run, RunManager, TooManyRunsError

logger = logging.getLogger(__name__)


class CreatedRun(BaseModel):
    id: str


def create_app(
    settings: Settings | None = None, llm_factory: Callable[[], LLMs] | None = None
) -> FastAPI:
    config = settings or Settings()
    factory = llm_factory or (lambda: build_llms(config))
    runs = RunManager(
        factory, max_concurrent=config.max_concurrent_runs, max_retained=config.max_retained_runs
    )
    token = config.api_access_token.get_secret_value() if config.api_access_token else ""
    if config.llm_mode == "bedrock" and not token:
        logger.warning(
            "API_ACCESS_TOKEN is not set: anyone who can reach this API can start Bedrock runs."
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        runs.shutdown()

    app = FastAPI(title="Policy Drafter", lifespan=lifespan)
    app.state.runs = runs

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if token and not secrets.compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode()
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A valid access token is required.")

    def get_run(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        return run

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "llm_mode": config.llm_mode,
            "auth_required": bool(token),
            "max_iterations": {
                "default": models.DEFAULT_MAX_ITERATIONS,
                "limit": models.MAX_ITERATIONS_LIMIT,
            },
            "rubrics": [rubric.model_dump() for rubric in list_rubrics()],
        }

    protected = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @protected.post("/runs", status_code=status.HTTP_201_CREATED)
    def create_run(body: RunConfig) -> CreatedRun:
        try:
            return CreatedRun(id=runs.start(body).id)
        except TooManyRunsError:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many runs in progress. Try again when one has finished.",
            ) from None

    @protected.get("/runs/{run_id}/events", response_class=EventSourceResponse)
    async def stream_events(
        run: Annotated[Run, Depends(get_run)],
        last_event_id: Annotated[int, Header()] = 0,
    ) -> AsyncIterable[ServerSentEvent]:
        async for seq, event in run.follow(after=last_event_id):
            yield ServerSentEvent(raw_data=event.model_dump_json(), id=str(seq))

    app.include_router(protected)

    if config.web_dist is not None:
        app.mount("/", StaticFiles(directory=config.web_dist, html=True), name="web")

    return app
