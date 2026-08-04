"""Blender-independent models for controlled internet asset discovery."""

from dataclasses import dataclass
from enum import StrEnum


class AssetFormat(StrEnum):
    OBJ = "obj"
    FBX = "fbx"
    GLTF = "gltf"
    GLB = "glb"
    UNKNOWN = "unknown"


class CandidateStatus(StrEnum):
    READY_TO_INSPECT = "ready_to_inspect"
    READY_TO_IMPORT = "ready_to_import"
    NEEDS_MANUAL_DOWNLOAD = "needs_manual_download"
    WRONG_FORMAT = "wrong_format"
    TOO_LARGE = "too_large"
    LICENSE_UNKNOWN = "license_unknown"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class Citation:
    url: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class InternetAccessSettings:
    discovery_enabled: bool = False
    require_explicit_search_confirmation: bool = True
    require_import_approval: bool = True
    max_asset_size_mb: int = 50
    max_results: int = 5
    allowed_formats: tuple[str, ...] = ("obj", "fbx", "gltf", "glb")

    def __post_init__(self) -> None:
        if self.max_asset_size_mb < 1:
            raise ValueError("max_asset_size_mb must be positive.")
        if self.max_results < 1:
            raise ValueError("max_results must be positive.")
        object.__setattr__(
            self,
            "allowed_formats",
            tuple(dict.fromkeys(item.lower().lstrip(".") for item in self.allowed_formats)),
        )


@dataclass(frozen=True, slots=True)
class AssetSearchRequest:
    query: str
    requested_formats: tuple[str, ...] = ("obj", "fbx", "gltf", "glb")
    max_results: int = 5
    require_direct_download: bool = True

    def __post_init__(self) -> None:
        query = self.query.strip()
        if not query:
            raise ValueError("Asset search query is required.")
        if self.max_results < 1:
            raise ValueError("max_results must be positive.")
        formats = tuple(
            dict.fromkeys(
                format_value.lower().lstrip(".") for format_value in self.requested_formats
            )
        )
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "requested_formats", formats)


@dataclass(frozen=True, slots=True)
class InternetDiscoveryIntent:
    requires_internet: bool
    asset_kind: str
    requested_formats: tuple[str, ...]
    scene_mutating: bool = False


@dataclass(frozen=True, slots=True)
class LinkInspectionResult:
    allowed: bool
    requested_url: str
    final_url: str
    extension: str
    size_bytes: int
    redirect_chain: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    title: str
    source_page_url: str
    direct_url: str | None = None
    asset_format: AssetFormat = AssetFormat.UNKNOWN
    license_label: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    status: CandidateStatus = CandidateStatus.READY_TO_INSPECT
    citations: tuple[Citation, ...] = ()

    def __post_init__(self) -> None:
        asset_format = self.asset_format
        if isinstance(asset_format, str):
            try:
                asset_format = AssetFormat(asset_format.lower().lstrip("."))
            except ValueError:
                asset_format = AssetFormat.UNKNOWN
            object.__setattr__(self, "asset_format", asset_format)
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(self, "confidence", min(1.0, max(0.0, float(self.confidence))))

    @property
    def scene_mutating(self) -> bool:
        return False

    @property
    def requires_license_acknowledgement(self) -> bool:
        label = (self.license_label or "").strip().lower()
        return label in {"", "unknown", "license unknown", "unspecified"}

    @property
    def attribution_properties(self) -> dict[str, str]:
        values = {
            "ai_asset_title": self.title,
            "ai_asset_source_page": self.source_page_url,
            "ai_asset_direct_url": self.direct_url,
            "ai_asset_license": self.license_label,
            "ai_asset_license_url": self.license_url,
            "ai_asset_attribution": self.attribution,
        }
        return {
            key: value
            for key, value in values.items()
            if isinstance(value, str) and value.strip()
        }


@dataclass(frozen=True, slots=True)
class AssetDiscoveryResult:
    candidates: tuple[AssetCandidate, ...]
    response_id: str = ""
    model: str = ""
    request_id: str = ""
