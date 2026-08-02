"""OpenAI image generation provider for generated texture images."""

import base64
import binascii
import random
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import requests

from ..config import resolve_environment_value
from ._shared import (
    TransportErrorMessages,
    post_with_transient_retries,
    raise_http_api_error,
    read_json_mapping_or_raise_http_error,
    request_id_from_headers,
)

OPENAI_IMAGE_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_OPENAI_IMAGE_QUALITY = "low"
DEFAULT_OPENAI_IMAGE_TIMEOUT_SECONDS = 180.0
DEFAULT_OPENAI_IMAGE_RETRIES = 1
OPENAI_IMAGE_API_NAME = "OpenAI image API"
OPENAI_IMAGE_TRANSPORT_MESSAGES = TransportErrorMessages(
    timeout=(
        "OpenAI image generation did not respond within {timeout_seconds:g} seconds. "
        "Increase the image timeout or use deterministic local texture generation."
    ),
    tls=(
        "A secure TLS connection to OpenAI image generation could not be established. "
        "Check the system clock, certificate store, proxy, and firewall settings."
    ),
    connection=(
        "Could not connect to OpenAI image generation. Confirm Blender network access and "
        "check the internet connection, proxy, firewall, and DNS settings."
    ),
    transport=(
        "The OpenAI image generation request failed before receiving a response. Check "
        "Blender network access and the extension's connection settings."
    ),
)


class OpenAIImageProviderError(RuntimeError):
    """Base error for OpenAI image provider failures."""


class OpenAIImageConfigurationError(OpenAIImageProviderError):
    """Raised when OpenAI image generation is not configured."""


class OpenAIImageAPIError(OpenAIImageProviderError):
    """Raised when the OpenAI image API returns an error."""

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


class OpenAIImageResponseError(OpenAIImageProviderError):
    """Raised when the OpenAI image response is unusable."""


class OpenAIImageProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_OPENAI_IMAGE_MODEL,
        quality: str = DEFAULT_OPENAI_IMAGE_QUALITY,
        timeout_seconds: float = DEFAULT_OPENAI_IMAGE_TIMEOUT_SECONDS,
        max_transient_retries: int = DEFAULT_OPENAI_IMAGE_RETRIES,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise OpenAIImageConfigurationError("An OpenAI API key is required.")
        if timeout_seconds <= 0:
            raise OpenAIImageConfigurationError("The image request timeout must be positive.")
        if max_transient_retries < 0:
            raise OpenAIImageConfigurationError("The transient retry count cannot be negative.")
        if not model.strip().startswith("gpt-image-"):
            raise OpenAIImageConfigurationError(
                "OpenAI texture generation requires a GPT image model."
            )
        if quality not in {"auto", "low", "medium", "high"}:
            raise OpenAIImageConfigurationError(
                "OpenAI image quality must be auto, low, medium, or high."
            )

        self._api_key = api_key.strip()
        self._model = model.strip()
        self._quality = quality
        self._timeout_seconds = timeout_seconds
        self._max_transient_retries = max_transient_retries
        self._session = session or requests.Session()
        self._sleep = sleep
        self._random_source = random_source

    @classmethod
    def from_environment(
        cls,
        *,
        api_key: str | None = None,
        timeout_seconds: float = DEFAULT_OPENAI_IMAGE_TIMEOUT_SECONDS,
        session: Any | None = None,
    ) -> "OpenAIImageProvider":
        configured_timeout = _environment_float(
            "OPENAI_IMAGE_TIMEOUT",
            timeout_seconds,
        )
        resolved_api_key = (
            resolve_environment_value("OPENAI_API_KEY") if api_key is None else api_key
        )
        return cls(
            resolved_api_key,
            model=resolve_environment_value("OPENAI_IMAGE_MODEL")
            or DEFAULT_OPENAI_IMAGE_MODEL,
            quality=resolve_environment_value("OPENAI_IMAGE_QUALITY")
            or DEFAULT_OPENAI_IMAGE_QUALITY,
            timeout_seconds=configured_timeout,
            session=session,
        )

    def generate_texture(
        self,
        *,
        prompt: str,
        width: int,
        height: int,
        destination: Path,
    ) -> Path:
        payload = self.build_payload(prompt=prompt, width=width, height=height)
        response = self._post_with_transient_retries(payload)
        request_id = self._request_id(response)
        data = read_json_mapping_or_raise_http_error(
            response,
            request_id=request_id,
            response_error_type=OpenAIImageResponseError,
            api_error_type=OpenAIImageAPIError,
            api_name=OPENAI_IMAGE_API_NAME,
            non_json_message="OpenAI image generation returned a non-JSON response.",
            unexpected_json_message=(
                "OpenAI image generation returned an unexpected JSON response."
            ),
        )

        if response.status_code >= 400:
            raise_http_api_error(
                response,
                data,
                request_id=request_id,
                api_error_type=OpenAIImageAPIError,
                api_name=OPENAI_IMAGE_API_NAME,
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_extract_image_bytes(data))
        return destination

    def build_payload(self, *, prompt: str, width: int, height: int) -> dict[str, Any]:
        return {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": _image_generation_size(width, height),
            "quality": self._quality,
            "output_format": "png",
        }

    def _post_with_transient_retries(self, payload: Mapping[str, Any]) -> Any:
        return post_with_transient_retries(
            session=self._session,
            url=OPENAI_IMAGE_GENERATIONS_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout_seconds=self._timeout_seconds,
            max_transient_retries=self._max_transient_retries,
            sleep=self._sleep,
            random_source=self._random_source,
            api_error_type=OpenAIImageAPIError,
            messages=OPENAI_IMAGE_TRANSPORT_MESSAGES,
        )

    @staticmethod
    def _request_id(response: Any) -> str:
        return request_id_from_headers(response, ("x-request-id", "X-Request-Id"))


def openai_image_generation_enabled(default: bool = True) -> bool:
    value = resolve_environment_value("OPENAI_IMAGE_GENERATION_ENABLED").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _image_generation_size(width: int, height: int) -> str:
    aspect = width / max(height, 1)
    if aspect > 1.2:
        return "1536x1024"
    if aspect < 0.8334:
        return "1024x1536"
    return "1024x1024"


def _extract_image_bytes(data: Mapping[str, Any]) -> bytes:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise OpenAIImageResponseError("OpenAI image generation returned no image data.")

    first = items[0]
    if not isinstance(first, Mapping):
        raise OpenAIImageResponseError("OpenAI image generation returned invalid image data.")

    b64_json = first.get("b64_json")
    if not isinstance(b64_json, str) or not b64_json:
        raise OpenAIImageResponseError("OpenAI image generation did not return base64 image data.")
    try:
        return base64.b64decode(b64_json, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OpenAIImageResponseError("OpenAI image generation returned invalid base64.") from exc


def _environment_float(name: str, default: float) -> float:
    value = resolve_environment_value(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default
