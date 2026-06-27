import json
import random
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import fastjsonschema
import requests

from ..config import resolve_environment_value
from .base import PlanRequest, PlanResponse, TokenUsage
from .instructions import SYSTEM_INSTRUCTIONS

NVIDIA_CHAT_COMPLETIONS_PATH = "/chat/completions"
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-20b"
NVIDIA_MODEL_OPTIONS = (
    (
        "openai/gpt-oss-20b",
        "GPT-OSS 20B",
        "Verified NVIDIA-hosted default for quicker iteration",
    ),
    (
        "meta/llama-3.3-70b-instruct",
        "Llama 3.3 70B Instruct",
        "General NVIDIA-hosted planning model",
    ),
    (
        "nvidia/nemotron-3-ultra-550b-a55b",
        "Nemotron 3 Ultra 550B",
        "Larger NVIDIA-hosted model for difficult planning",
    ),
)
DEFAULT_NVIDIA_TEMPERATURE = 0.2
DEFAULT_NVIDIA_TOP_P = 0.7
DEFAULT_NVIDIA_TIMEOUT_SECONDS = 180.0
DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS = 4_096
DEFAULT_NVIDIA_MAX_TRANSIENT_RETRIES = 2
MAX_REPAIR_OUTPUT_CHARACTERS = 12_000
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
CUSTOM_MODEL_OPTION = "CUSTOM"
NVIDIA_PLAN_FORMAT_REMINDER = """NVIDIA planning format reminder:
Return one JSON object with these exact top-level keys: snapshot_id, status, intent_summary,
assumptions, questions, operations. Use status "ready" when operations are complete or
"needs_clarification" when questions are required. Operation field names must match the schema
exactly. For primitive creation use:
{"operation_id":"create_cube","type":"CREATE_PRIMITIVE","primitive":"cube","name":"Cube",
"collection_id":null,"location":[0,0,0],"rotation_euler":[0,0,0],"scale":[1,1,1]}.
Do not use synonym keys such as operation_type, primitive_type, rotation, or target."""


class NvidiaProviderError(RuntimeError):
    """Base error for NVIDIA provider failures."""


class NvidiaConfigurationError(NvidiaProviderError):
    """Raised when required provider configuration is missing."""


class NvidiaAPIError(NvidiaProviderError):
    """Raised when the NVIDIA NIM API returns an error."""

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


class NvidiaResponseError(NvidiaProviderError):
    """Raised when the API response cannot produce a valid local plan."""


def resolve_nvidia_model_name(selection: str, custom_model: str = "") -> str:
    if selection == CUSTOM_MODEL_OPTION:
        resolved = custom_model.strip()
        if not resolved:
            raise NvidiaConfigurationError("Enter a custom NVIDIA model name.")
        return resolved

    supported_models = {identifier for identifier, _label, _description in NVIDIA_MODEL_OPTIONS}
    if selection not in supported_models:
        raise NvidiaConfigurationError(f"Unsupported NVIDIA model selection: {selection}.")
    return selection


class NvidiaProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_NVIDIA_MODEL,
        base_url: str = NVIDIA_DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_NVIDIA_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_NVIDIA_MAX_OUTPUT_TOKENS,
        temperature: float = DEFAULT_NVIDIA_TEMPERATURE,
        top_p: float = DEFAULT_NVIDIA_TOP_P,
        max_transient_retries: int = DEFAULT_NVIDIA_MAX_TRANSIENT_RETRIES,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise NvidiaConfigurationError("An NVIDIA API key is required.")
        if timeout_seconds <= 0:
            raise NvidiaConfigurationError("The request timeout must be positive.")
        if max_output_tokens < 1:
            raise NvidiaConfigurationError("The output token limit must be positive.")
        if not 0.0 <= temperature <= 2.0:
            raise NvidiaConfigurationError("Temperature must be between 0 and 2.")
        if not 0.0 <= top_p <= 1.0:
            raise NvidiaConfigurationError("Top-p must be between 0 and 1.")
        if max_transient_retries < 0:
            raise NvidiaConfigurationError("The transient retry count cannot be negative.")

        self._api_key = api_key
        self._model = model
        self._base_url = _normalize_base_url(base_url)
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._top_p = top_p
        self._max_transient_retries = max_transient_retries
        self._session = session or requests.Session()
        self._sleep = sleep
        self._random_source = random_source

    @classmethod
    def from_environment(
        cls,
        *,
        model: str = DEFAULT_NVIDIA_MODEL,
        base_url: str = NVIDIA_DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_NVIDIA_TIMEOUT_SECONDS,
        session: Any | None = None,
    ) -> "NvidiaProvider":
        api_key = resolve_environment_value("NVIDIA_API_KEY")
        resolved_base_url = resolve_environment_value("NVIDIA_BASE_URL") or base_url
        return cls(
            api_key,
            model=model,
            base_url=resolved_base_url,
            timeout_seconds=timeout_seconds,
            session=session,
        )

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        payload = self.build_payload(request)
        response = self._post_with_transient_retries(payload)
        request_id = self._request_id(response)

        try:
            data = self._read_json_response(response)
        except NvidiaResponseError as error:
            if response.status_code >= 400:
                suffix = f" Request ID: {request_id}." if request_id else ""
                raise NvidiaAPIError(
                    "NVIDIA NIM API returned HTTP "
                    f"{response.status_code} with a non-JSON error.{suffix}",
                    status_code=response.status_code,
                    request_id=request_id,
                    retryable=response.status_code in TRANSIENT_STATUS_CODES,
                ) from error
            raise

        if response.status_code >= 400:
            message, error_code = self._extract_api_error(data)
            suffix = f" Request ID: {request_id}." if request_id else ""
            raise NvidiaAPIError(
                f"NVIDIA NIM API returned HTTP {response.status_code}: {message}{suffix}",
                status_code=response.status_code,
                request_id=request_id,
                error_code=error_code,
                retryable=response.status_code in TRANSIENT_STATUS_CODES,
            )

        usage = self._extract_token_usage(data)
        try:
            plan = self._extract_and_validate_plan(data, request.response_schema)
        except NvidiaResponseError as error:
            data, request_id, usage = self._repair_schema_invalid_plan(
                request,
                data,
                request_id,
                usage,
                error,
            )
            try:
                plan = self._extract_and_validate_plan(data, request.response_schema)
            except NvidiaResponseError as repair_error:
                raise NvidiaResponseError(
                    "NVIDIA NIM returned a plan that failed local validation after "
                    "one repair attempt."
                ) from repair_error

        response_id = data.get("id", "")
        model = data.get("model", self._model)

        return PlanResponse(
            response_id=response_id if isinstance(response_id, str) else "",
            model=model if isinstance(model, str) else self._model,
            plan=plan,
            request_id=request_id,
            usage=usage,
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
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{SYSTEM_INSTRUCTIONS}\n{NVIDIA_PLAN_FORMAT_REMINDER}\n"
                        "Return only raw JSON. Do not wrap the plan in Markdown or "
                        "explanatory text."
                    ),
                },
                {"role": "user", "content": context_text},
            ],
            "temperature": self._temperature,
            "top_p": self._top_p,
            "max_tokens": self._max_output_tokens,
            "stream": False,
            "nvext": {"guided_json": dict(request.response_schema)},
        }

    def build_repair_payload(
        self,
        request: PlanRequest,
        *,
        invalid_output: str,
        validation_error: Exception,
    ) -> dict[str, Any]:
        payload = self.build_payload(request)
        payload["messages"].append(
            {
                "role": "assistant",
                "content": invalid_output[:MAX_REPAIR_OUTPUT_CHARACTERS],
            }
        )
        payload["messages"].append(
            {
                "role": "user",
                "content": (
                    "The previous answer failed local validation. Rewrite it as one "
                    "complete JSON object that exactly matches the supplied schema. "
                    "Preserve the same user request, scene snapshot_id, and intended "
                    "controlled operations. Use only exact schema field names and enum "
                    f"values. Validation error: {validation_error}"
                ),
            }
        )
        return payload

    def _repair_schema_invalid_plan(
        self,
        request: PlanRequest,
        data: Mapping[str, Any],
        request_id: str,
        usage: TokenUsage,
        validation_error: Exception,
    ) -> tuple[Mapping[str, Any], str, TokenUsage]:
        invalid_output = self._extract_output_text(data)
        repair_response = self._post_with_transient_retries(
            self.build_repair_payload(
                request,
                invalid_output=invalid_output,
                validation_error=validation_error,
            )
        )
        repair_request_id = self._request_id(repair_response) or request_id

        try:
            repair_data = self._read_json_response(repair_response)
        except NvidiaResponseError as error:
            if repair_response.status_code >= 400:
                suffix = f" Request ID: {repair_request_id}." if repair_request_id else ""
                raise NvidiaAPIError(
                    "NVIDIA NIM API returned HTTP "
                    f"{repair_response.status_code} with a non-JSON repair error.{suffix}",
                    status_code=repair_response.status_code,
                    request_id=repair_request_id,
                    retryable=repair_response.status_code in TRANSIENT_STATUS_CODES,
                ) from error
            raise

        if repair_response.status_code >= 400:
            message, error_code = self._extract_api_error(repair_data)
            suffix = f" Request ID: {repair_request_id}." if repair_request_id else ""
            raise NvidiaAPIError(
                f"NVIDIA NIM API returned HTTP {repair_response.status_code}: "
                f"{message}{suffix}",
                status_code=repair_response.status_code,
                request_id=repair_request_id,
                error_code=error_code,
                retryable=repair_response.status_code in TRANSIENT_STATUS_CODES,
            )

        return (
            repair_data,
            repair_request_id,
            usage + self._extract_token_usage(repair_data),
        )

    @staticmethod
    def _read_json_response(response: Any) -> Mapping[str, Any]:
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise NvidiaResponseError("NVIDIA NIM returned a non-JSON response.") from exc

        if not isinstance(data, Mapping):
            raise NvidiaResponseError("NVIDIA NIM returned an unexpected JSON response.")
        return data

    @staticmethod
    def _extract_api_error(data: Mapping[str, Any]) -> tuple[str, str]:
        error = data.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            code = error.get("code")
            return (
                message if isinstance(message, str) and message else "Request failed.",
                code if isinstance(code, str) else "",
            )
        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            return detail, ""
        return "Request failed.", ""

    def _post_with_transient_retries(self, payload: Mapping[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                response = self._session.post(
                    self._endpoint_url(),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout_seconds,
                )
            except requests.exceptions.Timeout as exc:
                raise NvidiaAPIError(
                    "NVIDIA NIM did not respond within "
                    f"{self._timeout_seconds:g} seconds. Increase Request Timeout in the "
                    "extension preferences or use a faster model.",
                    error_code="request_timeout",
                ) from exc
            except requests.exceptions.SSLError as exc:
                raise NvidiaAPIError(
                    "A secure TLS connection to NVIDIA NIM could not be established. Check "
                    "the system clock, certificate store, proxy, and firewall settings.",
                    error_code="tls_error",
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                raise NvidiaAPIError(
                    "Could not connect to NVIDIA NIM. Confirm Blender network access and "
                    "check the internet connection, proxy, firewall, DNS settings, and base URL.",
                    error_code="connection_error",
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise NvidiaAPIError(
                    "The NVIDIA NIM request failed before receiving a response. Check Blender "
                    "network access and the extension's connection settings.",
                    error_code="transport_error",
                ) from exc

            if (
                response.status_code not in TRANSIENT_STATUS_CODES
                or attempt >= self._max_transient_retries
            ):
                return response
            self._sleep(self._retry_delay(response, attempt))
            attempt += 1

    def _endpoint_url(self) -> str:
        return f"{self._base_url}{NVIDIA_CHAT_COMPLETIONS_PATH}"

    def _retry_delay(self, response: Any, attempt: int) -> float:
        headers = getattr(response, "headers", {})
        retry_after = headers.get("Retry-After") if isinstance(headers, Mapping) else None
        if isinstance(retry_after, str):
            try:
                return min(30.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
        base_delay = min(5.0, 0.25 * (2**attempt))
        return base_delay + (self._random_source() * 0.1)

    @staticmethod
    def _request_id(response: Any) -> str:
        headers = getattr(response, "headers", {})
        if not isinstance(headers, Mapping):
            return ""
        request_id = (
            headers.get("x-request-id")
            or headers.get("X-Request-Id")
            or headers.get("x-nvidia-request-id")
            or headers.get("NVCF-REQID")
        )
        return request_id if isinstance(request_id, str) else ""

    @classmethod
    def _extract_token_usage(cls, data: Mapping[str, Any]) -> TokenUsage:
        usage = data.get("usage")
        if not isinstance(usage, Mapping):
            return TokenUsage()

        input_tokens = cls._non_negative_int(usage.get("prompt_tokens"))
        output_tokens = cls._non_negative_int(usage.get("completion_tokens"))
        total_tokens_value = usage.get("total_tokens")
        total_tokens = (
            cls._non_negative_int(total_tokens_value)
            if isinstance(total_tokens_value, int) and not isinstance(total_tokens_value, bool)
            else input_tokens + output_tokens
        )
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
        return 0

    @classmethod
    def _extract_and_validate_plan(
        cls,
        data: Mapping[str, Any],
        response_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        output_text = cls._extract_output_text(data)

        try:
            plan = json.loads(_strip_json_code_fence(output_text))
        except json.JSONDecodeError as exc:
            raise NvidiaResponseError("NVIDIA NIM returned invalid plan JSON.") from exc

        if not isinstance(plan, Mapping):
            raise NvidiaResponseError("NVIDIA NIM returned a plan that is not an object.")

        try:
            fastjsonschema.compile(dict(response_schema))(plan)
        except fastjsonschema.JsonSchemaException as exc:
            message = f"NVIDIA NIM returned a plan that failed local validation: {exc.message}"
            raise NvidiaResponseError(message) from exc

        return plan

    @staticmethod
    def _extract_output_text(data: Mapping[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise NvidiaResponseError("NVIDIA NIM response did not contain choices.")

        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise NvidiaResponseError("NVIDIA NIM returned an unexpected choice.")

        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise NvidiaResponseError("NVIDIA NIM response was truncated by max_tokens.")
        if finish_reason == "content_filter":
            raise NvidiaResponseError("NVIDIA NIM filtered the planning response.")

        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise NvidiaResponseError("NVIDIA NIM response did not contain a message.")

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            text = "".join(parts).strip()
            if text:
                return text

        raise NvidiaResponseError("NVIDIA NIM response did not contain plan text.")


def _normalize_base_url(base_url: str) -> str:
    stripped = base_url.strip().rstrip("/")
    if not stripped:
        raise NvidiaConfigurationError("An NVIDIA base URL is required.")
    parsed = urlparse(stripped)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise NvidiaConfigurationError("NVIDIA base URL must be an HTTP or HTTPS URL.")
    return stripped


def _strip_json_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped
