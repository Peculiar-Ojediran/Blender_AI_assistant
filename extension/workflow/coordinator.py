"""Coordinate snapshot-bound provider planning without accessing Blender data."""

from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any

from ..context import SceneContextSnapshot, serialize_scene_context
from ..operations import (
    DEFAULT_OPERATION_LIMITS,
    OperationContractError,
    OperationLimits,
    OperationPlan,
    RiskAssessment,
    SnapshotMismatchError,
    assess_plan_risk,
    build_operation_plan_schema,
    validate_operation_plan,
)
from ..operations.targets import TargetResolutionError, validate_plan_target_references
from ..providers.base import PlanRequest, Provider, TokenUsage
from .async_runtime import CancellationToken, GenerationRuntime


@dataclass(frozen=True, slots=True)
class ClarificationTurn:
    questions: tuple[str, ...]
    answer: str


@dataclass(frozen=True, slots=True)
class PlanningConversation:
    original_prompt: str
    clarification_turns: tuple[ClarificationTurn, ...] = ()

    def with_clarification(
        self,
        questions: tuple[str, ...],
        answer: str,
    ) -> "PlanningConversation":
        return PlanningConversation(
            self.original_prompt,
            (*self.clarification_turns, ClarificationTurn(questions, answer)),
        )

    def render(self) -> str:
        if not self.clarification_turns:
            return self.original_prompt

        sections = [f"Original request:\n{self.original_prompt}"]
        for index, turn in enumerate(self.clarification_turns, start=1):
            questions = "\n".join(f"- {question}" for question in turn.questions)
            sections.append(
                f"Clarification round {index}:\n{questions}\nUser answer:\n{turn.answer}"
            )
        return "\n\n".join(sections)


@dataclass(frozen=True, slots=True)
class PlanningResult:
    snapshot: SceneContextSnapshot
    plan: OperationPlan
    risk: RiskAssessment
    response_id: str
    request_id: str
    model: str
    repair_attempted: bool
    conversation: PlanningConversation
    usage: TokenUsage
    provider_call_count: int


@dataclass(frozen=True, slots=True)
class PlanningSuccess:
    generation_id: int
    result: PlanningResult


@dataclass(frozen=True, slots=True)
class PlanningFailure:
    generation_id: int
    error: Exception


type PlanningEvent = PlanningSuccess | PlanningFailure


class PlanningCoordinator:
    """Own background planning generations and the approved-plan candidate."""

    def __init__(self) -> None:
        self._runtime: GenerationRuntime[PlanningResult] = GenerationRuntime()
        self._lock = Lock()
        self._pending_result: PlanningResult | None = None

    def start(
        self,
        *,
        prompt: str,
        snapshot: SceneContextSnapshot,
        provider: Provider,
        conversation: PlanningConversation | None = None,
        limits: OperationLimits = DEFAULT_OPERATION_LIMITS,
    ) -> int:
        scene_context: Mapping[str, Any] = serialize_scene_context(snapshot).payload
        active_conversation = conversation or PlanningConversation(prompt)
        provider_prompt = _provider_prompt(active_conversation, limits)
        response_schema = build_operation_plan_schema(limits)

        def plan(token: CancellationToken) -> PlanningResult:
            token.raise_if_cancelled()
            response = provider.create_plan(
                PlanRequest(
                    prompt=provider_prompt,
                    scene_context=scene_context,
                    response_schema=response_schema,
                )
            )
            token.raise_if_cancelled()
            usage = response.usage
            provider_call_count = 1
            repair_attempted = False
            try:
                operation_plan = _validate_response_plan(response.plan, snapshot, limits)
            except SnapshotMismatchError:
                raise
            except (OperationContractError, TargetResolutionError) as error:
                token.raise_if_cancelled()
                repair_attempted = True
                response = provider.create_plan(
                    PlanRequest(
                        prompt=_repair_prompt(provider_prompt, error),
                        scene_context=scene_context,
                        response_schema=response_schema,
                    )
                )
                token.raise_if_cancelled()
                usage += response.usage
                provider_call_count += 1
                operation_plan = _validate_response_plan(response.plan, snapshot, limits)
            return PlanningResult(
                snapshot=snapshot,
                plan=operation_plan,
                risk=assess_plan_risk(operation_plan),
                response_id=response.response_id,
                request_id=response.request_id,
                model=response.model,
                repair_attempted=repair_attempted,
                conversation=active_conversation,
                usage=usage,
                provider_call_count=provider_call_count,
            )

        self.clear_pending()
        return self._runtime.start(plan)

    def poll(self) -> tuple[PlanningEvent, ...]:
        events: list[PlanningEvent] = []
        for event in self._runtime.poll():
            if event.error is not None:
                events.append(PlanningFailure(event.generation_id, event.error))
            elif event.value is not None:
                events.append(PlanningSuccess(event.generation_id, event.value))
        return tuple(events)

    def retain(self, result: PlanningResult) -> None:
        with self._lock:
            self._pending_result = result

    @property
    def pending_result(self) -> PlanningResult | None:
        with self._lock:
            return self._pending_result

    @property
    def is_running(self) -> bool:
        return self._runtime.is_running

    @property
    def has_background_work(self) -> bool:
        return self._runtime.has_worker

    def cancel(self) -> int | None:
        return self._runtime.cancel_active()

    def clear_pending(self) -> None:
        with self._lock:
            self._pending_result = None

    def shutdown(self) -> None:
        self.clear_pending()
        self._runtime.shutdown()


def _validate_response_plan(
    raw_plan: Mapping[str, Any],
    snapshot: SceneContextSnapshot,
    limits: OperationLimits,
) -> OperationPlan:
    operation_plan = validate_operation_plan(
        raw_plan,
        expected_snapshot_id=snapshot.snapshot_id,
        limits=limits,
    )
    validate_plan_target_references(operation_plan, snapshot)
    return operation_plan


def _provider_prompt(
    conversation: PlanningConversation,
    limits: OperationLimits,
) -> str:
    return (
        f"{conversation.render()}\n\n"
        "Extension-enforced plan limits:\n"
        f"- Maximum operations in this plan: {limits.max_operations_per_plan}\n"
        "- Maximum existing object targets in one operation: "
        f"{limits.max_targets_per_operation}\n"
        "- Maximum total objects created by one DUPLICATE_OBJECTS operation: "
        f"{limits.max_duplicate_objects}. This total equals target count multiplied by "
        "the duplicate count."
    )


def _repair_prompt(prompt: str, error: Exception) -> str:
    return (
        f"{prompt}\n\n"
        "The previous plan failed local validation. Return one corrected plan for the same "
        f"request and snapshot. Validation error: {error}"
    )
