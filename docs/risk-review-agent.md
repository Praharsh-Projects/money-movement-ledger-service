# Financial Risk Review Workflow

## Purpose

The workflow turns a small set of tokenized transaction and identity-screening signals into a queue
recommendation for a human reviewer. It demonstrates applied-AI engineering boundaries; it does not
replace compliance staff or authorize customer-impacting actions.

## Sequence

```text
Authenticated API request
        |
        v
Strict ReviewCase schema ---- rejects extra fields and raw free-form payloads
        |
        v
Bounded workflow (maximum four model steps)
        |
        +--> get_case_facts ---- removes subject token and redacts untrusted notes
        |
        +--> search_policy ---- BM25 retrieval over packaged policy passages
        |
        v
Strict final schema ---- queue, summary, reason codes, evidence IDs, confidence
        |
        v
Deterministic guardrails ---- minimum queue, required policy, low-confidence escalation
        |
        v
Human-review routing recommendation
```

## Model boundary

`OpenAICompatibleGateway` supports local Ollama and hosted OpenAI-compatible chat-completion APIs. The
provider receives bounded context, two allowlisted read-only tools, temperature zero, a maximum output
token count, and a request timeout. The API key is sent in the `Authorization` header and never placed in
the URL, prompt, trace, or returned error.

`PolicyAwareBaselineGateway` is a deterministic offline baseline for tests and local operation. It follows
the same tool and guardrail route but is not an LLM and is not presented as model evidence.

## Guardrails

- The subject token remains at the application boundary but is excluded from model-visible case facts.
- Email addresses, phone-like numbers, Swedish personal identity numbers, and payment-card patterns are
  redacted from untrusted notes.
- Tool calls accept strict arguments; unknown tools and malformed calls fail closed.
- Policy-search queries include deterministic case context so required policies remain retrievable.
- Final evidence IDs must refer to retrieved passages; the guardrail adds the required policy if needed.
- Screening alerts cannot be routed below compliance manual review.
- Document mismatch, configured transaction velocity, and the SEK new-device/value threshold cannot be
  routed below priority manual review.
- Confidence below 0.65 cannot remain in the standard queue.
- Traces contain event classes and control decisions, not raw model output or direct identifiers.
- Every response requires a human and is labeled `ROUTING_RECOMMENDATION_ONLY`.

## Failure behavior

Provider errors, malformed model output, unknown tools, unsupported citations, and exhausted step budgets
return a fail-closed manual-review result. A screening case fails closed to the compliance queue; other
cases fail closed to priority review.

## Evaluation

`evals/risk_review_cases.json` contains 20 synthetic regression cases across standard operations, velocity,
identity-document/new-device signals, and screening alerts. The gate requires 100% expected routing, policy
citations, human-review gating, and bounded completion; zero direct-identifier leaks; and zero fail-closed
results for the deterministic baseline.

`scripts/live_risk_review_smoke.py` exercises three synthetic cases against an opt-in OpenAI-compatible
provider. It checks safe minimum queues, evidence, human-review gating, the step bound, identifier leakage,
and fail-closed outcomes. It is a smoke test, not a regulatory or production benchmark.

## Deliberate limits

- No real customer or transaction data is included.
- The policies are engineering fixtures, not legal advice or an institution's approved policy set.
- No transfer is approved, rejected, held, or blocked by the workflow.
- No sanctions source, identity provider, case-management system, or production model is integrated.
- Currency conversion and country-specific thresholds are intentionally out of scope.
- Production adoption would require policy ownership, legal and model-risk review, access control, audit
  retention, monitoring, calibrated evaluations, red-team testing, incident response, and measured latency
  and cost objectives.
