import { useState, type FormEvent } from "react";
import type { Meta, RunRequest } from "../types";

const EXAMPLE_REQUEST = "Draft an acceptable-use policy for AI tools for a 500-person fintech.";

interface Props {
  meta: Meta;
  busy: boolean;
  token: string;
  onTokenChange: (token: string) => void;
  onSubmit: (request: RunRequest) => void;
}

export function RequestForm({ meta, busy, token, onTokenChange, onSubmit }: Props) {
  const [request, setRequest] = useState(EXAMPLE_REQUEST);
  const [rubricId, setRubricId] = useState(meta.rubrics[0]?.id ?? "");
  const [maxIterations, setMaxIterations] = useState(meta.max_iterations.default);
  const [threshold, setThreshold] = useState("");
  const rubric = meta.rubrics.find((candidate) => candidate.id === rubricId);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      request,
      rubric_id: rubricId,
      max_iterations: maxIterations,
      threshold: threshold === "" ? null : Number(threshold),
    });
  }

  return (
    <form className="request-form" onSubmit={submit}>
      <label className="field">
        <span>What should be drafted?</span>
        <textarea
          value={request}
          required
          maxLength={4000}
          rows={5}
          onChange={(event) => setRequest(event.target.value)}
        />
      </label>

      <label className="field">
        <span>Rubric</span>
        <select value={rubricId} onChange={(event) => setRubricId(event.target.value)}>
          {meta.rubrics.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name}
            </option>
          ))}
        </select>
      </label>

      {rubric && (
        <div className="rubric-preview">
          <p>{rubric.description}</p>
          <ul>
            {rubric.criteria.map((criterion) => (
              <li key={criterion.id} title={criterion.description}>
                {criterion.name}
                <span className="pass-mark">
                  {threshold === "" ? (criterion.threshold ?? rubric.threshold) : threshold}/10
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="field-row">
        <label className="field">
          <span>Max iterations</span>
          <input
            type="number"
            min={1}
            max={meta.max_iterations.limit}
            value={maxIterations}
            required
            onChange={(event) => setMaxIterations(Number(event.target.value))}
          />
        </label>
        <label className="field">
          <span>Pass mark override</span>
          <input
            type="number"
            min={0}
            max={10}
            step={0.5}
            value={threshold}
            placeholder="Rubric default"
            onChange={(event) => setThreshold(event.target.value)}
          />
        </label>
      </div>

      {meta.auth_required && (
        <label className="field">
          <span>Access token</span>
          <input
            type="password"
            autoComplete="off"
            value={token}
            required
            onChange={(event) => onTokenChange(event.target.value)}
          />
        </label>
      )}

      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Running…" : "Run the loop"}
      </button>
    </form>
  );
}
