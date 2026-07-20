# Architecture

The service uses Domain-Driven Design boundaries so financial rules remain independent of HTTP,
PostgreSQL, and Redis.

```text
HTTP / FastAPI
      |
      v
Application service ---- Unit-of-work port
      |                         |
      v                         v
Domain model             PostgreSQL adapter
                                  |
                       transfers + ledger + outbox
                                  |
                                  v
                           Outbox worker
                                  |
                                  v
                            Redis Streams
```

## Transfer transaction

1. Look up the idempotency key and reject a changed request fingerprint.
2. Lock both account rows in deterministic account-ID order.
3. Validate account existence, currency, and available balance.
4. Create one transfer, one debit, one credit, one idempotency record, and one outbox event.
5. Commit all records and balance updates in one PostgreSQL transaction.
6. A separate worker publishes committed events to Redis Streams and marks them dispatched.

The outbox boundary prevents a database commit from being lost when the event broker is unavailable.
Delivery is at least once: downstream consumers must deduplicate on `event_id`.

## Domain boundaries

- **Domain:** money normalization, transfer invariants, balanced ledger entries, domain-event creation.
- **Application:** use-case orchestration and infrastructure ports.
- **Infrastructure:** SQLAlchemy/PostgreSQL unit of work and Redis Streams dispatcher.
- **API:** authentication, validation, HTTP error mapping, and correlation IDs.
