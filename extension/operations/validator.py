"""Validate provider plans against the controlled-operation contract."""

import math
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any

import fastjsonschema

from .limits import DEFAULT_OPERATION_LIMITS, OperationLimits
from .models import Operation, OperationPlan, OperationType, PlanStatus
from .schema import build_operation_plan_schema

RESULT_REFERENCE_PREFIX = "result:"

_RESULT_KINDS = {
    OperationType.CREATE_PRIMITIVE: "object",
    OperationType.CREATE_MATERIAL: "material",
    OperationType.ADD_LIGHT: "object",
    OperationType.ADD_CAMERA: "object",
}


class OperationContractError(ValueError):
    """Raised when provider data violates the controlled-operation contract."""


class SnapshotMismatchError(OperationContractError):
    """Raised when a plan does not belong to the retained context snapshot."""


def validate_operation_plan(
    data: Mapping[str, Any],
    *,
    expected_snapshot_id: str | None = None,
    limits: OperationLimits = DEFAULT_OPERATION_LIMITS,
) -> OperationPlan:
    plan_data = dict(data)

    try:
        _schema_validator(limits)(plan_data)
    except fastjsonschema.JsonSchemaException as exc:
        raise OperationContractError(f"Plan schema validation failed: {exc.message}") from exc

    _reject_non_finite_numbers(plan_data)
    _validate_plan_state(plan_data)
    if expected_snapshot_id is not None and plan_data["snapshot_id"] != expected_snapshot_id:
        raise SnapshotMismatchError("The plan was created for a different scene snapshot.")
    _validate_unique_operation_ids(plan_data)
    _validate_operation_semantics(plan_data, limits)

    return _to_operation_plan(plan_data)


def _validate_plan_state(data: Mapping[str, Any]) -> None:
    status = data["status"]
    operations = data["operations"]
    questions = data["questions"]

    if status == PlanStatus.READY.value:
        if not operations:
            raise OperationContractError("A ready plan must contain at least one operation.")
        if questions:
            raise OperationContractError("A ready plan cannot contain clarification questions.")
        return

    if operations:
        raise OperationContractError("A clarification response cannot contain operations.")
    if not questions:
        raise OperationContractError("A clarification response must contain at least one question.")


def _validate_unique_operation_ids(data: Mapping[str, Any]) -> None:
    operation_ids = [operation["operation_id"] for operation in data["operations"]]
    if len(operation_ids) != len(set(operation_ids)):
        raise OperationContractError("Operation IDs must be unique within a plan.")


@lru_cache(maxsize=32)
def _schema_validator(limits: OperationLimits) -> Any:
    return fastjsonschema.compile(build_operation_plan_schema(limits))


def _validate_operation_semantics(
    data: Mapping[str, Any],
    limits: OperationLimits,
) -> None:
    available_results: dict[str, str] = {}
    for operation in data["operations"]:
        operation_type = OperationType(operation["type"])

        target_ids = operation.get("target_ids", [])
        if len(target_ids) != len(set(target_ids)):
            raise OperationContractError(
                f"{operation_type.value} target IDs must be unique."
            )

        _validate_result_references(operation, available_results)

        if operation_type is OperationType.SET_TRANSFORM:
            transform_values = (
                operation["location"],
                operation["rotation_euler"],
                operation["scale"],
            )
            if all(value is None for value in transform_values):
                raise OperationContractError(
                    "SET_TRANSFORM must change location, rotation, or scale."
                )

        scale = operation.get("scale")
        if isinstance(scale, list) and any(abs(component) < 1e-9 for component in scale):
            raise OperationContractError("Scale components cannot be zero.")

        if operation_type is OperationType.DUPLICATE_OBJECTS:
            created_count = len(operation["target_ids"]) * operation["count"]
            if created_count > limits.max_duplicate_objects:
                message = (
                    "DUPLICATE_OBJECTS cannot create more than "
                    f"{limits.max_duplicate_objects} objects."
                )
                raise OperationContractError(message)

        if (
            operation_type is OperationType.ADD_LIGHT
            and operation["light_type"] == "sun"
            and operation["size"] > math.pi
        ):
            raise OperationContractError("Sun light angular size cannot exceed pi radians.")

        if operation_type is OperationType.RENAME_OBJECTS:
            target_ids = [rename["target_id"] for rename in operation["renames"]]
            if len(target_ids) != len(set(target_ids)):
                raise OperationContractError(
                    "RENAME_OBJECTS cannot rename the same target more than once."
                )

        result_kind = _RESULT_KINDS.get(operation_type)
        if result_kind is not None:
            available_results[operation["operation_id"]] = result_kind


def _validate_result_references(
    operation: Mapping[str, Any],
    available_results: Mapping[str, str],
) -> None:
    references: list[tuple[str, str]] = []
    references.extend((target_id, "object") for target_id in operation.get("target_ids", []))
    references.extend(
        (rename["target_id"], "object") for rename in operation.get("renames", [])
    )

    material_id = operation.get("material_id")
    if isinstance(material_id, str):
        references.append((material_id, "material"))

    for reference, expected_kind in references:
        if not reference.startswith(RESULT_REFERENCE_PREFIX):
            continue
        operation_id = reference.removeprefix(RESULT_REFERENCE_PREFIX)
        actual_kind = available_results.get(operation_id)
        if actual_kind is None:
            raise OperationContractError(
                f"Result reference {reference} must name an earlier creation operation."
            )
        if actual_kind != expected_kind:
            raise OperationContractError(
                f"Result reference {reference} produces {actual_kind}, not {expected_kind}."
            )


def _reject_non_finite_numbers(value: Any, path: str = "plan") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise OperationContractError(f"{path} contains a non-finite number.")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_non_finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_non_finite_numbers(child, f"{path}[{index}]")


def _to_operation_plan(data: Mapping[str, Any]) -> OperationPlan:
    operations = tuple(
        Operation(
            operation_id=operation["operation_id"],
            type=OperationType(operation["type"]),
            payload=MappingProxyType(
                {
                    key: _deep_freeze(value)
                    for key, value in operation.items()
                    if key not in {"operation_id", "type"}
                }
            ),
        )
        for operation in data["operations"]
    )

    return OperationPlan(
        snapshot_id=data["snapshot_id"],
        status=PlanStatus(data["status"]),
        intent_summary=data["intent_summary"],
        assumptions=tuple(data["assumptions"]),
        questions=tuple(data["questions"]),
        operations=operations,
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(child) for key, child in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(child) for child in value)
    return value
