# Threat model

## Protected assets

- Account balances and immutable ledger history.
- Transfer identifiers and idempotency records.
- API credentials and event contents.
- Tokenized risk-review facts, policy evidence, model credentials, and review traces.

## Controls implemented

- API requests use a header credential checked with a constant-time digest comparison.
- Strict request schemas reject unknown fields and constrain identifiers, amounts, currencies, and text.
- Decimal arithmetic and a balanced debit/credit invariant avoid binary floating-point accounting errors.
- Deterministic PostgreSQL row locking prevents concurrent overspending and reduces deadlock risk.
- Idempotency keys bind to a request fingerprint, preventing duplicate posting or key reuse with changed data.
- SQLAlchemy parameterizes database statements.
- Containers run as an unprivileged user; CI receives read-only repository permission.
- Correlation IDs support request tracing without exposing internal exception detail.
- Risk-review inputs exclude direct identity fields and redact common identifiers in untrusted notes.
- The model can call only case-fact and policy-search tools; neither tool mutates accounts or transfers.
- Provider credentials are carried in headers; provider errors are normalized without raw output.
- Strict output schemas, retrieved-evidence validation, deterministic minimum queues, and a four-step limit
  prevent unsupported autonomous decisions and unbounded loops.
- Every review response is a routing recommendation that requires a human decision.

## Deliberate limits

This is a reference implementation, not a production payment system. Before production use it needs a
managed secret store and key rotation, tenant-aware authorization, TLS termination, rate limiting,
database migrations, tamper-evident audit retention, observability and alerting, backup/restore drills,
regulatory review, and consumer-side event deduplication.

The risk-review workflow also needs institution-approved policies, case-system authorization, sanctions and
identity-provider integrations, tamper-evident review retention, calibrated model evaluations, red-team
testing, model/provider monitoring, and regulatory approval before any production use. The repository's
policy documents and test cases are synthetic engineering fixtures.
