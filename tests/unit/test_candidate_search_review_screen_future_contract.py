from __future__ import annotations

from pathlib import Path

import pytest

from extension.internet.models import AssetCandidate, AssetFormat, LinkInspectionResult
from extension.operations import RiskLevel
from extension.safety import evaluate_plan_safety
from extension.ui.asset_search import AssetCandidateRow

REPO_ROOT = Path(__file__).resolve().parents[2]

def importable_candidate() -> AssetCandidate:
    return AssetCandidate(
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


def inspected_link() -> LinkInspectionResult:
    return LinkInspectionResult(
        allowed=True,
        requested_url="https://cdn.example.com/base-mesh.glb",
        final_url="https://cdn.example.com/base-mesh.glb",
        extension=".glb",
        size_bytes=2048,
        redirect_chain=(),
        warnings=(),
    )


def test_default_asset_search_screen_state_is_idle_and_session_only() -> None:
    from extension.ui.asset_search import create_default_asset_search_state

    state = create_default_asset_search_state()

    assert state.status == "idle"
    assert state.query == ""
    assert state.format_filter == "ANY"
    assert state.max_results == 5
    assert state.direct_download_only is True
    assert state.selected_candidate_index == -1
    assert len(state.candidates) == 0
    assert state.persist_to_preferences is False


def test_clear_asset_search_screen_preserves_preferences_but_resets_results() -> None:
    from extension.ui.asset_search import (
        candidate_row_from_asset_candidate,
        clear_asset_search_state,
        create_default_asset_search_state,
    )

    state = create_default_asset_search_state()
    state.query = "male base mesh glb"
    state.status = "results_ready"
    state.error_headline = "Old warning"
    candidates: tuple[AssetCandidateRow, ...] = (
        candidate_row_from_asset_candidate(importable_candidate()),
    )
    state.candidates = candidates
    state.selected_candidate_index = 0

    clear_asset_search_state(state)

    assert state.status == "idle"
    assert state.query == ""
    assert state.error_headline == ""
    assert len(state.candidates) == 0
    assert state.selected_candidate_index == -1
    assert state.format_filter == "ANY"


def test_candidate_row_preserves_source_license_warning_and_inspection_fields() -> None:
    from extension.ui.asset_search import candidate_row_from_asset_candidate

    row = candidate_row_from_asset_candidate(
        importable_candidate(),
        inspection=inspected_link(),
    )

    assert row.title == "Male Base Mesh"
    assert row.source_host == "assets.example.com"
    assert row.format_label == "GLB"
    assert row.status_label == "Ready to import"
    assert row.license_label == "CC0"
    assert row.attribution == "Example Artist"
    assert row.confidence_label == "91%"
    assert row.size_label == "2.0 KB"
    assert row.import_ready is True
    assert row.inspected is True


def test_asset_search_panel_poll_requires_enabled_openai_discovery() -> None:
    from extension.providers.registry import PROVIDER_NVIDIA, PROVIDER_OPENAI
    from extension.ui.asset_search import asset_search_panel_poll

    assert asset_search_panel_poll(
        internet_discovery_enabled=False,
        provider_choice=PROVIDER_OPENAI,
    ) is False
    assert asset_search_panel_poll(
        internet_discovery_enabled=True,
        provider_choice=PROVIDER_NVIDIA,
    ) is False
    assert asset_search_panel_poll(
        internet_discovery_enabled=True,
        provider_choice=PROVIDER_OPENAI,
    ) is True


def test_search_request_view_model_builds_openai_discovery_request() -> None:
    from extension.ui.asset_search import (
        build_asset_search_request_from_state,
        create_default_asset_search_state,
    )

    state = create_default_asset_search_state()
    state.query = "free male base mesh"
    state.format_filter = "GLB"
    state.max_results = 25
    state.direct_download_only = True

    request = build_asset_search_request_from_state(state)

    assert request.query == "free male base mesh"
    assert request.requested_formats == ("glb",)
    assert request.max_results == 10
    assert request.require_direct_download is True


def test_asset_search_operator_ids_are_declared() -> None:
    source = (REPO_ROOT / "extension" / "ui" / "operators.py").read_text()

    for operator_id in (
        "blender_ai.search_assets",
        "blender_ai.cancel_asset_search",
        "blender_ai.clear_asset_search",
        "blender_ai.toggle_asset_candidate",
        "blender_ai.select_asset_candidate",
        "blender_ai.inspect_asset_candidate",
        "blender_ai.open_asset_source",
        "blender_ai.create_asset_import_plan",
        "blender_ai.reject_asset_candidate",
    ):
        assert operator_id in source


def test_asset_search_panel_is_registered_as_assistant_child_panel() -> None:
    source = (REPO_ROOT / "extension" / "ui" / "panels.py").read_text()
    ui_init = (REPO_ROOT / "extension" / "ui" / "__init__.py").read_text()

    assert "AIASSISTANT_PT_asset_search" in source
    assert 'bl_parent_id = "AIASSISTANT_PT_assistant"' in source
    assert "Asset Search" in source
    assert "AIASSISTANT_PT_asset_search" in ui_init or "ASSET_SEARCH_PANEL_CLASSES" in ui_init


def test_asset_search_runtime_ignores_stale_results_after_newer_search() -> None:
    from extension.ui.asset_search_runtime import AssetSearchCoordinator

    coordinator = AssetSearchCoordinator()
    first_generation = coordinator.start_search(lambda _token: ("old-result",))
    second_generation = coordinator.start_search(lambda _token: ("new-result",))

    coordinator.inject_result(first_generation, ("old-result",))
    coordinator.inject_result(second_generation, ("new-result",))

    events = coordinator.poll()

    assert tuple(event.value for event in events) == (("new-result",),)


def test_asset_search_error_reducer_preserves_existing_candidates() -> None:
    from extension.ui.asset_search import (
        apply_asset_search_error,
        candidate_row_from_asset_candidate,
        create_default_asset_search_state,
    )

    state = create_default_asset_search_state()
    state.query = "male base mesh"
    state.candidates = (candidate_row_from_asset_candidate(importable_candidate()),)

    apply_asset_search_error(
        state,
        RuntimeError("OpenAI web search failed"),
        operation="search",
    )

    assert state.status == "search_failed"
    assert state.query == "male base mesh"
    assert len(state.candidates) == 1
    assert state.error_headline == "Asset search failed"
    assert "OpenAI web search failed" in state.error_details


def test_inspection_success_marks_only_the_selected_candidate_ready_to_import() -> None:
    from extension.ui.asset_search import (
        apply_candidate_inspection_result,
        candidate_row_from_asset_candidate,
        create_default_asset_search_state,
    )

    state = create_default_asset_search_state()
    state.candidates = (
        candidate_row_from_asset_candidate(importable_candidate()),
        candidate_row_from_asset_candidate(
            AssetCandidate(
                title="Other Mesh",
                source_page_url="https://assets.example.com/other",
                direct_url="https://cdn.example.com/other.obj",
                asset_format=AssetFormat.OBJ,
            )
        ),
    )
    state.selected_candidate_index = 0

    apply_candidate_inspection_result(state, inspected_link())

    assert state.status == "ready_to_import"
    assert state.candidates[0].import_ready is True
    assert state.candidates[0].final_url == "https://cdn.example.com/base-mesh.glb"
    assert state.candidates[1].import_ready is False


def test_listing_candidate_cannot_create_import_plan() -> None:
    from extension.ui.asset_search import AssetSearchScreenError, build_import_plan_from_selection

    listing_candidate = AssetCandidate(
        title="Listing Only",
        source_page_url="https://assets.example.com/base-mesh",
        direct_url=None,
        asset_format=AssetFormat.UNKNOWN,
        license_label=None,
    )

    with pytest.raises(AssetSearchScreenError, match="direct download URL"):
        build_import_plan_from_selection(
            candidate=listing_candidate,
            inspection=None,
            snapshot_id="d" * 32,
            operation_id="import_listing",
        )


def test_verified_candidate_handoff_creates_high_risk_import_plan() -> None:
    from extension.ui.asset_search import build_import_plan_from_selection

    plan = build_import_plan_from_selection(
        candidate=importable_candidate(),
        inspection=inspected_link(),
        snapshot_id="d" * 32,
        operation_id="import_male_base_mesh",
        name_prefix="MaleBase",
    )

    assert plan.status.value == "ready"
    assert plan.operations[0].type.value == "IMPORT_ASSET"
    assert plan.operations[0].payload["asset_metadata"]["title"] == "Male Base Mesh"

    decision = evaluate_plan_safety(plan, global_undo_available=True)
    assert decision.risk.level is RiskLevel.HIGH
    assert decision.secondary_confirmation_required is True


def test_candidate_screen_test_surface_registry_is_declared() -> None:
    from extension.ui.asset_search_testing import planned_candidate_screen_test_surfaces

    surfaces = planned_candidate_screen_test_surfaces()

    assert "disabled_preference" in surfaces
    assert "mocked_search" in surfaces
    assert "mocked_inspection" in surfaces
    assert "listing_candidate_block" in surfaces
    assert "import_plan_handoff" in surfaces
    assert "panel_registration" in surfaces
