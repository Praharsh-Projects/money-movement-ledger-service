from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from money_movement.risk_review.models import (
    FinalRecommendation,
    ModelAction,
    ReviewQueue,
    ToolRequest,
)


class ModelGatewayError(RuntimeError):
    """Raised when a model provider response cannot be used safely."""


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    requested_tool: ToolRequest | None = None

    def provider_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"role": self.role}
        if self.requested_tool is not None:
            payload["content"] = None
            payload["tool_calls"] = [
                {
                    "id": self.requested_tool.call_id,
                    "type": "function",
                    "function": {
                        "name": self.requested_tool.name,
                        "arguments": json.dumps(
                            self.requested_tool.arguments, sort_keys=True, separators=(",", ":")
                        ),
                    },
                }
            ]
        else:
            payload["content"] = self.content or ""
        if self.name is not None:
            payload["name"] = self.name
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


class ModelGateway(Protocol):
    @property
    def model_name(self) -> str: ...

    async def next_action(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelAction: ...


def tool_definitions() -> tuple[dict[str, object], ...]:
    return (
        {
            "type": "function",
            "function": {
                "name": "get_case_facts",
                "description": "Read minimized, redacted facts for the current risk-review case.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_policy",
                "description": "Retrieve relevant internal policy passages for a review recommendation.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 240}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    )


class PolicyAwareBaselineGateway:
    """Deterministic local baseline used for CI and offline operation.

    It exercises the same tool-calling and guardrail path as a hosted model but is
    not described as an LLM. Live providers use ``OpenAICompatibleGateway``.
    """

    @property
    def model_name(self) -> str:
        return "policy-aware-baseline-v1"

    async def next_action(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelAction:
        del tools
        facts_message = next(
            (message for message in messages if message.role == "tool" and message.name == "get_case_facts"),
            None,
        )
        if facts_message is None:
            return ToolRequest(call_id="case-facts", name="get_case_facts", arguments={})

        facts = json.loads(facts_message.content or "{}")
        if not isinstance(facts, dict):
            raise ModelGatewayError("case facts tool returned an invalid object")

        policy_message = next(
            (message for message in messages if message.role == "tool" and message.name == "search_policy"),
            None,
        )
        if policy_message is None:
            return ToolRequest(
                call_id="policy-search",
                name="search_policy",
                arguments={"query": _policy_query(facts)},
            )

        evidence_payload = json.loads(policy_message.content or "[]")
        if not isinstance(evidence_payload, list) or not evidence_payload:
            raise ModelGatewayError("policy search returned no evidence")
        evidence_ids = [
            str(item["evidence_id"])
            for item in evidence_payload
            if isinstance(item, dict) and "evidence_id" in item
        ]
        queue, reason_codes = _baseline_recommendation(facts)
        summaries = {
            ReviewQueue.STANDARD_OPERATIONS: (
                "No configured escalation threshold was found; retain human operations review."
            ),
            ReviewQueue.PRIORITY_MANUAL_REVIEW: (
                "Configured risk signals require priority review by an operations analyst."
            ),
            ReviewQueue.COMPLIANCE_MANUAL_REVIEW: (
                "A screening signal requires review by the compliance queue."
            ),
        }
        return FinalRecommendation(
            queue=queue,
            summary=summaries[queue],
            reason_codes=reason_codes,
            evidence_ids=evidence_ids[:3],
            confidence=0.95,
        )


def _policy_query(facts: dict[str, Any]) -> str:
    if facts.get("screening_alert") != "NONE":
        return "sanctions screening alert compliance manual review human decision"
    if facts.get("document_mismatch"):
        return "identity document mismatch priority manual review data minimization"
    if int(facts.get("transfers_last_hour", 0)) >= 6:
        return "transaction velocity six transfers priority manual review"
    if (
        facts.get("new_device")
        and facts.get("currency") == "SEK"
        and int(facts.get("amount_minor", 0)) >= 2_500_000
    ):
        return "new device high value SEK priority manual review"
    return "standard operations queue human decision boundary routing recommendation"


def _baseline_recommendation(facts: dict[str, Any]) -> tuple[ReviewQueue, list[str]]:
    if facts.get("screening_alert") != "NONE":
        return ReviewQueue.COMPLIANCE_MANUAL_REVIEW, ["SCREENING_ALERT"]
    reasons: list[str] = []
    if facts.get("document_mismatch"):
        reasons.append("DOCUMENT_MISMATCH")
    if int(facts.get("transfers_last_hour", 0)) >= 6:
        reasons.append("HIGH_VELOCITY")
    if (
        facts.get("new_device")
        and facts.get("currency") == "SEK"
        and int(facts.get("amount_minor", 0)) >= 2_500_000
    ):
        reasons.append("NEW_DEVICE_HIGH_VALUE")
    if reasons:
        return ReviewQueue.PRIORITY_MANUAL_REVIEW, reasons
    return ReviewQueue.STANDARD_OPERATIONS, ["NO_CONFIGURED_ESCALATION_SIGNAL"]


class OpenAICompatibleGateway:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_output_tokens: int = 500,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._transport = transport

    @property
    def model_name(self) -> str:
        return self._model

    async def next_action(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[Mapping[str, object]],
    ) -> ModelAction:
        payload = {
            "model": self._model,
            "messages": [message.provider_payload() for message in messages],
            "temperature": 0,
            "max_tokens": self._max_output_tokens,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        else:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as client:
                response = await client.post(self._endpoint, json=payload)
                response.raise_for_status()
                body = response.json()
            message = cast(dict[str, Any], body["choices"][0]["message"])
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                if len(tool_calls) != 1:
                    raise ModelGatewayError("provider requested more than one tool in a step")
                call = cast(dict[str, Any], tool_calls[0])
                function = cast(dict[str, Any], call["function"])
                arguments = json.loads(str(function.get("arguments") or "{}"))
                if not isinstance(arguments, dict):
                    raise ModelGatewayError("tool arguments must be a JSON object")
                return ToolRequest(
                    call_id=str(call["id"]),
                    name=str(function["name"]),
                    arguments=arguments,
                )
            content = message.get("content")
            if not isinstance(content, str):
                raise ModelGatewayError("provider returned neither a tool call nor JSON content")
            return FinalRecommendation.model_validate_json(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise ModelGatewayError("provider response failed validation") from exc
