import { useMemo, useState } from "react";
import { collapseUnchanged, sideBySide, summarise, type DiffRow, type Side } from "../diff";
import type { IterationView } from "../runState";

export function DraftCompare({ iterations }: { iterations: IterationView[] }) {
  const drafted = iterations.filter((iteration) => iteration.draft !== null);
  const latest = drafted.at(-1)?.number ?? 0;
  // Until the reader picks something, follow the two most recent drafts as they arrive.
  const [leftChoice, setLeftChoice] = useState<number | null>(null);
  const [rightChoice, setRightChoice] = useState<number | null>(null);

  if (drafted.length < 2) {
    return <p className="empty">Comparison becomes available after the first revision.</p>;
  }

  const left = leftChoice ?? drafted.at(-2)?.number ?? 1;
  const right = rightChoice ?? latest;
  const draftOf = (number: number) =>
    drafted.find((iteration) => iteration.number === number)?.draft ?? "";

  return (
    <div className="compare">
      <div className="compare-controls">
        <IterationSelect label="Left" value={left} drafted={drafted} onChange={setLeftChoice} />
        <IterationSelect label="Right" value={right} drafted={drafted} onChange={setRightChoice} />
      </div>
      <DiffTable key={`${left}-${right}`} left={draftOf(left)} right={draftOf(right)} />
    </div>
  );
}

function IterationSelect({
  label,
  value,
  drafted,
  onChange,
}: {
  label: string;
  value: number;
  drafted: IterationView[];
  onChange: (value: number) => void;
}) {
  return (
    <label className="field inline">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {drafted.map((iteration) => (
          <option key={iteration.number} value={iteration.number}>
            Iteration {iteration.number}
          </option>
        ))}
      </select>
    </label>
  );
}

function DiffTable({ left, right }: { left: string; right: string }) {
  const rows = useMemo(() => sideBySide(left, right), [left, right]);
  const parts = useMemo(() => collapseUnchanged(rows), [rows]);
  const counts = summarise(rows);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());

  return (
    <>
      <p className="diff-summary">
        <span className="count-added">+{counts.added} added</span>
        <span className="count-removed">−{counts.removed} removed</span>
        <span className="count-changed">~{counts.changed} changed</span>
      </p>
      <div className="table-scroll">
        <table className="diff">
          <colgroup>
            <col className="gutter" />
            <col />
            <col className="gutter" />
            <col />
          </colgroup>
          <tbody>
            {parts.flatMap((part, index) => {
              if (part.type === "rows" || expanded.has(index)) {
                return part.rows.map((row) => <Row key={rowKey(row)} row={row} />);
              }
              return [
                <tr key={`fold-${index}`} className="fold">
                  <td colSpan={4}>
                    <button
                      type="button"
                      onClick={() => setExpanded(new Set(expanded).add(index))}
                    >
                      Show {part.rows.length} unchanged lines
                    </button>
                  </td>
                </tr>,
              ];
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function rowKey(row: DiffRow): string {
  return `${row.left?.number ?? "x"}-${row.right?.number ?? "x"}`;
}

function Row({ row }: { row: DiffRow }) {
  return (
    <tr className={`diff-row ${row.kind}`}>
      <SideCells side={row.left} sign={row.kind === "same" ? "" : "−"} tag="del" />
      <SideCells side={row.right} sign={row.kind === "same" ? "" : "+"} tag="ins" />
    </tr>
  );
}

function SideCells({ side, sign, tag: Tag }: { side: Side | null; sign: string; tag: "del" | "ins" }) {
  if (!side) {
    return (
      <>
        <td className="line-number" />
        <td className="line blank" />
      </>
    );
  }
  return (
    <>
      <td className="line-number">
        {side.number}
        {sign && <span className="sign"> {sign}</span>}
      </td>
      <td className="line">
        {side.segments.map((segment, index) =>
          segment.changed ? (
            <Tag key={index}>{segment.text}</Tag>
          ) : (
            <span key={index}>{segment.text}</span>
          ),
        )}
      </td>
    </>
  );
}
