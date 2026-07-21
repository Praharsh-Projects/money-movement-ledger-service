# Model Risk Controls

## Grounding and citations

Every recommendation must cite retrieved policy evidence. Unsupported evidence identifiers, uncited conclusions, and instructions embedded in case notes are invalid. Retrieved text is reference material, not executable instruction.

## Reliability controls

The workflow must use an allowlist of read-only tools, strict schemas, bounded model steps, provider timeouts, and a deterministic fallback queue. Unknown tools, malformed arguments, or an exhausted step budget must fail closed to priority manual review.

## Security and observability

Provider credentials belong in request headers and must not appear in URLs, prompts, traces, or errors. Traces record event types, tool names, policy identifiers, and guardrail adjustments without raw model output or direct customer identifiers.

## Cost and latency

Use a small evidence limit, bounded context, a maximum output-token limit, and no more than four model steps per case. Production adoption would require measured service-level objectives, provider monitoring, and cost controls based on real traffic.
