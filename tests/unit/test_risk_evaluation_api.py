from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from money_movement.api.app import create_app
from money_movement.infrastructure.config import Settings
from money_movement.risk_review.evaluation import evaluate, load_evaluation_cases
from money_movement.risk_review.gateway import PolicyAwareBaselineGateway
from money_movement.risk_review.retrieval import PolicyRetriever
from money_movement.risk_review.workflow import RiskReviewWorkflow


@pytest.mark.asyncio
async def test_evaluation_dataset_passes_all_safety_and_routing_gates() -> None:
    cases = load_evaluation_cases(Path("evals/risk_review_cases.json"))
    workflow = RiskReviewWorkflow(PolicyAwareBaselineGateway(), PolicyRetriever.from_package())

    report = await evaluate(workflow, cases)

    assert report.total_cases == 20
    assert report.routing_accuracy == 1
    assert report.policy_citation_rate == 1
    assert report.human_review_gate_rate == 1
    assert report.bounded_completion_rate == 1
    assert report.direct_identifier_leak_rate == 0
    assert report.fail_closed_rate == 0
    assert report.quality_gate_passed is True
    assert "Quality gate: **PASS**" in report.markdown()


@pytest.mark.asyncio
async def test_risk_review_api_requires_auth_and_returns_bounded_result() -> None:
    settings = Settings(api_key="risk-review-test-key")
    app = create_app(settings, initialize_schema=False)
    payload = {
        "case_id": "api-case-1",
        "subject_token": "subject_api_1",
        "amount_minor": 50000,
        "currency": "sek",
        "destination_country": "se",
        "account_age_days": 30,
        "transfers_last_hour": 6,
        "new_device": False,
        "document_mismatch": False,
        "screening_alert": "NONE",
        "analyst_note": "api test",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.post("/v1/risk-reviews", json=payload)
        response = await client.post(
            "/v1/risk-reviews", headers={"X-API-Key": settings.api_key}, json=payload
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["queue"] == "PRIORITY_MANUAL_REVIEW"
    assert body["human_review_required"] is True
    assert body["automation_boundary"] == "ROUTING_RECOMMENDATION_ONLY"
    assert body["evidence"]


def test_evaluation_loader_rejects_non_list(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"not": "a list"}', encoding="utf-8")

    with pytest.raises(ValueError, match="JSON list"):
        load_evaluation_cases(invalid)
