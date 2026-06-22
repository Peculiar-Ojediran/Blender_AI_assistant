"""Catalog supported operation behavior and local safety metadata."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .models import OperationType, RiskLevel


@dataclass(frozen=True, slots=True)
class OperationSpec:
    type: OperationType
    description: str
    base_risk: RiskLevel
    destructive: bool
    requires_targets: bool
    undo_expected: bool


OPERATION_CATALOG: Mapping[OperationType, OperationSpec] = MappingProxyType(
    {
        OperationType.CREATE_PRIMITIVE: OperationSpec(
            OperationType.CREATE_PRIMITIVE,
            "Create a supported mesh primitive.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.DELETE_OBJECTS: OperationSpec(
            OperationType.DELETE_OBJECTS,
            "Delete existing objects by context-issued target ID.",
            RiskLevel.HIGH,
            True,
            True,
            True,
        ),
        OperationType.DUPLICATE_OBJECTS: OperationSpec(
            OperationType.DUPLICATE_OBJECTS,
            "Duplicate existing objects with a bounded count and offset.",
            RiskLevel.MEDIUM,
            False,
            True,
            True,
        ),
        OperationType.SET_TRANSFORM: OperationSpec(
            OperationType.SET_TRANSFORM,
            "Set or offset object transforms.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.CREATE_MATERIAL: OperationSpec(
            OperationType.CREATE_MATERIAL,
            "Create a basic Principled BSDF material.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.ASSIGN_MATERIAL: OperationSpec(
            OperationType.ASSIGN_MATERIAL,
            "Assign a referenced material to objects.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.ADD_LIGHT: OperationSpec(
            OperationType.ADD_LIGHT,
            "Add a supported Blender light.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.ADD_CAMERA: OperationSpec(
            OperationType.ADD_CAMERA,
            "Add a camera and optionally make it active.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.RENAME_OBJECTS: OperationSpec(
            OperationType.RENAME_OBJECTS,
            "Rename existing objects with explicit target-to-name mappings.",
            RiskLevel.MEDIUM,
            False,
            True,
            True,
        ),
        OperationType.MOVE_TO_COLLECTION: OperationSpec(
            OperationType.MOVE_TO_COLLECTION,
            "Move existing objects to an existing collection.",
            RiskLevel.MEDIUM,
            False,
            True,
            True,
        ),
    }
)


def get_operation_spec(operation_type: OperationType) -> OperationSpec:
    return OPERATION_CATALOG[operation_type]
