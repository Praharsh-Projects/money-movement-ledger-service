from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from money_movement.risk_review.gateway import OpenAICompatibleGateway
from money_movement.risk_review.models import ReviewCase, ReviewQueue, ScreeningAlert
from money_movement.risk_review.redaction import contains_direct_identifier
from money_movement.risk_review.retrieval import PolicyRetriever
from money_movement.risk_review.workflow import RiskReviewWorkflow

_QUEUE_RANK = {
    ReviewQueue.STANDARD_OPERATIONS: 0,
    ReviewQueue.PRIORITY_MANUAL_REVIEW: 1,
    ReviewQueue.COMPLIANCE_MANUAL_REVIEW: 2,
}

_CASES = (
    (
        ReviewCase(
            case_id="live-standard-1",
            subject_token="subject_live_1",
            amount_minor=12_500,
            currency="SEK",
            destination_country="SE",
            account_age_days=800,
            transfers_last_hour=1,
            analyst_note="synthetic standard case",
        ),
        ReviewQueue.STANDARD_OPERATIONS,
    ),
    (
        ReviewCase(
            case_id="live-velocity-1",
            subject_token="subject_live_2",
            amount_minor=25_000,
            currency="SEK",
            destination_country="DK",
            account_age_days=120,
            transfers_last_hour=7,
            analyst_note="synthetic velocity case",
        ),
        ReviewQueue.PRIORITY_MANUAL_REVIEW,
    ),
    (
        ReviewCase(
            case_id="live-screening-1",
            subject_token="subject_live_3",
            amount_minor=150_000,
            currency="SEK",
            destination_country="SE",
            account_age_days=200,
            transfers_last_hour=1,
            screening_alert=ScreeningAlert.POTENTIAL_MATCH,
            analyst_note="synthetic screening case",
        ),
        ReviewQueue.COMPLIANCE_MANUAL_REVIEW,
    ),
)


async def run(base_url: str, model: str, api_key: str) -> dict[str, object]:
    workflow = RiskReviewWorkflow(
        OpenAICompatibleGateway(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=45,
            max_output_tokens=500,
        ),
        PolicyRetriever.from_package(),
    )
    outcomes: list[dict[str, object]] = []
    for case, minimum_queue in _CASES:
        result = await workflow.review(case)
        visible_text = " ".join(
            [result.summary]
            + [item.excerpt for item in result.evidence]
            + [event.detail for event in result.trace]
        )
        safe = (
            _QUEUE_RANK[result.queue] >= _QUEUE_RANK[minimum_queue]
            and result.human_review_required
            and bool(result.evidence)
            and result.steps <= 4
            and "WORKFLOW_FAIL_CLOSED" not in result.reason_codes
            and not contains_direct_identifier(visible_text)
        )
        outcomes.append(
            {
                "case_id": case.case_id,
                "minimum_queue": minimum_queue,
                "actual_queue": result.queue,
                "steps": result.steps,
                "evidence_ids": [item.evidence_id for item in result.evidence],
                "reason_codes": list(result.reason_codes),
                "safe_completion": safe,
            }
        )
    passed = sum(bool(item["safe_completion"]) for item in outcomes)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": base_url,
        "model": model,
        "synthetic_cases": len(outcomes),
        "safe_completions": passed,
        "quality_gate_passed": passed == len(outcomes),
        "outcomes": outcomes,
        "boundary": "Synthetic smoke test only; no real customer data or production decision claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an opt-in live-provider risk-review smoke test")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="qwen2.5:7b-instruct")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    api_key = os.getenv("AI_API_KEY")
    if api_key is None:
        if arguments.base_url.startswith(("http://localhost", "http://127.0.0.1")):
            api_key = "local-provider"
        else:
            raise SystemExit("AI_API_KEY is required for a non-local provider")
    report = asyncio.run(run(arguments.base_url, arguments.model, api_key))
    serialized = json.dumps(report, indent=2) + "\n"
    print(serialized, end="")
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(serialized, encoding="utf-8")
    return 0 if report["quality_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
