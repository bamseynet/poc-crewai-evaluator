import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialRun, runReducer } from "../runState";
import { evaluation, iterationEvents, started } from "../testing/fixtures";
import type { ProgressEvent } from "../types";
import { RunTimeline } from "./RunTimeline";

function renderAfter(events: ProgressEvent[]) {
  render(<RunTimeline run={events.reduce(runReducer, initialRun)} />);
}

describe("RunTimeline", () => {
  it("shows text streaming into the current phase", () => {
    renderAfter([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "phase_started", iteration: 1, phase: "draft" },
      { type: "token", iteration: 1, phase: "draft", text: "# Policy " },
      { type: "token", iteration: 1, phase: "draft", text: "text" },
    ]);

    expect(screen.getByRole("status")).toHaveTextContent("Drafter is writing");
    expect(screen.getByText("# Policy text")).toBeInTheDocument();
  });

  it("marks finished, active and waiting phases for screen readers", () => {
    renderAfter([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "phase_started", iteration: 1, phase: "research" },
      { type: "research_completed", iteration: 1, research: "n" },
      { type: "phase_started", iteration: 1, phase: "draft" },
    ]);

    expect(screen.getByText("Research").textContent).toContain("done");
    expect(screen.getByText("Draft").textContent).toContain("in progress");
    expect(screen.getByText("Evaluate").textContent).toContain("waiting");
  });

  it("says when a draft goes back for revision and shows the feedback", () => {
    renderAfter([started, ...iterationEvents(1, "One", evaluation(9, 5))]);

    expect(screen.getByText(/1 of 2 criteria passed, so the draft goes back/)).toBeInTheDocument();
    const feedback = screen.getByText(/Feedback sent to the drafter \(1\)/);
    expect(within(feedback.closest("details") as HTMLElement).getByText("Actionable")).toBeTruthy();
    expect(screen.getByText("Needs work.")).toBeInTheDocument();
  });

  it("shows no feedback section when every criterion passed", () => {
    renderAfter([started, ...iterationEvents(1, "One", evaluation(9, 9))]);

    expect(screen.getByText("2 of 2 criteria passed.")).toBeInTheDocument();
    expect(screen.queryByText(/Feedback sent/)).not.toBeInTheDocument();
  });

  it("does not claim '0 of 0 criteria passed' when nothing could be scored", () => {
    const unscored = { scores: [], parse_ok: false, warnings: ["a", "a"], all_passed: false };
    renderAfter([started, ...iterationEvents(1, "One", unscored)]);

    expect(screen.queryByText(/0 of 0/)).not.toBeInTheDocument();
    expect(screen.getByText(/no usable scores/)).toBeInTheDocument();
  });

  it("says so when every criterion came back unscored", () => {
    renderAfter([started, ...iterationEvents(1, "One", evaluation(null, null))]);

    expect(screen.getByText(/no usable scores/)).toBeInTheDocument();
    expect(screen.queryByText(/goes back for revision/)).not.toBeInTheDocument();
  });

  it("reports an evaluator retry", () => {
    renderAfter([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "evaluation_retried", iteration: 1, warnings: [] },
    ]);

    expect(screen.getByText(/was not usable/)).toBeInTheDocument();
  });

  it("renders an iteration per round of the loop", () => {
    renderAfter([
      started,
      ...iterationEvents(1, "One", evaluation(4, 5)),
      ...iterationEvents(2, "Two", evaluation(9, 9)),
    ]);

    expect(screen.getByRole("heading", { name: "Iteration 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Iteration 2" })).toBeInTheDocument();
  });
});
