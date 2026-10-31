"""What actually goes over the wire in `LLM_MODE=bedrock`, without touching AWS.

A local HTTP server stands in for the Bedrock runtime endpoint and speaks its Converse protocol,
so these tests run the real path through CrewAI, LiteLLM and botocore's request signing.
"""

import binascii
import json
import struct
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from policy_drafter.config import DEFAULT_MODEL_ID, DEFAULT_WORKER_MODEL_ID, Settings
from policy_drafter.events import ProgressEvent, TokenEmitted
from policy_drafter.flow import run_drafting
from policy_drafter.llm import build_llms
from policy_drafter.models import RunConfig, StopReason
from tests.conftest import scores_json

PASSING = scores_json("clarity", 9, "Good.")


@dataclass
class Recorded:
    path: str
    body: dict[str, Any]
    authorization: str


def _event_frame(event_type: str, payload: dict[str, Any]) -> bytes:
    """Encode one message in AWS's binary event-stream format."""
    headers = b""
    for name, value in (
        (":event-type", event_type),
        (":content-type", "application/json"),
        (":message-type", "event"),
    ):
        encoded = value.encode()
        headers += bytes([len(name)]) + name.encode() + b"\x07"
        headers += struct.pack(">H", len(encoded)) + encoded
    body = json.dumps(payload).encode()
    prelude = struct.pack(">II", 16 + len(headers) + len(body), len(headers))
    message = prelude + struct.pack(">I", binascii.crc32(prelude)) + headers + body
    return message + struct.pack(">I", binascii.crc32(message))


def _stream_reply(text: str) -> bytes:
    middle = len(text) // 2
    return b"".join(
        [
            _event_frame("messageStart", {"role": "assistant"}),
            _event_frame(
                "contentBlockDelta",
                {
                    "contentBlockIndex": 0,
                    "delta": {"reasoningContent": {"text": "SECRET-THINKING"}},
                },
            ),
            _event_frame("contentBlockStop", {"contentBlockIndex": 0}),
            _event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"text": text[:middle]}},
            ),
            _event_frame(
                "contentBlockDelta",
                {"contentBlockIndex": 1, "delta": {"text": text[middle:]}},
            ),
            _event_frame("contentBlockStop", {"contentBlockIndex": 1}),
            _event_frame("messageStop", {"stopReason": "end_turn"}),
            _event_frame(
                "metadata",
                {
                    "usage": {"inputTokens": 3, "outputTokens": 4, "totalTokens": 7},
                    "metrics": {"latencyMs": 1},
                },
            ),
        ]
    )


@dataclass
class FakeBedrock:
    requests: list[Recorded] = field(default_factory=list)


@pytest.fixture
def bedrock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeBedrock]:
    fake = FakeBedrock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            fake.requests.append(Recorded(self.path, body, self.headers["authorization"]))
            # Only the evaluator is asked for JSON.
            is_evaluator = "Compliance Evaluator" in json.dumps(body["system"])
            reply = _stream_reply(PASSING if is_evaluator else "Generated text.")
            self.send_response(200)
            self.send_header("content-type", "application/vnd.amazon.eventstream")
            self.send_header("content-length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AWS_BEDROCK_RUNTIME_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-only")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-only")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    yield fake
    server.shutdown()
    server.server_close()
    thread.join()


def _run(region: str = "us-west-2") -> tuple[StopReason | None, str | None, list[ProgressEvent]]:
    settings = Settings(llm_mode="bedrock", aws_region=region, _env_file=None)  # type: ignore[call-arg]
    events: list[ProgressEvent] = []
    state = run_drafting(
        RunConfig(request="A policy", rubric_id="clarity", max_iterations=1),
        build_llms(settings),
        on_event=events.append,
    )
    return state.stop_reason, state.error, events


def test_each_tier_calls_its_configured_inference_profile(bedrock: FakeBedrock) -> None:
    stop_reason, error, _ = _run()

    assert stop_reason is StopReason.PASSED, error
    by_role = {
        (
            "evaluator" if "Compliance Evaluator" in json.dumps(r.body["system"]) else "worker"
        ): r.path
        for r in bedrock.requests
    }
    assert by_role == {
        "evaluator": f"/model/{DEFAULT_MODEL_ID}/converse-stream",
        "worker": f"/model/{DEFAULT_WORKER_MODEL_ID}/converse-stream",
    }


def test_requests_are_signed_for_the_configured_region(bedrock: FakeBedrock) -> None:
    _run(region="eu-west-1")

    assert bedrock.requests
    for request in bedrock.requests:
        assert "/eu-west-1/bedrock/aws4_request" in request.authorization


def test_sampling_parameters_are_not_sent(bedrock: FakeBedrock) -> None:
    _run()

    for request in bedrock.requests:
        config = request.body["inferenceConfig"]
        assert "temperature" not in config
        assert "topP" not in config
        assert config["maxTokens"] > 0


def test_answer_text_streams_as_tokens_and_thinking_stays_out_of_the_draft(
    bedrock: FakeBedrock,
) -> None:
    stop_reason, error, events = _run()

    assert stop_reason is StopReason.PASSED, error
    tokens = [e for e in events if isinstance(e, TokenEmitted)]
    assert "".join(t.text for t in tokens if t.phase == "draft") == "Generated text."
    finished = events[-1]
    assert finished.type == "run_finished"
    assert finished.final_draft == "Generated text."
    assert "SECRET-THINKING" not in (finished.final_draft or "")
