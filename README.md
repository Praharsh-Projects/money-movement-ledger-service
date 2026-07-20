# Money Movement Ledger Service

A secure Python/FastAPI reference backend for posting account-to-account money movements. It demonstrates
Domain-Driven Design boundaries, transactional consistency, idempotent APIs, double-entry ledger rules,
and reliable event publication through a PostgreSQL transactional outbox and Redis Streams.

[![CI](https://github.com/Praharsh-Projects/money-movement-ledger-service/actions/workflows/ci.yml/badge.svg)](https://github.com/Praharsh-Projects/money-movement-ledger-service/actions/workflows/ci.yml)

> This is an independently built portfolio/reference project. It is not deployed to production and does
> not claim processing of real customer funds.

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

## Design

```text
src/money_movement/
├── domain/          # money, transfer, ledger, and event invariants
├── application/     # use cases and unit-of-work port
├── infrastructure/  # PostgreSQL and Redis adapters
└── api/             # FastAPI schemas, authentication, and HTTP mapping
```

See [architecture](docs/architecture.md), [transactional-outbox ADR](docs/adr/0001-transactional-outbox.md),
[threat model](docs/threat-model.md), and [runbook](docs/runbook.md).

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
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest tests/unit --cov=money_movement.domain --cov=money_movement.application --cov-report=term-missing
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
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | PostgreSQL and Redis readiness |

All `/v1` routes require `X-API-Key`; transfer creation also requires `Idempotency-Key`.

## Verification boundary

The test suite verifies domain invariants, idempotent behavior, atomic database state, outbox creation,
Redis publication, linting, strict type checking, and image construction. The project does not claim
production traffic, cloud deployment, regulatory certification, blockchain integration, or operational
ownership of a live financial system.
