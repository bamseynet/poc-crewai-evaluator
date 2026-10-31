# poc-crewai-evaluator

A proof of concept showing one agent framework, [CrewAI](https://docs.crewai.com), implementing one
agentic pattern, the **evaluator-optimizer** loop, for one enterprise job: drafting policy and
compliance documents.

A writer crew (researcher and drafter) produces a draft. An evaluator agent scores it against a
YAML rubric, criterion by criterion, with specific feedback. A CrewAI Flow feeds that feedback into
the next revision, until every criterion passes or the iteration budget runs out, and it records why
it stopped.

This branch adds the API and web UI to the agent core. Infrastructure and full documentation follow
in the next pull request.

## Try it

You need [uv](https://docs.astral.sh/uv/) and Node.js 22 or newer. No AWS account is required,
because the offline fake LLM is the default.

```bash
make dev     # API on :8000, UI on http://localhost:5173
make check   # lint, type check, tests and build, all offline
```

Submit a request, watch each iteration stream, compare drafts side by side, follow the score
history and export the final draft as Markdown. The same loop also runs without the UI:

```bash
uv run policy-drafter "Draft an acceptable-use policy for AI tools for a 500-person fintech" \
  --rubric regulatory_coverage --output policy.md
```

## Where to look

| File | What it shows |
| --- | --- |
| [`src/policy_drafter/flow.py`](src/policy_drafter/flow.py) | The loop, as a CrewAI Flow |
| [`src/policy_drafter/crews.py`](src/policy_drafter/crews.py) | The researcher, drafter and evaluator |
| [`src/policy_drafter/prompts.py`](src/policy_drafter/prompts.py) | What each role is told, including how feedback is fed back |
| [`src/policy_drafter/scoring.py`](src/policy_drafter/scoring.py) | Parsing model output so that malformed scores fail closed |
| [`src/policy_drafter/rubric_files/`](src/policy_drafter/rubric_files/) | The YAML rubrics |
| [`src/policy_drafter/api.py`](src/policy_drafter/api.py) | The HTTP API and its event stream |
| [`web/src/runState.ts`](web/src/runState.ts) | How the UI folds the event stream into what it shows |
| [`tests/test_flow.py`](tests/test_flow.py) | The behaviour of the loop |

## Known limitations / hardening

Found in review and deliberately left for later; none changes the result on normal input.

- **Score parsing is best-effort.** Unscored or ambiguous criteria fail closed, but a model that answers on another scale (0-1, 1-5) is read at face value and costs revisions.
- **Adversarial evaluator replies** (thousands of nested brackets, many fences) can make parsing slow; repair input is capped, strict decodes are not.
- **Fence stripping is a heuristic.** An untagged fence around a draft that is itself one code block, or fences of unequal length, are not told apart.
- **`mean_score` counts an unscored criterion as 0**, which only matters when breaking ties between drafts.
- **Evaluator retry has no backoff** and retries any exception, not just transient ones.
- **A failed or empty draft ends the run**, keeping the best evaluated draft, instead of retrying the drafter.
- **Prompt injection is mitigated, not solved.** Request, draft and feedback text cannot close the tags that frame them, but researcher notes reach the drafter unframed and a model can still be talked into following instructions inside user text. Treat the output as a draft for human review.
- **Token streaming** relies on CrewAI dispatching events with the caller's context; it is tested against CrewAI 1.15.x only, and tokens are dropped silently if that changes.
- **API/UI:** shutdown ends open event streams without a terminal event and does not stop in-flight workers; a client that reconnects mid-phase misses the live tokens already sent; an invalid `Last-Event-ID` header returns 422 rather than replaying from the start; the UI has no retry if the API is down at page load, and a malformed event payload shows as a dropped connection.
- **Auth:** with `LLM_MODE=bedrock` and no `API_ACCESS_TOKEN` the API only logs a warning. Always set a token when the API is reachable from a network.
- **Evaluator retry** keeps the first reading when both score the same number of criteria, even if the retry was stricter.

## Licence

[MIT](LICENSE)
