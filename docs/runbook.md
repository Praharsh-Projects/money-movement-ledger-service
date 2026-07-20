# Local runbook

## Start

```bash
export API_KEY="replace-with-a-long-random-secret"
docker compose up --build
```

API documentation is available at `http://localhost:8000/docs`. Liveness and dependency readiness are
exposed at `/health/live` and `/health/ready`.

## Verify a transfer

```bash
curl -sS -X POST http://localhost:8000/v1/accounts \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"account_id":"source","currency":"SEK","opening_balance":"500.0000"}'

curl -sS -X POST http://localhost:8000/v1/accounts \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"account_id":"destination","currency":"SEK","opening_balance":"0"}'

curl -sS -X POST http://localhost:8000/v1/transfers \
  -H "X-API-Key: $API_KEY" -H 'Idempotency-Key: demo-transfer-1' \
  -H 'Content-Type: application/json' \
  -d '{"source_account_id":"source","destination_account_id":"destination","amount":"125.5000","currency":"SEK","reference":"demo"}'
```

Repeating the final command returns the original transfer with `replayed: true` and does not post a
second ledger entry pair.

## Recovery notes

- If Redis is unavailable, transfers still commit and outbox rows remain pending; restart the worker.
- Monitor events with a non-null `last_error` or rising `attempts`.
- Do not delete an outbox row manually without confirming downstream receipt by `event_id`.
