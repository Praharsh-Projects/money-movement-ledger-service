from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from money_movement.risk_review.gateway import (
    ConversationMessage,
    ModelGateway,
    PolicyAwareBaselineGateway,
)
from money_movement.risk_review.models import (
    FinalRecommendation,
    ModelAction,
    ReviewCase,
    ReviewQueue,
    ScreeningAlert,
    ToolRequest,
)
from money_movement.risk_review.redaction import contains_direct_identifier, redact_text
from money_movement.risk_review.retrieval import PolicyRetriever
from money_movement.risk_review.workflow import RiskReviewWorkflow


def review_case(**overrides: object) -> ReviewCase:
    values: dict[str, object] = {
        "case_id": "case-001",
        "subject_token": "subject_001",
        "amount_minor": 50_000,
        "currency": "SEK",
        "destination_country": "SE",
        "account_age_days": 400,
        "transfers_last_hour": 1,
        "new_device": False,
        "document_mismatch": False,
        "screening_alert": "NONE",
        "analyst_note": "routine review",
    }
    values.update(overrides)
    return ReviewCase.model_validate(values)


def workflow(gateway: ModelGateway | None = None, *, max_steps: int = 4) -> RiskReviewWorkflow:
    return RiskReviewWorkflow(
        gateway or PolicyAwareBaselineGateway(), PolicyRetriever.from_package(), max_steps=max_steps
    )


@pytest.mark.parametrize(
    "value",
    [
        "email alice@example.com",
        "phone +46 70 123 45 67",
        "identity 19800101-1234",
        "card 4111 1111 1111 1111",
    ],
)
def test_redaction_removes_direct_identifiers(value: str) -> None:
    result = redact_text(value)

    assert "REDACTED" in result
    assert not contains_direct_identifier(result)


def test_policy_retriever_returns_ranked_evidence() -> None:
    evidence = PolicyRetriever.from_package().search(
        "sanctions screening potential match compliance manual review", limit=2
    )

    assert evidence
    assert evidence[0].source == "identity-and-screening.md"
    assert evidence[0].section == "Screening alerts"
    assert evidence[0].score >= evidence[-1].score


@pytest.mark.asyncio
async def test_standard_case_keeps_human_review_boundary_and_policy_citation() -> None:
    result = await workflow().review(review_case())

    assert result.queue is ReviewQueue.STANDARD_OPERATIONS
    assert result.human_review_required is True
    assert result.automation_boundary == "ROUTING_RECOMMENDATION_ONLY"
    assert result.evidence
    assert result.steps == 3
    assert result.trace[-1].detail == "human_review_required"


@pytest.mark.asyncio
async def test_deterministic_signals_route_to_expected_queues() -> None:
    priority = await workflow().review(review_case(transfers_last_hour=6))
    compliance = await workflow().review(review_case(screening_alert=ScreeningAlert.POTENTIAL_MATCH))

    assert priority.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW
    assert "HIGH_VELOCITY" in priority.reason_codes
    assert compliance.queue is ReviewQueue.COMPLIANCE_MANUAL_REVIEW
    assert "SCREENING_ALERT" in compliance.reason_codes


class CapturingGateway:
    def __init__(self) -> None:
        self._delegate = PolicyAwareBaselineGateway()
        self.seen: list[tuple[ConversationMessage, ...]] = []

    @property
    def model_name(self) -> str:
        return "capturing-baseline"

    async def next_action(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelAction:
        self.seen.append(tuple(messages))
        return await self._delegate.next_action(messages, tools)


@pytest.mark.asyncio
async def test_subject_token_is_excluded_and_note_is_redacted_before_model_access() -> None:
    gateway = CapturingGateway()

    await workflow(gateway).review(
        review_case(
            subject_token="secret_subject_99",
            analyst_note="email alice@example.com or call +46 70 123 45 67",
        )
    )

    visible = " ".join(message.content or "" for turn in gateway.seen for message in turn)
    assert "secret_subject_99" not in visible
    assert "alice@example.com" not in visible
    assert "+46 70 123 45 67" not in visible
    assert "[REDACTED_EMAIL]" in visible


class ScriptedGateway:
    def __init__(self, actions: Sequence[ModelAction], *, repeat_last: bool = False) -> None:
        self._actions = list(actions)
        self._repeat_last = repeat_last
        self._index = 0

    @property
    def model_name(self) -> str:
        return "scripted-test-model"

    async def next_action(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelAction:
        del messages, tools
        if self._index < len(self._actions):
            action = self._actions[self._index]
            self._index += 1
            return action
        if self._repeat_last and self._actions:
            return self._actions[-1]
        raise AssertionError("scripted gateway ran out of actions")


@pytest.mark.asyncio
async def test_unknown_tool_fails_closed_without_exposing_model_output() -> None:
    gateway = ScriptedGateway([ToolRequest(call_id="unknown-1", name="write_account_status", arguments={})])

    result = await workflow(gateway).review(review_case())

    assert result.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW
    assert result.reason_codes == ("WORKFLOW_FAIL_CLOSED", "ToolPolicyError")
    assert result.evidence


@pytest.mark.asyncio
async def test_step_budget_exhaustion_fails_closed() -> None:
    repeated = ToolRequest(call_id="facts-1", name="get_case_facts", arguments={})
    gateway = ScriptedGateway([repeated], repeat_last=True)

    result = await workflow(gateway, max_steps=2).review(review_case())

    assert result.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW
    assert "STEP_BUDGET_EXHAUSTED" in result.reason_codes
    assert result.steps == 2


@pytest.mark.asyncio
async def test_unsupported_citation_fails_closed() -> None:
    gateway = ScriptedGateway(
        [
            FinalRecommendation(
                queue=ReviewQueue.STANDARD_OPERATIONS,
                summary="Unsupported conclusion",
                reason_codes=["NO_SIGNAL"],
                evidence_ids=["invented:evidence"],
                confidence=0.9,
            )
        ]
    )

    result = await workflow(gateway).review(review_case())

    assert result.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW
    assert "RecommendationPolicyError" in result.reason_codes


@pytest.mark.asyncio
async def test_guardrail_prevents_screening_downgrade() -> None:
    retriever = PolicyRetriever.from_package()
    evidence = retriever.search("screening alert compliance manual review", limit=1)[0]
    gateway = ScriptedGateway(
        [
            ToolRequest(
                call_id="policy-1",
                name="search_policy",
                arguments={"query": "screening alert compliance manual review"},
            ),
            FinalRecommendation(
                queue=ReviewQueue.STANDARD_OPERATIONS,
                summary="Model attempted a lower queue.",
                reason_codes=["MODEL_OUTPUT"],
                evidence_ids=[evidence.evidence_id],
                confidence=0.9,
            ),
        ]
    )

    result = await workflow(gateway).review(review_case(screening_alert=ScreeningAlert.POTENTIAL_MATCH))

    assert result.queue is ReviewQueue.COMPLIANCE_MANUAL_REVIEW
    assert "DETERMINISTIC_ESCALATION" in result.reason_codes
    assert any(event.detail == "minimum_queue" for event in result.trace)


@pytest.mark.asyncio
async def test_low_confidence_standard_output_routes_to_priority_review() -> None:
    retriever = PolicyRetriever.from_package()
    evidence = retriever.search("human decision boundary", limit=1)[0]
    gateway = ScriptedGateway(
        [
            ToolRequest(
                call_id="policy-1",
                name="search_policy",
                arguments={"query": "human decision boundary"},
            ),
            FinalRecommendation(
                queue=ReviewQueue.STANDARD_OPERATIONS,
                summary="Uncertain recommendation",
                reason_codes=["UNCERTAIN"],
                evidence_ids=[evidence.evidence_id],
                confidence=0.4,
            ),
        ]
    )

    result = await workflow(gateway).review(review_case())

    assert result.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW
    assert "LOW_MODEL_CONFIDENCE" in result.reason_codes
