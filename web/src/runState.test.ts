import { describe, expect, it } from "vitest";
import { initialRun, runReducer, type RunView } from "./runState";
import { evaluation, iterationEvents, started } from "./testing/fixtures";
import type { ProgressEvent } from "./types";

function play(events: ProgressEvent[]): RunView {
  return events.reduce(runReducer, initialRun);
}

describe("runReducer", () => {
  it("starts idle", () => {
    expect(initialRun.status).toBe("idle");
    expect(initialRun.iterations).toEqual([]);
  });

  it("records the run settings when the run starts", () => {
    const run = play([started]);

    expect(run.status).toBe("running");
    expect(run.request).toBe("Draft an AI policy");
    expect(run.rubric?.id).toBe("clarity");
    expect(run.maxIterations).toBe(3);
  });

  it("tracks the current phase of the current iteration", () => {
    const run = play([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "phase_started", iteration: 1, phase: "research" },
    ]);

    expect(run.iterations).toHaveLength(1);
    expect(run.iterations[0]?.phase).toBe("research");
    expect(run.iterations[0]?.completedPhases).toEqual([]);
  });

  it("accumulates streamed tokens per phase", () => {
    const run = play([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "phase_started", iteration: 1, phase: "research" },
      { type: "token", iteration: 1, phase: "research", text: "Hello " },
      { type: "token", iteration: 1, phase: "research", text: "world" },
    ]);

    expect(run.iterations[0]?.live).toBe("Hello world");
  });

  it("clears live text when the next phase starts", () => {
    const run = play([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "phase_started", iteration: 1, phase: "research" },
      { type: "token", iteration: 1, phase: "research", text: "notes" },
      { type: "research_completed", iteration: 1, research: "notes" },
      { type: "phase_started", iteration: 1, phase: "draft" },
    ]);

    expect(run.iterations[0]?.live).toBe("");
    expect(run.iterations[0]?.research).toBe("notes");
    expect(run.iterations[0]?.completedPhases).toEqual(["research"]);
  });

  it("stores the draft and evaluation of each iteration", () => {
    const run = play([
      started,
      ...iterationEvents(1, "One", evaluation(4, 5)),
      ...iterationEvents(2, "Two", evaluation(8, 9)),
    ]);

    expect(run.iterations.map((iteration) => iteration.draft)).toEqual(["One", "Two"]);
    expect(run.iterations[1]?.evaluation?.all_passed).toBe(true);
    expect(run.iterations[1]?.phase).toBeNull();
    expect(run.iterations[1]?.completedPhases).toEqual(["research", "draft", "evaluate"]);
  });

  it("notes an evaluation retry", () => {
    const run = play([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "evaluation_retried", iteration: 1, warnings: ["No usable score"] },
    ]);

    expect(run.iterations[0]?.evaluationRetried).toBe(true);
  });

  it("finishes with the stop reason and final draft", () => {
    const run = play([
      started,
      ...iterationEvents(1, "One", evaluation(8, 9)),
      {
        type: "run_finished",
        stop_reason: "passed",
        iterations: 1,
        final_iteration: 1,
        final_draft: "One",
        error: null,
      },
    ]);

    expect(run.status).toBe("finished");
    expect(run.outcome).toEqual({
      stopReason: "passed",
      finalIteration: 1,
      finalDraft: "One",
      error: null,
    });
  });

  it("ignores an event for an iteration it has not seen rather than crashing", () => {
    const run = play([started, { type: "token", iteration: 9, phase: "draft", text: "x" }]);

    expect(run.iterations).toEqual([]);
  });

  it("does not create duplicates when a reconnect replays iteration_started", () => {
    const run = play([
      started,
      { type: "iteration_started", iteration: 1 },
      { type: "iteration_started", iteration: 1 },
    ]);

    expect(run.iterations).toHaveLength(1);
  });
});
