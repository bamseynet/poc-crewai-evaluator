import type { RunView } from "./runState";

/** The final draft as a Markdown file, with front matter recording how it was produced. */
export function exportMarkdown(run: RunView): string {
  const outcome = run.outcome;
  const final = run.iterations.find((iteration) => iteration.number === outcome?.finalIteration);
  const scores = final?.evaluation?.scores ?? [];
  const passed = outcome?.stopReason === "passed";

  const frontMatter = [
    "---",
    `status: ${quote(
      passed
        ? "AI-generated draft, requires legal and compliance review"
        : "AI-generated draft, did not pass every criterion, requires legal and compliance review",
    )}`,
    `request: ${quote(run.request)}`,
    `rubric: ${quote(run.rubric?.id ?? "")}`,
    `stop_reason: ${quote(outcome?.stopReason ?? "")}`,
    `iteration: ${outcome?.finalIteration ?? "null"}`,
    "scores:",
    ...scores.map(
      (score) =>
        `  ${score.criterion_id}: {score: ${score.score ?? "null"}, ` +
        `pass_mark: ${score.threshold}, passed: ${score.passed}}`,
    ),
    "---",
  ].join("\n");

  return `${frontMatter}\n\n${outcome?.finalDraft ?? ""}\n`;
}

export function exportFilename(run: RunView): string {
  return `policy-draft-iteration-${run.outcome?.finalIteration ?? "none"}.md`;
}

/** A JSON string is also a valid double-quoted YAML string. */
function quote(value: string): string {
  return JSON.stringify(value);
}
