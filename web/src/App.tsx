import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, createRun, fetchMeta, followRun } from "./api";
import { DraftCompare } from "./components/DraftCompare";
import { FinalDraft, OutcomeBanner } from "./components/Outcome";
import { RequestForm } from "./components/RequestForm";
import { RunTimeline } from "./components/RunTimeline";
import { ScoreChart } from "./components/ScoreChart";
import { initialRun, runReducer } from "./runState";
import type { Meta, RunRequest } from "./types";

const TOKEN_KEY = "policy-drafter-token";

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveToken(token: string) {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    // The token still works for this page view if storage is blocked.
  }
}

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [run, setRun] = useState(initialRun);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [token, setToken] = useState(readToken);
  const stream = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchMeta().then(setMeta, (reason: unknown) =>
      setError(reason instanceof Error ? reason.message : String(reason)),
    );
    return () => stream.current?.abort();
  }, []);

  const changeToken = useCallback((value: string) => {
    setToken(value);
    saveToken(value);
  }, []);

  const start = useCallback(
    async (request: RunRequest) => {
      stream.current?.abort();
      const controller = new AbortController();
      stream.current = controller;
      setRun(initialRun);
      setError(null);
      setStarting(true);
      try {
        const runId = await createRun(request, token);
        if (controller.signal.aborted) return;
        await followRun(runId, {
          token,
          signal: controller.signal,
          onEvent: (event) => {
            // Events of a superseded run must not leak into the run that replaced it.
            if (stream.current === controller) setRun((current) => runReducer(current, event));
          },
          onConnectionChange: (connected) => setReconnecting(!connected),
        });
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 401) {
          setError("The access token was not accepted.");
        } else {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      } finally {
        // A newer run may have replaced this one; it owns these flags now.
        if (stream.current === controller) {
          setStarting(false);
          setReconnecting(false);
        }
      }
    },
    [token],
  );

  const scored = run.iterations.some((iteration) => iteration.evaluation);
  const hasRun = run.status !== "idle";

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>Policy Drafter</h1>
          <p>An evaluator–optimizer loop, built with CrewAI Flows and Crews</p>
        </div>
        {meta && (
          <span className={`mode ${meta.llm_mode}`}>
            {meta.llm_mode === "fake" ? "Fake LLM, offline" : "Amazon Bedrock"}
          </span>
        )}
      </header>

      <main className="layout">
        <aside className="panel setup" aria-label="New run">
          <h2>New run</h2>
          {meta ? (
            <RequestForm
              meta={meta}
              busy={starting}
              token={token}
              onTokenChange={changeToken}
              onSubmit={(request) => void start(request)}
            />
          ) : (
            !error && <p className="empty">Loading…</p>
          )}
        </aside>

        <div className="results">
          {error && (
            <p className="outcome danger" role="alert">
              {error}
            </p>
          )}
          {reconnecting && (
            <p className="note" role="status">
              Connection lost. Reconnecting…
            </p>
          )}
          <OutcomeBanner run={run} />

          {!hasRun && !error && (
            <section className="panel intro">
              <h2>How the loop works</h2>
              <ol>
                <li>
                  <strong>Write.</strong> A researcher and a drafter produce a draft.
                </li>
                <li>
                  <strong>Evaluate.</strong> A separate agent scores it against each rubric
                  criterion and says what to fix.
                </li>
                <li>
                  <strong>Decide.</strong> Code compares the scores with the pass marks. If any
                  criterion fails and iterations remain, the feedback goes back to step 1.
                </li>
                <li>
                  <strong>Stop.</strong> The loop ends when everything passes or the iteration
                  limit is reached, and it records which.
                </li>
              </ol>
            </section>
          )}

          {hasRun && (
            <section className="panel">
              <h2>Iterations</h2>
              <RunTimeline run={run} />
            </section>
          )}

          {scored && (
            <section className="panel">
              <h2>Score history</h2>
              <ScoreChart run={run} />
            </section>
          )}

          {scored && (
            <section className="panel">
              <h2>Compare drafts</h2>
              <DraftCompare iterations={run.iterations} />
            </section>
          )}

          {run.outcome?.finalDraft != null && (
            <section className="panel">
              <h2>Final draft (iteration {run.outcome.finalIteration})</h2>
              <FinalDraft run={run} />
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
