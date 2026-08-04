from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from extension.operations import validate_operation_plan


@dataclass(frozen=True, slots=True)
class FakeSearchSession:
    payloads: list[dict[str, Any]]

    def post(self, _url: str, **kwargs: Any) -> Any:
        self.payloads.append(dict(kwargs))
        return FakeJsonResponse(
            {
                "id": "resp_asset_search",
                "model": "gpt-5.5",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '{"candidates":[{"title":"Male Base Mesh","source_page_url":'
                                    '"https://assets.example.com/base-mesh","direct_url":'
                                    '"https://cdn.example.com/base-mesh.glb","format":"glb",'
                                    '"license_label":"CC0","license_url":"https://assets.example.com/license",'
                                    '"attribution":"Example Artist","confidence":0.91,'
                                    '"warnings":[]}]}'
                                ),
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://assets.example.com/base-mesh",
                                        "title": "Male Base Mesh",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class FakeJsonResponse:
    body: dict[str, Any]
    status_code: int = 200
    headers: dict[str, str] | None = None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self.body


@dataclass(frozen=True, slots=True)
class FakeStreamResponse:
    headers: dict[str, str]
    chunks: tuple[bytes, ...]
    final_url: str
    status_code: int = 200

    @property
    def url(self) -> str:
        return self.final_url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int) -> tuple[bytes, ...]:
        assert chunk_size > 0
        return self.chunks

    def close(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class FakeDownloadSession:
    responses: tuple[FakeStreamResponse, ...]
    requested_urls: list[str]

    def get(self, url: str, **_kwargs: Any) -> FakeStreamResponse:
        self.requested_urls.append(url)
        if not self.responses:
            raise AssertionError("No fake response configured.")
        return self.responses[min(len(self.requested_urls) - 1, len(self.responses) - 1)]


def test_track_a_internet_asset_discovery_settings_default_to_disabled() -> None:
    from extension.internet.models import InternetAccessSettings

    settings = InternetAccessSettings()

    assert settings.discovery_enabled is False
    assert settings.require_explicit_search_confirmation is True
    assert settings.require_import_approval is True
    assert settings.max_asset_size_mb == 50


def test_track_a_prompt_router_detects_discovery_without_mutating_scene() -> None:
    from extension.internet.intent import classify_internet_intent

    intent = classify_internet_intent(
        "Find a free male base mesh in GLB format and import it at the origin."
    )

    assert intent.requires_internet is True
    assert intent.asset_kind == "model"
    assert intent.requested_formats == ("glb",)
    assert intent.scene_mutating is False


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example.com/base.glb",
        "ftp://cdn.example.com/base.glb",
        "file:///C:/assets/base.glb",
        "https://127.0.0.1/base.glb",
        "https://10.0.0.5/base.glb",
        "https://192.168.1.20/base.glb",
        "https://cdn.example.com/base.zip",
        "https://cdn.example.com/assets/",
    ],
)
def test_track_b_url_policy_rejects_unsafe_or_unsupported_asset_urls(url: str) -> None:
    from extension.internet.policy import InternetDownloadPolicy, InternetPolicyError
    from extension.internet.url_inspector import validate_asset_url

    with pytest.raises(InternetPolicyError):
        validate_asset_url(url, policy=InternetDownloadPolicy())


def test_track_b_url_inspector_accepts_bounded_direct_https_model_url() -> None:
    from extension.internet.policy import InternetDownloadPolicy
    from extension.internet.url_inspector import inspect_asset_url

    response = FakeStreamResponse(
        headers={"content-length": "1024", "content-type": "model/gltf-binary"},
        chunks=(b"glb bytes",),
        final_url="https://cdn.example.com/base-mesh.glb",
    )
    session = FakeDownloadSession(responses=(response,), requested_urls=[])

    result = inspect_asset_url(
        "https://cdn.example.com/base-mesh.glb",
        policy=InternetDownloadPolicy(max_asset_size_mb=50),
        session=session,
    )

    assert result.allowed is True
    assert result.final_url == "https://cdn.example.com/base-mesh.glb"
    assert result.extension == ".glb"
    assert result.size_bytes == 1024
    assert result.warnings == ()
    assert session.requested_urls == ["https://cdn.example.com/base-mesh.glb"]


def test_track_c_asset_candidate_keeps_license_and_attribution_metadata() -> None:
    from extension.internet.models import AssetCandidate, AssetFormat, CandidateStatus

    candidate = AssetCandidate(
        title="Male Base Mesh",
        source_page_url="https://assets.example.com/base-mesh",
        direct_url="https://cdn.example.com/base-mesh.glb",
        asset_format=AssetFormat.GLB,
        license_label="CC0",
        license_url="https://assets.example.com/license",
        attribution="Example Artist",
        confidence=0.91,
        warnings=(),
        status=CandidateStatus.READY_TO_INSPECT,
    )

    assert candidate.scene_mutating is False
    assert candidate.requires_license_acknowledgement is False
    assert candidate.attribution_properties["ai_asset_source_page"] == candidate.source_page_url
    assert candidate.attribution_properties["ai_asset_license"] == "CC0"


def test_track_d_openai_discovery_uses_web_search_not_operation_planning() -> None:
    from extension.internet.models import AssetSearchRequest
    from extension.internet.openai_search import OpenAIAssetDiscoveryProvider

    session = FakeSearchSession(payloads=[])
    provider = OpenAIAssetDiscoveryProvider(api_key="sk-test", model="gpt-5.5", session=session)

    result = provider.search(
        AssetSearchRequest(
            query="male base mesh",
            requested_formats=("glb",),
            max_results=3,
            require_direct_download=True,
        )
    )

    payload = session.payloads[0]["json"]
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["tool_choice"] == "required"
    assert payload["text"]["format"]["name"] == "asset_discovery_candidates"
    assert "blender_operation_plan" not in str(payload)
    assert result.candidates[0].direct_url == "https://cdn.example.com/base-mesh.glb"
    assert result.candidates[0].citations[0].url == "https://assets.example.com/base-mesh"


def test_track_e_candidate_review_blocks_listing_pages_until_direct_url_is_verified() -> None:
    from extension.internet.models import AssetCandidate, AssetFormat
    from extension.internet.review import review_asset_candidate

    listing_candidate = AssetCandidate(
        title="Listing Page",
        source_page_url="https://assets.example.com/base-mesh",
        direct_url=None,
        asset_format=AssetFormat.UNKNOWN,
        license_label=None,
        license_url=None,
        attribution=None,
        confidence=0.62,
        warnings=("No direct download URL found.",),
    )

    review = review_asset_candidate(listing_candidate)

    assert review.can_import is False
    assert review.status_label == "Needs manual download"
    assert "direct download URL" in " ".join(review.reasons)


def test_track_f_verified_candidate_converts_to_import_asset_operation() -> None:
    from extension.internet.asset_resolver import candidate_to_import_operation
    from extension.internet.models import AssetCandidate, AssetFormat, LinkInspectionResult

    candidate = AssetCandidate(
        title="Male Base Mesh",
        source_page_url="https://assets.example.com/base-mesh",
        direct_url="https://cdn.example.com/base-mesh.glb",
        asset_format=AssetFormat.GLB,
        license_label="CC0",
        license_url="https://assets.example.com/license",
        attribution="Example Artist",
        confidence=0.91,
        warnings=(),
    )
    inspection = LinkInspectionResult(
        allowed=True,
        requested_url="https://cdn.example.com/base-mesh.glb",
        final_url="https://cdn.example.com/base-mesh.glb",
        extension=".glb",
        size_bytes=2048,
        redirect_chain=(),
        warnings=(),
    )

    operation = candidate_to_import_operation(
        candidate,
        inspection,
        operation_id="import_male_base_mesh",
        collection_id=None,
        name_prefix="MaleBase",
    )

    assert operation["type"] == "IMPORT_ASSET"
    assert operation["filepath"] == "https://cdn.example.com/base-mesh.glb"
    assert operation["format"] == "glb"
    assert operation["name_prefix"] == "MaleBase"
    assert operation["asset_metadata"]["source_page_url"] == candidate.source_page_url
    assert operation["asset_metadata"]["license_label"] == "CC0"

    plan = validate_operation_plan(
        {
            "snapshot_id": "c" * 32,
            "status": "ready",
            "intent_summary": "Import the verified internet asset.",
            "assumptions": [],
            "questions": [],
            "operations": [operation],
        }
    )
    assert plan.operations[0].payload["asset_metadata"]["title"] == "Male Base Mesh"


def test_track_g_non_live_test_matrix_includes_internet_asset_discovery() -> None:
    from extension.internet.testing import planned_non_live_test_surfaces

    surfaces = planned_non_live_test_surfaces()

    assert "url_policy" in surfaces
    assert "redirects" in surfaces
    assert "size_limits" in surfaces
    assert "mocked_openai_discovery" in surfaces
    assert "candidate_review" in surfaces
    assert "import_handoff" in surfaces
