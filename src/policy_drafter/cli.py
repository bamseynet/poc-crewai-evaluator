"""Run the loop from a terminal: `uv run policy-drafter "Draft an AI use policy" --rubric tone`."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from policy_drafter.config import Settings
from policy_drafter.events import EvaluationCompleted, IterationStarted, ProgressEvent, RunFinished
from policy_drafter.flow import run_drafting
from policy_drafter.llm import build_llms
from policy_drafter.models import DEFAULT_MAX_ITERATIONS, RunConfig, StopReason
from policy_drafter.rubrics import list_rubrics


def _print_progress(event: ProgressEvent) -> None:
    match event:
        case IterationStarted(iteration=iteration):
            print(f"\nIteration {iteration}: researching, drafting and evaluating...")
        case EvaluationCompleted(evaluation=evaluation):
            for score in evaluation.scores:
                mark = "pass" if score.passed else "FAIL"
                value = f"{score.score:g}" if score.score is not None else "-"
                print(f"  {mark}  {value:>4} / {score.threshold:g}  {score.name}")
        case RunFinished(stop_reason=stop_reason, error=error):
            print(f"\nStop reason: {stop_reason.value}")
            if error:
                print(f"Error: {error}")
        case _:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft a policy with an evaluator-optimizer loop.")
    parser.add_argument("request", help="what to draft")
    parser.add_argument(
        "--rubric",
        default="completeness",
        help=f"one of: {', '.join(rubric.id for rubric in list_rubrics())}",
    )
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--threshold", type=float, help="override every criterion's pass mark")
    parser.add_argument("--output", type=Path, help="write the final draft to this file")
    args = parser.parse_args(argv)

    if args.output and not args.output.resolve().parent.is_dir():
        parser.error(f"--output directory does not exist: {args.output.resolve().parent}")

    logging.basicConfig(level=logging.WARNING)
    try:
        config = RunConfig(
            request=args.request,
            rubric_id=args.rubric,
            max_iterations=args.max_iterations,
            threshold=args.threshold,
        )
    except ValidationError as exc:
        parser.error(str(exc))

    try:
        llms = build_llms(Settings())
    except ValidationError as exc:
        parser.error(f"invalid settings: {exc}")
    state = run_drafting(config, llms, on_event=_print_progress)

    if state.final_draft is not None:
        if args.output:
            try:
                args.output.write_text(state.final_draft + "\n", encoding="utf-8")
            except OSError as error:
                # Do not lose a draft that cost real model calls: fall back to stdout.
                print(f"\nCould not write {args.output}: {error}\n\n{state.final_draft}")
                return 2
            print(f"Wrote iteration {state.final_iteration} to {args.output}")
        else:
            print(f"\n{state.final_draft}")
    return 0 if state.stop_reason is StopReason.PASSED else 1
