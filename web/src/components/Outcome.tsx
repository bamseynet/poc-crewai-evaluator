import { exportFilename, exportMarkdown } from "../exportMarkdown";
import type { RunView } from "../runState";
import type { StopReason } from "../types";

const TONE: Record<StopReason, string> = {
  passed: "success",
  max_iterations: "warning",
  evaluator_error: "warning",
  error: "danger",
};

function headline(run: RunView): string {
  const outcome = run.outcome;
  switch (outcome?.stopReason) {
    case "passed":
      return `Passed at iteration ${outcome.finalIteration}. Every criterion met its pass mark.`;
    case "max_iterations":
      return `Stopped at the limit of ${run.maxIterations} iterations without passing every criterion. Showing the best draft, from iteration ${outcome.finalIteration}.`;
    case "evaluator_error":
      return "Stopped because the evaluator's replies could not be parsed, so this draft is unverified.";
    case "error":
      return `Stopped by an error: ${outcome.error ?? "unknown error"}`;
    default:
      return "";
  }
}

function download(run: RunView) {
  const url = URL.createObjectURL(new Blob([exportMarkdown(run)], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = exportFilename(run);
  link.click();
  // Some browsers start the download asynchronously, so the URL must outlive the click.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function OutcomeBanner({ run }: { run: RunView }) {
  if (!run.outcome) return null;
  return (
    <div className={`outcome ${TONE[run.outcome.stopReason]}`} role="status">
      <div>
        <p className="outcome-reason">
          Stop reason: <code>{run.outcome.stopReason}</code>
        </p>
        <p>{headline(run)}</p>
      </div>
      {run.outcome.finalDraft !== null && (
        <button type="button" className="primary" onClick={() => download(run)}>
          Export Markdown
        </button>
      )}
    </div>
  );
}

export function FinalDraft({ run }: { run: RunView }) {
  if (run.outcome?.finalDraft == null) return null;
  return <pre className="document">{run.outcome.finalDraft}</pre>;
}
