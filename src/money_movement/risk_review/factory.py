from __future__ import annotations

from money_movement.infrastructure.config import Settings
from money_movement.risk_review.gateway import (
    ModelGateway,
    OpenAICompatibleGateway,
    PolicyAwareBaselineGateway,
)
from money_movement.risk_review.retrieval import PolicyRetriever
from money_movement.risk_review.workflow import RiskReviewWorkflow


def build_risk_review_workflow(settings: Settings) -> RiskReviewWorkflow:
    retriever = PolicyRetriever.from_package()
    gateway: ModelGateway
    if settings.risk_review_mode == "openai_compatible":
        if settings.ai_api_key is None:
            raise ValueError("AI_API_KEY is required when RISK_REVIEW_MODE=openai_compatible")
        gateway = OpenAICompatibleGateway(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key.get_secret_value(),
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_output_tokens=settings.ai_max_output_tokens,
        )
    else:
        gateway = PolicyAwareBaselineGateway()
    return RiskReviewWorkflow(gateway, retriever)
