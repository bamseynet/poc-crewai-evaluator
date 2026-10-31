import { describe, expect, it, vi } from "vitest";
import { ApiError, createRun, followRun } from "./api";
import type { ProgressEvent } from "./types";

const finished: ProgressEvent = {
  type: "run_finished",
  stop_reason: "passed",
  iterations: 1,
  final_iteration: 1,
  final_draft: "Draft",
  error: null,
};

function sse(events: [number, ProgressEvent][]): string {
  return events.map(([id, event]) => `id: ${id}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

function streamResponse(...chunks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

function follow(onEvent: (event: ProgressEvent) => void = () => {}, token = "") {
  return followRun("abc", {
    token,
    signal: new AbortController().signal,
    onEvent,
    onConnectionChange: () => {},
    reconnectBaseMs: 1,
  });
}

describe("followRun", () => {
  it("delivers events until the run finishes", async () => {
    const started: ProgressEvent = { type: "iteration_started", iteration: 1 };
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse(
        sse([
          [1, started],
          [2, finished],
        ]),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const events: ProgressEvent[] = [];

    await follow((event) => events.push(event));

    expect(events).toEqual([started, finished]);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("resumes from the last event after a dropped connection", async () => {
    const started: ProgressEvent = { type: "iteration_started", iteration: 1 };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(streamResponse(sse([[7, started]])))
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockResolvedValueOnce(streamResponse(sse([[8, finished]])));
    vi.stubGlobal("fetch", fetchMock);
    const events: ProgressEvent[] = [];

    await follow((event) => events.push(event));

    expect(events).toEqual([started, finished]);
    expect(fetchMock.mock.calls.at(-1)?.[1].headers["Last-Event-ID"]).toBe("7");
  });

  it("gives up after repeated failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network error")));

    await expect(follow()).rejects.toThrow("Lost the connection");
  });

  it("does not retry when the server refuses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: "Unknown run." }), { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(follow()).rejects.toThrow("Unknown run.");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("keeps following through a gateway error from a proxy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("Bad gateway", { status: 502 }))
      .mockResolvedValueOnce(streamResponse(sse([[1, finished]])));
    vi.stubGlobal("fetch", fetchMock);
    const events: ProgressEvent[] = [];

    await follow((event) => events.push(event));

    expect(events).toEqual([finished]);
  });

  it("sends the access token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse(sse([[1, finished]])));
    vi.stubGlobal("fetch", fetchMock);

    await follow(() => {}, "s3cret");

    expect(fetchMock.mock.calls[0]?.[1].headers.Authorization).toBe("Bearer s3cret");
  });
});

describe("createRun", () => {
  const body = { request: "x", rubric_id: "tone", max_iterations: 2, threshold: null };

  it("returns the run id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "r1" }), { status: 201 })),
    );

    await expect(createRun(body, "")).resolves.toBe("r1");
  });

  it("surfaces validation messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: [{ msg: "Too long" }] }), { status: 422 }),
        ),
    );

    await expect(createRun(body, "")).rejects.toThrow("Too long");
  });

  it("keeps the status so the UI can ask for a token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "No." }), { status: 401 })),
    );

    await expect(createRun(body, "")).rejects.toMatchObject({ status: 401 } satisfies Partial<ApiError>);
  });
});
