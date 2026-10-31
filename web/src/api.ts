import { SseParser } from "./sse";
import type { Meta, ProgressEvent, RunRequest } from "./types";

const MAX_RECONNECTS = 5;
const RECONNECT_BASE_MS = 500;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function authHeaders(token: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorFrom(response: Response): Promise<ApiError> {
  const fallback = `The server returned ${response.status}.`;
  try {
    const { detail } = (await response.json()) as { detail?: unknown };
    if (typeof detail === "string") return new ApiError(response.status, detail);
    if (Array.isArray(detail)) {
      const messages = detail.map((item: { msg?: string }) => item.msg).filter(Boolean);
      return new ApiError(response.status, messages.join(" ") || fallback);
    }
  } catch {
    // The body was not JSON, so the status code is all there is to report.
  }
  return new ApiError(response.status, fallback);
}

export async function fetchMeta(): Promise<Meta> {
  const response = await fetch("/api/meta");
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as Meta;
}

export async function createRun(body: RunRequest, token: string): Promise<string> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  const { id } = (await response.json()) as { id: string };
  return id;
}

interface FollowOptions {
  token: string;
  signal: AbortSignal;
  onEvent: (event: ProgressEvent) => void;
  onConnectionChange: (connected: boolean) => void;
  reconnectBaseMs?: number;
}

/**
 * Streams a run's events until it finishes. A dropped connection resumes from the last event seen,
 * which matters for long-running real models behind load balancers.
 */
function isTransient(status: number): boolean {
  return status === 429 || status >= 500;
}

export async function followRun(runId: string, options: FollowOptions): Promise<void> {
  const { token, signal, onEvent, onConnectionChange } = options;
  const baseDelay = options.reconnectBaseMs ?? RECONNECT_BASE_MS;
  let lastEventId = 0;
  let failures = 0;

  for (;;) {
    try {
      const response = await fetch(`/api/runs/${runId}/events`, {
        headers: { "Last-Event-ID": String(lastEventId), ...authHeaders(token) },
        signal,
      });
      if (!response.ok) throw await errorFrom(response);
      if (!response.body) throw new Error("The response has no body to stream.");
      onConnectionChange(true);

      const parser = new SseParser();
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const message of parser.feed(value)) {
          const event = JSON.parse(message.data) as ProgressEvent;
          onEvent(event);
          // Reset only once the event was handled, or a message that always fails to parse or
          // apply would be replayed on every reconnect and never reach the retry limit.
          failures = 0;
          // Only after the event was delivered, so a failure here does not skip it on resume.
          if (message.id !== null) lastEventId = message.id;
          if (event.type === "run_finished") return;
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      // The server answered and said no, so retrying would not help. Gateway errors and
      // throttling from a proxy in front of it are different: the run is probably still going.
      if (error instanceof ApiError && !isTransient(error.status)) throw error;
    }

    failures++;
    if (failures > MAX_RECONNECTS) {
      throw new Error("Lost the connection to the server.");
    }
    onConnectionChange(false);
    await new Promise((resolve) => setTimeout(resolve, baseDelay * 2 ** (failures - 1)));
    if (signal.aborted) return;
  }
}
