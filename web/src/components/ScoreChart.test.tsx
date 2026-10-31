import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialRun, runReducer } from "../runState";
import { evaluation, iterationEvents, started } from "../testing/fixtures";
import type { ProgressEvent } from "../types";
import { ScoreChart } from "./ScoreChart";

function renderAfter(events: ProgressEvent[]) {
  return render(<ScoreChart run={events.reduce(runReducer, initialRun)} />);
}

const twoIterations = [
  started,
  ...iterationEvents(1, "One", evaluation(4, 5)),
  ...iterationEvents(2, "Two", evaluation(8, 9)),
];

describe("ScoreChart", () => {
  it("renders nothing until a draft has been scored", () => {
    const { container } = renderAfter([started]);

    expect(container).toBeEmptyDOMElement();
  });

  it("plots one marker per scored criterion per iteration, labelled with its value", () => {
    const { container } = renderAfter(twoIterations);

    const chart = screen.getByRole("img");
    expect(chart.querySelectorAll(".marker")).toHaveLength(4);
    expect(container.textContent).toContain("Plain language, iteration 1: 4 (needs 7)");
    expect(container.textContent).toContain("Actionable, iteration 2: 9 (needs 8)");
  });

  it("draws a line through the history of each criterion", () => {
    renderAfter(twoIterations);

    expect(screen.getByRole("img").querySelectorAll("polyline")).toHaveLength(2);
  });

  it("draws one pass line for each distinct pass mark", () => {
    renderAfter(twoIterations);

    expect(screen.getByRole("img").querySelectorAll(".pass-line")).toHaveLength(2);
    expect(screen.getByText("pass 7")).toBeInTheDocument();
    expect(screen.getByText("pass 8")).toBeInTheDocument();
  });

  it("leaves a gap for an unscored iteration rather than drawing through it", () => {
    renderAfter([
      started,
      ...iterationEvents(1, "One", evaluation(4, 5)),
      ...iterationEvents(2, "Two", evaluation(null, 6)),
      ...iterationEvents(3, "Three", evaluation(8, 9)),
    ]);

    const chart = screen.getByRole("img");
    expect(chart.querySelectorAll(".marker")).toHaveLength(5);
    expect(chart.querySelectorAll(".series-1 polyline")).toHaveLength(2);
    expect(chart.querySelectorAll(".series-2 polyline")).toHaveLength(1);
  });

  it("gives the same data as an accessible table", () => {
    renderAfter(twoIterations);

    const row = screen.getByRole("row", { name: /Actionable/ });
    const cells = within(row).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("8");
    expect(cells[1]).toHaveTextContent("5");
    expect(cells[1]).toHaveTextContent("failed");
    expect(cells[2]).toHaveTextContent("9");
    expect(cells[2]).toHaveTextContent("passed");
  });

  it("shows an unscored criterion as failed", () => {
    renderAfter([started, ...iterationEvents(1, "One", evaluation(null, 9))]);

    const cells = within(screen.getByRole("row", { name: /Plain language/ })).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("–");
    expect(cells[1]).toHaveTextContent("failed");
  });
});
