"""Derive non-bypassable approval and recovery requirements locally."""

from dataclasses import dataclass

from ..operations.catalog import get_operation_spec
from ..operations.models import OperationPlan, PlanStatus, RiskAssessment, RiskLevel
from ..operations.risk import assess_plan_risk

PROHIBITED_CAPABILITIES: tuple[str, ...] = (
    "arbitrary_python",
    "file_read",
    "file_write",
    "external_asset_download",
    "subprocess_execution",
)


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    risk: RiskAssessment
    explicit_approval_required: bool
    secondary_confirmation_required: bool
    recovery_point_required: bool
    blocked: bool
    reasons: tuple[str, ...]


class SafetyPolicyError(RuntimeError):
    """Raised when local policy blocks an otherwise valid plan."""


class SafetyConfirmationRequired(SafetyPolicyError):
    """Raised when a high-risk plan bypasses its second confirmation."""


def evaluate_plan_safety(
    plan: OperationPlan,
    *,
    global_undo_available: bool | None = None,
) -> SafetyDecision:
    risk = assess_plan_risk(plan)
    reasons = list(risk.reasons)
    blocked = plan.status is not PlanStatus.READY

    if blocked:
        reasons.append("Only a ready plan can be approved for execution.")

    specs = tuple(get_operation_spec(operation.type) for operation in plan.operations)
    unsupported_undo = tuple(spec.type.value for spec in specs if not spec.undo_expected)
    if unsupported_undo:
        blocked = True
        reasons.append(
            "Reliable undo is unavailable for: " + ", ".join(unsupported_undo) + "."
        )

    destructive = any(spec.destructive for spec in specs)
    recovery_point_required = destructive or risk.level is RiskLevel.HIGH
    if recovery_point_required and global_undo_available is False:
        blocked = True
        reasons.append(
            "Destructive and high-risk plans require Blender Global Undo to be enabled."
        )

    return SafetyDecision(
        risk=risk,
        explicit_approval_required=True,
        secondary_confirmation_required=risk.level is RiskLevel.HIGH,
        recovery_point_required=recovery_point_required,
        blocked=blocked,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def authorize_plan_execution(
    decision: SafetyDecision,
    *,
    secondary_confirmation: bool,
) -> None:
    if decision.blocked:
        detail = " ".join(decision.reasons) or "The plan is blocked by local safety policy."
        raise SafetyPolicyError(detail)
    if decision.secondary_confirmation_required and not secondary_confirmation:
        raise SafetyConfirmationRequired(
            "High-risk plans require a second explicit confirmation."
        )
