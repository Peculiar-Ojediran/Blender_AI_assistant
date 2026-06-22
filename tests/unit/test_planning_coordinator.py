import threading
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from extension.context import (
    ContextScope,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
)
from extension.operations import OperationLimits, OperationType, RiskLevel
from extension.operations.targets import TargetResolutionError
from extension.providers.base import PlanRequest, PlanResponse, TokenUsage
from extension.workflow import (
    PlanningConversation,
    PlanningCoordinator,
    PlanningFailure,
    PlanningSuccess,
)

SNAPSHOT_ID = "a" * 32


class FakeProvider:
    def __init__(self, plan: Mapping[str, Any]) -> None:
        self.plan = plan

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        return PlanResponse("resp_test", "model_test", self.plan)


class SequenceProvider:
    def __init__(self, plans: list[Mapping[str, Any]]) -> None:
        self.plans = plans
        self.requests: list[PlanRequest] = []

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        self.requests.append(request)
        call_number = len(self.requests)
        return PlanResponse(
            f"resp_{call_number}",
            "model_test",
            self.plans[call_number - 1],
            usage=TokenUsage(
                input_tokens=call_number * 100,
                output_tokens=call_number * 10,
                total_tokens=call_number * 110,
            ),
        )


class BlockingInvalidProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        self.call_count += 1
        if self.call_count == 1:
            self.started.set()
            self.release.wait(timeout=2.0)
            invalid_plan = dict(_create_plan())
            invalid_plan["operations"] = [
                {
                    "operation_id": "empty_transform",
                    "type": "SET_TRANSFORM",
                    "target_ids": ["obj_0001"],
                    "mode": "absolute",
                    "location": None,
                    "rotation_euler": None,
                    "scale": None,
                }
            ]
            return PlanResponse("resp_invalid", "model_test", invalid_plan)
        return PlanResponse("resp_repair", "model_test", _create_plan())


def test_coordinator_returns_a_validated_snapshot_bound_plan() -> None:
    coordinator = PlanningCoordinator()
    snapshot = _empty_snapshot()
    coordinator.start(
        prompt="Create a cube",
        snapshot=snapshot,
        provider=FakeProvider(_create_plan()),
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningSuccess)
    assert event.result.snapshot is snapshot
    assert event.result.plan.operations[0].type is OperationType.CREATE_PRIMITIVE
    assert event.result.risk.level is RiskLevel.LOW


def test_coordinator_rejects_a_plan_for_another_snapshot() -> None:
    coordinator = PlanningCoordinator()
    plan = dict(_create_plan())
    plan["snapshot_id"] = "b" * 32
    provider = SequenceProvider([plan, _create_plan()])
    coordinator.start(
        prompt="Create a cube",
        snapshot=_empty_snapshot(),
        provider=provider,
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningFailure)
    assert "different scene snapshot" in str(event.error)
    assert len(provider.requests) == 1


def test_coordinator_rejects_unknown_context_targets() -> None:
    coordinator = PlanningCoordinator()
    plan = {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Move an object.",
        "assumptions": [],
        "questions": [],
        "operations": [
            {
                "operation_id": "move_object",
                "type": "SET_TRANSFORM",
                "target_ids": ["obj_0001"],
                "mode": "relative",
                "location": [1.0, 0.0, 0.0],
                "rotation_euler": None,
                "scale": None,
            }
        ],
    }
    coordinator.start(
        prompt="Move the object",
        snapshot=_empty_snapshot(),
        provider=FakeProvider(plan),
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningFailure)
    assert isinstance(event.error, TargetResolutionError)


def test_coordinator_repairs_one_locally_invalid_plan() -> None:
    invalid_plan = dict(_create_plan())
    invalid_plan["operations"] = [
        {
            "operation_id": "empty_transform",
            "type": "SET_TRANSFORM",
            "target_ids": ["obj_0001"],
            "mode": "absolute",
            "location": None,
            "rotation_euler": None,
            "scale": None,
        }
    ]
    provider = SequenceProvider([invalid_plan, _create_plan()])
    coordinator = PlanningCoordinator()
    coordinator.start(
        prompt="Create a cube",
        snapshot=_empty_snapshot(),
        provider=provider,
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningSuccess)
    assert event.result.repair_attempted is True
    assert event.result.response_id == "resp_2"
    assert event.result.provider_call_count == 2
    assert event.result.usage == TokenUsage(
        input_tokens=300,
        output_tokens=30,
        total_tokens=330,
    )
    assert len(provider.requests) == 2
    assert "previous plan failed local validation" in provider.requests[1].prompt


def test_coordinator_propagates_selected_limits_to_schema_and_prompt() -> None:
    provider = SequenceProvider([_create_plan()])
    coordinator = PlanningCoordinator()
    limits = OperationLimits(3, 4, 5)
    coordinator.start(
        prompt="Create a cube",
        snapshot=_empty_snapshot(),
        provider=provider,
        limits=limits,
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningSuccess)
    schema = provider.requests[0].response_schema
    assert schema["properties"]["operations"]["maxItems"] == 3
    assert "Maximum operations in this plan: 3" in provider.requests[0].prompt
    assert "Maximum existing object targets in one operation: 4" in (
        provider.requests[0].prompt
    )
    assert "Maximum total objects created by one DUPLICATE_OBJECTS operation: 5" in (
        provider.requests[0].prompt
    )


def test_coordinator_repairs_a_plan_over_the_selected_operation_limit() -> None:
    invalid_plan = dict(_create_plan())
    second_operation = dict(invalid_plan["operations"][0])
    second_operation["operation_id"] = "create_second_cube"
    invalid_plan["operations"] = [invalid_plan["operations"][0], second_operation]
    provider = SequenceProvider([invalid_plan, _create_plan()])
    coordinator = PlanningCoordinator()
    coordinator.start(
        prompt="Create one cube",
        snapshot=_empty_snapshot(),
        provider=provider,
        limits=OperationLimits(max_operations_per_plan=1),
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningSuccess)
    assert event.result.repair_attempted is True
    assert len(provider.requests) == 2


def test_cancelled_request_cannot_start_a_repair_request() -> None:
    provider = BlockingInvalidProvider()
    coordinator = PlanningCoordinator()
    coordinator.start(
        prompt="Create a cube",
        snapshot=_empty_snapshot(),
        provider=provider,
    )
    assert provider.started.wait(timeout=1.0)

    coordinator.cancel()
    provider.release.set()
    deadline = time.monotonic() + 2.0
    while coordinator.has_background_work and time.monotonic() < deadline:
        time.sleep(0.005)

    assert coordinator.has_background_work is False
    assert provider.call_count == 1
    assert coordinator.poll() == ()


def test_multiple_clarification_rounds_are_retained_in_provider_prompt() -> None:
    conversation = (
        PlanningConversation("Create a product display")
        .with_clarification(("Which material?",), "Brushed steel")
        .with_clarification(("How large?",), "Two meters wide")
    )
    provider = SequenceProvider([_create_plan()])
    coordinator = PlanningCoordinator()
    coordinator.start(
        prompt=conversation.original_prompt,
        snapshot=_empty_snapshot(),
        provider=provider,
        conversation=conversation,
    )

    event = _wait_for_event(coordinator)

    assert isinstance(event, PlanningSuccess)
    assert event.result.conversation == conversation
    assert "Brushed steel" in provider.requests[0].prompt
    assert "Two meters wide" in provider.requests[0].prompt


def _wait_for_event(
    coordinator: PlanningCoordinator,
) -> PlanningSuccess | PlanningFailure:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        events = coordinator.poll()
        if events:
            return events[0]
        time.sleep(0.005)
    raise AssertionError("Planning coordinator did not produce an event.")


def _create_plan() -> Mapping[str, Any]:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Create a cube.",
        "assumptions": [],
        "questions": [],
        "operations": [
            {
                "operation_id": "create_cube",
                "type": "CREATE_PRIMITIVE",
                "primitive": "cube",
                "name": "Generated Cube",
                "collection_id": None,
                "location": [0.0, 0.0, 0.0],
                "rotation_euler": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        ],
    }


def _empty_snapshot() -> SceneContextSnapshot:
    context = SceneContext(
        schema_version=1,
        blender_version="5.1.0",
        scene_name="Scene",
        file_path=None,
        unit_system="NONE",
        unit_scale=1.0,
        scope=ContextScope.SELECTION,
        active_object_id=None,
        active_collection_id=None,
        total_scene_objects=0,
        scoped_object_count=0,
        object_summaries=(),
        detailed_objects=(),
        materials=(),
        collections=(),
        omissions=OmissionReport(),
        warnings=(),
        include_custom_properties=False,
        include_file_paths=False,
        include_viewport_image=False,
        character_budget=100_000,
    )
    return SceneContextSnapshot(SNAPSHOT_ID, context, MappingProxyType({}))
