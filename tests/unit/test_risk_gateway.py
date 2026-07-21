from __future__ import annotations

import json

import httpx
import pytest

from money_movement.risk_review.gateway import (
    ConversationMessage,
    ModelGatewayError,
    OpenAICompatibleGateway,
    tool_definitions,
)
from money_movement.risk_review.models import FinalRecommendation, ReviewQueue, ToolRequest


@pytest.mark.asyncio
async def test_openai_compatible_gateway_sends_secret_in_header_and_parses_tool_call() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_case_facts",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    gateway = OpenAICompatibleGateway(
        base_url="https://provider.example/v1",
        api_key="top-secret-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    action = await gateway.next_action(
        [ConversationMessage(role="system", content="bounded test")], tool_definitions()
    )

    assert isinstance(action, ToolRequest)
    assert action.name == "get_case_facts"
    assert observed["authorization"] == "Bearer top-secret-key"
    assert "top-secret-key" not in str(observed["url"])
    assert observed["payload"] != {}


@pytest.mark.asyncio
async def test_openai_compatible_gateway_parses_strict_final_json() -> None:
    final = {
        "queue": "PRIORITY_MANUAL_REVIEW",
        "summary": "Human review is required.",
        "reason_codes": ["HIGH_VELOCITY"],
        "evidence_ids": ["manual-review:transaction-velocity"],
        "confidence": 0.88,
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": json.dumps(final)}}]},
        )

    gateway = OpenAICompatibleGateway(
        base_url="http://localhost:11434/v1",
        api_key="local-test-key",
        model="local-model",
        transport=httpx.MockTransport(handler),
    )

    action = await gateway.next_action(
        [ConversationMessage(role="user", content="review")], tool_definitions()
    )

    assert isinstance(action, FinalRecommendation)
    assert action.queue is ReviewQueue.PRIORITY_MANUAL_REVIEW


@pytest.mark.asyncio
async def test_openai_compatible_gateway_rejects_malformed_provider_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    gateway = OpenAICompatibleGateway(
        base_url="https://provider.example/v1",
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError, match="failed validation"):
        await gateway.next_action([ConversationMessage(role="user", content="review")], tool_definitions())


def test_openai_compatible_gateway_validates_configuration() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        OpenAICompatibleGateway(base_url="file:///tmp", api_key="key", model="model")
    with pytest.raises(ValueError, match="api_key"):
        OpenAICompatibleGateway(base_url="https://example.test", api_key="", model="model")
    with pytest.raises(ValueError, match="model"):
        OpenAICompatibleGateway(base_url="https://example.test", api_key="key", model="")
