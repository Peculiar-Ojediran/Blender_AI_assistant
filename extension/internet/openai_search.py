"""OpenAI web-search-backed asset discovery provider."""

import json
from collections.abc import Mapping
from typing import Any

import requests

from ..providers._shared import request_id_from_headers
from .models import (
    AssetCandidate,
    AssetDiscoveryResult,
    AssetFormat,
    AssetSearchRequest,
    CandidateStatus,
    Citation,
)

OPENAI_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_DISCOVERY_MODEL = "gpt-5.5"
DEFAULT_OPENAI_DISCOVERY_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_DISCOVERY_MAX_OUTPUT_TOKENS = 4096

DISCOVERY_INSTRUCTIONS = (
    "Find candidate external Blender-compatible assets. Return only JSON matching the supplied "
    "schema. Do not return a Blender operation plan. Prefer direct HTTPS download URLs ending in "
    ".obj, .fbx, .gltf, or .glb. If a result is only a listing page, keep direct_url null and add "
    "a warning. Include license and attribution only when the source provides them."
)

ASSET_DISCOVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "source_page_url": {"type": "string"},
                    "direct_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "format": {
                        "type": "string",
                        "enum": ["obj", "fbx", "gltf", "glb", "unknown"],
                    },
                    "license_label": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "license_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "attribution": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "title",
                    "source_page_url",
                    "direct_url",
                    "format",
                    "license_label",
                    "license_url",
                    "attribution",
                    "confidence",
                    "warnings",
                ],
                "additionalProperties": False,
            },
            "minItems": 0,
            "maxItems": 10,
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


class OpenAIAssetDiscoveryError(RuntimeError):
    """Base error for OpenAI asset discovery failures."""


class OpenAIAssetDiscoveryConfigurationError(OpenAIAssetDiscoveryError):
    """Raised when the discovery provider is misconfigured."""


class OpenAIAssetDiscoveryResponseError(OpenAIAssetDiscoveryError):
    """Raised when OpenAI returns unusable discovery content."""


class OpenAIAssetDiscoveryProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_OPENAI_DISCOVERY_MODEL,
        timeout_seconds: float = DEFAULT_OPENAI_DISCOVERY_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_OPENAI_DISCOVERY_MAX_OUTPUT_TOKENS,
        session: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise OpenAIAssetDiscoveryConfigurationError("An OpenAI API key is required.")
        if timeout_seconds <= 0:
            raise OpenAIAssetDiscoveryConfigurationError("The discovery timeout must be positive.")
        if max_output_tokens < 1:
            raise OpenAIAssetDiscoveryConfigurationError(
                "The discovery output token limit must be positive."
            )
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._session = session or requests.Session()

    def search(self, request: AssetSearchRequest) -> AssetDiscoveryResult:
        payload = self.build_payload(request)
        try:
            response = self._session.post(
                OPENAI_RESPONSES_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except requests.exceptions.RequestException as exc:
            raise OpenAIAssetDiscoveryResponseError(
                "OpenAI asset discovery failed before receiving a response."
            ) from exc

        request_id = request_id_from_headers(response, ("x-request-id", "X-Request-Id"))
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise OpenAIAssetDiscoveryResponseError(
                "OpenAI asset discovery returned a non-JSON response."
            ) from exc
        if not isinstance(data, Mapping):
            raise OpenAIAssetDiscoveryResponseError(
                "OpenAI asset discovery returned an unexpected response."
            )

        status_code = getattr(response, "status_code", 200)
        if isinstance(status_code, int) and status_code >= 400:
            raise OpenAIAssetDiscoveryResponseError(
                f"OpenAI asset discovery returned HTTP {status_code}."
            )

        self._validate_response_status(data)
        output_text, citations = _extract_output_text_and_citations(data)
        raw_result = _decode_result(output_text)

        response_id = data.get("id", "")
        model = data.get("model", self._model)
        return AssetDiscoveryResult(
            candidates=_parse_candidates(raw_result, citations, request.max_results),
            response_id=response_id if isinstance(response_id, str) else "",
            model=model if isinstance(model, str) else self._model,
            request_id=request_id,
        )

    def build_payload(self, request: AssetSearchRequest) -> dict[str, Any]:
        input_text = json.dumps(
            {
                "query": request.query,
                "requested_formats": request.requested_formats,
                "max_results": request.max_results,
                "require_direct_download": request.require_direct_download,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return {
            "model": self._model,
            "instructions": DISCOVERY_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_text}],
                }
            ],
            "tools": [{"type": "web_search"}],
            "tool_choice": "required",
            "max_output_tokens": self._max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "asset_discovery_candidates",
                    "strict": True,
                    "schema": ASSET_DISCOVERY_SCHEMA,
                }
            },
        }

    @staticmethod
    def _validate_response_status(data: Mapping[str, Any]) -> None:
        status = data.get("status")
        if status in {None, "completed"}:
            return
        raise OpenAIAssetDiscoveryResponseError(
            f"OpenAI asset discovery did not complete: {status}."
        )


def _decode_result(output_text: str) -> Mapping[str, Any]:
    try:
        result = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIAssetDiscoveryResponseError(
            "OpenAI asset discovery returned invalid candidate JSON."
        ) from exc
    if not isinstance(result, Mapping):
        raise OpenAIAssetDiscoveryResponseError(
            "OpenAI asset discovery candidate JSON must be an object."
        )
    return result


def _extract_output_text_and_citations(data: Mapping[str, Any]) -> tuple[str, tuple[Citation, ...]]:
    output = data.get("output")
    if not isinstance(output, list):
        raise OpenAIAssetDiscoveryResponseError(
            "OpenAI asset discovery response did not contain output items."
        )

    citations: list[Citation] = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            annotations = part.get("annotations")
            if isinstance(annotations, list):
                citations.extend(_parse_citations(annotations))
            if part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    return text, tuple(citations)
    raise OpenAIAssetDiscoveryResponseError(
        "OpenAI asset discovery response did not contain candidate text."
    )


def _parse_citations(annotations: list[Any]) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for annotation in annotations:
        if not isinstance(annotation, Mapping) or annotation.get("type") != "url_citation":
            continue
        url = annotation.get("url")
        title = annotation.get("title")
        if isinstance(url, str) and url:
            citations.append(Citation(url=url, title=title if isinstance(title, str) else ""))
    return tuple(citations)


def _parse_candidates(
    result: Mapping[str, Any],
    citations: tuple[Citation, ...],
    max_results: int,
) -> tuple[AssetCandidate, ...]:
    raw_candidates = result.get("candidates")
    if not isinstance(raw_candidates, list):
        raise OpenAIAssetDiscoveryResponseError(
            "OpenAI asset discovery result did not contain candidates."
        )

    candidates: list[AssetCandidate] = []
    for raw_candidate in raw_candidates[:max_results]:
        if not isinstance(raw_candidate, Mapping):
            continue
        title = _optional_string(raw_candidate.get("title")) or "Untitled asset"
        source_page_url = _optional_string(raw_candidate.get("source_page_url"))
        if source_page_url is None:
            continue
        direct_url = _optional_string(raw_candidate.get("direct_url"))
        asset_format = _candidate_format(raw_candidate.get("format"), direct_url)
        warnings = raw_candidate.get("warnings")
        candidates.append(
            AssetCandidate(
                title=title,
                source_page_url=source_page_url,
                direct_url=direct_url,
                asset_format=asset_format,
                license_label=_optional_string(raw_candidate.get("license_label")),
                license_url=_optional_string(raw_candidate.get("license_url")),
                attribution=_optional_string(raw_candidate.get("attribution")),
                confidence=_confidence(raw_candidate.get("confidence")),
                warnings=tuple(str(item) for item in warnings)
                if isinstance(warnings, list)
                else (),
                status=CandidateStatus.READY_TO_INSPECT
                if direct_url
                else CandidateStatus.NEEDS_MANUAL_DOWNLOAD,
                citations=citations,
            )
        )
    return tuple(candidates)


def _candidate_format(value: Any, direct_url: str | None) -> AssetFormat:
    if isinstance(value, str):
        try:
            return AssetFormat(value.lower().lstrip("."))
        except ValueError:
            pass
    if isinstance(direct_url, str):
        lowered = direct_url.lower()
        for asset_format in (AssetFormat.OBJ, AssetFormat.FBX, AssetFormat.GLTF, AssetFormat.GLB):
            if lowered.endswith(f".{asset_format.value}"):
                return asset_format
    return AssetFormat.UNKNOWN


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _confidence(value: Any) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return min(1.0, max(0.0, float(value)))
    return 0.0
