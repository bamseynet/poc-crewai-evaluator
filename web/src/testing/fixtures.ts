import type { CriterionScore, Evaluation, ProgressEvent, Rubric } from "../types";

export const rubric: Rubric = {
  id: "clarity",
  name: "Clarity",
  description: "Can the reader follow it?",
  threshold: 7,
  criteria: [
    { id: "plain_language", name: "Plain language", description: "Short sentences.", threshold: null },
    { id: "actionable", name: "Actionable", description: "Testable rules.", threshold: 8 },
  ],
};

export function score(overrides: Partial<CriterionScore> & { criterion_id: string }): CriterionScore {
  const criterion = rubric.criteria.find((c) => c.id === overrides.criterion_id);
  const threshold = overrides.threshold ?? criterion?.threshold ?? rubric.threshold;
  const value = overrides.score === undefined ? 5 : overrides.score;
  return {
    name: criterion?.name ?? overrides.criterion_id,
    score: value,
    threshold,
    passed: value !== null && value >= threshold,
    feedback: "Needs work.",
    ...overrides,
  };
}

export function evaluation(plain: number | null, actionable: number | null): Evaluation {
  const scores = [
    score({ criterion_id: "plain_language", score: plain }),
    score({ criterion_id: "actionable", score: actionable }),
  ];
  return {
    scores,
    parse_ok: scores.some((s) => s.score !== null),
    warnings: [],
    all_passed: scores.every((s) => s.passed),
  };
}

export const started: ProgressEvent = {
  type: "run_started",
  request: "Draft an AI policy",
  rubric,
  max_iterations: 3,
  threshold: null,
};

/** The full event sequence of one completed iteration. */
export function iterationEvents(
  iteration: number,
  draft: string,
  result: Evaluation,
): ProgressEvent[] {
  return [
    { type: "iteration_started", iteration },
    { type: "phase_started", iteration, phase: "research" },
    { type: "research_completed", iteration, research: `Notes ${iteration}` },
    { type: "phase_started", iteration, phase: "draft" },
    { type: "draft_completed", iteration, draft },
    { type: "phase_started", iteration, phase: "evaluate" },
    { type: "evaluation_completed", iteration, evaluation: result },
  ];
}
