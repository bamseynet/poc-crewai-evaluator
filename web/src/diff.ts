import { diffArrays, diffWordsWithSpace } from "diff";

export interface Segment {
  text: string;
  changed: boolean;
}

export interface Side {
  number: number;
  segments: Segment[];
}

export interface DiffRow {
  kind: "same" | "added" | "removed" | "changed";
  left: Side | null;
  right: Side | null;
}

export type DiffPart = { type: "rows"; rows: DiffRow[] } | { type: "fold"; rows: DiffRow[] };

/** Fewer hidden lines than this are not worth a "show more" control. */
const MIN_FOLD = 3;

/** Aligns two documents line by line. A replaced line is paired up and diffed word by word. */
export function sideBySide(leftText: string, rightText: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let leftNumber = 0;
  let rightNumber = 0;
  const leftSide = (text: string, changed = false): Side => ({
    number: ++leftNumber,
    segments: [{ text, changed }],
  });
  const rightSide = (text: string, changed = false): Side => ({
    number: ++rightNumber,
    segments: [{ text, changed }],
  });

  let removed: string[] = [];
  let added: string[] = [];
  const flushChanges = () => {
    const paired = Math.min(removed.length, added.length);
    for (let index = 0; index < paired; index++) {
      const words = diffWordsWithSpace(removed[index] ?? "", added[index] ?? "");
      rows.push({
        kind: "changed",
        left: {
          number: ++leftNumber,
          segments: words
            .filter((word) => !word.added)
            .map((word) => ({ text: word.value, changed: Boolean(word.removed) })),
        },
        right: {
          number: ++rightNumber,
          segments: words
            .filter((word) => !word.removed)
            .map((word) => ({ text: word.value, changed: Boolean(word.added) })),
        },
      });
    }
    for (const line of removed.slice(paired)) {
      rows.push({ kind: "removed", left: leftSide(line, true), right: null });
    }
    for (const line of added.slice(paired)) {
      rows.push({ kind: "added", left: null, right: rightSide(line, true) });
    }
    removed = [];
    added = [];
  };

  for (const change of diffArrays(toLines(leftText), toLines(rightText))) {
    if (change.removed) {
      removed.push(...change.value);
    } else if (change.added) {
      added.push(...change.value);
    } else {
      flushChanges();
      for (const line of change.value) {
        rows.push({ kind: "same", left: leftSide(line), right: rightSide(line) });
      }
    }
  }
  flushChanges();
  return rows;
}

export function summarise(rows: DiffRow[]): { added: number; removed: number; changed: number } {
  const count = (kind: DiffRow["kind"]) => rows.filter((row) => row.kind === kind).length;
  return { added: count("added"), removed: count("removed"), changed: count("changed") };
}

/** Splits rows into visible parts and foldable unchanged runs, keeping context around changes. */
export function collapseUnchanged(rows: DiffRow[], context = 3): DiffPart[] {
  const parts: DiffPart[] = [];
  const pushRows = (visible: DiffRow[]) => {
    if (visible.length === 0) return;
    const last = parts.at(-1);
    if (last?.type === "rows") {
      last.rows.push(...visible);
    } else {
      parts.push({ type: "rows", rows: [...visible] });
    }
  };

  let index = 0;
  while (index < rows.length) {
    const start = index;
    const unchanged = rows[index]?.kind === "same";
    while (index < rows.length && (rows[index]?.kind === "same") === unchanged) index++;
    const run = rows.slice(start, index);

    if (!unchanged) {
      pushRows(run);
      continue;
    }
    const keepBefore = start === 0 ? 0 : context;
    const keepAfter = index === rows.length ? 0 : context;
    const hidden = run.length - keepBefore - keepAfter;
    if (hidden < MIN_FOLD) {
      pushRows(run);
      continue;
    }
    pushRows(run.slice(0, keepBefore));
    parts.push({ type: "fold", rows: run.slice(keepBefore, run.length - keepAfter) });
    pushRows(run.slice(run.length - keepAfter));
  }
  return parts;
}

function toLines(text: string): string[] {
  return text === "" ? [] : text.split("\n");
}
