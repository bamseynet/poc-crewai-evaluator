import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { initialRun, runReducer, type RunView } from "../runState";
import { evaluation, iterationEvents, started } from "../testing/fixtures";
import type { ProgressEvent } from "../types";
import { DraftCompare } from "./DraftCompare";

function runWithDrafts(...drafts: string[]): RunView {
  const events: ProgressEvent[] = [
    started,
    ...drafts.flatMap((draft, index) => iterationEvents(index + 1, draft, evaluation(4, 5))),
  ];
  return events.reduce(runReducer, initialRun);
}

function renderDrafts(...drafts: string[]) {
  return render(<DraftCompare iterations={runWithDrafts(...drafts).iterations} />);
}

describe("DraftCompare", () => {
  it("waits until there are two drafts to compare", () => {
    renderDrafts("Only one");

    expect(screen.getByText(/after the first revision/)).toBeInTheDocument();
  });

  it("compares the two most recent drafts by default", () => {
    renderDrafts("first", "second", "third");

    expect(screen.getByLabelText("Left")).toHaveValue("2");
    expect(screen.getByLabelText("Right")).toHaveValue("3");
    expect(screen.getByText("second")).toBeInTheDocument();
    expect(screen.getByText("third")).toBeInTheDocument();
  });

  it("highlights changed words in both columns", () => {
    const { container } = renderDrafts("Staff should comply.", "Staff must comply.");

    expect(container.querySelector("del")).toHaveTextContent("should");
    expect(container.querySelector("ins")).toHaveTextContent("must");
  });

  it("summarises the changes", () => {
    renderDrafts("a\nb", "a\nB\nc");

    expect(screen.getByText("+1 added")).toBeInTheDocument();
    expect(screen.getByText("−0 removed")).toBeInTheDocument();
    expect(screen.getByText("~1 changed")).toBeInTheDocument();
  });

  it("lets the reader pick which iterations to compare", async () => {
    const user = userEvent.setup();
    renderDrafts("alpha", "beta", "gamma");

    await user.selectOptions(screen.getByLabelText("Left"), "1");

    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.queryByText("beta")).not.toBeInTheDocument();
  });

  it("follows new iterations until the reader makes a choice", () => {
    const { rerender } = render(
      <DraftCompare iterations={runWithDrafts("alpha", "beta").iterations} />,
    );

    rerender(<DraftCompare iterations={runWithDrafts("alpha", "beta", "gamma").iterations} />);

    expect(screen.getByLabelText("Right")).toHaveValue("3");
  });

  it("folds long unchanged runs and can expand them", async () => {
    const user = userEvent.setup();
    const shared = Array.from({ length: 20 }, (_, index) => `line ${index}`).join("\n");
    renderDrafts(`${shared}\nold`, `${shared}\nnew`);

    expect(screen.queryByText("line 0")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show 17 unchanged lines" }));

    expect(screen.getAllByText("line 0")).toHaveLength(2);
  });
});
