"""Blender-independent state helpers for the asset search/review screen."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from ..internet.asset_resolver import AssetResolutionError, candidate_to_import_operation
from ..internet.models import (
    AssetCandidate,
    AssetDiscoveryResult,
    AssetFormat,
    AssetSearchRequest,
    Citation,
    LinkInspectionResult,
)
from ..internet.review import review_asset_candidate
from ..operations import OperationContractError, OperationPlan, validate_operation_plan
from ..providers.registry import PROVIDER_OPENAI

ASSET_SEARCH_MAX_RESULTS = 10
ASSET_SEARCH_DEFAULT_MAX_RESULTS = 5
ASSET_SEARCH_FORMATS = ("obj", "fbx", "gltf", "glb")
_DERIVED_REVIEW_MESSAGES = frozenset(
    {
        "A direct download URL is required before import.",
        "The candidate format is unsupported or unknown.",
        "The candidate license is unknown and must be acknowledged.",
        "Inspect the direct URL before import.",
    }
)


class AssetSearchStatus(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    SEARCH_FAILED = "search_failed"
    RESULTS_READY = "results_ready"
    INSPECTING = "inspecting"
    INSPECTION_FAILED = "inspection_failed"
    READY_TO_IMPORT = "ready_to_import"
    HANDOFF_CREATED = "handoff_created"


class AssetSearchScreenError(RuntimeError):
    """Raised when the candidate search screen cannot complete a UI action."""


@dataclass(slots=True)
class AssetCandidateRow:
    title: str
    source_page_url: str
    direct_url: str
    final_url: str
    source_host: str
    asset_format: str
    format_label: str
    license_label: str
    license_url: str
    attribution: str
    confidence: float
    confidence_label: str
    size_bytes: int
    size_label: str
    status_label: str
    warnings: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    expanded: bool = False
    selected: bool = False
    inspected: bool = False
    import_ready: bool = False
    rejected: bool = False

    @property
    def warnings_text(self) -> str:
        return "\n".join(self.warnings)

    @property
    def citations_text(self) -> str:
        return "\n".join(
            citation.url if not citation.title else f"{citation.title} - {citation.url}"
            for citation in self.citations
        )


@dataclass(slots=True)
class AssetSearchState:
    status: str = AssetSearchStatus.IDLE.value
    query: str = ""
    format_filter: str = "ANY"
    max_results: int = ASSET_SEARCH_DEFAULT_MAX_RESULTS
    direct_download_only: bool = True
    error_headline: str = ""
    error_details: str = ""
    selected_candidate_index: int = -1
    candidates: tuple[AssetCandidateRow, ...] = ()
    persist_to_preferences: bool = False


def create_default_asset_search_state() -> AssetSearchState:
    return AssetSearchState()


def clear_asset_search_state(state: Any) -> None:
    _set_search_status(state, AssetSearchStatus.IDLE)
    _set_text(state, "query", "asset_search_query", "")
    _set_text(state, "error_headline", "asset_search_error_headline", "")
    _set_text(state, "error_details", "asset_search_error_details", "")
    _set_int(state, "selected_candidate_index", "selected_asset_candidate_index", -1)
    _replace_candidates(state, ())


def asset_search_panel_poll(
    *,
    internet_discovery_enabled: bool,
    provider_choice: str,
) -> bool:
    return bool(internet_discovery_enabled) and provider_choice == PROVIDER_OPENAI


def build_asset_search_request_from_state(state: Any) -> AssetSearchRequest:
    format_filter = _state_value(state, "format_filter", "asset_search_format", "ANY")
    requested_formats = (
        ASSET_SEARCH_FORMATS
        if format_filter == "ANY"
        else (str(format_filter).lower(),)
    )
    return AssetSearchRequest(
        query=str(_state_value(state, "query", "asset_search_query", "")).strip(),
        requested_formats=requested_formats,
        max_results=min(
            ASSET_SEARCH_MAX_RESULTS,
            max(1, int(_state_value(state, "max_results", "asset_search_max_results", 5))),
        ),
        require_direct_download=bool(
            _state_value(state, "direct_download_only", "asset_search_direct_only", True)
        ),
    )


def candidate_row_from_asset_candidate(
    candidate: AssetCandidate,
    inspection: LinkInspectionResult | None = None,
    *,
    expanded: bool = False,
    selected: bool = False,
    rejected: bool = False,
    license_acknowledged: bool = False,
) -> AssetCandidateRow:
    review = review_asset_candidate(
        candidate,
        inspection=inspection,
        license_acknowledged=license_acknowledged,
    )
    warnings = tuple(dict.fromkeys((*candidate.warnings, *review.reasons)))
    if inspection is not None:
        warnings = tuple(dict.fromkeys((*warnings, *inspection.warnings)))
    return AssetCandidateRow(
        title=candidate.title,
        source_page_url=candidate.source_page_url,
        direct_url=candidate.direct_url or "",
        final_url=inspection.final_url if inspection is not None else "",
        source_host=_host_label(candidate.source_page_url),
        asset_format=candidate.asset_format.value,
        format_label=_format_label(candidate.asset_format),
        license_label=candidate.license_label or "Unknown",
        license_url=candidate.license_url or "",
        attribution=candidate.attribution or "",
        confidence=candidate.confidence,
        confidence_label=f"{candidate.confidence:.0%}",
        size_bytes=inspection.size_bytes if inspection is not None else 0,
        size_label=_size_label(inspection.size_bytes) if inspection is not None else "",
        status_label=review.status_label,
        warnings=warnings,
        citations=candidate.citations,
        expanded=expanded,
        selected=selected,
        inspected=inspection is not None,
        import_ready=review.can_import,
        rejected=rejected,
    )


def apply_asset_discovery_result(state: Any, result: AssetDiscoveryResult) -> None:
    rows = tuple(candidate_row_from_asset_candidate(candidate) for candidate in result.candidates)
    _replace_candidates(state, rows)
    _set_int(
        state,
        "selected_candidate_index",
        "selected_asset_candidate_index",
        0 if rows else -1,
    )
    _set_text(state, "error_headline", "asset_search_error_headline", "")
    _set_text(state, "error_details", "asset_search_error_details", "")
    if rows:
        _set_search_status(state, AssetSearchStatus.RESULTS_READY)
    else:
        _set_search_status(state, AssetSearchStatus.SEARCH_FAILED)
        _set_text(state, "error_headline", "asset_search_error_headline", "No assets found")
        _set_text(
            state,
            "error_details",
            "asset_search_error_details",
            "The search completed but did not return import candidates.",
        )


def apply_asset_search_error(
    state: Any,
    error: Exception,
    *,
    operation: str,
) -> None:
    if operation == "inspection":
        _set_search_status(state, AssetSearchStatus.INSPECTION_FAILED)
        _set_text(
            state,
            "error_headline",
            "asset_search_error_headline",
            "URL inspection failed",
        )
    else:
        _set_search_status(state, AssetSearchStatus.SEARCH_FAILED)
        _set_text(
            state,
            "error_headline",
            "asset_search_error_headline",
            "Asset search failed",
        )
    _set_text(
        state,
        "error_details",
        "asset_search_error_details",
        str(error) or type(error).__name__,
    )


def apply_candidate_inspection_result(
    state: Any,
    inspection: LinkInspectionResult,
    *,
    candidate_index: int | None = None,
) -> None:
    rows = list(_candidate_rows(state))
    index = (
        candidate_index
        if candidate_index is not None
        else int(
            _state_value(
                state,
                "selected_candidate_index",
                "selected_asset_candidate_index",
                -1,
            )
        )
    )
    if index < 0 or index >= len(rows):
        raise AssetSearchScreenError("Select an asset candidate before inspecting it.")

    updated_rows: list[AssetCandidateRow] = []
    for row_index, row in enumerate(rows):
        candidate = asset_candidate_from_row(row)
        if row_index == index:
            updated_rows.append(
                candidate_row_from_asset_candidate(
                    candidate,
                    inspection=inspection,
                    expanded=row.expanded,
                    selected=True,
                    rejected=row.rejected,
                )
            )
        else:
            updated_rows.append(
                replace(row, selected=False, import_ready=False)
                if isinstance(row, AssetCandidateRow)
                else row
            )

    _replace_candidates(state, tuple(updated_rows))
    _set_int(state, "selected_candidate_index", "selected_asset_candidate_index", index)
    _set_text(state, "error_headline", "asset_search_error_headline", "")
    _set_text(state, "error_details", "asset_search_error_details", "")
    _set_search_status(
        state,
        AssetSearchStatus.READY_TO_IMPORT
        if updated_rows[index].import_ready
        else AssetSearchStatus.INSPECTION_FAILED,
    )
    if not updated_rows[index].import_ready:
        _set_text(
            state,
            "error_headline",
            "asset_search_error_headline",
            "URL inspection failed",
        )
        _set_text(
            state,
            "error_details",
            "asset_search_error_details",
            updated_rows[index].warnings_text,
        )


def select_asset_candidate(state: Any, candidate_index: int) -> None:
    rows = list(_candidate_rows(state))
    if candidate_index < 0 or candidate_index >= len(rows):
        raise AssetSearchScreenError("Select a valid asset candidate.")
    rows = [
        replace(row, selected=index == candidate_index)
        for index, row in enumerate(rows)
    ]
    _replace_candidates(state, tuple(rows))
    _set_int(
        state,
        "selected_candidate_index",
        "selected_asset_candidate_index",
        candidate_index,
    )


def toggle_asset_candidate_expanded(state: Any, candidate_index: int) -> None:
    rows = list(_candidate_rows(state))
    if candidate_index < 0 or candidate_index >= len(rows):
        raise AssetSearchScreenError("Select a valid asset candidate.")
    rows[candidate_index] = replace(
        rows[candidate_index],
        expanded=not rows[candidate_index].expanded,
    )
    _replace_candidates(state, tuple(rows))


def reject_asset_candidate(state: Any, candidate_index: int | None = None) -> None:
    rows = list(_candidate_rows(state))
    index = (
        candidate_index
        if candidate_index is not None
        else int(
            _state_value(
                state,
                "selected_candidate_index",
                "selected_asset_candidate_index",
                -1,
            )
        )
    )
    if index < 0 or index >= len(rows):
        raise AssetSearchScreenError("Select a valid asset candidate.")
    rows[index] = replace(rows[index], rejected=True, selected=False, import_ready=False)
    _replace_candidates(state, tuple(rows))
    _set_int(state, "selected_candidate_index", "selected_asset_candidate_index", -1)
    _set_search_status(
        state,
        AssetSearchStatus.RESULTS_READY
        if any(not row.rejected for row in rows)
        else AssetSearchStatus.IDLE,
    )


def selected_asset_candidate_row(state: Any) -> AssetCandidateRow:
    rows = _candidate_rows(state)
    index = int(
        _state_value(
            state,
            "selected_candidate_index",
            "selected_asset_candidate_index",
            -1,
        )
    )
    if index < 0 or index >= len(rows):
        raise AssetSearchScreenError("Select an asset candidate first.")
    return rows[index]


def asset_candidate_from_row(row: Any) -> AssetCandidate:
    direct_url = str(getattr(row, "direct_url", "")).strip() or None
    return AssetCandidate(
        title=str(getattr(row, "title", "")).strip() or "Untitled asset",
        source_page_url=str(getattr(row, "source_page_url", "")).strip(),
        direct_url=direct_url,
        asset_format=_asset_format_from_row(row, direct_url),
        license_label=_optional_text(getattr(row, "license_label", None)),
        license_url=_optional_text(getattr(row, "license_url", None)),
        attribution=_optional_text(getattr(row, "attribution", None)),
        confidence=float(getattr(row, "confidence", 0.0)),
        warnings=tuple(
            warning
            for warning in _split_lines(getattr(row, "warnings_text", ""))
            if warning not in _DERIVED_REVIEW_MESSAGES
        ),
        citations=_parse_citation_lines(getattr(row, "citations_text", "")),
    )


def inspection_result_from_row(row: Any) -> LinkInspectionResult | None:
    if not bool(getattr(row, "inspected", False)):
        return None
    final_url = str(getattr(row, "final_url", "")).strip()
    if not final_url:
        return None
    direct_url = str(getattr(row, "direct_url", "")).strip() or final_url
    extension = _url_extension(final_url) or f".{_asset_format_from_row(row, direct_url).value}"
    return LinkInspectionResult(
        allowed=bool(getattr(row, "import_ready", False)),
        requested_url=direct_url,
        final_url=final_url,
        extension=extension,
        size_bytes=int(getattr(row, "size_bytes", 0)),
        redirect_chain=(),
        warnings=_split_lines(getattr(row, "warnings_text", "")),
    )


def build_import_plan_from_selection(
    *,
    candidate: AssetCandidate,
    inspection: LinkInspectionResult | None,
    snapshot_id: str,
    operation_id: str,
    name_prefix: str | None = None,
    collection_id: str | None = None,
    license_acknowledged: bool = False,
) -> OperationPlan:
    if not candidate.direct_url:
        raise AssetSearchScreenError("The selected candidate needs a direct download URL.")
    if inspection is None:
        raise AssetSearchScreenError("Inspect the direct download URL before import.")

    review = review_asset_candidate(
        candidate,
        inspection=inspection,
        license_acknowledged=license_acknowledged,
    )
    if not review.can_import:
        raise AssetSearchScreenError(" ".join(review.reasons) or review.status_label)

    try:
        operation = candidate_to_import_operation(
            candidate,
            inspection,
            operation_id=operation_id,
            collection_id=collection_id,
            name_prefix=name_prefix or _default_name_prefix(candidate.title),
        )
        return validate_operation_plan(
            {
                "snapshot_id": snapshot_id,
                "status": "ready",
                "intent_summary": f"Import verified internet asset {candidate.title}.",
                "assumptions": [
                    "The user selected this asset candidate from internet discovery."
                ],
                "questions": [],
                "operations": [operation],
            }
        )
    except (AssetResolutionError, OperationContractError) as exc:
        raise AssetSearchScreenError(str(exc)) from exc


def _candidate_rows(state: Any) -> tuple[AssetCandidateRow, ...]:
    if hasattr(state, "candidates"):
        return tuple(state.candidates)
    if hasattr(state, "asset_candidates"):
        return tuple(_row_from_blender_item(item) for item in state.asset_candidates)
    return ()


def _replace_candidates(state: Any, rows: tuple[AssetCandidateRow, ...]) -> None:
    if hasattr(state, "candidates"):
        state.candidates = rows
        return
    collection = getattr(state, "asset_candidates", None)
    if collection is None:
        return
    collection.clear()
    for row in rows:
        item = collection.add()
        _write_blender_row(item, row)


def _row_from_blender_item(item: Any) -> AssetCandidateRow:
    return AssetCandidateRow(
        title=str(item.title),
        source_page_url=str(item.source_page_url),
        direct_url=str(item.direct_url),
        final_url=str(item.final_url),
        source_host=str(item.source_host),
        asset_format=str(item.asset_format),
        format_label=str(item.format_label),
        license_label=str(item.license_label),
        license_url=str(item.license_url),
        attribution=str(item.attribution),
        confidence=float(item.confidence),
        confidence_label=str(item.confidence_label),
        size_bytes=int(item.size_bytes),
        size_label=str(item.size_label),
        status_label=str(item.status_label),
        warnings=_split_lines(item.warnings_text),
        citations=_parse_citation_lines(item.citations_text),
        expanded=bool(item.expanded),
        selected=bool(item.selected),
        inspected=bool(item.inspected),
        import_ready=bool(item.import_ready),
        rejected=bool(item.rejected),
    )


def _write_blender_row(item: Any, row: AssetCandidateRow) -> None:
    item.title = row.title
    item.source_page_url = row.source_page_url
    item.direct_url = row.direct_url
    item.final_url = row.final_url
    item.source_host = row.source_host
    item.asset_format = row.asset_format
    item.format_label = row.format_label
    item.license_label = row.license_label
    item.license_url = row.license_url
    item.attribution = row.attribution
    item.confidence = row.confidence
    item.confidence_label = row.confidence_label
    item.size_bytes = row.size_bytes
    item.size_label = row.size_label
    item.status_label = row.status_label
    item.warnings_text = row.warnings_text
    item.citations_text = row.citations_text
    item.expanded = row.expanded
    item.selected = row.selected
    item.inspected = row.inspected
    item.import_ready = row.import_ready
    item.rejected = row.rejected


def _state_value(state: Any, pure_name: str, blender_name: str, default: Any) -> Any:
    if hasattr(state, pure_name):
        return getattr(state, pure_name)
    return getattr(state, blender_name, default)


def _set_search_status(state: Any, status: AssetSearchStatus) -> None:
    _set_text(state, "status", "asset_search_status", status.value)


def _set_text(state: Any, pure_name: str, blender_name: str, value: str) -> None:
    if hasattr(state, pure_name):
        setattr(state, pure_name, value)
    elif hasattr(state, blender_name):
        setattr(state, blender_name, value)


def _set_int(state: Any, pure_name: str, blender_name: str, value: int) -> None:
    if hasattr(state, pure_name):
        setattr(state, pure_name, value)
    elif hasattr(state, blender_name):
        setattr(state, blender_name, value)


def _host_label(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or parsed.netloc or url).lower()


def _format_label(asset_format: AssetFormat) -> str:
    return "Unknown" if asset_format is AssetFormat.UNKNOWN else asset_format.value.upper()


def _size_label(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if stripped in {"", "Unknown"} else stripped


def _asset_format_from_row(row: Any, direct_url: str | None) -> AssetFormat:
    raw_format = str(getattr(row, "asset_format", "")).strip().lower()
    if raw_format:
        try:
            asset_format = AssetFormat(raw_format)
            if asset_format is not AssetFormat.UNKNOWN:
                return asset_format
        except ValueError:
            pass
    raw_label = str(getattr(row, "format_label", "")).strip().lower()
    if raw_label:
        try:
            return AssetFormat(raw_label)
        except ValueError:
            pass
    if direct_url:
        suffix = urlparse(direct_url).path.rsplit(".", 1)[-1].lower()
        try:
            return AssetFormat(suffix)
        except ValueError:
            pass
    return AssetFormat.UNKNOWN


def _url_extension(url: str) -> str:
    path = urlparse(url).path
    if "." not in path:
        return ""
    extension = f".{path.rsplit('.', 1)[-1].lower()}"
    return extension if extension.lstrip(".") in ASSET_SEARCH_FORMATS else ""


def _split_lines(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _parse_citation_lines(value: Any) -> tuple[Citation, ...]:
    citations = []
    for line in _split_lines(value):
        title, separator, url = line.partition(" - ")
        citations.append(
            Citation(url=url if separator else title, title=title if separator else "")
        )
    return tuple(citations)


def _default_name_prefix(title: str) -> str:
    prefix = "".join(character for character in title.title() if character.isalnum())
    return prefix[:48] or "ImportedAsset"
