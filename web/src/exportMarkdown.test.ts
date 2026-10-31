import { describe, expect, it } from "vitest";
import { exportFilename, exportMarkdown } from "./exportMarkdown";
import { initialRun, runReducer, type RunView } from "./runState";
import { evaluation, iterationEvents, started } from "./testing/fixtures";
import type { ProgressEvent, StopReason } from "./types";

function finishedRun(stopReason: StopReason, draft = "# Policy\n\nBody."): RunView {
  const events: ProgressEvent[] = [
    started,
    ...iterationEvents(1, draft, evaluation(9, 6)),
    {
      type: "run_finished",
      stop_reason: stopReason,
      iterations: 1,
      final_iteration: 1,
      final_draft: draft,
      error: null,
    },
  ];
  return events.reduce(runReducer, initialRun);
}

describe("exportMarkdown", () => {
  it("is the final draft preceded by front matter", () => {
    const markdown = exportMarkdown(finishedRun("passed"));

    expect(markdown.startsWith("---\n")).toBe(true);
    expect(markdown.endsWith("---\n\n# Policy\n\nBody.\n")).toBe(true);
  });

  it("records how the draft was produced", () => {
    const markdown = exportMarkdown(finishedRun("passed"));

    expect(markdown).toContain('rubric: "clarity"');
    expect(markdown).toContain('stop_reason: "passed"');
    expect(markdown).toContain("iteration: 1");
    expect(markdown).toContain('plain_language: {score: 9, pass_mark: 7, passed: true}');
    expect(markdown).toContain('actionable: {score: 6, pass_mark: 8, passed: false}');
  });

  it("says plainly that a human still has to review it", () => {
    expect(exportMarkdown(finishedRun("passed"))).toContain(
      'status: "AI-generated draft, requires legal and compliance review"',
    );
  });

  it("flags a draft that did not meet the quality bar", () => {
    expect(exportMarkdown(finishedRun("max_iterations"))).toContain(
      'status: "AI-generated draft, did not pass every criterion, requires legal and compliance review"',
    );
  });

  it("quotes the request so that YAML special characters are safe", () => {
    const run = { ...finishedRun("passed"), request: 'A "quoted": request\nwith a newline' };

    expect(exportMarkdown(run)).toContain('request: "A \\"quoted\\": request\\nwith a newline"');
  });

  it("names the file after the iteration", () => {
    expect(exportFilename(finishedRun("passed"))).toBe("policy-draft-iteration-1.md");
  });
});
