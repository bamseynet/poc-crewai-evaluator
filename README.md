# poc-crewai-evaluator

A proof of concept showing one agent framework, [CrewAI](https://docs.crewai.com), implementing one
agentic pattern, the **evaluator-optimizer** loop, for one enterprise job: drafting policy and
compliance documents.

A writer crew (researcher and drafter) produces a draft. An evaluator agent scores it against a
YAML rubric, criterion by criterion, with specific feedback. A CrewAI Flow feeds that feedback into
the next revision, until every criterion passes or the iteration budget runs out, and it records why
it stopped.

This branch contains the agent core. The API, web UI, infrastructure and full documentation follow
in later pull requests.

## Try it

You need [uv](https://docs.astral.sh/uv/). No AWS account is required, because the offline fake LLM
is the default.

```bash
make install
uv run policy-drafter "Draft an acceptable-use policy for AI tools for a 500-person fintech" \
  --rubric regulatory_coverage --output policy.md
make check   # lint, type check and tests, all offline
```

## Where to look

| File | What it shows |
| --- | --- |
| [`src/policy_drafter/flow.py`](src/policy_drafter/flow.py) | The loop, as a CrewAI Flow |
| [`src/policy_drafter/crews.py`](src/policy_drafter/crews.py) | The researcher, drafter and evaluator |
| [`src/policy_drafter/prompts.py`](src/policy_drafter/prompts.py) | What each role is told, including how feedback is fed back |
| [`src/policy_drafter/scoring.py`](src/policy_drafter/scoring.py) | Parsing model output so that malformed scores fail closed |
| [`src/policy_drafter/rubric_files/`](src/policy_drafter/rubric_files/) | The YAML rubrics |
| [`tests/test_flow.py`](tests/test_flow.py) | The behaviour of the loop |

## Licence

[MIT](LICENSE)
