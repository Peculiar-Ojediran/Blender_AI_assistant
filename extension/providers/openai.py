import json
import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import requests

from ..config import resolve_environment_value
from ._shared import (
    TransportErrorMessages,
    non_negative_int,
    parse_and_validate_plan,
    post_with_transient_retries,
    raise_http_api_error,
    read_json_mapping_or_raise_http_error,
    request_id_from_headers,
    retry_delay,
)
from .base import PlanRequest, PlanResponse, TokenUsage
from .instructions import SYSTEM_INSTRUCTIONS

RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-nano"
CUSTOM_MODEL_OPTION = "CUSTOM"
OPENAI_MODEL_OPTIONS = (
    (
        "gpt-5-nano",
        "GPT-5 Nano",
        "Verified low-cost default for routine planning",
    ),
    (
        "gpt-5.4-nano",
        "GPT-5.4 Nano",
        "Newer nano model for efficient planning",
    ),
    (
        "gpt-5.4-mini",
        "GPT-5.4 Mini",
        "Balanced model for more difficult scene planning",
    ),
    (
        "gpt-5.5",
        "GPT-5.5",
        "Highest-quality listed model for complex planning",
    ),
)
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_OUTPUT_TOKENS = 32_768
DEFAULT_MAX_TRANSIENT_RETRIES = 2
OPENAI_API_NAME = "OpenAI API"
OPENAI_TRANSPORT_MESSAGES = TransportErrorMessages(
    timeout=(
        "OpenAI did not respond within {timeout_seconds:g} seconds. Increase Request Timeout in "
        "the extension preferences or use a faster model."
    ),
    tls=(
        "A secure TLS connection to OpenAI could not be established. Check the system clock, "
        "certificate store, proxy, and firewall settings."
    ),
    connection=(
        "Could not connect to OpenAI. Confirm Blender network access and check the internet "
        "connection, proxy, firewall, and DNS settings."
    ),
    transport=(
        "The OpenAI request failed before receiving a response. Check Blender network access and "
        "the extension's connection settings."
    ),
)


class OpenAIProviderError(RuntimeError):
    """Base error for OpenAI provider failures."""


class OpenAIConfigurationError(OpenAIProviderError):
    """Raised when required provider configuration is missing."""


class OpenAIAPIError(OpenAIProviderError):
    """Raised when the Responses API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str = "",
        error_code: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.error_code = error_code
        self.retryable = retryable


class OpenAIResponseError(OpenAIProviderError):
    """Raised when the API response cannot produce a valid local plan."""


def resolve_model_name(selection: str, custom_model: str = "") -> str:
    if selection == CUSTOM_MODEL_OPTION:
        resolved = custom_model.strip()
        if not resolved:
            raise OpenAIConfigurationError("Enter a custom OpenAI model name.")
        return resolved

    supported_models = {identifier for identifier, _label, _description in OPENAI_MODEL_OPTIONS}
    if selection not in supported_models:
        raise OpenAIConfigurationError(f"Unsupported OpenAI model selection: {selection}.")
    return selection


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_transient_retries: int = DEFAULT_MAX_TRANSIENT_RETRIES,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise OpenAIConfigurationError("An OpenAI API key is required.")
        if timeout_seconds <= 0:
            raise OpenAIConfigurationError("The request timeout must be positive.")
        if max_output_tokens < 1:
            raise OpenAIConfigurationError("The output token limit must be positive.")
        if max_transient_retries < 0:
            raise OpenAIConfigurationError("The transient retry count cannot be negative.")
        if reasoning_effort not in {"low", "medium", "high"}:
            raise OpenAIConfigurationError(
                "Reasoning effort must be low, medium, or high."
            )

        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._max_transient_retries = max_transient_retries
        self._session = session or requests.Session()
        self._sleep = sleep
        self._random_source = random_source

    @classmethod
    def from_environment(
        cls,
        *,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any | None = None,
    ) -> "OpenAIProvider":
        api_key = resolve_environment_value("OPENAI_API_KEY")
        return cls(
            api_key,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
            session=session,
        )

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        payload = self.build_payload(request)
        response = self._post_with_transient_retries(payload)
        request_id = self._request_id(response)
        data = read_json_mapping_or_raise_http_error(
            response,
            request_id=request_id,
            response_error_type=OpenAIResponseError,
            api_error_type=OpenAIAPIError,
            api_name=OPENAI_API_NAME,
            non_json_message="OpenAI returned a non-JSON response.",
            unexpected_json_message="OpenAI returned an unexpected JSON response.",
        )

        if response.status_code >= 400:
            raise_http_api_error(
                response,
                data,
                request_id=request_id,
                api_error_type=OpenAIAPIError,
                api_name=OPENAI_API_NAME,
            )

        self._validate_response_status(data)
        plan = self._extract_and_validate_plan(data, request.response_schema)
        response_id = data.get("id", "")
        model = data.get("model", self._model)

        return PlanResponse(
            response_id=response_id if isinstance(response_id, str) else "",
            model=model if isinstance(model, str) else self._model,
            plan=plan,
            request_id=request_id,
            usage=self._extract_token_usage(data),
        )

    def build_payload(self, request: PlanRequest) -> dict[str, Any]:
        context_text = json.dumps(
            {
                "user_request": request.prompt,
                "scene_context": request.scene_context,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )

        return {
            "model": self._model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": context_text}],
                }
            ],
            "reasoning": {"effort": self._reasoning_effort},
            "max_output_tokens": self._max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "blender_operation_plan",
                    "strict": True,
                    "schema": dict(request.response_schema),
                }
            },
        }

    @staticmethod
    def _validate_response_status(data: Mapping[str, Any]) -> None:
        status = data.get("status")
        if status == "completed":
            return
        if status == "incomplete":
            details = data.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, Mapping) else None
            suffix = f": {reason}" if isinstance(reason, str) and reason else "."
            raise OpenAIResponseError(f"OpenAI returned an incomplete response{suffix}")
        if status in {"failed", "cancelled"}:
            error = data.get("error")
            message = error.get("message") if isinstance(error, Mapping) else None
            detail = message if isinstance(message, str) and message else status
            raise OpenAIResponseError(f"OpenAI response did not complete: {detail}.")
        raise OpenAIResponseError(f"OpenAI returned unexpected response status: {status}.")

    def _post_with_transient_retries(self, payload: Mapping[str, Any]) -> Any:
        return post_with_transient_retries(
            session=self._session,
            url=RESPONSES_API_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout_seconds=self._timeout_seconds,
            max_transient_retries=self._max_transient_retries,
            sleep=self._sleep,
            random_source=self._random_source,
            api_error_type=OpenAIAPIError,
            messages=OPENAI_TRANSPORT_MESSAGES,
        )

    def _retry_delay(self, response: Any, attempt: int) -> float:
        return retry_delay(response, attempt, self._random_source)

    @staticmethod
    def _request_id(response: Any) -> str:
        return request_id_from_headers(response, ("x-request-id", "X-Request-Id"))

    @classmethod
    def _extract_token_usage(cls, data: Mapping[str, Any]) -> TokenUsage:
        usage = data.get("usage")
        if not isinstance(usage, Mapping):
            return TokenUsage()

        input_tokens = non_negative_int(usage.get("input_tokens"))
        output_tokens = non_negative_int(usage.get("output_tokens"))
        input_details = usage.get("input_tokens_details")
        output_details = usage.get("output_tokens_details")
        cached_input_tokens = (
            non_negative_int(input_details.get("cached_tokens"))
            if isinstance(input_details, Mapping)
            else 0
        )
        reasoning_tokens = (
            non_negative_int(output_details.get("reasoning_tokens"))
            if isinstance(output_details, Mapping)
            else 0
        )
        total_tokens_value = usage.get("total_tokens")
        total_tokens = (
            non_negative_int(total_tokens_value)
            if isinstance(total_tokens_value, int) and not isinstance(total_tokens_value, bool)
            else input_tokens + output_tokens
        )
        return TokenUsage(
            input_tokens=input_tokens,
            cached_input_tokens=min(cached_input_tokens, input_tokens),
            output_tokens=output_tokens,
            reasoning_tokens=min(reasoning_tokens, output_tokens),
            total_tokens=total_tokens,
        )

    @classmethod
    def _extract_and_validate_plan(
        cls,
        data: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        output_text = cls._extract_output_text(data)
        return parse_and_validate_plan(
            output_text,
            response_schema,
            response_error_type=OpenAIResponseError,
            invalid_json_message="OpenAI returned invalid plan JSON.",
            not_object_message="OpenAI returned a plan that is not an object.",
            validation_message=lambda _error: (
                "OpenAI returned a plan that failed local validation."
            ),
        )

    @staticmethod
    def _extract_output_text(data: Mapping[str, Any]) -> str:
        output = data.get("output")
        if not isinstance(output, list):
            raise OpenAIResponseError("OpenAI response did not contain output items.")

        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "refusal":
                    refusal = part.get("refusal")
                    detail = refusal if isinstance(refusal, str) else "Request refused."
                    raise OpenAIResponseError(f"OpenAI refused the planning request: {detail}")
                if part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        return text

        raise OpenAIResponseError("OpenAI response did not contain plan text.")
