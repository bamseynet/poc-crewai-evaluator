"""The HTTP API: starting runs and streaming their progress as Server-Sent Events."""

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from policy_drafter.api import create_app
from policy_drafter.config import Settings
from policy_drafter.events import DraftCompleted, TokenEmitted
from policy_drafter.llm import LLMs
from policy_drafter.runs import Run
from tests.conftest import ScriptedLLM, scores_json

PASS = scores_json("clarity", 9, "Good.")
FAIL = scores_json("clarity", 4)
BODY = {"request": "Draft an AI use policy", "rubric_id": "clarity", "max_iterations": 3}


def settings(**overrides: Any) -> Settings:
    return Settings(llm_mode="fake", _env_file=None, **overrides)  # type: ignore[call-arg]


def scripted(**scripts: Any) -> Callable[[], LLMs]:
    def factory() -> LLMs:
        llm = ScriptedLLM.build(**scripts)
        return LLMs(evaluator=llm, worker=llm)

    return factory


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(settings(), llm_factory=scripted(evaluator=[FAIL, PASS]))
    with TestClient(app) as test_client:
        yield test_client


def read_events(
    client: TestClient, run_id: str, headers: dict[str, str] | None = None
) -> list[tuple[int, dict[str, Any]]]:
    """Parse the SSE stream into (id, payload) pairs."""
    response = client.get(f"/api/runs/{run_id}/events", headers=headers or {})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if "data" in fields:
            events.append((int(fields["id"]), json.loads(fields["data"])))
    return events


def start_run(client: TestClient, body: dict[str, Any] = BODY) -> str:
    response = client.post("/api/runs", json=body)
    assert response.status_code == 201, response.text
    run_id: str = response.json()["id"]
    return run_id


def test_health_needs_no_credentials() -> None:
    app = create_app(settings(api_access_token=SecretStr("s3cret")))

    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_tells_the_ui_what_it_can_offer(client: TestClient) -> None:
    meta = client.get("/api/meta").json()

    assert meta["llm_mode"] == "fake"
    assert meta["auth_required"] is False
    assert meta["max_iterations"] == {"default": 4, "limit": 8}
    assert {rubric["id"] for rubric in meta["rubrics"]} == {
        "completeness",
        "regulatory_coverage",
        "clarity",
        "tone",
    }
    clarity = next(rubric for rubric in meta["rubrics"] if rubric["id"] == "clarity")
    assert clarity["criteria"][0]["id"] == "plain_language"


def test_a_run_streams_every_iteration_then_ends(client: TestClient) -> None:
    run_id = start_run(client)

    events = read_events(client, run_id)

    types = [payload["type"] for _, payload in events if payload["type"] != "token"]
    assert types[0] == "run_started"
    assert types.count("iteration_started") == 2
    assert types.count("evaluation_completed") == 2
    assert types[-1] == "run_finished"
    assert events[-1][1]["stop_reason"] == "passed"
    assert events[-1][1]["final_iteration"] == 2


def test_event_ids_increase_so_a_client_can_resume(client: TestClient) -> None:
    run_id = start_run(client)

    ids = [event_id for event_id, _ in read_events(client, run_id)]

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_evaluation_events_carry_scores_for_the_chart(client: TestClient) -> None:
    run_id = start_run(client)

    evaluations = [
        payload
        for _, payload in read_events(client, run_id)
        if payload["type"] == "evaluation_completed"
    ]

    first = evaluations[0]["evaluation"]
    assert first["all_passed"] is False
    assert first["scores"][0] == {
        "criterion_id": "plain_language",
        "name": "Plain language",
        "score": 4.0,
        "threshold": 7.0,
        "passed": False,
        "feedback": "Needs work.",
    }


def test_last_event_id_resumes_without_repeating_events(client: TestClient) -> None:
    run_id = start_run(client)
    everything = read_events(client, run_id)
    lifecycle = [event for event in everything if event[1]["type"] != "token"]
    cursor = lifecycle[3][0]

    resumed = read_events(client, run_id, headers={"Last-Event-ID": str(cursor)})

    assert all(event_id > cursor for event_id, _ in resumed)
    assert [e for e in resumed if e[1]["type"] != "token"] == lifecycle[4:]


def test_tokens_from_finished_phases_are_not_replayed() -> None:
    """Completed events hold the full text, so a late subscriber does not need old tokens."""
    run = Run("run")
    run.publish(TokenEmitted(iteration=1, phase="draft", text="partial "))
    run.publish(TokenEmitted(iteration=1, phase="draft", text="draft"))
    assert [seq for seq, _ in run.events_after(0)] == [1, 2]

    run.publish(DraftCompleted(iteration=1, draft="partial draft"))

    assert [(seq, event.type) for seq, event in run.events_after(0)] == [(3, "draft_completed")]


def test_a_live_subscriber_is_woken_by_events_from_the_worker_thread() -> None:
    run = Run("run")
    run.publish(TokenEmitted(iteration=1, phase="draft", text="first"))

    def finish_from_another_thread() -> None:
        run.publish(DraftCompleted(iteration=1, draft="first"))
        run.finish()

    async def collect() -> list[str]:
        received: list[str] = []
        async for _, event in run.follow():
            received.append(event.type)
            if len(received) == 1:
                threading.Thread(target=finish_from_another_thread).start()
        return received

    assert asyncio.run(asyncio.wait_for(collect(), timeout=5)) == ["token", "draft_completed"]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**BODY, "rubric_id": "nope"}, id="unknown-rubric"),
        pytest.param({**BODY, "max_iterations": 0}, id="too-few-iterations"),
        pytest.param({**BODY, "max_iterations": 99}, id="too-many-iterations"),
        pytest.param({**BODY, "threshold": 11}, id="threshold-off-scale"),
        pytest.param({**BODY, "request": "   "}, id="blank-request"),
        pytest.param({"rubric_id": "clarity"}, id="missing-request"),
    ],
)
def test_invalid_runs_are_rejected(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/runs", json=body).status_code == 422


def test_unknown_run_is_a_404(client: TestClient) -> None:
    assert client.get("/api/runs/does-not-exist/events").status_code == 404


def test_concurrent_runs_are_limited_because_each_one_costs_money() -> None:
    release = threading.Event()

    def gated(prompt: str) -> str:
        release.wait(timeout=10)
        return PASS

    app = create_app(settings(max_concurrent_runs=1), llm_factory=scripted(evaluator=[gated]))
    with TestClient(app) as client:
        first = start_run(client)
        refused = client.post("/api/runs", json=BODY)
        release.set()
        read_events(client, first)
        accepted = client.post("/api/runs", json=BODY)

    assert refused.status_code == 429
    assert accepted.status_code == 201


def test_llm_failure_ends_the_stream_with_an_error_stop_reason() -> None:
    app = create_app(settings(), llm_factory=scripted(drafter=[RuntimeError("Access denied")]))
    with TestClient(app) as client:
        events = read_events(client, start_run(client))

    last = events[-1][1]
    assert last["type"] == "run_finished"
    assert last["stop_reason"] == "error"
    assert "Access denied" in last["error"]


def test_finished_runs_are_evicted_beyond_the_retention_limit() -> None:
    app = create_app(settings(max_retained_runs=2), llm_factory=scripted(evaluator=[PASS]))
    with TestClient(app) as client:
        first = start_run(client)
        read_events(client, first)
        second = start_run(client)
        read_events(client, second)
        third = start_run(client)
        read_events(client, third)

        assert client.get(f"/api/runs/{first}/events").status_code == 404
        assert client.get(f"/api/runs/{third}/events").status_code == 200


class TestAccessToken:
    @pytest.fixture
    def secured(self) -> Iterator[TestClient]:
        app = create_app(
            settings(api_access_token=SecretStr("s3cret")),
            llm_factory=scripted(evaluator=[PASS]),
        )
        with TestClient(app) as client:
            yield client

    def test_meta_is_public_and_says_a_token_is_needed(self, secured: TestClient) -> None:
        assert secured.get("/api/meta").json()["auth_required"] is True

    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param({}, id="missing"),
            pytest.param({"Authorization": "Bearer wrong"}, id="wrong"),
            pytest.param({"Authorization": "s3cret"}, id="not-bearer"),
        ],
    )
    def test_rejects_bad_credentials(self, secured: TestClient, headers: dict[str, str]) -> None:
        assert secured.post("/api/runs", json=BODY, headers=headers).status_code == 401
        assert secured.get("/api/runs/any/events", headers=headers).status_code == 401

    def test_accepts_the_right_token(self, secured: TestClient) -> None:
        headers = {"Authorization": "Bearer s3cret"}

        response = secured.post("/api/runs", json=BODY, headers=headers)

        assert response.status_code == 201
        assert read_events(secured, response.json()["id"], headers=headers)[-1][1]["type"] == (
            "run_finished"
        )


def test_serves_the_built_ui_when_configured(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>Policy Drafter</title>")

    with TestClient(create_app(settings(web_dist=tmp_path))) as client:
        assert "Policy Drafter" in client.get("/").text
        assert client.get("/api/health").json() == {"status": "ok"}


def test_a_blank_access_token_is_treated_as_unset_and_bedrock_mode_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(llm_mode="bedrock", api_access_token="  ")  # type: ignore[arg-type]

    with caplog.at_level("WARNING"):
        app = create_app(
            settings,
            llm_factory=lambda: LLMs(evaluator=ScriptedLLM.build(), worker=ScriptedLLM.build()),
        )

    assert settings.api_access_token is None
    assert "API_ACCESS_TOKEN is not set" in caplog.text
    assert app is not None
