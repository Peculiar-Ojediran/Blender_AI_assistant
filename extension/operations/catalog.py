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
        OperationType.SET_MATERIAL_PROPERTIES: OperationSpec(
            OperationType.SET_MATERIAL_PROPERTIES,
            "Update a referenced Principled BSDF material.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.CREATE_COLLECTION: OperationSpec(
            OperationType.CREATE_COLLECTION,
            "Create a collection under the scene or a referenced parent collection.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.SET_LIGHT_PROPERTIES: OperationSpec(
            OperationType.SET_LIGHT_PROPERTIES,
            "Update referenced Blender light objects.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.SET_CAMERA_PROPERTIES: OperationSpec(
            OperationType.SET_CAMERA_PROPERTIES,
            "Update referenced camera objects and optionally make them active.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.ADD_MODIFIER: OperationSpec(
            OperationType.ADD_MODIFIER,
            "Add a supported non-applied modifier to mesh objects.",
            RiskLevel.MEDIUM,
            False,
            True,
            True,
        ),
        OperationType.SET_MODIFIER_PROPERTIES: OperationSpec(
            OperationType.SET_MODIFIER_PROPERTIES,
            "Update supported properties on existing object modifiers.",
            RiskLevel.MEDIUM,
            False,
            True,
            True,
        ),
        OperationType.CREATE_TEXT_OBJECT: OperationSpec(
            OperationType.CREATE_TEXT_OBJECT,
            "Create a Blender text object.",
            RiskLevel.LOW,
            False,
            False,
            True,
        ),
        OperationType.SET_OBJECT_VISIBILITY: OperationSpec(
            OperationType.SET_OBJECT_VISIBILITY,
            "Show or hide objects in viewport and render output.",
            RiskLevel.LOW,
            False,
            True,
            True,
        ),
        OperationType.IMPORT_ASSET: OperationSpec(
            OperationType.IMPORT_ASSET,
            "Import a supported local asset file.",
            RiskLevel.HIGH,
            False,
            False,
            True,
        ),
        OperationType.LINK_OR_APPEND_BLEND_DATA: OperationSpec(
            OperationType.LINK_OR_APPEND_BLEND_DATA,
            "Link or append explicit objects or collections from a local blend file.",
            RiskLevel.HIGH,
            False,
            False,
            True,
        ),
        OperationType.BOOLEAN_OPERATION: OperationSpec(
            OperationType.BOOLEAN_OPERATION,
            "Create a controlled non-applied Boolean modifier between two mesh objects.",
            RiskLevel.HIGH,
            True,
            True,
            True,
        ),
        OperationType.JOIN_OBJECTS: OperationSpec(
            OperationType.JOIN_OBJECTS,
            "Join mesh objects into one generated mesh object.",
            RiskLevel.HIGH,
            True,
            True,
            True,
        ),
        OperationType.SEPARATE_OBJECTS: OperationSpec(
            OperationType.SEPARATE_OBJECTS,
            "Separate mesh objects into generated mesh objects by material or loose parts.",
            RiskLevel.HIGH,
            True,
            True,
            True,
        ),
    }
)


def get_operation_spec(operation_type: OperationType) -> OperationSpec:
    return OPERATION_CATALOG[operation_type]
