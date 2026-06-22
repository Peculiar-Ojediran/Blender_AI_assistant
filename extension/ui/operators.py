"""Blender commands for the assistant UX."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from ..context import (
    ContextOptions,
    ContextScope,
    SceneContextSnapshot,
    SerializedSceneContext,
    read_scene_context,
    serialize_scene_context,
)
from ..operations import (
    ExecutionPreflightError,
    ExecutionResult,
    PlanExecutionError,
    execute_plan,
    preflight_plan,
)
from ..operations.undo import create_recovery_point, global_undo_enabled
from ..providers.openai import DEFAULT_REASONING_EFFORT
from ..safety import (
    SafetyConfirmationRequired,
    SafetyPolicyError,
    authorize_plan_execution,
    evaluate_plan_safety,
)
from ..workflow import PlanningConversation
from ..workflow.state import BUSY_STATUSES, WorkflowStatus
from .planning import (
    cancel_planning_job,
    clear_planning_result,
    pending_planning_result,
    start_planning_job,
)
from .preferences import (
    get_preferences,
    resolve_api_key,
    resolve_operation_limits,
    resolve_selected_model,
)
from .properties import (
    AIASSISTANT_PG_State,
    add_history_entry,
    clear_plan,
    clear_provider_usage,
    reset_request,
)

type OperatorResult = set[
    Literal["RUNNING_MODAL", "CANCELLED", "FINISHED", "PASS_THROUGH", "INTERFACE"]
]

def _state(context: Any) -> AIASSISTANT_PG_State:
    return context.window_manager.blender_ai_state


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


def _request_summary(state: AIASSISTANT_PG_State) -> str:
    text = (state.submitted_prompt or state.draft_prompt).strip()
    return text if len(text) <= 80 else f"{text[:77]}..."


def _context_options(context: Any, state: AIASSISTANT_PG_State) -> ContextOptions:
    preferences = get_preferences(context)
    detailed_budget = preferences.context_object_budget if preferences is not None else 25
    return ContextOptions(
        scope=ContextScope(state.context_scope.lower()),
        detailed_object_budget=detailed_budget,
        summary_object_budget=max(
            200,
            detailed_budget,
            preferences.max_operation_targets if preferences is not None else 0,
        ),
        include_custom_properties=(
            preferences.include_custom_properties if preferences is not None else False
        ),
        include_file_paths=(
            preferences.include_file_paths if preferences is not None else False
        ),
        include_viewport_image=(
            preferences.include_viewport_image if preferences is not None else False
        ),
        max_serialized_characters=(
            preferences.context_character_budget if preferences is not None else 100_000
        ),
    )


def _collect_context(
    context: Any,
    state: AIASSISTANT_PG_State,
) -> tuple[SceneContextSnapshot, SerializedSceneContext]:
    snapshot = read_scene_context(context, _context_options(context, state))
    serialized = serialize_scene_context(snapshot)
    scene_context = snapshot.context
    state.context_summary = (
        f"{scene_context.scoped_object_count} scoped, "
        f"{len(scene_context.detailed_objects)} detailed"
    )
    state.context_included_count = len(snapshot.target_index)
    state.context_omitted_count = scene_context.omissions.total
    state.context_serialized_size = serialized.character_count
    return snapshot, serialized


def _start_planning(
    context: Any,
    state: AIASSISTANT_PG_State,
    *,
    prompt: str,
    submitted_prompt: str,
    conversation: PlanningConversation | None = None,
) -> None:
    if conversation is None:
        clear_provider_usage(state)
    snapshot, _ = _collect_context(context, state)
    preferences = get_preferences(context)
    model = resolve_selected_model(preferences)
    reasoning_effort = (
        preferences.reasoning_effort
        if preferences is not None
        else DEFAULT_REASONING_EFFORT
    )
    timeout = preferences.request_timeout if preferences is not None else 60.0
    max_output_tokens = preferences.max_output_tokens if preferences is not None else 4_096
    limits = resolve_operation_limits(preferences)
    start_planning_job(
        prompt=prompt,
        snapshot=snapshot,
        api_key=resolve_api_key(context),
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout,
        max_output_tokens=max_output_tokens,
        conversation=conversation,
        limits=limits,
    )
    clear_plan(state)
    state.clarification_response = ""
    state.submitted_prompt = submitted_prompt
    state.workflow_status = WorkflowStatus.PLANNING.value
    state.status_message = "Planning changes"
    state.error_headline = ""
    state.error_details = ""


def _set_context_error(state: AIASSISTANT_PG_State, error: Exception) -> None:
    state.workflow_status = WorkflowStatus.ERROR.value
    state.status_message = "Context collection failed"
    state.error_headline = "Could not read the Blender scene"
    state.error_details = str(error)


def _set_planning_start_error(state: AIASSISTANT_PG_State, error: Exception) -> None:
    clear_plan(state)
    state.workflow_status = WorkflowStatus.ERROR.value
    state.status_message = "Planning failed"
    state.error_headline = "Could not start planning"
    state.error_details = str(error) or type(error).__name__


def _execution_details(result: ExecutionResult) -> str:
    details = [
        f"{change.change.value.title()} {change.datablock_kind} {change.name}: "
        f"{change.detail}"
        for change in result.changes
    ]
    return " | ".join(details)[:4096]


def _populate_result_details(
    state: AIASSISTANT_PG_State,
    result: ExecutionResult,
) -> None:
    state.show_result_details = False
    state.result_details.clear()
    for change in result.changes:
        item = state.result_details.add()
        item.value = (
            f"{change.change.value.title()} {change.datablock_kind} {change.name}: "
            f"{change.detail}"
        )


def _show_safety_block(state: AIASSISTANT_PG_State, error: SafetyPolicyError) -> None:
    state.workflow_status = WorkflowStatus.ERROR.value
    state.status_message = "Execution blocked"
    state.error_headline = "Local safety policy blocked this plan"
    state.error_details = str(error)[:4096]


class AIASSISTANT_OT_open_preferences(Operator):
    bl_idname = "blender_ai.open_preferences"
    bl_label = "Open Settings"
    bl_description = "Open Blender preferences for the AI Assistant"

    def execute(self, context: Any) -> OperatorResult:
        context.preferences.active_section = "ADDONS"
        bpy.ops.screen.userpref_show()
        return {"FINISHED"}


class AIASSISTANT_OT_clear_session_key(Operator):
    bl_idname = "blender_ai.clear_session_key"
    bl_label = "Clear Session Key"
    bl_description = "Clear the non-persistent OpenAI session key"

    def execute(self, context: Any) -> OperatorResult:
        preferences = get_preferences(context)
        if preferences is not None:
            preferences.session_api_key = ""
        return {"FINISHED"}


class AIASSISTANT_OT_clear_prompt(Operator):
    bl_idname = "blender_ai.clear_prompt"
    bl_label = "Clear Request"
    bl_description = "Clear the request draft"

    def execute(self, context: Any) -> OperatorResult:
        _state(context).draft_prompt = ""
        return {"FINISHED"}


class AIASSISTANT_OT_toggle_context_details(Operator):
    bl_idname = "blender_ai.toggle_context_details"
    bl_label = "Preview Context"
    bl_description = "Show or hide the current context summary"

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        state.show_context_details = not state.show_context_details
        if state.show_context_details:
            try:
                _collect_context(context, state)
            except Exception as error:
                _set_context_error(state, error)
                self.report({"ERROR"}, state.error_headline)
                return {"CANCELLED"}
        return {"FINISHED"}


class AIASSISTANT_OT_plan_changes(Operator):
    bl_idname = "blender_ai.plan_changes"
    bl_label = "Plan Changes"
    bl_description = "Prepare a validated plan without changing the scene"

    @classmethod
    def poll(cls, context: Any) -> bool:
        state = _state(context)
        status = WorkflowStatus(state.workflow_status)
        return not state.has_plan and status in {
            WorkflowStatus.CONFIGURATION_REQUIRED,
            WorkflowStatus.IDLE,
            WorkflowStatus.COMPLETE,
            WorkflowStatus.ERROR,
            WorkflowStatus.CANCELED,
        }

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        prompt = state.draft_prompt.strip()
        if not prompt:
            self.report({"WARNING"}, "Enter a request before planning changes.")
            return {"CANCELLED"}

        if not resolve_api_key(context):
            state.workflow_status = WorkflowStatus.CONFIGURATION_REQUIRED.value
            state.status_message = "OpenAI setup required"
            self.report({"WARNING"}, "Configure an OpenAI API key before planning changes.")
            return {"CANCELLED"}

        state.workflow_status = WorkflowStatus.COLLECTING_CONTEXT.value
        state.status_message = "Reading scene"
        try:
            _start_planning(
                context,
                state,
                prompt=prompt,
                submitted_prompt=prompt,
            )
        except Exception as error:
            _set_planning_start_error(state, error)
            self.report({"ERROR"}, state.error_headline)
            return {"CANCELLED"}
        return {"FINISHED"}


class AIASSISTANT_OT_continue_planning(Operator):
    bl_idname = "blender_ai.continue_planning"
    bl_label = "Continue Planning"
    bl_description = "Continue planning with the clarification response"

    @classmethod
    def poll(cls, context: Any) -> bool:
        state = _state(context)
        return state.workflow_status == WorkflowStatus.NEEDS_CLARIFICATION.value

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        if not state.clarification_response.strip():
            self.report({"WARNING"}, "Answer the clarification question before continuing.")
            return {"CANCELLED"}
        if not resolve_api_key(context):
            state.workflow_status = WorkflowStatus.CONFIGURATION_REQUIRED.value
            state.status_message = "OpenAI setup required"
            self.report({"WARNING"}, "Configure an OpenAI API key before continuing.")
            return {"CANCELLED"}

        pending_result = pending_planning_result()
        if pending_result is None:
            self.report({"ERROR"}, "The clarification session is no longer available.")
            return {"CANCELLED"}
        conversation = pending_result.conversation.with_clarification(
            tuple(item.value for item in state.questions),
            state.clarification_response.strip(),
        )
        state.workflow_status = WorkflowStatus.COLLECTING_CONTEXT.value
        state.status_message = "Reading scene"
        try:
            _start_planning(
                context,
                state,
                prompt=state.submitted_prompt,
                submitted_prompt=state.submitted_prompt,
                conversation=conversation,
            )
        except Exception as error:
            _set_planning_start_error(state, error)
            self.report({"ERROR"}, state.error_headline)
            return {"CANCELLED"}
        return {"FINISHED"}


class AIASSISTANT_OT_cancel_request(Operator):
    bl_idname = "blender_ai.cancel_request"
    bl_label = "Cancel Request"
    bl_description = "Cancel pending work or remaining safe operation boundaries"

    @classmethod
    def poll(cls, context: Any) -> bool:
        status = WorkflowStatus(_state(context).workflow_status)
        return status in BUSY_STATUSES

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        cancel_planning_job()
        state.workflow_status = WorkflowStatus.CANCELED.value
        state.status_message = "Request canceled"
        add_history_entry(
            state,
            timestamp=_timestamp(),
            summary=_request_summary(state),
            status="canceled",
            risk_level=state.risk_level,
        )
        return {"FINISHED"}


class AIASSISTANT_OT_reject_plan(Operator):
    bl_idname = "blender_ai.reject_plan"
    bl_label = "Reject"
    bl_description = "Reject the current plan without changing the scene"

    @classmethod
    def poll(cls, context: Any) -> bool:
        state = _state(context)
        return state.has_plan or state.workflow_status == WorkflowStatus.NEEDS_CLARIFICATION.value

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        clear_planning_result()
        add_history_entry(
            state,
            timestamp=_timestamp(),
            summary=_request_summary(state),
            status="rejected",
            risk_level=state.risk_level,
        )
        clear_plan(state)
        state.workflow_status = WorkflowStatus.IDLE.value
        state.status_message = "Ready"
        return {"FINISHED"}


class AIASSISTANT_OT_rephrase_plan(Operator):
    bl_idname = "blender_ai.rephrase_plan"
    bl_label = "Rephrase"
    bl_description = "Return the current request to the editor and invalidate the plan"

    @classmethod
    def poll(cls, context: Any) -> bool:
        return _state(context).has_plan

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        clear_planning_result()
        state.draft_prompt = state.submitted_prompt
        clear_plan(state)
        state.workflow_status = WorkflowStatus.IDLE.value
        state.status_message = "Ready to rephrase"
        return {"FINISHED"}


class AIASSISTANT_OT_apply_plan(Operator):
    bl_idname = "blender_ai.apply_plan"
    bl_label = "Apply Plan"
    bl_description = "Apply the current immutable validated plan"
    bl_options: set[Any] = {"REGISTER", "UNDO"}  # noqa: RUF012

    if TYPE_CHECKING:
        secondary_confirmation: bool
    else:
        secondary_confirmation: BoolProperty(
            name="High-Risk Confirmation",
            default=False,
            options={"HIDDEN", "SKIP_SAVE"},
        )

    @classmethod
    def poll(cls, context: Any) -> bool:
        state = _state(context)
        return (
            state.has_plan
            and state.workflow_status == WorkflowStatus.AWAITING_APPROVAL.value
            and pending_planning_result() is not None
            and context.mode == "OBJECT"
        )

    def invoke(self, context: Any, event: Any) -> OperatorResult:
        pending = pending_planning_result()
        if pending is None:
            return {"CANCELLED"}
        decision = evaluate_plan_safety(
            pending.plan,
            global_undo_available=global_undo_enabled(context),
        )
        if decision.blocked:
            error = SafetyPolicyError(" ".join(decision.reasons))
            _show_safety_block(_state(context), error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if decision.secondary_confirmation_required:
            self.secondary_confirmation = True
            message = (
                f"This plan affects {decision.risk.affected_object_count} object(s). "
                + " ".join(decision.reasons)
            )
            window_manager: Any = context.window_manager
            return window_manager.invoke_confirm(
                self,
                event,
                title="Confirm High-Risk Plan",
                message=message[:512],
                confirm_text="Apply High-Risk Plan",
                icon="ERROR",
            )
        return self.execute(context)

    def draw(self, context: Any) -> None:
        state = _state(context)
        layout = self.layout
        assert layout is not None
        column = layout.column(align=True)
        column.label(text="Confirm high-risk plan", icon="ERROR")
        column.label(text=f"Affected objects: {state.target_count}")
        if state.risk_reason:
            column.label(text=state.risk_reason)

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        pending = pending_planning_result()
        if pending is None:
            self.report({"ERROR"}, "The approved plan is no longer available.")
            return {"CANCELLED"}

        summary = state.plan_summary or pending.plan.intent_summary
        decision = evaluate_plan_safety(
            pending.plan,
            global_undo_available=global_undo_enabled(context),
        )
        risk_level = decision.risk.level.value
        request_summary = _request_summary(state)
        recovery_point = False

        try:
            authorize_plan_execution(
                decision,
                secondary_confirmation=self.secondary_confirmation,
            )
        except SafetyConfirmationRequired as error:
            state.workflow_status = WorkflowStatus.AWAITING_APPROVAL.value
            state.status_message = "High-risk confirmation required"
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        except SafetyPolicyError as error:
            _show_safety_block(state, error)
            self.report({"ERROR"}, state.error_headline)
            return {"CANCELLED"}

        def update_progress(current: int, total: int) -> None:
            state.progress_current = current
            state.progress_total = total

        try:
            preflight_plan(context, pending.plan, pending.snapshot)
            recovery_point = create_recovery_point(context, "Before AI Assistant Plan")
            if decision.recovery_point_required and not recovery_point:
                safety_error = SafetyPolicyError(
                    "Blender could not create the required pre-plan recovery point."
                )
                _show_safety_block(state, safety_error)
                self.report({"ERROR"}, state.error_headline)
                return {"CANCELLED"}
            state.workflow_status = WorkflowStatus.EXECUTING.value
            state.status_message = "Applying plan"
            state.progress_current = 0
            state.progress_total = len(pending.plan.operations)
            state.error_headline = ""
            state.error_details = ""
            result = execute_plan(
                context,
                pending.plan,
                pending.snapshot,
                progress_callback=update_progress,
            )
        except ExecutionPreflightError as error:
            clear_planning_result()
            clear_plan(state)
            state.workflow_status = WorkflowStatus.ERROR.value
            state.status_message = "Execution blocked"
            state.error_headline = "The approved plan is no longer safe to apply"
            state.error_details = str(error)
            state.changed_count = 0
            state.undo_available = False
            add_history_entry(
                state,
                timestamp=_timestamp(),
                summary=request_summary,
                status="failed",
                risk_level=risk_level,
                details=str(error),
            )
            self.report({"ERROR"}, state.error_headline)
            return {"CANCELLED"}
        except PlanExecutionError as error:
            clear_planning_result()
            clear_plan(state)
            result = error.result
            state.workflow_status = WorkflowStatus.ERROR.value
            state.status_message = (
                "Execution partially applied" if result.partial else "Execution failed"
            )
            state.error_headline = (
                "The plan stopped after changing part of the scene"
                if result.partial
                else "The plan failed and its changes were rolled back"
            )
            state.error_details = f"{error} {error.recovery_instructions}"[:4096]
            state.changed_count = result.changed_count
            _populate_result_details(state, result)
            state.undo_available = result.partial and recovery_point
            add_history_entry(
                state,
                timestamp=_timestamp(),
                summary=request_summary,
                status="partial" if result.partial else "failed",
                risk_level=risk_level,
                details=(
                    f"{state.error_details} {_execution_details(result)}"
                )[:4096],
            )
            self.report({"ERROR"}, state.error_headline)
            return {"CANCELLED"}

        clear_planning_result()
        clear_plan(state)
        state.workflow_status = WorkflowStatus.COMPLETE.value
        state.status_message = "Plan applied"
        state.result_summary = (
            f"{summary} Applied {result.completed_operations} operation(s) and changed "
            f"{result.changed_count} datablock(s)."
        )
        state.changed_count = result.changed_count
        _populate_result_details(state, result)
        state.undo_available = global_undo_enabled(context)
        add_history_entry(
            state,
            timestamp=_timestamp(),
            summary=request_summary,
            status="completed",
            risk_level=risk_level,
            details=_execution_details(result),
        )
        return {"FINISHED"}


class AIASSISTANT_OT_dismiss_error(Operator):
    bl_idname = "blender_ai.dismiss_error"
    bl_label = "Edit Request"
    bl_description = "Return to the request editor"

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        if state.has_plan and pending_planning_result() is not None:
            state.workflow_status = WorkflowStatus.AWAITING_APPROVAL.value
            state.status_message = "Review plan"
        else:
            state.workflow_status = WorkflowStatus.IDLE.value
            state.status_message = "Ready"
        state.error_headline = ""
        state.error_details = ""
        return {"FINISHED"}


class AIASSISTANT_OT_new_request(Operator):
    bl_idname = "blender_ai.new_request"
    bl_label = "New Request"
    bl_description = "Clear the completed workflow and start a new request"

    def execute(self, context: Any) -> OperatorResult:
        state = _state(context)
        clear_planning_result()
        reset_request(state)
        state.draft_prompt = ""
        return {"FINISHED"}


CLASSES = (
    AIASSISTANT_OT_open_preferences,
    AIASSISTANT_OT_clear_session_key,
    AIASSISTANT_OT_clear_prompt,
    AIASSISTANT_OT_toggle_context_details,
    AIASSISTANT_OT_plan_changes,
    AIASSISTANT_OT_continue_planning,
    AIASSISTANT_OT_cancel_request,
    AIASSISTANT_OT_reject_plan,
    AIASSISTANT_OT_rephrase_plan,
    AIASSISTANT_OT_apply_plan,
    AIASSISTANT_OT_dismiss_error,
    AIASSISTANT_OT_new_request,
)
