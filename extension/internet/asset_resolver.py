"""Convert verified internet asset candidates into controlled operations."""

from typing import Any

from .models import AssetCandidate, AssetFormat, LinkInspectionResult
from .policy import asset_format_from_extension


class AssetResolutionError(RuntimeError):
    """Raised when an asset candidate cannot be converted to an import operation."""


def candidate_to_import_operation(
    candidate: AssetCandidate,
    inspection: LinkInspectionResult,
    *,
    operation_id: str,
    collection_id: str | None,
    name_prefix: str | None,
    location: tuple[float, float, float] | None = None,
    rotation_euler: tuple[float, float, float] | None = None,
    scale: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    if not inspection.allowed:
        raise AssetResolutionError("Only policy-approved asset URLs can be imported.")
    asset_format = asset_format_from_extension(inspection.extension)
    if asset_format is AssetFormat.UNKNOWN:
        raise AssetResolutionError("The inspected asset URL has an unsupported format.")

    return {
        "operation_id": operation_id,
        "type": "IMPORT_ASSET",
        "filepath": inspection.final_url,
        "format": asset_format.value,
        "collection_id": collection_id,
        "name_prefix": name_prefix,
        "location": list(location or (0.0, 0.0, 0.0)),
        "rotation_euler": list(rotation_euler or (0.0, 0.0, 0.0)),
        "scale": list(scale or (1.0, 1.0, 1.0)),
        "asset_metadata": _asset_metadata(candidate, inspection),
    }


def _asset_metadata(
    candidate: AssetCandidate,
    inspection: LinkInspectionResult,
) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "source_page_url": candidate.source_page_url,
        "direct_url": candidate.direct_url,
        "final_url": inspection.final_url,
        "license_label": candidate.license_label,
        "license_url": candidate.license_url,
        "attribution": candidate.attribution,
        "size_bytes": inspection.size_bytes,
        "confidence": candidate.confidence,
        "warnings": list(dict.fromkeys((*candidate.warnings, *inspection.warnings))),
    }
