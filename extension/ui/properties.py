"""Blender properties used by the extension UI and workflow state."""

from typing import TYPE_CHECKING, Any

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from ..workflow.state import WorkflowStatus

CONTEXT_SCOPE_ITEMS = (
    ("SELECTION", "Selection", "Selected objects and minimal scene metadata"),
    ("COLLECTION", "Collection", "Active collection and minimal scene metadata"),
    ("SCENE", "Scene", "Budgeted scene summary with detailed active objects"),
)

WORKFLOW_STATUS_ITEMS = tuple(
    (status.value, status.value.replace("_", " ").title(), "") for status in WorkflowStatus
)

RISK_LEVEL_ITEMS = (
    ("low", "Low", "Low local risk"),
    ("medium", "Medium", "Medium local risk"),
    ("high", "High", "High local risk"),
)

HISTORY_STATUS_ITEMS = (
    ("completed", "Completed", "All required operations completed"),
    ("partial", "Partial", "Only part of the plan completed"),
    ("rejected", "Rejected", "The plan was rejected"),
    ("failed", "Failed", "The request failed"),
    ("canceled", "Canceled", "The request was canceled"),
)


class AIASSISTANT_PG_TextItem(PropertyGroup):
    if TYPE_CHECKING:
        value: str
    else:
        value: StringProperty(name="Value")


class AIASSISTANT_PG_OperationPreview(PropertyGroup):
    if TYPE_CHECKING:
        operation_id: str
        label: str
        detail: str
        target_count: int
        expanded: bool
    else:
        operation_id: StringProperty(name="Operation ID")
        label: StringProperty(name="Operation")
        detail: StringProperty(name="Details")
        target_count: IntProperty(name="Targets", min=0)
        expanded: BoolProperty(name="Expanded", default=False)


class AIASSISTANT_PG_HistoryEntry(PropertyGroup):
    if TYPE_CHECKING:
        timestamp: str
        summary: str
        status: str
        risk_level: str
        details: str
    else:
        timestamp: StringProperty(name="Timestamp")
        summary: StringProperty(name="Summary")
        status: EnumProperty(name="Status", items=HISTORY_STATUS_ITEMS, default="completed")
        risk_level: EnumProperty(name="Risk", items=RISK_LEVEL_ITEMS, default="low")
        details: StringProperty(name="Details")


class AIASSISTANT_PG_State(PropertyGroup):
    if TYPE_CHECKING:
        workflow_status: str
        status_message: str
        draft_prompt: str
        submitted_prompt: str
        clarification_response: str
        context_scope: str
        context_summary: str
        context_included_count: int
        context_omitted_count: int
        context_serialized_size: int
        show_context_details: bool
        provider_model: str
        provider_call_count: int
        input_tokens: int
        cached_input_tokens: int
        output_tokens: int
        reasoning_tokens: int
        total_tokens: int
        has_plan: bool
        plan_summary: str
        risk_level: str
        risk_reason: str
        operation_count: int
        target_count: int
        progress_current: int
        progress_total: int
        error_headline: str
        error_details: str
        result_summary: str
        show_result_details: bool
        changed_count: int
        undo_available: bool
        assumptions: Any
        questions: Any
        operation_previews: Any
        result_details: Any
        history: Any
    else:
        workflow_status: EnumProperty(
            name="Workflow Status",
            items=WORKFLOW_STATUS_ITEMS,
            default=WorkflowStatus.IDLE.value,
        )
        status_message: StringProperty(name="Status", default="Ready")
        draft_prompt: StringProperty(name="Request", maxlen=4096)
        submitted_prompt: StringProperty(name="Submitted Request", maxlen=4096)
        clarification_response: StringProperty(name="Response", maxlen=4096)
        context_scope: EnumProperty(
            name="Context Scope",
            items=CONTEXT_SCOPE_ITEMS,
            default="SELECTION",
        )
        context_summary: StringProperty(name="Context", default="No context collected")
        context_included_count: IntProperty(name="Included", min=0)
        context_omitted_count: IntProperty(name="Omitted", min=0)
        context_serialized_size: IntProperty(name="Serialized Size", min=0)
        show_context_details: BoolProperty(name="Show Context Details", default=False)
        provider_model: StringProperty(name="Model", maxlen=128)
        provider_call_count: IntProperty(name="Provider Calls", min=0)
        input_tokens: IntProperty(name="Input Tokens", min=0)
        cached_input_tokens: IntProperty(name="Cached Input Tokens", min=0)
        output_tokens: IntProperty(name="Output Tokens", min=0)
        reasoning_tokens: IntProperty(name="Reasoning Tokens", min=0)
        total_tokens: IntProperty(name="Total Tokens", min=0)
        has_plan: BoolProperty(name="Has Plan", default=False)
        plan_summary: StringProperty(name="Plan Summary", maxlen=4096)
        risk_level: EnumProperty(name="Risk", items=RISK_LEVEL_ITEMS, default="low")
        risk_reason: StringProperty(name="Risk Reason", maxlen=1024)
        operation_count: IntProperty(name="Operations", min=0)
        target_count: IntProperty(name="Targets", min=0)
        progress_current: IntProperty(name="Current Operation", min=0)
        progress_total: IntProperty(name="Total Operations", min=0)
        error_headline: StringProperty(name="Error", maxlen=256)
        error_details: StringProperty(name="Error Details", maxlen=4096)
        result_summary: StringProperty(name="Result", maxlen=4096)
        show_result_details: BoolProperty(name="Show Changed Data", default=False)
        changed_count: IntProperty(name="Changed Data", min=0)
        undo_available: BoolProperty(name="Undo Available", default=False)
        assumptions: CollectionProperty(type=AIASSISTANT_PG_TextItem)
        questions: CollectionProperty(type=AIASSISTANT_PG_TextItem)
        operation_previews: CollectionProperty(type=AIASSISTANT_PG_OperationPreview)
        result_details: CollectionProperty(type=AIASSISTANT_PG_TextItem)
        history: CollectionProperty(type=AIASSISTANT_PG_HistoryEntry)


def clear_plan(state: AIASSISTANT_PG_State) -> None:
    state.has_plan = False
    state.plan_summary = ""
    state.risk_level = "low"
    state.risk_reason = ""
    state.operation_count = 0
    state.target_count = 0
    state.assumptions.clear()
    state.questions.clear()
    state.operation_previews.clear()


def clear_provider_usage(state: AIASSISTANT_PG_State) -> None:
    state.provider_model = ""
    state.provider_call_count = 0
    state.input_tokens = 0
    state.cached_input_tokens = 0
    state.output_tokens = 0
    state.reasoning_tokens = 0
    state.total_tokens = 0


def reset_request(state: AIASSISTANT_PG_State) -> None:
    clear_plan(state)
    clear_provider_usage(state)
    state.workflow_status = WorkflowStatus.IDLE.value
    state.status_message = "Ready"
    state.submitted_prompt = ""
    state.clarification_response = ""
    state.progress_current = 0
    state.progress_total = 0
    state.error_headline = ""
    state.error_details = ""
    state.result_summary = ""
    state.show_result_details = False
    state.result_details.clear()
    state.changed_count = 0
    state.undo_available = False


def add_history_entry(
    state: AIASSISTANT_PG_State,
    *,
    timestamp: str,
    summary: str,
    status: str,
    risk_level: str = "low",
    details: str = "",
) -> None:
    while len(state.history) >= 20:
        state.history.remove(0)

    entry = state.history.add()
    entry.timestamp = timestamp
    entry.summary = summary
    entry.status = status
    entry.risk_level = risk_level
    entry.details = details


CLASSES = (
    AIASSISTANT_PG_TextItem,
    AIASSISTANT_PG_OperationPreview,
    AIASSISTANT_PG_HistoryEntry,
    AIASSISTANT_PG_State,
)
