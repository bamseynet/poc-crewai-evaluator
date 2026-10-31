import type { RunView } from "../runState";
import type { CriterionScore } from "../types";

const WIDTH = 640;
const HEIGHT = 260;
const MARGIN = { top: 16, right: 56, bottom: 36, left: 36 };
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
const Y_TICKS = [0, 2, 4, 6, 8, 10];
const MARKER_RADIUS = 5;
/** Spreads series sideways, so that equal scores do not hide each other's markers. */
const DODGE = 5;
/** Keeps the first and last markers clear of the axis labels and pass mark labels. */
const INSET = 24;
const SHAPES = ["circle", "square", "triangle", "diamond", "triangle-down", "cross"] as const;
type Shape = (typeof SHAPES)[number];

interface Series {
  id: string;
  name: string;
  index: number;
  points: { iteration: number; score: CriterionScore | undefined }[];
}

export function ScoreChart({ run }: { run: RunView }) {
  const criteria = run.rubric?.criteria ?? [];
  const scored = run.iterations.filter((iteration) => iteration.evaluation);
  if (scored.length === 0) return null;

  const series: Series[] = criteria.map((criterion, index) => ({
    id: criterion.id,
    name: criterion.name,
    index,
    points: scored.map((iteration) => ({
      iteration: iteration.number,
      score: iteration.evaluation?.scores.find((score) => score.criterion_id === criterion.id),
    })),
  }));
  const latest = scored.at(-1)?.evaluation?.scores ?? [];
  const passMarks = [...new Set(latest.map((score) => score.threshold))];
  const domain = Math.max(run.maxIterations, scored.length, 2);

  const x = (iteration: number, seriesIndex = 0) =>
    MARGIN.left +
    INSET +
    ((iteration - 1) / (domain - 1)) * (PLOT_WIDTH - INSET * 2) +
    (seriesIndex - (series.length - 1) / 2) * DODGE;
  const y = (score: number) => MARGIN.top + (1 - score / 10) * PLOT_HEIGHT;

  return (
    <div className="chart">
      <div className="chart-plot">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Score history for ${series.length} criteria over ${scored.length} iterations. The table below has the same data.`}
        >
          {Y_TICKS.map((tick) => (
            <g key={tick}>
              <line
                className="grid-line"
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
              />
              <text className="axis-label" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {tick}
              </text>
            </g>
          ))}
          {Array.from({ length: domain }, (_, index) => index + 1).map((iteration) => (
            <text
              key={iteration}
              className="axis-label"
              x={x(iteration, (series.length - 1) / 2)}
              y={HEIGHT - MARGIN.bottom + 18}
              textAnchor="middle"
            >
              {iteration}
            </text>
          ))}
          <text
            className="axis-label"
            x={MARGIN.left + PLOT_WIDTH / 2}
            y={HEIGHT - 2}
            textAnchor="middle"
          >
            Iteration
          </text>

          {passMarks.map((mark) => (
            <g key={mark}>
              <line
                className="pass-line"
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(mark)}
                y2={y(mark)}
              />
              <text className="pass-label" x={WIDTH - MARGIN.right + 6} y={y(mark)} dy="0.32em">
                pass {mark}
              </text>
            </g>
          ))}

          {series.map((line) => (
            <g key={line.id} className={`series series-${(line.index % SHAPES.length) + 1}`}>
              {lineSegments(line).map((segment) => (
                <polyline
                  key={segment[0]?.iteration}
                  className="series-line"
                  points={segment
                    .map((point) => `${x(point.iteration, line.index)},${y(point.value)}`)
                    .join(" ")}
                />
              ))}
              {line.points.map(({ iteration, score }) =>
                score && score.score !== null ? (
                  <Marker
                    key={iteration}
                    shape={SHAPES[line.index % SHAPES.length] ?? "circle"}
                    cx={x(iteration, line.index)}
                    cy={y(score.score)}
                    title={`${line.name}, iteration ${iteration}: ${score.score} (needs ${score.threshold})`}
                  />
                ) : null,
              )}
            </g>
          ))}
        </svg>
      </div>

      <div className="table-scroll">
        <table className="score-table">
          <thead>
            <tr>
              <th scope="col">Criterion</th>
              <th scope="col" className="number">
                Pass mark
              </th>
              {scored.map((iteration) => (
                <th key={iteration.number} scope="col" className="number">
                  Iter {iteration.number}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {series.map((line) => (
              <tr key={line.id}>
                <th scope="row">
                  <span className={`legend-key series series-${(line.index % SHAPES.length) + 1}`}>
                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                      <Marker
                        shape={SHAPES[line.index % SHAPES.length] ?? "circle"}
                        cx={8}
                        cy={8}
                      />
                    </svg>
                  </span>
                  {line.name}
                </th>
                <td className="number">
                  {latest.find((score) => score.criterion_id === line.id)?.threshold}
                </td>
                {line.points.map(({ iteration, score }) => (
                  <td
                    key={iteration}
                    className={score?.passed ? "number cell-pass" : "number cell-fail"}
                  >
                    {score?.score ?? "–"}{" "}
                    <span aria-hidden="true">{score?.passed ? "✓" : "✗"}</span>
                    <span className="visually-hidden">{score?.passed ? "passed" : "failed"}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Runs of consecutive scored iterations. An unscored iteration leaves a gap in the line. */
function lineSegments(line: Series): { iteration: number; value: number }[][] {
  const segments: { iteration: number; value: number }[][] = [];
  let current: { iteration: number; value: number }[] = [];
  for (const { iteration, score } of line.points) {
    if (score && score.score !== null) {
      current.push({ iteration, value: score.score });
    } else if (current.length > 0) {
      segments.push(current);
      current = [];
    }
  }
  if (current.length > 0) segments.push(current);
  return segments;
}

function Marker({
  shape,
  cx,
  cy,
  title,
}: {
  shape: Shape;
  cx: number;
  cy: number;
  title?: string;
}) {
  const r = MARKER_RADIUS;
  const label = title ? <title>{title}</title> : null;
  switch (shape) {
    case "circle":
      return (
        <circle className="marker" cx={cx} cy={cy} r={r}>
          {label}
        </circle>
      );
    case "square":
      return (
        <rect className="marker" x={cx - r} y={cy - r} width={r * 2} height={r * 2}>
          {label}
        </rect>
      );
    case "triangle":
      return <Polygon points={[[0, -r - 1], [r + 1, r], [-r - 1, r]]} cx={cx} cy={cy} label={label} />;
    case "triangle-down":
      return <Polygon points={[[0, r + 1], [r + 1, -r], [-r - 1, -r]]} cx={cx} cy={cy} label={label} />;
    case "diamond":
      return <Polygon points={[[0, -r - 1], [r + 1, 0], [0, r + 1], [-r - 1, 0]]} cx={cx} cy={cy} label={label} />;
    case "cross":
      return (
        <Polygon
          points={[[-2, -r], [2, -r], [2, -2], [r, -2], [r, 2], [2, 2], [2, r], [-2, r], [-2, 2], [-r, 2], [-r, -2], [-2, -2]]}
          cx={cx}
          cy={cy}
          label={label}
        />
      );
  }
}

function Polygon({
  points,
  cx,
  cy,
  label,
}: {
  points: number[][];
  cx: number;
  cy: number;
  label: React.ReactNode;
}) {
  return (
    <polygon
      className="marker"
      points={points.map(([dx = 0, dy = 0]) => `${cx + dx},${cy + dy}`).join(" ")}
    >
      {label}
    </polygon>
  );
}
