import { useEffect, useRef } from "react";
import type { IterationView, RunView } from "../runState";
import type { Phase } from "../types";

const PHASES: { id: Phase; label: string }[] = [
  { id: "research", label: "Research" },
  { id: "draft", label: "Draft" },
  { id: "evaluate", label: "Evaluate" },
];

const ACTIVITY: Record<Phase, string> = {
  research: "Researcher is gathering notes",
  draft: "Drafter is writing",
  evaluate: "Evaluator is scoring",
};

export function RunTimeline({ run }: { run: RunView }) {
  return (
    <ol className="timeline" aria-label="Iterations">
      {run.iterations.map((iteration) => (
        <IterationCard key={iteration.number} iteration={iteration} run={run} />
      ))}
    </ol>
  );
}

function IterationCard({ iteration, run }: { iteration: IterationView; run: RunView }) {
  const failing = iteration.evaluation?.scores.filter((score) => !score.passed) ?? [];
  const isLast = iteration.number === run.iterations.at(-1)?.number;

  return (
    <li className="iteration">
      <header className="iteration-header">
        <h3>Iteration {iteration.number}</h3>
        <ol className="phases">
          {PHASES.map((phase) => (
            <li key={phase.id} className={phaseClass(iteration, phase.id)}>
              {phase.label}
              <span className="visually-hidden">: {phaseStatus(iteration, phase.id)}</span>
            </li>
          ))}
        </ol>
      </header>

      {iteration.phase && (
        <LiveOutput
          activity={ACTIVITY[iteration.phase]}
          text={iteration.live}
          // Evaluator output is JSON, which is summarised below once it has been parsed.
          raw={iteration.phase === "evaluate"}
        />
      )}
      {iteration.evaluationRetried && (
        <p className="note">
          The evaluator's reply could not be parsed, so it was asked to score the draft again.
        </p>
      )}

      {iteration.evaluation && (
        <>
          <p className="verdict">
            {verdict(iteration, failing.length, isLast, run.status === "finished")}
          </p>
          {iteration.evaluation.warnings.length > 0 && (
            <ul className="warnings">
              {iteration.evaluation.warnings.map((warning, index) => (
                <li key={`${index}-${warning}`}>{warning}</li>
              ))}
            </ul>
          )}
          {failing.length > 0 && (
            <details open={isLast}>
              <summary>Feedback sent to the drafter ({failing.length})</summary>
              <dl className="feedback">
                {failing.map((score) => (
                  <div key={score.criterion_id}>
                    <dt>
                      {score.name}{" "}
                      <span className="pass-mark">
                        {score.score ?? "not scored"} / needs {score.threshold}
                      </span>
                    </dt>
                    <dd>{score.feedback}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </>
      )}

      {iteration.research && (
        <details>
          <summary>Research notes</summary>
          <pre className="document">{iteration.research}</pre>
        </details>
      )}
    </li>
  );
}

function LiveOutput({ activity, text, raw }: { activity: string; text: string; raw: boolean }) {
  const scroller = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const element = scroller.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [text]);

  return (
    <div className="live">
      <p className="activity" role="status">
        <span className="pulse" aria-hidden="true" />
        {activity}…
      </p>
      {text && (
        <pre ref={scroller} className={raw ? "live-text raw" : "live-text"} aria-hidden="true">
          {text}
        </pre>
      )}
    </div>
  );
}

function verdict(
  iteration: IterationView,
  failing: number,
  isLast: boolean,
  finished: boolean,
): string {
  const scores = iteration.evaluation?.scores ?? [];
  if (scores.length === 0) return "The evaluator's reply contained no usable scores.";
  const summary = `${scores.length - failing} of ${scores.length} criteria passed`;
  if (failing === 0) return `${summary}.`;
  if (isLast && finished) return `${summary}. The loop stopped here.`;
  return `${summary}, so the draft goes back for revision.`;
}

function phaseClass(iteration: IterationView, phase: Phase): string {
  if (iteration.completedPhases.includes(phase)) return "phase done";
  return iteration.phase === phase ? "phase active" : "phase";
}

function phaseStatus(iteration: IterationView, phase: Phase): string {
  if (iteration.completedPhases.includes(phase)) return "done";
  return iteration.phase === phase ? "in progress" : "waiting";
}
