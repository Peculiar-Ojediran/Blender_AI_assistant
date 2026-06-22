from typing import Any

import pytest

from extension.operations import RiskLevel, assess_plan_risk, validate_operation_plan
from extension.safety import (
    PROHIBITED_CAPABILITIES,
    SafetyConfirmationRequired,
    SafetyPolicyError,
    authorize_plan_execution,
    evaluate_plan_safety,
)

SNAPSHOT_ID = "a" * 32


def ready_plan(*operations: dict[str, Any]) -> Any:
    return validate_operation_plan(
        {
            "snapshot_id": SNAPSHOT_ID,
            "status": "ready",
            "intent_summary": "Apply a controlled plan.",
            "assumptions": [],
            "questions": [],
            "operations": list(operations),
        }
    )


def create_cube(operation_id: str = "create_cube") -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "type": "CREATE_PRIMITIVE",
        "primitive": "cube",
        "name": operation_id,
        "collection_id": None,
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def delete_cube() -> dict[str, Any]:
    return {
        "operation_id": "delete_cube",
        "type": "DELETE_OBJECTS",
        "target_ids": ["obj_0001"],
        "reason": "The user explicitly requested deletion.",
    }


def test_every_plan_requires_approval_but_low_risk_needs_no_second_confirmation() -> None:
    decision = evaluate_plan_safety(ready_plan(create_cube()))

    assert decision.explicit_approval_required
    assert not decision.secondary_confirmation_required
    assert not decision.blocked
    assert decision.risk.level is RiskLevel.LOW
    assert decision.risk.affected_object_count == 1


def test_destructive_plan_requires_global_undo() -> None:
    decision = evaluate_plan_safety(
        ready_plan(delete_cube()),
        global_undo_available=False,
    )

    assert decision.blocked
    assert decision.secondary_confirmation_required
    assert decision.recovery_point_required
    with pytest.raises(SafetyPolicyError, match="Global Undo"):
        authorize_plan_execution(decision, secondary_confirmation=True)


def test_high_risk_plan_cannot_bypass_second_confirmation() -> None:
    decision = evaluate_plan_safety(
        ready_plan(delete_cube()),
        global_undo_available=True,
    )

    with pytest.raises(SafetyConfirmationRequired, match="second explicit"):
        authorize_plan_execution(decision, secondary_confirmation=False)

    authorize_plan_execution(decision, secondary_confirmation=True)


def test_broad_non_destructive_plan_requires_global_undo_and_recovery() -> None:
    duplicate = {
        "operation_id": "duplicate_cube",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001"],
        "count": 30,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": "Copy",
    }

    blocked = evaluate_plan_safety(
        ready_plan(duplicate),
        global_undo_available=False,
    )
    allowed = evaluate_plan_safety(
        ready_plan(duplicate),
        global_undo_available=True,
    )

    assert blocked.blocked
    assert blocked.recovery_point_required
    assert "Global Undo" in " ".join(blocked.reasons)
    assert not allowed.blocked
    assert allowed.secondary_confirmation_required
    assert allowed.recovery_point_required


def test_blast_radius_counts_unique_existing_and_created_objects() -> None:
    transform_one = {
        "operation_id": "move_once",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001"],
        "mode": "relative",
        "location": [1.0, 0.0, 0.0],
        "rotation_euler": None,
        "scale": None,
    }
    transform_two = {**transform_one, "operation_id": "move_twice"}
    duplicate = {
        "operation_id": "duplicate_cube",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001"],
        "count": 30,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": "Copy",
    }
    assessment = assess_plan_risk(
        ready_plan(transform_one, transform_two, duplicate, create_cube("new_cube"))
    )

    assert assessment.affected_object_count == 32
    assert assessment.level is RiskLevel.HIGH
    assert any("affects 32 objects" in reason for reason in assessment.reasons)


def test_prohibited_capabilities_cover_code_file_and_process_access() -> None:
    assert {
        "arbitrary_python",
        "file_read",
        "file_write",
        "external_asset_download",
        "subprocess_execution",
    }.issubset(PROHIBITED_CAPABILITIES)
