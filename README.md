# Money Movement Ledger and Risk Review Service

A secure Python/FastAPI reference backend for posting account-to-account money movements. It demonstrates
Domain-Driven Design boundaries, transactional consistency, idempotent APIs, double-entry ledger rules,
reliable event publication through a PostgreSQL transactional outbox and Redis Streams, and a bounded
AI-assisted workflow for routing tokenized financial-risk cases to human review.

[![CI](https://github.com/Praharsh-Projects/money-movement-ledger-service/actions/workflows/ci.yml/badge.svg)](https://github.com/Praharsh-Projects/money-movement-ledger-service/actions/workflows/ci.yml)

> This is an independently built portfolio/reference project. It is not deployed to production and does
> not claim processing real customer funds, making KYC decisions, or handling real customer data.

## What is implemented

- Python 3.12, FastAPI, SQLAlchemy asyncio, PostgreSQL, and Redis Streams.
- Domain entities that enforce positive decimal money, distinct accounts, and balanced debit/credit rows.
- One ACID transaction for balance updates, transfer, ledger entries, idempotency record, and outbox event.
- Account row locks acquired in sorted order to prevent concurrent overspending and reduce deadlocks.
- Idempotency replay for the same request and conflict detection for a changed request.
- Outbox worker with `FOR UPDATE SKIP LOCKED` and at-least-once Redis Streams delivery.
- Constant-time API-key verification, strict schemas, correlation IDs, and health endpoints.
- Unit tests plus real PostgreSQL/Redis integration tests in GitHub Actions.
- Multi-stage, non-root container build and local Docker Compose topology.
- A four-step maximum risk-review loop with read-only tool calling, strict model schemas, policy retrieval,
  evidence citations, deterministic minimum queues, and fail-closed human escalation.
- Data minimization and identifier redaction before model access; provider credentials stay in headers.
- An OpenAI-compatible gateway for opt-in LLM use plus a deterministic offline baseline for CI.
- A 20-case synthetic regression evaluation and an opt-in three-case live Ollama smoke test.

## Design

```text
src/money_movement/
├── domain/          # money, transfer, ledger, and event invariants
├── application/     # use cases and unit-of-work port
├── infrastructure/  # PostgreSQL and Redis adapters
├── risk_review/     # tool loop, retrieval, guardrails, provider gateway, evaluation
└── api/             # authentication, validation, and HTTP mapping
```

See [architecture](docs/architecture.md), [risk-review design](docs/risk-review-agent.md),
[transactional-outbox ADR](docs/adr/0001-transactional-outbox.md), [threat model](docs/threat-model.md),
and [runbook](docs/runbook.md).

## Run locally

Docker is the shortest complete path:

```bash
export API_KEY="replace-with-a-long-random-secret"
docker compose up --build
```

Open `http://localhost:8000/docs`. See the [runbook](docs/runbook.md) for request examples.

For local code checks without infrastructure:

```bash
uv sync --all-extras
make quality
```

The PostgreSQL/Redis integration suite runs in CI. It can also run against local services by setting
`TEST_DATABASE_URL` and `TEST_REDIS_URL` before `uv run pytest tests/integration -v`.

## API summary

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/accounts` | Create a test ledger account |
| `POST` | `/v1/transfers` | Post an idempotent money movement |
| `GET` | `/v1/transfers/{transfer_id}` | Retrieve a transfer |
| `GET` | `/v1/accounts/{account_id}/ledger` | Retrieve account ledger entries |
| `POST` | `/v1/risk-reviews` | Recommend a human-review queue with policy citations |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | PostgreSQL and Redis readiness |

All `/v1` routes require `X-API-Key`; transfer creation also requires `Idempotency-Key`.

## AI-assisted risk review

The default `policy_baseline` mode runs locally and deterministically. It traverses the same case-facts,
policy-search, grounding, and guardrail boundary used by the provider gateway, but it is not described as
an LLM. To use an OpenAI-compatible provider, set:

```bash
export RISK_REVIEW_MODE=openai_compatible
export AI_BASE_URL=http://localhost:11434/v1
export AI_MODEL=qwen2.5:7b-instruct
export AI_API_KEY=local-provider
```

The API accepts tokenized synthetic case facts rather than names, addresses, raw identity numbers,
payment-card data, document images, or account credentials. Every output sets
`human_review_required=true` and `automation_boundary=ROUTING_RECOMMENDATION_ONLY`.

Run the deterministic evaluation:

```bash
make eval
```

Run the opt-in live-provider smoke test against a local Ollama server:

```bash
uv run python scripts/live_risk_review_smoke.py
```

The checked deterministic suite contains 20 synthetic cases. It measures queue routing, policy citation,
bounded completion, human-review gating, identifier leakage, and fail-closed behavior. The live smoke test
uses three synthetic cases and does not establish production accuracy.

## Verification snapshot

- 35 unit and API tests passed with 93.97% combined coverage over the ledger domain/application and
  risk-review core.
- 20/20 deterministic evaluation cases passed all routing and safety gates.
- 3/3 synthetic live-provider cases completed safely with local Ollama and `qwen2.5:7b-instruct`.
- The Python environment audit reported no known third-party dependency vulnerabilities.
- The wheel build contains the packaged policy corpus and passed an isolated install/retrieval smoke test.

Measured reports are checked in under [`reports/`](reports/). These results do not establish production
service levels, model accuracy on customer data, or regulatory suitability.

## Verification boundary

The test suite verifies domain invariants, idempotent behavior, atomic database state, outbox creation,
Redis publication, risk routing and guardrails, API authentication, policy retrieval, provider-response
validation, identifier redaction, deterministic evaluation, linting, strict type checking, and image
construction. The project does not claim production traffic, cloud deployment, regulatory certification,
autonomous KYC or fraud decisions, provider service levels, or ownership of a live financial system.
