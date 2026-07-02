import base64
from pathlib import Path
from typing import Any

import pytest

from extension.providers.openai_images import (
    OpenAIImageAPIError,
    OpenAIImageConfigurationError,
    OpenAIImageProvider,
    OpenAIImageResponseError,
    _image_generation_size,
    openai_image_generation_enabled,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        data: Any | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._data = data if data is not None else {}
        self.text = text
        self.headers = {"x-request-id": "req_image_test"}

    def json(self) -> Any:
        return self._data


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.posts: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self.response


def test_openai_image_provider_generates_png_from_base64(tmp_path: Path) -> None:
    image_bytes = b"png-bytes"
    session = FakeSession(
        FakeResponse(data={"data": [{"b64_json": base64.b64encode(image_bytes).decode()}]})
    )
    provider = OpenAIImageProvider(
        "sk-test",
        model="gpt-image-2",
        quality="low",
        session=session,
        sleep=lambda _seconds: None,
    )

    destination = tmp_path / "generated.png"
    result = provider.generate_texture(
        prompt="rough blue ceramic texture",
        width=64,
        height=64,
        destination=destination,
    )

    assert result == destination
    assert destination.read_bytes() == image_bytes
    payload = session.posts[0]["json"]
    assert payload == {
        "model": "gpt-image-2",
        "prompt": "rough blue ceramic texture",
        "n": 1,
        "size": "1024x1024",
        "quality": "low",
        "output_format": "png",
    }


def test_openai_image_provider_uses_aspect_ratio_size() -> None:
    assert _image_generation_size(512, 256) == "1536x1024"
    assert _image_generation_size(256, 512) == "1024x1536"
    assert _image_generation_size(512, 512) == "1024x1024"


def test_openai_image_provider_requires_gpt_image_model() -> None:
    with pytest.raises(OpenAIImageConfigurationError, match="GPT image model"):
        OpenAIImageProvider("sk-test", model="dall-e-3")


def test_openai_image_provider_reports_http_errors(tmp_path: Path) -> None:
    session = FakeSession(
        FakeResponse(
            status_code=400,
            data={"error": {"message": "bad image prompt", "code": "invalid_prompt"}},
        )
    )
    provider = OpenAIImageProvider("sk-test", session=session, sleep=lambda _seconds: None)

    with pytest.raises(OpenAIImageAPIError, match="bad image prompt"):
        provider.generate_texture(
            prompt="texture",
            width=64,
            height=64,
            destination=tmp_path / "unused.png",
        )


def test_openai_image_provider_reports_missing_image_data(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(data={"data": []}))
    provider = OpenAIImageProvider("sk-test", session=session, sleep=lambda _seconds: None)

    with pytest.raises(OpenAIImageResponseError, match="no image data"):
        provider.generate_texture(
            prompt="texture",
            width=64,
            height=64,
            destination=tmp_path / "unused.png",
        )


def test_openai_image_generation_enabled_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_IMAGE_GENERATION_ENABLED", "true")
    assert openai_image_generation_enabled() is True

    monkeypatch.setenv("OPENAI_IMAGE_GENERATION_ENABLED", "false")
    assert openai_image_generation_enabled() is False
