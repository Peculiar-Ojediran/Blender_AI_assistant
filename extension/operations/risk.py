"""Derive risk and confirmation requirements from validated operations."""

from .catalog import get_operation_spec
from .models import OperationPlan, OperationType, RiskAssessment, RiskLevel
from .targets import RESULT_REFERENCE_PREFIX

_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
_BROAD_PLAN_MEDIUM_THRESHOLD = 10
_BROAD_PLAN_HIGH_THRESHOLD = 25


def assess_plan_risk(plan: OperationPlan) -> RiskAssessment:
    level = RiskLevel.LOW
    reasons: list[str] = []
    reason_set: set[str] = set()

    for operation in plan.operations:
        spec = get_operation_spec(operation.type)
        if _RISK_RANK[spec.base_risk] > _RISK_RANK[level]:
            level = spec.base_risk
        if spec.base_risk is not RiskLevel.LOW:
            reason = f"{operation.type.value} has {spec.base_risk.value} base risk."
            if reason not in reason_set:
                reasons.append(reason)
                reason_set.add(reason)

    target_count = affected_object_count(plan)
    if target_count > _BROAD_PLAN_HIGH_THRESHOLD and level is not RiskLevel.HIGH:
        level = RiskLevel.HIGH
        reasons.append(f"The plan affects {target_count} objects.")
    elif target_count > _BROAD_PLAN_MEDIUM_THRESHOLD and level is RiskLevel.LOW:
        level = RiskLevel.MEDIUM
        reasons.append(f"The plan affects {target_count} objects.")

    if len(plan.operations) > _BROAD_PLAN_MEDIUM_THRESHOLD and level is RiskLevel.LOW:
        level = RiskLevel.MEDIUM
        reasons.append(f"The plan contains {len(plan.operations)} operations.")

    return RiskAssessment(
        level=level,
        requires_confirmation=level is not RiskLevel.LOW,
        reasons=tuple(reasons),
        affected_object_count=target_count,
    )


def affected_object_count(plan: OperationPlan) -> int:
    existing_targets = {
        target_id
        for operation in plan.operations
        for target_id in operation.target_ids
        if not target_id.startswith(RESULT_REFERENCE_PREFIX)
    }
    created_objects = 0
    for operation in plan.operations:
        if operation.type in {
            OperationType.CREATE_PRIMITIVE,
            OperationType.ADD_LIGHT,
            OperationType.ADD_CAMERA,
        }:
            created_objects += 1
        elif operation.type is OperationType.DUPLICATE_OBJECTS:
            created_objects += len(operation.target_ids) * int(operation.payload["count"])
    return len(existing_targets) + created_objects
