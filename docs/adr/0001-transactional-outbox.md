# ADR 0001: PostgreSQL transactional outbox

## Status

Accepted.

## Context

A transfer and its integration event must not diverge. Publishing directly to Redis before committing
the ledger can announce a failed transfer; publishing after commit can lose the event during a crash.

## Decision

Write the transfer, balances, double-entry ledger rows, idempotency record, and outbox event in one
PostgreSQL transaction. A worker claims undispatched rows with `FOR UPDATE SKIP LOCKED`, publishes each
event to Redis Streams, and records dispatch metadata.

## Consequences

- Database state and event intent commit atomically.
- Delivery is at least once, so consumers must deduplicate by `event_id`.
- A production deployment should add dead-letter handling and alerting for repeated dispatch failures.
