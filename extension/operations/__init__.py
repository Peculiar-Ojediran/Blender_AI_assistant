"""Controlled Blender operation contract, validation, and execution."""

from .catalog import OPERATION_CATALOG, OperationSpec, get_operation_spec
from .executor import (
    ChangeKind,
    ChangeRecord,
    ExecutionError,
    ExecutionPreflightError,
    ExecutionResult,
    PlanExecutionError,
    PreparedExecution,
    execute_plan,
    preflight_plan,
)
from .limits import (
    DEFAULT_MAX_DUPLICATE_OBJECTS,
    DEFAULT_MAX_OPERATIONS_PER_PLAN,
    DEFAULT_MAX_TARGETS_PER_OPERATION,
    DEFAULT_OPERATION_LIMITS,
    HARD_MAX_DUPLICATE_OBJECTS,
    HARD_MAX_OPERATIONS_PER_PLAN,
    HARD_MAX_TARGETS_PER_OPERATION,
    OperationLimits,
)
from .models import (
    Operation,
    OperationPlan,
    OperationType,
    PlanStatus,
    RiskAssessment,
    RiskLevel,
)
from .risk import affected_object_count, assess_plan_risk
from .schema import (
    OPERATION_PLAN_SCHEMA,
    OPERATION_SCHEMAS,
    build_operation_plan_schema,
    build_operation_schemas,
)
from .validator import OperationContractError, SnapshotMismatchError, validate_operation_plan

__all__ = [
    "DEFAULT_MAX_DUPLICATE_OBJECTS",
    "DEFAULT_MAX_OPERATIONS_PER_PLAN",
    "DEFAULT_MAX_TARGETS_PER_OPERATION",
    "DEFAULT_OPERATION_LIMITS",
    "HARD_MAX_DUPLICATE_OBJECTS",
    "HARD_MAX_OPERATIONS_PER_PLAN",
    "HARD_MAX_TARGETS_PER_OPERATION",
    "OPERATION_CATALOG",
    "OPERATION_PLAN_SCHEMA",
    "OPERATION_SCHEMAS",
    "ChangeKind",
    "ChangeRecord",
    "ExecutionError",
    "ExecutionPreflightError",
    "ExecutionResult",
    "Operation",
    "OperationContractError",
    "OperationLimits",
    "OperationPlan",
    "OperationSpec",
    "OperationType",
    "PlanExecutionError",
    "PlanStatus",
    "PreparedExecution",
    "RiskAssessment",
    "RiskLevel",
    "SnapshotMismatchError",
    "affected_object_count",
    "assess_plan_risk",
    "build_operation_plan_schema",
    "build_operation_schemas",
    "execute_plan",
    "get_operation_spec",
    "preflight_plan",
    "validate_operation_plan",
]
