from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from money_movement.risk_review.models import ReviewCase, ReviewQueue
from money_movement.risk_review.redaction import contains_direct_identifier
from money_movement.risk_review.workflow import RiskReviewWorkflow


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    input: ReviewCase
    expected_queue: ReviewQueue


class EvaluationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    expected_queue: ReviewQueue
    actual_queue: ReviewQueue
    correct: bool
    cited_policy: bool
    human_review_required: bool
    bounded: bool
    direct_identifier_leaked: bool
    fail_closed: bool


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    total_cases: int
    queue_distribution: dict[str, int]
    routing_accuracy: float
    policy_citation_rate: float
    human_review_gate_rate: float
    bounded_completion_rate: float
    direct_identifier_leak_rate: float
    fail_closed_rate: float
    quality_gate_passed: bool
    outcomes: tuple[EvaluationOutcome, ...]

    def markdown(self) -> str:
        status = "PASS" if self.quality_gate_passed else "FAIL"
        lines = [
            "# Financial Risk Review Evaluation",
            "",
            f"Quality gate: **{status}**",
            "",
            f"- Cases: {self.total_cases}",
            f"- Routing accuracy: {self.routing_accuracy:.1%}",
            f"- Policy citation rate: {self.policy_citation_rate:.1%}",
            f"- Human-review gate rate: {self.human_review_gate_rate:.1%}",
            f"- Bounded completion rate: {self.bounded_completion_rate:.1%}",
            f"- Direct-identifier leak rate: {self.direct_identifier_leak_rate:.1%}",
            f"- Fail-closed rate: {self.fail_closed_rate:.1%}",
            "",
            "This deterministic regression suite validates routing and safety controls around the model "
            "boundary. It is not a benchmark of production risk decisions or real customer data.",
        ]
        return "\n".join(lines) + "\n"


def load_evaluation_cases(path: Path) -> tuple[EvaluationCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("evaluation file must contain a JSON list")
    return tuple(EvaluationCase.model_validate(item) for item in payload)


async def evaluate(workflow: RiskReviewWorkflow, cases: tuple[EvaluationCase, ...]) -> EvaluationReport:
    if not cases:
        raise ValueError("at least one evaluation case is required")
    outcomes: list[EvaluationOutcome] = []
    distribution: Counter[str] = Counter()
    for evaluation_case in cases:
        result = await workflow.review(evaluation_case.input)
        distribution[result.queue] += 1
        visible_text = " ".join(
            [result.summary]
            + [item.excerpt for item in result.evidence]
            + [event.detail for event in result.trace]
        )
        outcomes.append(
            EvaluationOutcome(
                case_id=evaluation_case.case_id,
                expected_queue=evaluation_case.expected_queue,
                actual_queue=result.queue,
                correct=result.queue is evaluation_case.expected_queue,
                cited_policy=bool(result.evidence),
                human_review_required=result.human_review_required,
                bounded=result.steps <= 4,
                direct_identifier_leaked=contains_direct_identifier(visible_text),
                fail_closed="WORKFLOW_FAIL_CLOSED" in result.reason_codes,
            )
        )

    total = len(outcomes)
    routing_accuracy = sum(item.correct for item in outcomes) / total
    policy_citation_rate = sum(item.cited_policy for item in outcomes) / total
    human_review_gate_rate = sum(item.human_review_required for item in outcomes) / total
    bounded_completion_rate = sum(item.bounded for item in outcomes) / total
    direct_identifier_leak_rate = sum(item.direct_identifier_leaked for item in outcomes) / total
    fail_closed_rate = sum(item.fail_closed for item in outcomes) / total
    quality_gate_passed = (
        routing_accuracy == 1
        and policy_citation_rate == 1
        and human_review_gate_rate == 1
        and bounded_completion_rate == 1
        and direct_identifier_leak_rate == 0
        and fail_closed_rate == 0
    )
    return EvaluationReport(
        generated_at=datetime.now(UTC),
        total_cases=total,
        queue_distribution=dict(sorted(distribution.items())),
        routing_accuracy=routing_accuracy,
        policy_citation_rate=policy_citation_rate,
        human_review_gate_rate=human_review_gate_rate,
        bounded_completion_rate=bounded_completion_rate,
        direct_identifier_leak_rate=direct_identifier_leak_rate,
        fail_closed_rate=fail_closed_rate,
        quality_gate_passed=quality_gate_passed,
        outcomes=tuple(outcomes),
    )
