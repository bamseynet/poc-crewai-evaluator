import type { Evaluation, Phase, ProgressEvent, Rubric, StopReason } from "./types";

export interface IterationView {
  number: number;
  phase: Phase | null;
  completedPhases: Phase[];
  /** Text streaming in for the current phase. */
  live: string;
  research: string | null;
  draft: string | null;
  evaluation: Evaluation | null;
  evaluationRetried: boolean;
}

export interface Outcome {
  stopReason: StopReason;
  finalIteration: number | null;
  finalDraft: string | null;
  error: string | null;
}

export interface RunView {
  status: "idle" | "running" | "finished";
  request: string;
  rubric: Rubric | null;
  maxIterations: number;
  iterations: IterationView[];
  outcome: Outcome | null;
}

export const initialRun: RunView = {
  status: "idle",
  request: "",
  rubric: null,
  maxIterations: 0,
  iterations: [],
  outcome: null,
};

/** Folds the event stream into everything the UI shows. Each event is applied exactly once. */
export function runReducer(run: RunView, event: ProgressEvent): RunView {
  switch (event.type) {
    case "run_started":
      return {
        ...initialRun,
        status: "running",
        request: event.request,
        rubric: event.rubric,
        maxIterations: event.max_iterations,
      };
    case "iteration_started":
      if (run.iterations.some((iteration) => iteration.number === event.iteration)) {
        return run;
      }
      return { ...run, iterations: [...run.iterations, newIteration(event.iteration)] };
    case "phase_started":
      return update(run, event.iteration, () => ({ phase: event.phase, live: "" }));
    case "token":
      // A token can arrive after the phase it belongs to has completed; it must not reappear.
      return update(run, event.iteration, (iteration) =>
        iteration.completedPhases.includes(event.phase) ? {} : { live: iteration.live + event.text },
      );
    case "research_completed":
      return update(run, event.iteration, (iteration) => ({
        ...complete(iteration, "research"),
        research: event.research,
      }));
    case "draft_completed":
      return update(run, event.iteration, (iteration) => ({
        ...complete(iteration, "draft"),
        draft: event.draft,
      }));
    case "evaluation_retried":
      return update(run, event.iteration, () => ({ evaluationRetried: true, live: "" }));
    case "evaluation_completed":
      return update(run, event.iteration, (iteration) => ({
        ...complete(iteration, "evaluate"),
        evaluation: event.evaluation,
      }));
    case "run_finished":
      return {
        ...run,
        status: "finished",
        iterations: run.iterations.map((iteration) => ({ ...iteration, phase: null, live: "" })),
        outcome: {
          stopReason: event.stop_reason,
          finalIteration: event.final_iteration,
          finalDraft: event.final_draft,
          error: event.error,
        },
      };
  }
}

function newIteration(number: number): IterationView {
  return {
    number,
    phase: null,
    completedPhases: [],
    live: "",
    research: null,
    draft: null,
    evaluation: null,
    evaluationRetried: false,
  };
}

function complete(iteration: IterationView, phase: Phase): Partial<IterationView> {
  return { phase: null, live: "", completedPhases: [...iteration.completedPhases, phase] };
}

function update(
  run: RunView,
  number: number,
  change: (iteration: IterationView) => Partial<IterationView>,
): RunView {
  return {
    ...run,
    iterations: run.iterations.map((iteration) =>
      iteration.number === number ? { ...iteration, ...change(iteration) } : iteration,
    ),
  };
}
