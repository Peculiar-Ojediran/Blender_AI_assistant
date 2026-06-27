import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

from extension.operations import OPERATION_PLAN_SCHEMA
from extension.providers.base import PlanRequest, TokenUsage
from extension.providers.nvidia import (
    CUSTOM_MODEL_OPTION,
    DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS,
    DEFAULT_NVIDIA_MODEL,
    DEFAULT_NVIDIA_TEMPERATURE,
    DEFAULT_NVIDIA_TIMEOUT_SECONDS,
    DEFAULT_NVIDIA_TOP_P,
    NVIDIA_DEFAULT_BASE_URL,
    NvidiaAPIError,
    NvidiaConfigurationError,
    NvidiaProvider,
    NvidiaResponseError,
    resolve_nvidia_model_name,
)

VALID_PLAN = {
    "snapshot_id": "a" * 32,
    "status": "ready",
    "intent_summary": "Create a cube.",
    "assumptions": [],
    "questions": [],
    "operations": [
        {
            "operation_id": "create_cube",
            "type": "CREATE_PRIMITIVE",
            "primitive": "cube",
            "name": "Cube",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        }
    ],
}


@dataclass
class FakeResponse:
    status_code: int
    data: Any
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return self.data


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.last_request: dict[str, Any] | None = None

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.last_request = {"url": url, **kwargs}
        return self.response


class SequenceSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.call_count = 0
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


class FailingSession:
    def __init__(self, error: requests.exceptions.RequestException) -> None:
        self.error = error
        self.call_count = 0

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.call_count += 1
        raise self.error


def make_chat_response(plan: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl_test",
        "model": DEFAULT_NVIDIA_MODEL,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(plan)},
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
        },
    }


def make_request() -> PlanRequest:
    return PlanRequest(
        prompt="Create a cube",
        scene_context={"snapshot_id": "a" * 32, "selected_objects": []},
        response_schema=OPERATION_PLAN_SCHEMA,
    )


def test_payload_uses_nvidia_guided_json_without_storage() -> None:
    provider = NvidiaProvider("test-key")

    payload = provider.build_payload(make_request())

    assert payload["model"] == DEFAULT_NVIDIA_MODEL
    assert payload["temperature"] == DEFAULT_NVIDIA_TEMPERATURE
    assert payload["top_p"] == DEFAULT_NVIDIA_TOP_P
    assert payload["max_tokens"] == DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS
    assert payload["stream"] is False
    assert payload["nvext"] == {"guided_json": OPERATION_PLAN_SCHEMA}
    assert "untrusted data" in payload["messages"][0]["content"]
    assert "raw JSON" in payload["messages"][0]["content"]
    assert "operation_type" in payload["messages"][0]["content"]
    assert "CREATE_PRIMITIVE" in payload["messages"][0]["content"]
    assert "test-key" not in json.dumps(payload)


def test_create_plan_returns_locally_validated_plan() -> None:
    session = FakeSession(
        FakeResponse(200, make_chat_response(VALID_PLAN), {"NVCF-REQID": "req_test"})
    )
    provider = NvidiaProvider("test-key", session=session)

    response = provider.create_plan(make_request())

    assert response.response_id == "chatcmpl_test"
    assert response.model == DEFAULT_NVIDIA_MODEL
    assert response.plan == VALID_PLAN
    assert response.request_id == "req_test"
    assert response.usage == TokenUsage(
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
    )
    assert session.last_request is not None
    assert session.last_request["url"] == f"{NVIDIA_DEFAULT_BASE_URL}/chat/completions"
    assert session.last_request["headers"]["Authorization"] == "Bearer test-key"
    assert session.last_request["timeout"] == DEFAULT_NVIDIA_TIMEOUT_SECONDS


def test_model_selection_accepts_catalog_and_custom_models() -> None:
    assert resolve_nvidia_model_name("openai/gpt-oss-20b") == "openai/gpt-oss-20b"
    assert resolve_nvidia_model_name(CUSTOM_MODEL_OPTION, "  custom/model  ") == (
        "custom/model"
    )


@pytest.mark.parametrize("selection", ["", "unknown-model"])
def test_model_selection_rejects_unknown_catalog_values(selection: str) -> None:
    with pytest.raises(NvidiaConfigurationError, match="Unsupported NVIDIA model"):
        resolve_nvidia_model_name(selection)


def test_model_selection_requires_a_custom_name() -> None:
    with pytest.raises(NvidiaConfigurationError, match="custom NVIDIA model"):
        resolve_nvidia_model_name(CUSTOM_MODEL_OPTION, "  ")


def test_provider_requires_key_and_valid_base_url() -> None:
    with pytest.raises(NvidiaConfigurationError, match="API key"):
        NvidiaProvider("")
    with pytest.raises(NvidiaConfigurationError, match="base URL"):
        NvidiaProvider("test-key", base_url="not-a-url")


def test_schema_invalid_output_gets_one_repair_request() -> None:
    invalid_plan = {
        "snapshot_id": "a" * 32,
        "operations": [
            {
                "operation_id": "op1",
                "operation_type": "CREATE_PRIMITIVE",
                "primitive_type": "CUBE",
            }
        ],
    }
    session = SequenceSession(
        [
            FakeResponse(200, make_chat_response(invalid_plan)),
            FakeResponse(200, make_chat_response(VALID_PLAN), {"NVCF-REQID": "req_repair"}),
        ]
    )
    provider = NvidiaProvider("test-key", session=session)

    response = provider.create_plan(make_request())

    assert response.plan == VALID_PLAN
    assert response.request_id == "req_repair"
    assert response.usage == TokenUsage(
        input_tokens=240,
        output_tokens=60,
        total_tokens=300,
    )
    assert session.call_count == 2
    repair_messages = session.requests[1]["json"]["messages"]
    assert "operation_type" in repair_messages[2]["content"]
    assert "failed local validation" in repair_messages[3]["content"]


def test_create_plan_rejects_schema_invalid_output_after_one_repair() -> None:
    invalid_plan = {"status": "ready", "intent_summary": "Missing required fields."}
    session = SequenceSession(
        [
            FakeResponse(200, make_chat_response(invalid_plan)),
            FakeResponse(200, make_chat_response(invalid_plan)),
        ]
    )
    provider = NvidiaProvider("test-key", session=session)

    with pytest.raises(NvidiaResponseError, match="after one repair attempt"):
        provider.create_plan(make_request())

    assert session.call_count == 2


def test_create_plan_rejects_truncated_output() -> None:
    response_data = make_chat_response(VALID_PLAN)
    response_data["choices"][0]["finish_reason"] = "length"
    provider = NvidiaProvider(
        "test-key",
        session=FakeSession(FakeResponse(200, response_data)),
    )

    with pytest.raises(NvidiaResponseError, match="truncated"):
        provider.create_plan(make_request())


def test_create_plan_reports_api_errors() -> None:
    provider = NvidiaProvider(
        "test-key",
        session=FakeSession(
            FakeResponse(
                401,
                {"error": {"message": "Invalid authentication credentials"}},
                {"x-nvidia-request-id": "req_error"},
            )
        ),
    )

    with pytest.raises(NvidiaAPIError, match="HTTP 401") as captured:
        provider.create_plan(make_request())

    assert captured.value.request_id == "req_error"


def test_transient_http_error_retries_with_retry_after() -> None:
    delays: list[float] = []
    session = SequenceSession(
        [
            FakeResponse(429, {"error": {"message": "Rate limited"}}, {"Retry-After": "0"}),
            FakeResponse(200, make_chat_response(VALID_PLAN)),
        ]
    )
    provider = NvidiaProvider(
        "test-key",
        session=session,
        sleep=delays.append,
        random_source=lambda: 0.0,
    )

    provider.create_plan(make_request())

    assert session.call_count == 2
    assert delays == [0.0]


def test_transport_timeout_fails_without_ambiguous_retry() -> None:
    session = FailingSession(requests.exceptions.Timeout("timed out"))
    provider = NvidiaProvider("test-key", session=session, timeout_seconds=180.0)

    with pytest.raises(NvidiaAPIError, match="180 seconds") as captured:
        provider.create_plan(make_request())

    assert captured.value.error_code == "request_timeout"
    assert captured.value.retryable is False
    assert session.call_count == 1
