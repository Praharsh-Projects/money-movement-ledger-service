# Threat model

## Protected assets

- Account balances and immutable ledger history.
- Transfer identifiers and idempotency records.
- API credentials and event contents.

## Controls implemented

- API requests use a header credential checked with a constant-time digest comparison.
- Strict request schemas reject unknown fields and constrain identifiers, amounts, currencies, and text.
- Decimal arithmetic and a balanced debit/credit invariant avoid binary floating-point accounting errors.
- Deterministic PostgreSQL row locking prevents concurrent overspending and reduces deadlock risk.
- Idempotency keys bind to a request fingerprint, preventing duplicate posting or key reuse with changed data.
- SQLAlchemy parameterizes database statements.
- Containers run as an unprivileged user; CI receives read-only repository permission.
- Correlation IDs support request tracing without exposing internal exception detail.

## Deliberate limits

This is a reference implementation, not a production payment system. Before production use it needs a
managed secret store and key rotation, tenant-aware authorization, TLS termination, rate limiting,
database migrations, tamper-evident audit retention, observability and alerting, backup/restore drills,
regulatory review, and consumer-side event deduplication.
