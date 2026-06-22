"""Conservative defaults and configurable controlled-operation ceilings."""

from dataclasses import dataclass

DEFAULT_MAX_OPERATIONS_PER_PLAN = 20
DEFAULT_MAX_TARGETS_PER_OPERATION = 100
DEFAULT_MAX_DUPLICATE_OBJECTS = 100

HARD_MAX_OPERATIONS_PER_PLAN = 100
HARD_MAX_TARGETS_PER_OPERATION = 500
HARD_MAX_DUPLICATE_OBJECTS = 1_000


@dataclass(frozen=True, slots=True)
class OperationLimits:
    max_operations_per_plan: int = DEFAULT_MAX_OPERATIONS_PER_PLAN
    max_targets_per_operation: int = DEFAULT_MAX_TARGETS_PER_OPERATION
    max_duplicate_objects: int = DEFAULT_MAX_DUPLICATE_OBJECTS

    def __post_init__(self) -> None:
        _validate_limit(
            "max_operations_per_plan",
            self.max_operations_per_plan,
            HARD_MAX_OPERATIONS_PER_PLAN,
        )
        _validate_limit(
            "max_targets_per_operation",
            self.max_targets_per_operation,
            HARD_MAX_TARGETS_PER_OPERATION,
        )
        _validate_limit(
            "max_duplicate_objects",
            self.max_duplicate_objects,
            HARD_MAX_DUPLICATE_OBJECTS,
        )


def _validate_limit(name: str, value: int, hard_maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")
    if not 1 <= value <= hard_maximum:
        raise ValueError(f"{name} must be between 1 and {hard_maximum}.")


DEFAULT_OPERATION_LIMITS = OperationLimits()
