import json
from copy import deepcopy
from typing import Any

import pytest

from extension.operations import (
    DEFAULT_MAX_DUPLICATE_OBJECTS,
    DEFAULT_MAX_OPERATIONS_PER_PLAN,
    DEFAULT_MAX_TARGETS_PER_OPERATION,
    DEFAULT_OPERATION_LIMITS,
    HARD_MAX_DUPLICATE_OBJECTS,
    HARD_MAX_OPERATIONS_PER_PLAN,
    HARD_MAX_TARGETS_PER_OPERATION,
    OPERATION_CATALOG,
    OPERATION_PLAN_SCHEMA,
    OPERATION_SCHEMAS,
    OperationContractError,
    OperationLimits,
    OperationType,
    PlanStatus,
    RiskLevel,
    assess_plan_risk,
    build_operation_plan_schema,
    validate_operation_plan,
)

SNAPSHOT_ID = "a" * 32


def create_primitive_operation(operation_id: str = "create_cube") -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "type": "CREATE_PRIMITIVE",
        "primitive": "cube",
        "name": "Cube",
        "collection_id": None,
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def ready_plan(*operations: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Apply the requested scene changes.",
        "assumptions": [],
        "questions": [],
        "operations": list(operations),
    }


VALID_OPERATIONS = [
    create_primitive_operation(),
    {
        "operation_id": "delete_cube",
        "type": "DELETE_OBJECTS",
        "target_ids": ["obj_0001"],
        "reason": "The user explicitly requested deletion.",
    },
    {
        "operation_id": "duplicate_cube",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001"],
        "count": 2,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": "Copy",
    },
    {
        "operation_id": "move_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001"],
        "mode": "relative",
        "location": [1.0, 0.0, 0.0],
        "rotation_euler": None,
        "scale": None,
    },
    {
        "operation_id": "create_red_material",
        "type": "CREATE_MATERIAL",
        "name": "Red Material",
        "base_color": [1.0, 0.0, 0.0],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
    },
    {
        "operation_id": "assign_red_material",
        "type": "ASSIGN_MATERIAL",
        "target_ids": ["obj_0001"],
        "material_id": "mat_0001",
    },
    {
        "operation_id": "add_key_light",
        "type": "ADD_LIGHT",
        "light_type": "area",
        "name": "Key Light",
        "collection_id": None,
        "location": [4.0, -4.0, 6.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "color": [1.0, 0.9, 0.8],
        "energy": 1000.0,
        "size": 5.0,
    },
    {
        "operation_id": "add_camera",
        "type": "ADD_CAMERA",
        "name": "Hero Camera",
        "collection_id": None,
        "location": [6.0, -6.0, 4.0],
        "rotation_euler": [1.0, 0.0, 0.8],
        "focal_length": 50.0,
        "make_active": True,
    },
    {
        "operation_id": "rename_cube",
        "type": "RENAME_OBJECTS",
        "renames": [{"target_id": "obj_0001", "new_name": "HeroCube"}],
    },
    {
        "operation_id": "move_collection",
        "type": "MOVE_TO_COLLECTION",
        "target_ids": ["obj_0001"],
        "collection_id": "col_0001",
    },
]


def test_catalog_and_schema_cover_the_same_operations() -> None:
    assert set(OPERATION_CATALOG) == set(OperationType)
    assert set(OPERATION_SCHEMAS) == set(OperationType)


def test_provider_schema_is_json_serializable() -> None:
    assert json.loads(json.dumps(OPERATION_PLAN_SCHEMA)) == OPERATION_PLAN_SCHEMA


def test_default_limits_match_the_controlled_contract() -> None:
    assert OperationLimits(
        max_operations_per_plan=DEFAULT_MAX_OPERATIONS_PER_PLAN,
        max_targets_per_operation=DEFAULT_MAX_TARGETS_PER_OPERATION,
        max_duplicate_objects=DEFAULT_MAX_DUPLICATE_OBJECTS,
    ) == DEFAULT_OPERATION_LIMITS


def test_hard_limits_allow_values_above_the_safe_defaults() -> None:
    limits = OperationLimits(
        max_operations_per_plan=HARD_MAX_OPERATIONS_PER_PLAN,
        max_targets_per_operation=HARD_MAX_TARGETS_PER_OPERATION,
        max_duplicate_objects=HARD_MAX_DUPLICATE_OBJECTS,
    )

    assert limits.max_operations_per_plan > DEFAULT_MAX_OPERATIONS_PER_PLAN
    assert limits.max_targets_per_operation > DEFAULT_MAX_TARGETS_PER_OPERATION
    assert limits.max_duplicate_objects > DEFAULT_MAX_DUPLICATE_OBJECTS


@pytest.mark.parametrize(
    ("field", "value", "maximum"),
    [
        ("max_operations_per_plan", 0, HARD_MAX_OPERATIONS_PER_PLAN),
        (
            "max_targets_per_operation",
            HARD_MAX_TARGETS_PER_OPERATION + 1,
            HARD_MAX_TARGETS_PER_OPERATION,
        ),
        (
            "max_duplicate_objects",
            HARD_MAX_DUPLICATE_OBJECTS + 1,
            HARD_MAX_DUPLICATE_OBJECTS,
        ),
    ],
)
def test_limits_reject_values_outside_hard_contract(
    field: str,
    value: int,
    maximum: int,
) -> None:
    values = {
        "max_operations_per_plan": 1,
        "max_targets_per_operation": 1,
        "max_duplicate_objects": 1,
    }
    values[field] = value

    with pytest.raises(ValueError, match=rf"between 1 and {maximum}"):
        OperationLimits(**values)


def test_configured_limits_are_embedded_in_provider_schema() -> None:
    limits = OperationLimits(3, 4, 5)
    schema = build_operation_plan_schema(limits)
    variants = schema["properties"]["operations"]["items"]["anyOf"]
    operations = {
        variant["properties"]["type"]["enum"][0]: variant for variant in variants
    }

    assert schema["properties"]["operations"]["maxItems"] == 3
    assert operations["SET_TRANSFORM"]["properties"]["target_ids"]["maxItems"] == 4
    assert operations["RENAME_OBJECTS"]["properties"]["renames"]["maxItems"] == 4
    assert operations["DUPLICATE_OBJECTS"]["properties"]["count"]["maximum"] == 5


def test_configured_operation_limit_is_enforced_locally() -> None:
    limits = OperationLimits(max_operations_per_plan=1)

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(
            ready_plan(
                create_primitive_operation("first_cube"),
                create_primitive_operation("second_cube"),
            ),
            limits=limits,
        )


def test_configured_target_limit_is_enforced_locally() -> None:
    operation = deepcopy(VALID_OPERATIONS[3])
    operation["target_ids"] = ["obj_0001", "obj_0002", "obj_0003"]

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(
            ready_plan(operation),
            limits=OperationLimits(max_targets_per_operation=2),
        )


def test_configured_duplicate_output_limit_uses_targets_times_count() -> None:
    operation = deepcopy(VALID_OPERATIONS[2])
    operation["target_ids"] = ["obj_0001", "obj_0002"]
    operation["count"] = 3

    with pytest.raises(OperationContractError, match="more than 5"):
        validate_operation_plan(
            ready_plan(operation),
            limits=OperationLimits(
                max_targets_per_operation=2,
                max_duplicate_objects=5,
            ),
        )


@pytest.mark.parametrize(
    "operation",
    VALID_OPERATIONS,
    ids=[operation["type"].lower() for operation in VALID_OPERATIONS],
)
def test_each_supported_operation_validates(operation: dict[str, Any]) -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(operation)))

    assert plan.operations[0].type.value == operation["type"]


def test_valid_ready_plan_becomes_typed_model() -> None:
    plan = validate_operation_plan(ready_plan(create_primitive_operation()))

    assert plan.status is PlanStatus.READY
    assert plan.operations[0].type is OperationType.CREATE_PRIMITIVE
    assert plan.operations[0].operation_id == "create_cube"
    assert plan.operations[0].payload["primitive"] == "cube"


def test_validated_operation_payload_is_deeply_immutable() -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(VALID_OPERATIONS[8])))
    renames = plan.operations[0].payload["renames"]

    assert isinstance(renames, tuple)
    with pytest.raises(TypeError):
        renames[0]["new_name"] = "ChangedAfterApproval"


def test_valid_clarification_has_no_operations() -> None:
    plan = validate_operation_plan(
        {
            "snapshot_id": SNAPSHOT_ID,
            "status": "needs_clarification",
            "intent_summary": "The target objects are unclear.",
            "assumptions": [],
            "questions": ["Which objects should be changed?"],
            "operations": [],
        }
    )

    assert plan.status is PlanStatus.NEEDS_CLARIFICATION
    assert not plan.operations


def test_unknown_fields_are_rejected() -> None:
    operation = create_primitive_operation()
    operation["python_code"] = "import bpy"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_unknown_operation_type_is_rejected() -> None:
    operation = create_primitive_operation()
    operation["type"] = "RUN_PYTHON"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_ready_plan_requires_an_operation() -> None:
    with pytest.raises(OperationContractError, match="at least one operation"):
        validate_operation_plan(ready_plan())


def test_clarification_cannot_include_operations() -> None:
    data = {
        "snapshot_id": SNAPSHOT_ID,
        "status": "needs_clarification",
        "intent_summary": "More information is needed.",
        "assumptions": [],
        "questions": ["Continue?"],
        "operations": [create_primitive_operation()],
    }

    with pytest.raises(OperationContractError, match="cannot contain operations"):
        validate_operation_plan(data)


def test_duplicate_operation_ids_are_rejected() -> None:
    with pytest.raises(OperationContractError, match="Operation IDs must be unique"):
        validate_operation_plan(
            ready_plan(create_primitive_operation(), create_primitive_operation())
        )


def test_duplicate_target_ids_are_rejected_locally() -> None:
    operation = {
        "operation_id": "move_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001", "obj_0001"],
        "mode": "relative",
        "location": [1.0, 0.0, 0.0],
        "rotation_euler": None,
        "scale": None,
    }

    with pytest.raises(OperationContractError, match="target IDs must be unique"):
        validate_operation_plan(ready_plan(operation))


def test_plan_must_match_the_expected_scene_snapshot() -> None:
    with pytest.raises(OperationContractError, match="different scene snapshot"):
        validate_operation_plan(
            ready_plan(create_primitive_operation()),
            expected_snapshot_id="b" * 32,
        )


def test_transform_must_change_at_least_one_component() -> None:
    operation = {
        "operation_id": "transform_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001"],
        "mode": "absolute",
        "location": None,
        "rotation_euler": None,
        "scale": None,
    }

    with pytest.raises(OperationContractError, match="must change"):
        validate_operation_plan(ready_plan(operation))


def test_zero_scale_is_rejected() -> None:
    operation = create_primitive_operation()
    operation["scale"] = [1.0, 0.0, 1.0]

    with pytest.raises(OperationContractError, match="cannot be zero"):
        validate_operation_plan(ready_plan(operation))


def test_material_color_outside_normalized_range_is_rejected() -> None:
    operation = deepcopy(VALID_OPERATIONS[4])
    operation["base_color"] = [1.5, 0.0, 0.0]

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_non_finite_numbers_are_rejected() -> None:
    operation = create_primitive_operation()
    operation["location"] = [float("nan"), 0.0, 0.0]

    with pytest.raises(OperationContractError, match="non-finite"):
        validate_operation_plan(ready_plan(operation))


def test_duplicate_blast_radius_is_bounded() -> None:
    operation = {
        "operation_id": "duplicate_cubes",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001", "obj_0002"],
        "count": 51,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": None,
    }

    with pytest.raises(OperationContractError, match="more than 100"):
        validate_operation_plan(ready_plan(operation))


def test_later_operation_can_reference_an_earlier_creation_result() -> None:
    create_material = deepcopy(VALID_OPERATIONS[4])
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_red_material"

    plan = validate_operation_plan(ready_plan(create_material, assign_material))

    assert plan.operations[1].payload["material_id"] == "result:create_red_material"


def test_forward_result_reference_is_rejected() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_red_material"

    with pytest.raises(OperationContractError, match="earlier creation operation"):
        validate_operation_plan(
            ready_plan(assign_material, deepcopy(VALID_OPERATIONS[4]))
        )


def test_result_reference_must_have_the_expected_kind() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_cube"

    with pytest.raises(OperationContractError, match="produces object, not material"):
        validate_operation_plan(ready_plan(create_primitive_operation(), assign_material))


def test_snapshot_reference_prefix_must_match_the_field_kind() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "obj_0001"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(assign_material))


def test_sun_angular_size_is_bounded_in_radians() -> None:
    sun = deepcopy(VALID_OPERATIONS[6])
    sun["light_type"] = "sun"
    sun["size"] = 4.0

    with pytest.raises(OperationContractError, match="pi radians"):
        validate_operation_plan(ready_plan(sun))


def test_low_risk_plan_does_not_require_confirmation() -> None:
    plan = validate_operation_plan(ready_plan(create_primitive_operation()))

    assessment = assess_plan_risk(plan)

    assert assessment.level is RiskLevel.LOW
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    ("operation", "expected_level"),
    [
        (
            {
                "operation_id": "rename_cube",
                "type": "RENAME_OBJECTS",
                "renames": [{"target_id": "obj_0001", "new_name": "HeroCube"}],
            },
            RiskLevel.MEDIUM,
        ),
        (
            {
                "operation_id": "delete_cube",
                "type": "DELETE_OBJECTS",
                "target_ids": ["obj_0001"],
                "reason": "The user explicitly requested deletion.",
            },
            RiskLevel.HIGH,
        ),
    ],
)
def test_risky_operations_require_confirmation(
    operation: dict[str, Any],
    expected_level: RiskLevel,
) -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(operation)))

    assessment = assess_plan_risk(plan)

    assert assessment.level is expected_level
    assert assessment.requires_confirmation is True
