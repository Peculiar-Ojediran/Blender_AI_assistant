"""Strict JSON Schema supplied to AI providers for operation planning."""

from typing import Any

from .limits import DEFAULT_OPERATION_LIMITS, OperationLimits
from .models import OperationType, PlanStatus

MAX_STRING_LENGTH = 200
MAX_NAME_LENGTH = 128
MAX_FILE_PATH_LENGTH = 1024


def _bounded_number(minimum: float, maximum: float) -> dict[str, Any]:
    return {"type": "number", "minimum": minimum, "maximum": maximum}


def _vector(length: int, minimum: float, maximum: float) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _bounded_number(minimum, maximum),
        "minItems": length,
        "maxItems": length,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _identifier() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": "^[A-Za-z][A-Za-z0-9_-]*$",
    }


def _name() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": MAX_NAME_LENGTH}


def _reference(prefix: str, *, allow_result: bool = True) -> dict[str, Any]:
    context_reference = {
        "type": "string",
        "pattern": f"^{prefix}_[0-9]{{4,}}$",
        "maxLength": MAX_STRING_LENGTH,
    }
    if not allow_result:
        return context_reference
    return {
        "anyOf": [
            context_reference,
            {
                "type": "string",
                "pattern": "^result:[A-Za-z][A-Za-z0-9_-]*$",
                "maxLength": MAX_STRING_LENGTH,
            },
        ]
    }


def _target_ids(maximum: int, minimum: int = 1) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _reference("obj"),
        "minItems": minimum,
        "maxItems": maximum,
    }


def _file_path() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": MAX_FILE_PATH_LENGTH}


def _asset_source() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": MAX_FILE_PATH_LENGTH}


def _name_array(maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "items": _name(),
        "minItems": 1,
        "maxItems": maximum,
    }


def _operation_schema(
    operation_type: OperationType,
    properties: dict[str, Any],
) -> dict[str, Any]:
    all_properties = {
        "operation_id": _identifier(),
        "type": {"type": "string", "enum": [operation_type.value]},
        **properties,
    }
    return {
        "type": "object",
        "properties": all_properties,
        "required": list(all_properties),
        "additionalProperties": False,
    }


def build_operation_schemas(
    limits: OperationLimits = DEFAULT_OPERATION_LIMITS,
) -> dict[OperationType, dict[str, Any]]:
    targets = limits.max_targets_per_operation
    return {
        OperationType.CREATE_PRIMITIVE: _operation_schema(
            OperationType.CREATE_PRIMITIVE,
            {
                "primitive": {
                    "type": "string",
                    "enum": ["cube", "sphere", "cylinder", "cone", "plane", "torus"],
                },
                "name": _name(),
                "collection_id": _nullable(_reference("col")),
                "location": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation_euler": _vector(3, -1_000_000.0, 1_000_000.0),
                "scale": _vector(3, -10_000.0, 10_000.0),
            },
        ),
        OperationType.DELETE_OBJECTS: _operation_schema(
            OperationType.DELETE_OBJECTS,
            {
                "target_ids": _target_ids(targets),
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_STRING_LENGTH,
                },
            },
        ),
        OperationType.DUPLICATE_OBJECTS: _operation_schema(
            OperationType.DUPLICATE_OBJECTS,
            {
                "target_ids": _target_ids(targets),
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": limits.max_duplicate_objects,
                },
                "offset": _vector(3, -1_000_000.0, 1_000_000.0),
                "name_prefix": _nullable(_name()),
            },
        ),
        OperationType.SET_TRANSFORM: _operation_schema(
            OperationType.SET_TRANSFORM,
            {
                "target_ids": _target_ids(targets),
                "mode": {"type": "string", "enum": ["absolute", "relative"]},
                "location": _nullable(_vector(3, -1_000_000.0, 1_000_000.0)),
                "rotation_euler": _nullable(_vector(3, -1_000_000.0, 1_000_000.0)),
                "scale": _nullable(_vector(3, -10_000.0, 10_000.0)),
            },
        ),
        OperationType.CREATE_MATERIAL: _operation_schema(
            OperationType.CREATE_MATERIAL,
            {
                "name": _name(),
                "base_color": _vector(3, 0.0, 1.0),
                "metallic": _bounded_number(0.0, 1.0),
                "roughness": _bounded_number(0.0, 1.0),
                "alpha": _bounded_number(0.0, 1.0),
            },
        ),
        OperationType.ASSIGN_MATERIAL: _operation_schema(
            OperationType.ASSIGN_MATERIAL,
            {
                "target_ids": _target_ids(targets),
                "material_id": _reference("mat"),
            },
        ),
        OperationType.ADD_LIGHT: _operation_schema(
            OperationType.ADD_LIGHT,
            {
                "light_type": {
                    "type": "string",
                    "enum": ["point", "sun", "spot", "area"],
                },
                "name": _name(),
                "collection_id": _nullable(_reference("col")),
                "location": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation_euler": _vector(3, -1_000_000.0, 1_000_000.0),
                "color": _vector(3, 0.0, 1.0),
                "energy": _bounded_number(0.0, 1_000_000_000.0),
                "size": _bounded_number(0.001, 1_000_000.0),
            },
        ),
        OperationType.ADD_CAMERA: _operation_schema(
            OperationType.ADD_CAMERA,
            {
                "name": _name(),
                "collection_id": _nullable(_reference("col")),
                "location": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation_euler": _vector(3, -1_000_000.0, 1_000_000.0),
                "focal_length": _bounded_number(1.0, 1_000.0),
                "make_active": {"type": "boolean"},
            },
        ),
        OperationType.RENAME_OBJECTS: _operation_schema(
            OperationType.RENAME_OBJECTS,
            {
                "renames": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target_id": _reference("obj"),
                            "new_name": _name(),
                        },
                        "required": ["target_id", "new_name"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": targets,
                }
            },
        ),
        OperationType.MOVE_TO_COLLECTION: _operation_schema(
            OperationType.MOVE_TO_COLLECTION,
            {
                "target_ids": _target_ids(targets),
                "collection_id": _reference("col"),
            },
        ),
        OperationType.SET_MATERIAL_PROPERTIES: _operation_schema(
            OperationType.SET_MATERIAL_PROPERTIES,
            {
                "material_id": _reference("mat"),
                "base_color": _nullable(_vector(3, 0.0, 1.0)),
                "metallic": _nullable(_bounded_number(0.0, 1.0)),
                "roughness": _nullable(_bounded_number(0.0, 1.0)),
                "alpha": _nullable(_bounded_number(0.0, 1.0)),
            },
        ),
        OperationType.CREATE_COLLECTION: _operation_schema(
            OperationType.CREATE_COLLECTION,
            {
                "name": _name(),
                "parent_collection_id": _nullable(_reference("col")),
            },
        ),
        OperationType.SET_LIGHT_PROPERTIES: _operation_schema(
            OperationType.SET_LIGHT_PROPERTIES,
            {
                "target_ids": _target_ids(targets),
                "color": _nullable(_vector(3, 0.0, 1.0)),
                "energy": _nullable(_bounded_number(0.0, 1_000_000_000.0)),
                "size": _nullable(_bounded_number(0.001, 1_000_000.0)),
            },
        ),
        OperationType.SET_CAMERA_PROPERTIES: _operation_schema(
            OperationType.SET_CAMERA_PROPERTIES,
            {
                "target_ids": _target_ids(targets),
                "focal_length": _nullable(_bounded_number(1.0, 1_000.0)),
                "make_active": _nullable({"type": "boolean"}),
            },
        ),
        OperationType.ADD_MODIFIER: _operation_schema(
            OperationType.ADD_MODIFIER,
            {
                "target_ids": _target_ids(targets),
                "modifier_type": {
                    "type": "string",
                    "enum": [
                        "bevel",
                        "solidify",
                        "mirror",
                        "subdivision_surface",
                        "array",
                        "weighted_normal",
                    ],
                },
                "name": _name(),
                "width": _nullable(_bounded_number(0.0, 1_000.0)),
                "segments": _nullable({"type": "integer", "minimum": 1, "maximum": 64}),
                "thickness": _nullable(_bounded_number(-1_000.0, 1_000.0)),
                "count": _nullable({"type": "integer", "minimum": 1, "maximum": 1_000}),
                "relative_offset": _nullable(_vector(3, -1_000.0, 1_000.0)),
                "levels": _nullable({"type": "integer", "minimum": 0, "maximum": 6}),
                "axis": _nullable({"type": "string", "enum": ["X", "Y", "Z"]}),
            },
        ),
        OperationType.SET_MODIFIER_PROPERTIES: _operation_schema(
            OperationType.SET_MODIFIER_PROPERTIES,
            {
                "target_ids": _target_ids(targets),
                "modifier_name": _name(),
                "width": _nullable(_bounded_number(0.0, 1_000.0)),
                "segments": _nullable({"type": "integer", "minimum": 1, "maximum": 64}),
                "thickness": _nullable(_bounded_number(-1_000.0, 1_000.0)),
                "count": _nullable({"type": "integer", "minimum": 1, "maximum": 1_000}),
                "relative_offset": _nullable(_vector(3, -1_000.0, 1_000.0)),
                "levels": _nullable({"type": "integer", "minimum": 0, "maximum": 6}),
                "axis": _nullable({"type": "string", "enum": ["X", "Y", "Z"]}),
            },
        ),
        OperationType.CREATE_TEXT_OBJECT: _operation_schema(
            OperationType.CREATE_TEXT_OBJECT,
            {
                "name": _name(),
                "collection_id": _nullable(_reference("col")),
                "body": {"type": "string", "minLength": 1, "maxLength": 1_000},
                "location": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation_euler": _vector(3, -1_000_000.0, 1_000_000.0),
                "scale": _vector(3, -10_000.0, 10_000.0),
                "align_x": {"type": "string", "enum": ["LEFT", "CENTER", "RIGHT"]},
                "align_y": {"type": "string", "enum": ["TOP", "CENTER", "BOTTOM"]},
                "size": _bounded_number(0.001, 1_000_000.0),
                "extrude": _bounded_number(0.0, 1_000.0),
            },
        ),
        OperationType.SET_OBJECT_VISIBILITY: _operation_schema(
            OperationType.SET_OBJECT_VISIBILITY,
            {
                "target_ids": _target_ids(targets),
                "viewport_visible": _nullable({"type": "boolean"}),
                "render_visible": _nullable({"type": "boolean"}),
            },
        ),
        OperationType.IMPORT_ASSET: _operation_schema(
            OperationType.IMPORT_ASSET,
            {
                "filepath": _asset_source(),
                "format": {"type": "string", "enum": ["obj", "fbx", "gltf", "glb"]},
                "collection_id": _nullable(_reference("col")),
                "name_prefix": _nullable(_name()),
                "location": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation_euler": _vector(3, -1_000_000.0, 1_000_000.0),
                "scale": _vector(3, -10_000.0, 10_000.0),
            },
        ),
        OperationType.LINK_OR_APPEND_BLEND_DATA: _operation_schema(
            OperationType.LINK_OR_APPEND_BLEND_DATA,
            {
                "filepath": _file_path(),
                "mode": {"type": "string", "enum": ["link", "append"]},
                "datablock_type": {"type": "string", "enum": ["object", "collection"]},
                "datablock_names": _name_array(targets),
                "collection_id": _nullable(_reference("col")),
                "name_prefix": _nullable(_name()),
            },
        ),
        OperationType.BOOLEAN_OPERATION: _operation_schema(
            OperationType.BOOLEAN_OPERATION,
            {
                "target_id": _reference("obj"),
                "cutter_id": _reference("obj"),
                "boolean_operation": {
                    "type": "string",
                    "enum": ["difference", "union", "intersect"],
                },
                "solver": {"type": "string", "enum": ["exact", "fast"]},
                "apply": {"type": "boolean", "enum": [False]},
                "modifier_name": _name(),
                "hide_cutter": {"type": "boolean"},
            },
        ),
        OperationType.JOIN_OBJECTS: _operation_schema(
            OperationType.JOIN_OBJECTS,
            {
                "target_ids": _target_ids(targets, minimum=2),
                "new_name": _name(),
                "collection_id": _nullable(_reference("col")),
            },
        ),
        OperationType.SEPARATE_OBJECTS: _operation_schema(
            OperationType.SEPARATE_OBJECTS,
            {
                "target_ids": _target_ids(targets),
                "mode": {"type": "string", "enum": ["by_material", "loose_parts"]},
                "name_prefix": _name(),
                "collection_id": _nullable(_reference("col")),
            },
        ),
    }


def build_operation_plan_schema(
    limits: OperationLimits = DEFAULT_OPERATION_LIMITS,
) -> dict[str, Any]:
    operation_schemas = build_operation_schemas(limits)
    return {
        "type": "object",
        "properties": {
            "snapshot_id": {
                "type": "string",
                "pattern": "^[a-f0-9]{32}$",
            },
            "status": {"type": "string", "enum": [status.value for status in PlanStatus]},
            "intent_summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
            "assumptions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_STRING_LENGTH,
                },
                "maxItems": 10,
            },
            "questions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
                "maxItems": 5,
            },
            "operations": {
                "type": "array",
                "items": {"anyOf": list(operation_schemas.values())},
                "maxItems": limits.max_operations_per_plan,
            },
        },
        "required": [
            "snapshot_id",
            "status",
            "intent_summary",
            "assumptions",
            "questions",
            "operations",
        ],
        "additionalProperties": False,
    }


OPERATION_SCHEMAS = build_operation_schemas()
OPERATION_PLAN_SCHEMA = build_operation_plan_schema()
