import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { rubric } from "../testing/fixtures";
import type { Meta } from "../types";
import { RequestForm } from "./RequestForm";

const meta: Meta = {
  llm_mode: "fake",
  auth_required: false,
  max_iterations: { default: 4, limit: 8 },
  rubrics: [rubric, { ...rubric, id: "tone", name: "Tone", criteria: [] }],
};

function setup(overrides: Partial<Meta> = {}, busy = false) {
  const onSubmit = vi.fn();
  const onTokenChange = vi.fn();
  render(
    <RequestForm
      meta={{ ...meta, ...overrides }}
      busy={busy}
      token=""
      onTokenChange={onTokenChange}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, onTokenChange, user: userEvent.setup() };
}

describe("RequestForm", () => {
  it("submits the request, rubric and limits", async () => {
    const { onSubmit, user } = setup();

    await user.clear(screen.getByLabelText("What should be drafted?"));
    await user.type(screen.getByLabelText("What should be drafted?"), "A retention policy");
    await user.selectOptions(screen.getByLabelText("Rubric"), "tone");
    await user.clear(screen.getByLabelText("Max iterations"));
    await user.type(screen.getByLabelText("Max iterations"), "2");
    await user.click(screen.getByRole("button", { name: "Run the loop" }));

    expect(onSubmit).toHaveBeenCalledWith({
      request: "A retention policy",
      rubric_id: "tone",
      max_iterations: 2,
      threshold: null,
    });
  });

  it("sends a numeric pass mark override when one is entered", async () => {
    const { onSubmit, user } = setup();

    await user.type(screen.getByLabelText("Pass mark override"), "9");
    await user.click(screen.getByRole("button", { name: "Run the loop" }));

    expect(onSubmit.mock.calls[0]?.[0].threshold).toBe(9);
  });

  it("previews the selected rubric's criteria and pass marks", async () => {
    const { user } = setup();

    expect(screen.getByText("Plain language")).toBeInTheDocument();
    expect(screen.getByText("7/10")).toBeInTheDocument();
    expect(screen.getByText("8/10")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Pass mark override"), "9");

    expect(screen.getAllByText("9/10")).toHaveLength(2);
  });

  it("enforces the iteration limit from the server", () => {
    setup();

    expect(screen.getByLabelText("Max iterations")).toHaveAttribute("max", "8");
  });

  it("cannot be resubmitted while a run is in progress", () => {
    setup({}, true);

    expect(screen.getByRole("button", { name: "Running…" })).toBeDisabled();
  });

  it("asks for an access token only when the server requires one", async () => {
    setup();
    expect(screen.queryByLabelText("Access token")).not.toBeInTheDocument();
  });

  it("reports the access token when required", async () => {
    const { onTokenChange, user } = setup({ auth_required: true });

    await user.type(screen.getByLabelText("Access token"), "x");

    expect(onTokenChange).toHaveBeenCalledWith("x");
  });
});
