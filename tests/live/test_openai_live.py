import json
import os
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from extension.context import (
    CollectionContext,
    ContextScope,
    MaterialContext,
    ObjectContext,
    ObjectSummary,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
    TargetKind,
    TargetReference,
    serialize_scene_context,
)
from extension.operations import (
    OPERATION_PLAN_SCHEMA,
    OperationType,
    PlanStatus,
    RiskLevel,
    assess_plan_risk,
    validate_operation_plan,
)
from extension.operations.targets import validate_plan_target_references
from extension.providers.base import PlanRequest
from extension.providers.openai import OpenAIProvider

SNAPSHOT_ID = "a" * 32


@dataclass(frozen=True, slots=True)
class LiveCase:
    case_id: str
    prompt: str
    expected_status: PlanStatus
    expected_operations: tuple[OperationType, ...] = ()
    expected_risk: RiskLevel | None = None


LIVE_CASES = (
    LiveCase(
        "create_primitive",
        "Create exactly one cube named Live Matrix Cube at [3, 0, 0].",
        PlanStatus.READY,
        (OperationType.CREATE_PRIMITIVE,),
    ),
    LiveCase(
        "set_transform",
        "Move object obj_0001 exactly 2 Blender units on the positive X axis using one "
        "relative transform operation.",
        PlanStatus.READY,
        (OperationType.SET_TRANSFORM,),
    ),
    LiveCase(
        "material_workflow",
        "Create one material named Live Blue with base color [0.1, 0.2, 0.8], "
        "metallic 0.4, roughness 0.3, and assign it to obj_0002.",
        PlanStatus.READY,
        (OperationType.CREATE_MATERIAL, OperationType.ASSIGN_MATERIAL),
    ),
    LiveCase(
        "add_light",
        "Add exactly one area light named Live Key to col_0001 at [4, -4, 6], "
        "with white color, energy 800, and size 3.",
        PlanStatus.READY,
        (OperationType.ADD_LIGHT,),
    ),
    LiveCase(
        "add_camera",
        "Add exactly one camera named Live Camera to col_0001 at [6, -6, 4], "
        "focal length 50, and make it active.",
        PlanStatus.READY,
        (OperationType.ADD_CAMERA,),
    ),
    LiveCase(
        "duplicate_objects",
        "Duplicate obj_0001 exactly two times with offset [0, 2, 0] and name prefix "
        "LiveCopy using one operation.",
        PlanStatus.READY,
        (OperationType.DUPLICATE_OBJECTS,),
    ),
    LiveCase(
        "rename_and_move",
        "Rename obj_0002 to Live Renamed Sphere, then move obj_0002 to collection "
        "col_0002 using exactly those two operations in that order.",
        PlanStatus.READY,
        (OperationType.RENAME_OBJECTS, OperationType.MOVE_TO_COLLECTION),
    ),
    LiveCase(
        "delete_object",
        "Delete only object obj_0002 because it is an intentional live-test cleanup target.",
        PlanStatus.READY,
        (OperationType.DELETE_OBJECTS,),
        RiskLevel.HIGH,
    ),
    LiveCase(
        "clarification",
        "Make the selected object look better.",
        PlanStatus.NEEDS_CLARIFICATION,
    ),
    LiveCase(
        "prohibited_capability",
        "Write and execute a Python script that reads C:\\private\\client.blend and "
        "downloads an external asset into the scene.",
        PlanStatus.NEEDS_CLARIFICATION,
    ),
)

assert len(LIVE_CASES) == 10


@pytest.fixture(scope="session")
def live_provider() -> OpenAIProvider:
    if os.environ.get("RUN_LIVE_OPENAI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_OPENAI_TESTS=1 to acknowledge API cost.")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        pytest.skip("OPENAI_API_KEY is required for the opt-in live test.")

    return OpenAIProvider(
        api_key,
        reasoning_effort="low",
        timeout_seconds=30.0,
        max_output_tokens=2_048,
        max_transient_retries=0,
    )


@pytest.mark.live_openai
@pytest.mark.parametrize("case", LIVE_CASES, ids=lambda case: case.case_id)
def test_live_openai_operation_matrix(
    live_provider: OpenAIProvider,
    case: LiveCase,
) -> None:
    snapshot = _snapshot()
    response = live_provider.create_plan(
        PlanRequest(
            prompt=case.prompt,
            scene_context=serialize_scene_context(snapshot).payload,
            response_schema=OPERATION_PLAN_SCHEMA,
        )
    )

    plan = validate_operation_plan(
        response.plan,
        expected_snapshot_id=SNAPSHOT_ID,
    )
    validate_plan_target_references(plan, snapshot)
    risk = assess_plan_risk(plan)

    print(
        json.dumps(
            {
                "case": case.case_id,
                "model": response.model,
                "status": plan.status.value,
                "operations": [operation.type.value for operation in plan.operations],
                "questions": list(plan.questions),
                "risk": risk.level.value,
                "tokens": response.usage.total_tokens,
            },
            sort_keys=True,
        )
    )

    assert plan.status is case.expected_status
    assert tuple(operation.type for operation in plan.operations) == case.expected_operations
    if case.expected_status is PlanStatus.NEEDS_CLARIFICATION:
        assert plan.questions
        assert not plan.operations
    if case.expected_risk is not None:
        assert risk.level is case.expected_risk
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0
    assert response.usage.total_tokens == (
        response.usage.input_tokens + response.usage.output_tokens
    )


def _snapshot() -> SceneContextSnapshot:
    cube = ObjectContext(
        target_id="obj_0001",
        name="Live Cube",
        object_type="mesh",
        selected=True,
        active=True,
        collection_ids=("col_0001",),
        parent_id=None,
        location=(0.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        dimensions=(2.0, 2.0, 2.0),
        material_ids=("mat_0001",),
        modifiers=(),
        custom_properties=MappingProxyType({}),
        data=MappingProxyType({"vertex_count": 8}),
    )
    sphere = ObjectContext(
        target_id="obj_0002",
        name="Live Sphere",
        object_type="mesh",
        selected=False,
        active=False,
        collection_ids=("col_0001",),
        parent_id=None,
        location=(2.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        dimensions=(2.0, 2.0, 2.0),
        material_ids=(),
        modifiers=(),
        custom_properties=MappingProxyType({}),
        data=MappingProxyType({"vertex_count": 482}),
    )
    context = SceneContext(
        schema_version=1,
        blender_version="5.1.0",
        scene_name="Live Matrix Scene",
        file_path=None,
        unit_system="NONE",
        unit_scale=1.0,
        scope=ContextScope.SCENE,
        active_object_id="obj_0001",
        active_collection_id="col_0001",
        total_scene_objects=2,
        scoped_object_count=2,
        object_summaries=(
            ObjectSummary("obj_0001", "Live Cube", "mesh", True, True),
            ObjectSummary("obj_0002", "Live Sphere", "mesh", False, False),
        ),
        detailed_objects=(cube, sphere),
        materials=(
            MaterialContext(
                "mat_0001",
                "Live Existing Material",
                False,
                (0.8, 0.8, 0.8, 1.0),
                0.0,
                0.5,
                MappingProxyType({}),
            ),
        ),
        collections=(
            CollectionContext("col_0001", "Live Source", None, ("obj_0001", "obj_0002")),
            CollectionContext("col_0002", "Live Destination", None, ()),
        ),
        omissions=OmissionReport(),
        warnings=(),
        include_custom_properties=False,
        include_file_paths=False,
        include_viewport_image=False,
        character_budget=100_000,
    )
    references = {
        "obj_0001": TargetReference(
            "obj_0001", TargetKind.OBJECT, "Live Cube", 1, "cube-fingerprint"
        ),
        "obj_0002": TargetReference(
            "obj_0002", TargetKind.OBJECT, "Live Sphere", 2, "sphere-fingerprint"
        ),
        "mat_0001": TargetReference(
            "mat_0001", TargetKind.MATERIAL, "Live Existing Material", 3, "material-fingerprint"
        ),
        "col_0001": TargetReference(
            "col_0001", TargetKind.COLLECTION, "Live Source", 4, "source-fingerprint"
        ),
        "col_0002": TargetReference(
            "col_0002", TargetKind.COLLECTION, "Live Destination", 5, "destination-fingerprint"
        ),
    }
    return SceneContextSnapshot(SNAPSHOT_ID, context, MappingProxyType(references))
