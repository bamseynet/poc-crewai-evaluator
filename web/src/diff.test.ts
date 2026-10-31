import { describe, expect, it } from "vitest";
import { collapseUnchanged, sideBySide, summarise } from "./diff";

describe("sideBySide", () => {
  it("aligns identical documents line by line", () => {
    const rows = sideBySide("a\nb", "a\nb");

    expect(rows.map((row) => row.kind)).toEqual(["same", "same"]);
    expect(rows[1]?.left?.number).toBe(2);
    expect(rows[1]?.right?.number).toBe(2);
  });

  it("shows an added line only on the right", () => {
    const rows = sideBySide("a\nc", "a\nb\nc");

    expect(rows.map((row) => row.kind)).toEqual(["same", "added", "same"]);
    expect(rows[1]?.left).toBeNull();
    expect(rows[1]?.right?.number).toBe(2);
    expect(rows[2]?.left?.number).toBe(2);
    expect(rows[2]?.right?.number).toBe(3);
  });

  it("shows a removed line only on the left", () => {
    const rows = sideBySide("a\nb\nc", "a\nc");

    expect(rows.map((row) => row.kind)).toEqual(["same", "removed", "same"]);
    expect(rows[1]?.right).toBeNull();
  });

  it("pairs a changed line and highlights the changed words", () => {
    const rows = sideBySide("Employees should comply.", "Employees must comply.");

    expect(rows).toHaveLength(1);
    expect(rows[0]?.kind).toBe("changed");
    expect(rows[0]?.left?.segments.filter((s) => s.changed).map((s) => s.text)).toEqual(["should"]);
    expect(rows[0]?.right?.segments.filter((s) => s.changed).map((s) => s.text)).toEqual(["must"]);
  });

  it("handles unequal numbers of changed lines", () => {
    const rows = sideBySide("one\ntwo", "uno\ndos\ntres");

    expect(rows.map((row) => row.kind)).toEqual(["changed", "changed", "added"]);
  });

  it("handles empty documents", () => {
    expect(sideBySide("", "")).toEqual([]);
    expect(sideBySide("", "a").map((row) => row.kind)).toEqual(["added"]);
    expect(sideBySide("a", "").map((row) => row.kind)).toEqual(["removed"]);
  });

  it("keeps blank lines", () => {
    expect(sideBySide("a\n\nb", "a\n\nb")).toHaveLength(3);
  });
});

describe("summarise", () => {
  it("counts added, removed and changed lines", () => {
    expect(summarise(sideBySide("a\nb\nc", "a\nB\nd\ne"))).toEqual({
      added: 1,
      removed: 0,
      changed: 2,
    });
  });
});

describe("collapseUnchanged", () => {
  const lines = (count: number, prefix = "line") =>
    Array.from({ length: count }, (_, index) => `${prefix} ${index}`);

  it("folds long unchanged runs but keeps context around a change", () => {
    const left = lines(20).join("\n");
    const right = [...lines(10), "new", ...lines(20).slice(10)].join("\n");

    const parts = collapseUnchanged(sideBySide(left, right), 2);

    expect(parts.map((part) => part.type)).toEqual(["fold", "rows", "fold"]);
    const [first, middle] = parts;
    expect(first?.type === "fold" && first.rows).toHaveLength(8);
    expect(middle?.type === "rows" && middle.rows.map((row) => row.kind)).toEqual([
      "same",
      "same",
      "added",
      "same",
      "same",
    ]);
  });

  it("does not fold a run that is too short to be worth folding", () => {
    const parts = collapseUnchanged(sideBySide("a\nb\nc\nd", "a\nb\nc\nX"), 2);

    expect(parts.map((part) => part.type)).toEqual(["rows"]);
  });

  it("folds a whole identical document", () => {
    const text = lines(30).join("\n");

    expect(collapseUnchanged(sideBySide(text, text), 2).map((part) => part.type)).toEqual(["fold"]);
  });
});
