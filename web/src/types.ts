/** Mirrors the Python models in `src/policy_drafter/events.py` and `scoring.py`. */

export type Phase = "research" | "draft" | "evaluate";
export type StopReason = "passed" | "max_iterations" | "evaluator_error" | "error";

export interface Criterion {
  id: string;
  name: string;
  description: string;
  threshold: number | null;
}

export interface Rubric {
  id: string;
  name: string;
  description: string;
  threshold: number;
  criteria: Criterion[];
}

export interface Meta {
  llm_mode: "fake" | "bedrock";
  auth_required: boolean;
  max_iterations: { default: number; limit: number };
  rubrics: Rubric[];
}

export interface CriterionScore {
  criterion_id: string;
  name: string;
  score: number | null;
  threshold: number;
  passed: boolean;
  feedback: string;
}

export interface Evaluation {
  scores: CriterionScore[];
  parse_ok: boolean;
  warnings: string[];
  all_passed: boolean;
}

export interface RunRequest {
  request: string;
  rubric_id: string;
  max_iterations: number;
  threshold: number | null;
}

export type ProgressEvent =
  | {
      type: "run_started";
      request: string;
      rubric: Rubric;
      max_iterations: number;
      threshold: number | null;
    }
  | { type: "iteration_started"; iteration: number }
  | { type: "phase_started"; iteration: number; phase: Phase }
  | { type: "token"; iteration: number; phase: Phase; text: string }
  | { type: "research_completed"; iteration: number; research: string }
  | { type: "draft_completed"; iteration: number; draft: string }
  | { type: "evaluation_retried"; iteration: number; warnings: string[] }
  | { type: "evaluation_completed"; iteration: number; evaluation: Evaluation }
  | {
      type: "run_finished";
      stop_reason: StopReason;
      iterations: number;
      final_iteration: number | null;
      final_draft: string | null;
      error: string | null;
    };
