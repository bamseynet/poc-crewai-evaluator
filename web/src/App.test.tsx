import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { evaluation, iterationEvents, rubric, started } from "./testing/fixtures";
import type { Meta, ProgressEvent } from "./types";

const meta: Meta = {
  llm_mode: "fake",
  auth_required: false,
  max_iterations: { default: 4, limit: 8 },
  rubrics: [rubric],
};

const events: ProgressEvent[] = [
  started,
  ...iterationEvents(1, "Staff should comply.", evaluation(4, 5)),
  ...iterationEvents(2, "Staff must comply.", evaluation(9, 9)),
  {
    type: "run_finished",
    stop_reason: "passed",
    iterations: 2,
    final_iteration: 2,
    final_draft: "Staff must comply.",
    error: null,
  },
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function stream(items: ProgressEvent[]): Response {
  const text = items
    .map((event, index) => `id: ${index + 1}\ndata: ${JSON.stringify(event)}\n\n`)
    .join("");
  return new Response(text, { status: 200 });
}

function stubServer(run: () => Response) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/meta") return json(meta);
    if (url === "/api/runs") return run();
    return stream(events);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("App", () => {
  beforeEach(() => sessionStorage.clear());

  it("explains the pattern and names the LLM mode before anything has run", async () => {
    stubServer(() => json({ id: "r1" }, 201));
    render(<App />);

    expect(await screen.findByText("Fake LLM, offline")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How the loop works" })).toBeInTheDocument();
  });

  it("runs a request through to a final draft", async () => {
    const user = userEvent.setup();
    stubServer(() => json({ id: "r1" }, 201));
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Run the loop" }));

    const outcome = await screen.findByText(/Passed at iteration 2/);
    expect(within(outcome.closest(".outcome") as HTMLElement).getByText("passed")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Iteration 2" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Score history" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Compare drafts" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Final draft (iteration 2)" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "How the loop works" })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Run the loop" })).toBeEnabled(),
    );
  });

  it("exports the final draft as a Markdown file", async () => {
    const user = userEvent.setup();
    stubServer(() => json({ id: "r1" }, 201));
    let exported: Blob | undefined;
    vi.stubGlobal("URL", {
      createObjectURL: (blob: Blob) => {
        exported = blob;
        return "blob:test";
      },
      revokeObjectURL: () => {},
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Run the loop" }));
    await user.click(await screen.findByRole("button", { name: "Export Markdown" }));

    expect(click).toHaveBeenCalledOnce();
    const text = await exported?.text();
    expect(text).toContain("Staff must comply.");
    expect(text).toContain('stop_reason: "passed"');
  });

  it("shows the server's explanation when a run is refused", async () => {
    const user = userEvent.setup();
    stubServer(() => json({ detail: "Too many runs in progress." }, 429));
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Run the loop" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many runs in progress.");
    expect(screen.getByRole("button", { name: "Run the loop" })).toBeEnabled();
  });

  it("says when an access token is rejected", async () => {
    const user = userEvent.setup();
    stubServer(() => json({ detail: "A valid access token is required." }, 401));
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Run the loop" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("access token was not accepted");
  });

  it("shows a run that stopped at the iteration limit as a warning, not a success", async () => {
    const user = userEvent.setup();
    const limited: ProgressEvent[] = [
      started,
      ...iterationEvents(1, "One", evaluation(4, 5)),
      {
        type: "run_finished",
        stop_reason: "max_iterations",
        iterations: 1,
        final_iteration: 1,
        final_draft: "One",
        error: null,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/meta") return json(meta);
        if (url === "/api/runs") return json({ id: "r1" }, 201);
        return stream(limited);
      }),
    );
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Run the loop" }));

    const message = await screen.findByText(/without passing every criterion/);
    expect(message.closest(".outcome")).toHaveClass("warning");
  });
});
