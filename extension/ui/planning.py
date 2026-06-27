"""Bridge background planning events back to Blender's main thread."""

import traceback
from typing import Any, cast

import bpy

from ..context import SceneContextSnapshot
from ..operations import (
    DEFAULT_OPERATION_LIMITS,
    Operation,
    OperationLimits,
    OperationPlan,
    OperationType,
    PlanStatus,
)
from ..operations.targets import TargetResolutionError, resolve_plan_targets
from ..providers.base import Provider
from ..providers.nvidia import (
    DEFAULT_NVIDIA_MODEL,
    NVIDIA_DEFAULT_BASE_URL,
    NvidiaAPIError,
    NvidiaProvider,
)
from ..providers.openai import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT_SECONDS,
    OpenAIAPIError,
    OpenAIProvider,
)
from ..providers.registry import PROVIDER_NVIDIA, PROVIDER_OPENAI, provider_label
from ..workflow import (
    PlanningConversation,
    PlanningCoordinator,
    PlanningFailure,
    PlanningResult,
    PlanningSuccess,
)
from ..workflow.state import WorkflowStatus
from .properties import AIASSISTANT_PG_State, clear_plan

POLL_INTERVAL_SECONDS = 0.2

_coordinator: PlanningCoordinator | None = None


def register_planning_runtime() -> None:
    global _coordinator

    if _coordinator is not None:
        _coordinator.shutdown()
    _coordinator = PlanningCoordinator()
    if not bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.register(
            _poll_timer,
            first_interval=POLL_INTERVAL_SECONDS,
            persistent=True,
        )


def unregister_planning_runtime() -> None:
    global _coordinator

    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    if _coordinator is not None:
        _coordinator.shutdown()
        _coordinator = None


def start_planning_job(
    *,
    prompt: str,
    snapshot: SceneContextSnapshot,
    api_key: str,
    provider_choice: str = PROVIDER_OPENAI,
    model: str = DEFAULT_MODEL,
    nvidia_base_url: str = NVIDIA_DEFAULT_BASE_URL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    provider: Provider | None = None,
    conversation: PlanningConversation | None = None,
    limits: OperationLimits = DEFAULT_OPERATION_LIMITS,
) -> int:
    active_provider = provider or _build_provider(
        provider_choice=provider_choice,
        api_key=api_key,
        model=model,
        nvidia_base_url=nvidia_base_url,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )
    return _get_coordinator().start(
        prompt=prompt,
        snapshot=snapshot,
        provider=active_provider,
        conversation=conversation,
        limits=limits,
    )


def cancel_planning_job() -> int | None:
    return _get_coordinator().cancel()


def clear_planning_result() -> None:
    _get_coordinator().clear_pending()


def pending_planning_result() -> PlanningResult | None:
    return _get_coordinator().pending_result


def _build_provider(
    *,
    provider_choice: str,
    api_key: str,
    model: str,
    nvidia_base_url: str,
    reasoning_effort: str,
    timeout_seconds: float,
    max_output_tokens: int,
) -> Provider:
    if provider_choice == PROVIDER_NVIDIA:
        resolved_model = model or DEFAULT_NVIDIA_MODEL
        return NvidiaProvider(
            api_key,
            model=resolved_model,
            base_url=nvidia_base_url,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
        )
    return OpenAIProvider(
        api_key,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )


def process_planning_events(context: Any) -> int:
    state = _state(context)
    processed = 0
    for event in _get_coordinator().poll():
        processed += 1
        if isinstance(event, PlanningFailure):
            _show_failure(state, event.error)
            continue
        if isinstance(event, PlanningSuccess):
            _show_result(state, event.result)
    return processed


def _poll_timer() -> float:
    window_manager = getattr(bpy.context, "window_manager", None)
    try:
        if window_manager is not None and hasattr(window_manager, "blender_ai_state"):
            process_planning_events(bpy.context)
    except Exception:
        traceback.print_exc()
    return POLL_INTERVAL_SECONDS


def _show_result(state: AIASSISTANT_PG_State, result: PlanningResult) -> None:
    state.workflow_status = WorkflowStatus.VALIDATING.value
    state.status_message = "Validating plan"
    _record_provider_usage(state, result)
    clear_plan(state)

    try:
        resolve_plan_targets(result.plan, result.snapshot)
    except TargetResolutionError as error:
        _show_failure(state, error)
        return

    if result.plan.status is PlanStatus.NEEDS_CLARIFICATION:
        _get_coordinator().retain(result)
        _populate_questions(state, result.plan)
        state.workflow_status = WorkflowStatus.NEEDS_CLARIFICATION.value
        state.status_message = "More information needed"
        return

    _get_coordinator().retain(result)
    _populate_plan(state, result)
    state.workflow_status = WorkflowStatus.AWAITING_APPROVAL.value
    state.status_message = "Review plan"


def _record_provider_usage(
    state: AIASSISTANT_PG_State,
    result: PlanningResult,
) -> None:
    if state.provider_model and state.provider_model != result.model:
        state.provider_model = "Multiple models"
    elif not state.provider_model:
        state.provider_model = result.model
    state.provider_call_count += result.provider_call_count
    state.input_tokens += result.usage.input_tokens
    state.cached_input_tokens += result.usage.cached_input_tokens
    state.output_tokens += result.usage.output_tokens
    state.reasoning_tokens += result.usage.reasoning_tokens
    state.total_tokens += result.usage.total_tokens


def _populate_questions(state: AIASSISTANT_PG_State, plan: OperationPlan) -> None:
    state.clarification_response = ""
    state.questions.clear()
    for question in plan.questions:
        state.questions.add().value = question
    state.assumptions.clear()
    for assumption in plan.assumptions:
        state.assumptions.add().value = assumption


def _populate_plan(state: AIASSISTANT_PG_State, result: PlanningResult) -> None:
    plan = result.plan
    state.has_plan = True
    state.plan_summary = plan.intent_summary
    state.risk_level = result.risk.level.value
    state.risk_reason = " ".join(result.risk.reasons)
    state.operation_count = len(plan.operations)
    state.target_count = result.risk.affected_object_count
    state.operation_previews.clear()
    for operation in plan.operations:
        preview = state.operation_previews.add()
        preview.operation_id = operation.operation_id
        preview.label = _operation_label(operation.type)
        preview.detail = _operation_detail(operation)
        preview.target_count = len(operation.target_ids)

    state.assumptions.clear()
    for assumption in plan.assumptions:
        state.assumptions.add().value = assumption
    state.questions.clear()


def _operation_label(operation_type: OperationType) -> str:
    return operation_type.value.replace("_", " ").title()


def _operation_detail(operation: Operation) -> str:
    payload = operation.payload
    if operation.type is OperationType.CREATE_PRIMITIVE:
        return f"Create {payload['primitive']} named {payload['name']}"
    if operation.type is OperationType.CREATE_MATERIAL:
        return f"Create material named {payload['name']}"
    if operation.type is OperationType.ADD_LIGHT:
        return f"Add {payload['light_type']} light named {payload['name']}"
    if operation.type is OperationType.ADD_CAMERA:
        return f"Add camera named {payload['name']}"
    if operation.type is OperationType.SET_TRANSFORM:
        return f"{str(payload['mode']).title()} transform"
    return f"Affect {len(operation.target_ids)} object reference(s)"


def _show_failure(state: AIASSISTANT_PG_State, error: Exception) -> None:
    _get_coordinator().clear_pending()
    clear_plan(state)
    state.workflow_status = WorkflowStatus.ERROR.value
    state.status_message = "Planning failed"
    error_code = _provider_error_code(error)
    label = _provider_error_label(error)
    if error_code == "request_timeout":
        state.error_headline = f"{label} request timed out"
    elif error_code in {
        "connection_error",
        "tls_error",
        "transport_error",
    }:
        state.error_headline = f"Could not connect to {label}"
    else:
        state.error_headline = "Could not prepare a valid plan"
    state.error_details = str(error) or type(error).__name__


def _provider_error_code(error: Exception) -> str:
    if isinstance(error, (OpenAIAPIError, NvidiaAPIError)):
        return error.error_code
    return ""


def _provider_error_label(error: Exception) -> str:
    if isinstance(error, NvidiaAPIError):
        return provider_label(PROVIDER_NVIDIA)
    return provider_label(PROVIDER_OPENAI)


def _state(context: Any) -> AIASSISTANT_PG_State:
    window_manager = cast(Any, context.window_manager)
    return window_manager.blender_ai_state


def _get_coordinator() -> PlanningCoordinator:
    if _coordinator is None:
        raise RuntimeError("The planning runtime is not registered.")
    return _coordinator
