"""Shared provider request and response helpers."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import fastjsonschema
import requests

TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class TransportErrorMessages:
    timeout: str
    tls: str
    connection: str
    transport: str


def post_with_transient_retries(
    *,
    session: Any,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
    max_transient_retries: int,
    sleep: Callable[[float], None],
    random_source: Callable[[], float],
    api_error_type: Any,
    messages: TransportErrorMessages,
    transient_status_codes: frozenset[int] = TRANSIENT_STATUS_CODES,
) -> Any:
    attempt = 0
    while True:
        try:
            response = session.post(
                url,
                headers=dict(headers),
                json=payload,
                timeout=timeout_seconds,
            )
        except requests.exceptions.Timeout as exc:
            raise api_error_type(
                messages.timeout.format(timeout_seconds=timeout_seconds),
                error_code="request_timeout",
            ) from exc
        except requests.exceptions.SSLError as exc:
            raise api_error_type(messages.tls, error_code="tls_error") from exc
        except requests.exceptions.ConnectionError as exc:
            raise api_error_type(
                messages.connection,
                error_code="connection_error",
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise api_error_type(
                messages.transport,
                error_code="transport_error",
            ) from exc

        if (
            response.status_code not in transient_status_codes
            or attempt >= max_transient_retries
        ):
            return response
        sleep(retry_delay(response, attempt, random_source))
        attempt += 1


def retry_delay(
    response: Any,
    attempt: int,
    random_source: Callable[[], float],
) -> float:
    headers = getattr(response, "headers", {})
    retry_after = headers.get("Retry-After") if isinstance(headers, Mapping) else None
    if isinstance(retry_after, str):
        try:
            return min(30.0, max(0.0, float(retry_after)))
        except ValueError:
            pass
    base_delay = min(5.0, 0.25 * (2**attempt))
    return base_delay + (random_source() * 0.1)


def request_id_from_headers(response: Any, header_names: tuple[str, ...]) -> str:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return ""
    for header_name in header_names:
        request_id = headers.get(header_name)
        if isinstance(request_id, str):
            return request_id
    return ""


def read_json_mapping_or_raise_http_error(
    response: Any,
    *,
    request_id: str,
    response_error_type: Any,
    api_error_type: Any,
    api_name: str,
    non_json_message: str,
    unexpected_json_message: str,
    non_json_error_kind: str = "error",
    transient_status_codes: frozenset[int] = TRANSIENT_STATUS_CODES,
) -> Mapping[str, Any]:
    try:
        data = response.json()
    except (TypeError, ValueError) as exc:
        if response.status_code >= 400:
            suffix = f" Request ID: {request_id}." if request_id else ""
            raise api_error_type(
                f"{api_name} returned HTTP {response.status_code} with a non-JSON "
                f"{non_json_error_kind}.{suffix}",
                status_code=response.status_code,
                request_id=request_id,
                retryable=response.status_code in transient_status_codes,
            ) from exc
        raise response_error_type(non_json_message) from exc

    if not isinstance(data, Mapping):
        if response.status_code >= 400:
            suffix = f" Request ID: {request_id}." if request_id else ""
            raise api_error_type(
                f"{api_name} returned HTTP {response.status_code} with a non-JSON "
                f"{non_json_error_kind}.{suffix}",
                status_code=response.status_code,
                request_id=request_id,
                retryable=response.status_code in transient_status_codes,
            )
        raise response_error_type(unexpected_json_message)
    return data


def raise_http_api_error(
    response: Any,
    data: Mapping[str, Any],
    *,
    request_id: str,
    api_error_type: Any,
    api_name: str,
    include_detail: bool = False,
    transient_status_codes: frozenset[int] = TRANSIENT_STATUS_CODES,
) -> None:
    message, error_code = extract_api_error(data, include_detail=include_detail)
    suffix = f" Request ID: {request_id}." if request_id else ""
    raise api_error_type(
        f"{api_name} returned HTTP {response.status_code}: {message}{suffix}",
        status_code=response.status_code,
        request_id=request_id,
        error_code=error_code,
        retryable=response.status_code in transient_status_codes,
    )


def extract_api_error(
    data: Mapping[str, Any],
    *,
    include_detail: bool = False,
) -> tuple[str, str]:
    error = data.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        code = error.get("code")
        return (
            message if isinstance(message, str) and message else "Request failed.",
            code if isinstance(code, str) else "",
        )
    detail = data.get("detail")
    if include_detail and isinstance(detail, str) and detail:
        return detail, ""
    return "Request failed.", ""


def parse_and_validate_plan(
    output_text: str,
    response_schema: Mapping[str, Any],
    *,
    response_error_type: Any,
    invalid_json_message: str,
    not_object_message: str,
    validation_message: Callable[[fastjsonschema.JsonSchemaException], str],
    normalize_text: Callable[[str], str] | None = None,
) -> Mapping[str, Any]:
    text = normalize_text(output_text) if normalize_text is not None else output_text
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as exc:
        raise response_error_type(invalid_json_message) from exc

    if not isinstance(plan, Mapping):
        raise response_error_type(not_object_message)

    try:
        fastjsonschema.compile(dict(response_schema))(plan)
    except fastjsonschema.JsonSchemaException as exc:
        raise response_error_type(validation_message(exc)) from exc

    return plan


def non_negative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0
