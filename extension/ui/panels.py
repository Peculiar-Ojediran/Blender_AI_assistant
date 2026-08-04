"""Blender sidebar panels for requests, plans, context, results, and history."""

from textwrap import wrap
from typing import Any, Literal

from bpy.types import Panel

from ..providers.openai import CUSTOM_MODEL_OPTION
from ..providers.registry import PROVIDER_NVIDIA, provider_label
from ..workflow.state import BUSY_STATUSES, PROMPT_EDITABLE_STATUSES, WorkflowStatus
from .asset_search import AssetSearchStatus, asset_search_panel_poll
from .preferences import get_preferences, resolve_api_key, resolve_provider_choice
from .properties import AIASSISTANT_PG_State

STATUS_PRESENTATION: dict[WorkflowStatus, tuple[Any, str]] = {
    WorkflowStatus.CONFIGURATION_REQUIRED: ("ERROR", "Provider setup required"),
    WorkflowStatus.IDLE: ("CHECKMARK", "Ready"),
    WorkflowStatus.COLLECTING_CONTEXT: ("TIME", "Reading scene"),
    WorkflowStatus.PLANNING: ("TIME", "Planning changes"),
    WorkflowStatus.VALIDATING: ("TIME", "Validating plan"),
    WorkflowStatus.NEEDS_CLARIFICATION: ("QUESTION", "More information needed"),
    WorkflowStatus.AWAITING_APPROVAL: ("INFO", "Review plan"),
    WorkflowStatus.EXECUTING: ("TIME", "Applying changes"),
    WorkflowStatus.COMPLETE: ("CHECKMARK", "Changes applied"),
    WorkflowStatus.ERROR: ("ERROR", "Request failed"),
    WorkflowStatus.CANCELED: ("CANCEL", "Request canceled"),
}

RISK_PRESENTATION: dict[str, tuple[Any, str]] = {
    "low": ("INFO", "Low risk"),
    "medium": ("ERROR", "Medium risk"),
    "high": ("CANCEL", "High risk"),
}

HISTORY_ICONS: dict[str, Any] = {
    "completed": "CHECKMARK",
    "partial": "ERROR",
    "rejected": "X",
    "failed": "CANCEL",
    "canceled": "CANCEL",
}

ASSET_SEARCH_STATUS_PRESENTATION: dict[str, tuple[Any, str]] = {
    AssetSearchStatus.IDLE.value: ("URL", "Ready"),
    AssetSearchStatus.SEARCHING.value: ("TIME", "Searching"),
    AssetSearchStatus.SEARCH_FAILED.value: ("ERROR", "Search failed"),
    AssetSearchStatus.RESULTS_READY.value: ("VIEWZOOM", "Results ready"),
    AssetSearchStatus.INSPECTING.value: ("TIME", "Inspecting"),
    AssetSearchStatus.INSPECTION_FAILED.value: ("ERROR", "Inspection failed"),
    AssetSearchStatus.READY_TO_IMPORT.value: ("CHECKMARK", "Ready to import"),
    AssetSearchStatus.HANDOFF_CREATED.value: ("CHECKMARK", "Import plan created"),
}


def _state(context: Any) -> AIASSISTANT_PG_State:
    return context.window_manager.blender_ai_state


def _draw_wrapped(layout: Any, text: str, *, width: int = 42, icon: Any = "NONE") -> None:
    lines = wrap(text, width=width) or [""]
    for index, line in enumerate(lines):
        layout.label(text=line, icon=icon if index == 0 else "NONE")


def _compact(text: str, limit: int = 48) -> str:
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _draw_provider_usage(layout: Any, state: AIASSISTANT_PG_State) -> None:
    layout.label(text="AI Usage", icon="INFO")
    if state.provider_model:
        layout.label(text=f"Model: {state.provider_model}")
    if state.total_tokens:
        layout.label(
            text=(
                f"Tokens: {state.total_tokens:,} total "
                f"({state.input_tokens:,} in, {state.output_tokens:,} out)"
            )
        )
        if state.cached_input_tokens:
            layout.label(text=f"Cached input: {state.cached_input_tokens:,}")
        if state.reasoning_tokens:
            layout.label(text=f"Reasoning output: {state.reasoning_tokens:,}")
    else:
        layout.label(text="Token usage unavailable")
    if state.provider_call_count > 1:
        layout.label(text=f"Provider calls: {state.provider_call_count}")


class AIASSISTANT_PT_Base(Panel):
    bl_space_type: Literal["VIEW_3D"] = "VIEW_3D"
    bl_region_type: Literal["UI"] = "UI"
    bl_category: str = "AI Assistant"


class AIASSISTANT_PT_Assistant(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_assistant"
    bl_label = "Assistant"

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        state = _state(context)
        status = WorkflowStatus(state.workflow_status)
        has_api_key = bool(resolve_api_key(context))

        if not has_api_key and status is WorkflowStatus.IDLE:
            icon, label = STATUS_PRESENTATION[WorkflowStatus.CONFIGURATION_REQUIRED]
        else:
            icon, label = STATUS_PRESENTATION[status]

        status_row = layout.row(align=True)
        status_row.label(text=state.status_message or label, icon=icon)
        if not has_api_key:
            status_row.operator("blender_ai.open_preferences", text="", icon="PREFERENCES")

        layout.separator()
        layout.label(text="Request")
        preferences = get_preferences(context)
        if preferences is not None:
            model_column = layout.column(align=True)
            model_column.enabled = status not in BUSY_STATUSES and not state.has_plan
            model_column.prop(preferences, "provider_choice", text="Provider")
            if preferences.provider_choice == PROVIDER_NVIDIA:
                model_column.prop(preferences, "nvidia_model_choice", text="Model")
                if preferences.nvidia_model_choice == CUSTOM_MODEL_OPTION:
                    model_column.prop(
                        preferences,
                        "custom_nvidia_model",
                        text="Custom Model",
                    )
            else:
                model_column.prop(preferences, "model_choice", text="Model")
                if preferences.model_choice == CUSTOM_MODEL_OPTION:
                    model_column.prop(preferences, "custom_model", text="Custom Model")
        prompt_column = layout.column(align=True)
        prompt_column.enabled = status in PROMPT_EDITABLE_STATUSES and not state.has_plan
        prompt_column.prop(state, "draft_prompt", text="")
        action_row = prompt_column.row(align=True)
        action_row.operator("blender_ai.plan_changes", icon="PLAY")
        action_row.operator("blender_ai.clear_prompt", text="", icon="X")

        if preferences is not None and not bool(preferences.internet_discovery_enabled):
            layout.separator()
            disabled_row = layout.row(align=True)
            disabled_row.label(text="Internet discovery disabled", icon="URL")
            disabled_row.operator("blender_ai.open_preferences", text="", icon="PREFERENCES")
        elif preferences is not None and preferences.provider_choice == PROVIDER_NVIDIA:
            layout.separator()
            layout.label(
                text=f"Asset search unavailable for {provider_label(PROVIDER_NVIDIA)}",
                icon="URL",
            )

        if status in BUSY_STATUSES:
            progress = layout.column(align=True)
            if state.progress_total:
                progress.label(
                    text=f"Operation {state.progress_current} of {state.progress_total}",
                    icon="TIME",
                )
            progress.operator("blender_ai.cancel_request", icon="CANCEL")

        if status is WorkflowStatus.NEEDS_CLARIFICATION:
            self._draw_clarification(layout, state)
        elif status is WorkflowStatus.ERROR:
            self._draw_error(layout, state, has_api_key)
        elif status is WorkflowStatus.COMPLETE:
            self._draw_result(layout, state)
        elif status is WorkflowStatus.CANCELED:
            layout.operator("blender_ai.new_request", icon="FILE_NEW")

        if state.provider_call_count:
            layout.separator()
            _draw_provider_usage(layout, state)

    @staticmethod
    def _draw_clarification(layout: Any, state: AIASSISTANT_PG_State) -> None:
        layout.separator()
        layout.label(text="Clarification", icon="QUESTION")
        for question in state.questions:
            _draw_wrapped(layout, question.value)
        layout.prop(state, "clarification_response", text="Response")
        row = layout.row(align=True)
        row.operator("blender_ai.continue_planning", icon="PLAY")
        row.operator("blender_ai.reject_plan", icon="X")

    @staticmethod
    def _draw_error(layout: Any, state: AIASSISTANT_PG_State, has_api_key: bool) -> None:
        layout.separator()
        _draw_wrapped(layout, state.error_headline or "Request failed", icon="ERROR")
        if state.error_details:
            _draw_wrapped(layout, state.error_details)
        row = layout.row(align=True)
        row.operator("blender_ai.dismiss_error", icon="GREASEPENCIL")
        if not has_api_key:
            row.operator("blender_ai.open_preferences", icon="PREFERENCES")

    @staticmethod
    def _draw_result(layout: Any, state: AIASSISTANT_PG_State) -> None:
        layout.separator()
        _draw_wrapped(layout, state.result_summary or "Changes applied", icon="CHECKMARK")
        layout.label(text=f"Changed data: {state.changed_count}")
        if state.result_details:
            disclosure = layout.row(align=True)
            disclosure.prop(
                state,
                "show_result_details",
                text="",
                icon="TRIA_DOWN" if state.show_result_details else "TRIA_RIGHT",
                emboss=False,
            )
            disclosure.label(text=f"Changes ({len(state.result_details)})")
            if state.show_result_details:
                for detail in state.result_details:
                    _draw_wrapped(layout, detail.value)
        if state.undo_available:
            layout.label(text="Available through Blender Undo", icon="LOOP_BACK")
        layout.operator("blender_ai.new_request", icon="FILE_NEW")


class AIASSISTANT_PT_Context(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_context"
    bl_parent_id = "AIASSISTANT_PT_assistant"
    bl_label = "Context"

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        state = _state(context)
        status = WorkflowStatus(state.workflow_status)

        scope = layout.row()
        scope.enabled = status not in BUSY_STATUSES and not state.has_plan
        scope.prop(state, "context_scope", expand=True)
        layout.label(text=state.context_summary, icon="OUTLINER_COLLECTION")

        details_icon: Any = "TRIA_DOWN" if state.show_context_details else "TRIA_RIGHT"
        layout.operator(
            "blender_ai.toggle_context_details",
            text="Hide Context" if state.show_context_details else "Preview Context",
            icon=details_icon,
        )

        if state.show_context_details:
            details = layout.column(align=True)
            details.label(text=f"Included: {state.context_included_count}")
            details.label(text=f"Omitted: {state.context_omitted_count}")
            details.label(text=f"Serialized size: {state.context_serialized_size} characters")


class AIASSISTANT_PT_Plan(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_plan"
    bl_parent_id = "AIASSISTANT_PT_assistant"
    bl_label = "Plan"

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _state(context).has_plan

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        state = _state(context)

        _draw_wrapped(layout, state.plan_summary or "Validated plan")
        risk_icon, risk_label = RISK_PRESENTATION[state.risk_level]
        layout.label(
            text=f"{risk_label} - {state.target_count} affected objects",
            icon=risk_icon,
        )
        if state.risk_reason:
            _draw_wrapped(layout, state.risk_reason)
        layout.label(text=f"Operations: {state.operation_count}")

        for index, operation in enumerate(state.operation_previews, start=1):
            row = layout.row(align=True)
            row.prop(
                operation,
                "expanded",
                text="",
                icon="TRIA_DOWN" if operation.expanded else "TRIA_RIGHT",
                emboss=False,
            )
            target_text = f" - {operation.target_count} targets" if operation.target_count else ""
            row.label(text=_compact(f"{index}. {operation.label}{target_text}"))
            if operation.expanded and operation.detail:
                _draw_wrapped(layout, operation.detail)

        if state.assumptions:
            layout.label(text="Assumptions", icon="INFO")
            for assumption in state.assumptions:
                _draw_wrapped(layout, assumption.value)

        actions = layout.row(align=True)
        actions.operator("blender_ai.apply_plan", icon="CHECKMARK")
        actions.operator("blender_ai.rephrase_plan", icon="GREASEPENCIL")
        actions.operator("blender_ai.reject_plan", text="", icon="X")


class AIASSISTANT_PT_asset_search(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_asset_search"
    bl_parent_id = "AIASSISTANT_PT_assistant"
    bl_label = "Asset Search"
    bl_options: set[Any] = {"DEFAULT_CLOSED"}  # noqa: RUF012

    @classmethod
    def poll(cls, context: Any) -> bool:
        preferences = get_preferences(context)
        if preferences is None:
            return False
        return asset_search_panel_poll(
            internet_discovery_enabled=bool(preferences.internet_discovery_enabled),
            provider_choice=resolve_provider_choice(preferences),
        )

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        state = _state(context)
        status_icon, status_label = ASSET_SEARCH_STATUS_PRESENTATION.get(
            state.asset_search_status,
            ("INFO", state.asset_search_status.replace("_", " ").title()),
        )

        status_row = layout.row(align=True)
        status_row.label(text=status_label, icon=status_icon)

        search_box = layout.column(align=True)
        search_box.enabled = state.asset_search_status not in {
            AssetSearchStatus.SEARCHING.value,
            AssetSearchStatus.INSPECTING.value,
        }
        search_box.prop(state, "asset_search_query", text="")
        search_box.prop(state, "asset_search_format", text="Format")
        search_box.prop(state, "asset_search_max_results")
        search_box.prop(state, "asset_search_direct_only")
        action_row = search_box.row(align=True)
        action_row.operator("blender_ai.search_assets", icon="VIEWZOOM")
        action_row.operator("blender_ai.clear_asset_search", icon="X")

        if state.asset_search_status in {
            AssetSearchStatus.SEARCHING.value,
            AssetSearchStatus.INSPECTING.value,
        }:
            layout.operator("blender_ai.cancel_asset_search", icon="CANCEL")

        if state.asset_search_error_headline:
            layout.separator()
            _draw_wrapped(layout, state.asset_search_error_headline, icon="ERROR")
            if state.asset_search_error_details:
                _draw_wrapped(layout, state.asset_search_error_details)

        if len(state.asset_candidates):
            layout.separator()
            layout.label(text="Candidates", icon="OUTLINER_OB_MESH")
            for index, candidate in enumerate(state.asset_candidates):
                self._draw_candidate(layout, candidate, index)

        selected = state.selected_asset_candidate_index
        if 0 <= selected < len(state.asset_candidates):
            layout.separator()
            self._draw_selected_candidate(layout, state.asset_candidates[selected])

    @staticmethod
    def _draw_candidate(layout: Any, candidate: Any, index: int) -> None:
        if candidate.rejected:
            return
        row = layout.row(align=True)
        toggle = row.operator(
            "blender_ai.toggle_asset_candidate",
            text="",
            icon="TRIA_DOWN" if candidate.expanded else "TRIA_RIGHT",
            emboss=False,
        )
        toggle.candidate_index = index
        label = _compact(
            f"{candidate.title} - {candidate.format_label} - {candidate.status_label}",
            52,
        )
        row.label(text=label, icon="CHECKMARK" if candidate.import_ready else "NONE")

        if not candidate.expanded:
            return

        details = layout.column(align=True)
        details.label(text=f"Source: {candidate.source_host}")
        details.label(text=f"License: {candidate.license_label}")
        details.label(text=f"Confidence: {candidate.confidence_label}")
        if candidate.size_label:
            details.label(text=f"Size: {candidate.size_label}")
        if candidate.warnings_text:
            _draw_wrapped(details, candidate.warnings_text, icon="ERROR")

        actions = layout.row(align=True)
        select = actions.operator("blender_ai.select_asset_candidate", icon="RESTRICT_SELECT_OFF")
        select.candidate_index = index
        inspect = actions.operator("blender_ai.inspect_asset_candidate", icon="CHECKMARK")
        inspect.candidate_index = index
        source = actions.operator("blender_ai.open_asset_source", icon="URL")
        source.candidate_index = index

    @staticmethod
    def _draw_selected_candidate(layout: Any, candidate: Any) -> None:
        layout.label(text="Selected Candidate", icon="RESTRICT_SELECT_OFF")
        _draw_wrapped(layout, f"Title: {candidate.title}")
        if candidate.final_url:
            _draw_wrapped(layout, f"Final URL: {candidate.final_url}")
        elif candidate.direct_url:
            _draw_wrapped(layout, f"Direct URL: {candidate.direct_url}")
        if candidate.size_label:
            layout.label(text=f"Size: {candidate.size_label}")
        layout.label(text=f"License: {candidate.license_label}")
        if candidate.attribution:
            _draw_wrapped(layout, f"Attribution: {candidate.attribution}")

        actions = layout.row(align=True)
        import_action = actions.row(align=True)
        import_action.enabled = bool(candidate.import_ready)
        import_action.operator("blender_ai.create_asset_import_plan", icon="IMPORT")
        actions.operator("blender_ai.reject_asset_candidate", icon="X")


class AIASSISTANT_PT_Limits(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_limits"
    bl_parent_id = "AIASSISTANT_PT_assistant"
    bl_label = "Plan Limits"
    bl_options: set[Any] = {"DEFAULT_CLOSED"}  # noqa: RUF012

    @classmethod
    def poll(cls, context: Any) -> bool:
        return get_preferences(context) is not None

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        state = _state(context)
        preferences = get_preferences(context)
        if preferences is None:
            return

        limits = layout.column(align=True)
        limits.enabled = (
            WorkflowStatus(state.workflow_status) not in BUSY_STATUSES
            and not state.has_plan
        )
        limits.prop(preferences, "max_plan_operations")
        limits.prop(preferences, "max_operation_targets")
        limits.prop(preferences, "max_duplicate_objects")


class AIASSISTANT_PT_History(AIASSISTANT_PT_Base):
    bl_idname = "AIASSISTANT_PT_history"
    bl_parent_id = "AIASSISTANT_PT_assistant"
    bl_label = "History"
    bl_options: set[Any] = {"DEFAULT_CLOSED"}  # noqa: RUF012

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(_state(context).history)

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None
        history = _state(context).history
        for index in range(len(history) - 1, max(-1, len(history) - 6), -1):
            entry = history[index]
            row = layout.row(align=True)
            row.label(text=entry.timestamp)
            row.label(
                text=_compact(entry.summary, 34),
                icon=HISTORY_ICONS.get(entry.status, "INFO"),
            )


CLASSES = (
    AIASSISTANT_PT_Assistant,
    AIASSISTANT_PT_Context,
    AIASSISTANT_PT_Plan,
    AIASSISTANT_PT_asset_search,
    AIASSISTANT_PT_Limits,
    AIASSISTANT_PT_History,
)
