import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

from extension.operations import OPERATION_PLAN_SCHEMA
from extension.providers.base import PlanRequest, TokenUsage
from extension.providers.openai import (
    CUSTOM_MODEL_OPTION,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT_SECONDS,
    OpenAIAPIError,
    OpenAIConfigurationError,
    OpenAIProvider,
    OpenAIResponseError,
    resolve_model_name,
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

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
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


def make_api_response(plan: Any) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "model": DEFAULT_MODEL,
        "status": "completed",
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 20},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 10},
            "total_tokens": 150,
        },
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(plan)}],
            }
        ],
    }


def make_request() -> PlanRequest:
    return PlanRequest(
        prompt="Create a cube",
        scene_context={"snapshot_id": "a" * 32, "selected_objects": []},
        response_schema=OPERATION_PLAN_SCHEMA,
    )


def test_payload_uses_structured_outputs_without_storage() -> None:
    provider = OpenAIProvider("test-key")

    payload = provider.build_payload(make_request())

    assert payload["model"] == DEFAULT_MODEL
    assert payload["store"] is False
    assert payload["reasoning"] == {"effort": DEFAULT_REASONING_EFFORT}
    assert payload["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    assert "untrusted data" in payload["instructions"]
    assert payload["text"]["format"] == {
        "type": "json_schema",
        "name": "blender_operation_plan",
        "strict": True,
        "schema": OPERATION_PLAN_SCHEMA,
    }
    assert "test-key" not in json.dumps(payload)
    assert "IMPORT_ASSET" in payload["instructions"]
    assert "LINK_OR_APPEND_BLEND_DATA" in payload["instructions"]
    assert "HTTPS" in payload["instructions"]
    assert "outside IMPORT_ASSET" in payload["instructions"]


def test_provider_schema_avoids_regex_lookarounds() -> None:
    schema_text = json.dumps(OPERATION_PLAN_SCHEMA)

    assert "(?!" not in schema_text
    assert "(?=" not in schema_text
    assert "(?<" not in schema_text


def test_create_plan_returns_locally_validated_plan() -> None:
    session = FakeSession(FakeResponse(200, make_api_response(VALID_PLAN)))
    provider = OpenAIProvider("test-key", session=session)

    response = provider.create_plan(make_request())

    assert response.response_id == "resp_test"
    assert response.model == DEFAULT_MODEL
    assert response.plan == VALID_PLAN
    assert response.usage == TokenUsage(
        input_tokens=120,
        cached_input_tokens=20,
        output_tokens=30,
        reasoning_tokens=10,
        total_tokens=150,
    )
    assert session.last_request is not None
    assert session.last_request["headers"]["Authorization"] == "Bearer test-key"
    assert session.last_request["timeout"] == DEFAULT_TIMEOUT_SECONDS


def test_payload_accepts_explicit_reasoning_effort() -> None:
    provider = OpenAIProvider("test-key", reasoning_effort="medium")

    assert provider.build_payload(make_request())["reasoning"] == {"effort": "medium"}


def test_model_selection_accepts_catalog_and_custom_models() -> None:
    assert resolve_model_name("gpt-5.4-mini") == "gpt-5.4-mini"
    assert resolve_model_name(CUSTOM_MODEL_OPTION, "  account-fine-tuned-model  ") == (
        "account-fine-tuned-model"
    )


@pytest.mark.parametrize("selection", ["", "unknown-model"])
def test_model_selection_rejects_unknown_catalog_values(selection: str) -> None:
    with pytest.raises(OpenAIConfigurationError, match="Unsupported OpenAI model"):
        resolve_model_name(selection)


def test_model_selection_requires_a_custom_name() -> None:
    with pytest.raises(OpenAIConfigurationError, match="custom OpenAI model"):
        resolve_model_name(CUSTOM_MODEL_OPTION, "  ")


def test_provider_rejects_unknown_reasoning_effort() -> None:
    with pytest.raises(OpenAIConfigurationError, match="Reasoning effort"):
        OpenAIProvider("test-key", reasoning_effort="extreme")


def test_create_plan_rejects_schema_invalid_output() -> None:
    invalid_plan = {"status": "ready", "intent_summary": "Missing required fields."}
    session = FakeSession(FakeResponse(200, make_api_response(invalid_plan)))
    provider = OpenAIProvider("test-key", session=session)

    with pytest.raises(OpenAIResponseError, match="failed local validation"):
        provider.create_plan(make_request())


def test_create_plan_rejects_incomplete_responses() -> None:
    response_data = make_api_response(VALID_PLAN)
    response_data["status"] = "incomplete"
    response_data["incomplete_details"] = {"reason": "max_output_tokens"}
    session = FakeSession(FakeResponse(200, response_data))
    provider = OpenAIProvider("test-key", session=session)

    with pytest.raises(OpenAIResponseError, match="max_output_tokens"):
        provider.create_plan(make_request())


def test_create_plan_rejects_missing_response_status() -> None:
    response_data = make_api_response(VALID_PLAN)
    del response_data["status"]
    session = FakeSession(FakeResponse(200, response_data))
    provider = OpenAIProvider("test-key", session=session)

    with pytest.raises(OpenAIResponseError, match="status: None"):
        provider.create_plan(make_request())


def test_transient_http_error_retries_with_retry_after_and_request_id() -> None:
    delays: list[float] = []
    session = SequenceSession(
        [
            FakeResponse(
                429,
                {"error": {"message": "Rate limited", "code": "rate_limit"}},
                {"Retry-After": "0"},
            ),
            FakeResponse(
                200,
                make_api_response(VALID_PLAN),
                {"x-request-id": "req_test"},
            ),
        ]
    )
    provider = OpenAIProvider(
        "test-key",
        session=session,
        sleep=delays.append,
        random_source=lambda: 0.0,
    )

    response = provider.create_plan(make_request())

    assert session.call_count == 2
    assert delays == [0.0]
    assert response.request_id == "req_test"


def test_retry_after_is_bounded() -> None:
    provider = OpenAIProvider("test-key")
    response = FakeResponse(429, {}, {"Retry-After": "120"})

    assert provider._retry_delay(response, 0) == 30.0


def test_missing_or_malformed_usage_is_safe() -> None:
    response_data = make_api_response(VALID_PLAN)
    response_data["usage"] = {
        "input_tokens": "120",
        "input_tokens_details": {"cached_tokens": 50},
        "output_tokens": -3,
        "output_tokens_details": {"reasoning_tokens": True},
    }
    provider = OpenAIProvider(
        "test-key",
        session=FakeSession(FakeResponse(200, response_data)),
    )

    response = provider.create_plan(make_request())

    assert response.usage == TokenUsage()


def test_non_json_http_error_preserves_status_and_request_id() -> None:
    session = FakeSession(
        FakeResponse(400, "not-json", {"x-request-id": "req_error"})
    )
    provider = OpenAIProvider("test-key", session=session)

    with pytest.raises(OpenAIAPIError) as captured:
        provider.create_plan(make_request())

    assert captured.value.status_code == 400
    assert captured.value.request_id == "req_error"


def test_create_plan_reports_api_errors() -> None:
    session = FakeSession(
        FakeResponse(401, {"error": {"message": "Invalid authentication credentials"}})
    )
    provider = OpenAIProvider("test-key", session=session)

    with pytest.raises(OpenAIAPIError, match="HTTP 401"):
        provider.create_plan(make_request())


def test_transport_timeout_fails_without_ambiguous_retry() -> None:
    session = FailingSession(requests.exceptions.Timeout("timed out"))
    provider = OpenAIProvider("test-key", session=session, timeout_seconds=180.0)

    with pytest.raises(OpenAIAPIError, match="180 seconds") as captured:
        provider.create_plan(make_request())

    assert captured.value.error_code == "request_timeout"
    assert captured.value.retryable is False
    assert session.call_count == 1


@pytest.mark.parametrize(
    ("transport_error", "expected_code", "expected_message"),
    [
        (
            requests.exceptions.ConnectionError("offline"),
            "connection_error",
            "Blender network access",
        ),
        (requests.exceptions.SSLError("certificate"), "tls_error", "TLS connection"),
        (
            requests.exceptions.RequestException("transport"),
            "transport_error",
            "connection settings",
        ),
    ],
)
def test_transport_failures_report_actionable_categories(
    transport_error: requests.exceptions.RequestException,
    expected_code: str,
    expected_message: str,
) -> None:
    provider = OpenAIProvider("test-key", session=FailingSession(transport_error))

    with pytest.raises(OpenAIAPIError, match=expected_message) as captured:
        provider.create_plan(make_request())

    assert captured.value.error_code == expected_code


def test_transient_server_errors_stop_at_the_retry_budget() -> None:
    delays: list[float] = []
    session = SequenceSession(
        [
            FakeResponse(500, {"error": {"message": "temporary"}}),
            FakeResponse(503, {"error": {"message": "temporary"}}),
            FakeResponse(
                500,
                {"error": {"message": "still unavailable"}},
                {"x-request-id": "req_final"},
            ),
        ]
    )
    provider = OpenAIProvider(
        "test-key",
        session=session,
        sleep=delays.append,
        random_source=lambda: 0.0,
    )

    with pytest.raises(OpenAIAPIError) as captured:
        provider.create_plan(make_request())

    assert session.call_count == 3
    assert delays == [0.25, 0.5]
    assert captured.value.status_code == 500
    assert captured.value.request_id == "req_final"
    assert captured.value.retryable is True


def test_from_environment_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "extension.providers.openai.resolve_environment_value",
        lambda name: "",
    )

    with pytest.raises(OpenAIConfigurationError, match="API key"):
        OpenAIProvider.from_environment()
