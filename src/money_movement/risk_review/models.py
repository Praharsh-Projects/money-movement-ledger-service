from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

CaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class ReviewQueue(StrEnum):
    STANDARD_OPERATIONS = "STANDARD_OPERATIONS"
    PRIORITY_MANUAL_REVIEW = "PRIORITY_MANUAL_REVIEW"
    COMPLIANCE_MANUAL_REVIEW = "COMPLIANCE_MANUAL_REVIEW"


class ScreeningAlert(StrEnum):
    NONE = "NONE"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    CONFIRMED_TEST_MATCH = "CONFIRMED_TEST_MATCH"


class ReviewCase(BaseModel):
    """Synthetic or tokenized case facts accepted by the review workflow.

    The API deliberately excludes names, document images, addresses, and raw identity
    numbers. ``analyst_note`` is untrusted text and is redacted before model access.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: CaseId
    subject_token: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
    amount_minor: int = Field(gt=0, le=1_000_000_000)
    currency: Currency
    destination_country: CountryCode
    account_age_days: int = Field(ge=0, le=36_500)
    transfers_last_hour: int = Field(ge=0, le=10_000)
    new_device: bool = False
    document_mismatch: bool = False
    screening_alert: ScreeningAlert = ScreeningAlert.NONE
    analyst_note: str = Field(default="", max_length=500)

    @field_validator("currency", "destination_country", mode="before")
    @classmethod
    def normalize_uppercase(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    source: str
    section: str
    excerpt: str
    score: float = Field(ge=0)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool_request"] = "tool_request"
    call_id: CaseId
    name: str
    arguments: dict[str, object]


class FinalRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["final"] = "final"
    queue: ReviewQueue
    summary: str = Field(min_length=1, max_length=400)
    reason_codes: list[str] = Field(min_length=1, max_length=8)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)
    confidence: float = Field(ge=0, le=1)


ModelAction = ToolRequest | FinalRecommendation


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step: int = Field(ge=1)
    event: Literal["model_action", "tool_result", "guardrail_adjustment", "completed"]
    detail: str


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    queue: ReviewQueue
    summary: str
    reason_codes: tuple[str, ...]
    evidence: tuple[PolicyEvidence, ...]
    human_review_required: Literal[True] = True
    automation_boundary: Literal["ROUTING_RECOMMENDATION_ONLY"] = "ROUTING_RECOMMENDATION_ONLY"
    model_name: str
    steps: int = Field(ge=1)
    trace: tuple[TraceEvent, ...]
