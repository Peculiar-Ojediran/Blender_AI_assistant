"""Strict JSON Schema supplied to AI providers for operation planning."""

from typing import Any

from .limits import DEFAULT_OPERATION_LIMITS, OperationLimits
from .models import OperationType, PlanStatus
from .registries import (
    GENERATED_MESH_VARIANTS,
    GENERATED_TEXTURE_PATTERNS,
    GEOMETRY_NODE_GROUP_TEMPLATES,
    GEOMETRY_NODE_INPUTS,
    GEOMETRY_NODES_PRESETS,
    MATERIAL_FAMILIES,
    MESH_PROCESSING_LIMITS,
    PBR_TEXTURE_ROLES,
    PREVIEW_IMAGE_KINDS,
    PROCEDURAL_PATTERNS,
    RENDER_PREVIEW_MODES,
    SCULPT_REGION_OPERATIONS,
    SHADER_GRAPH_TEMPLATES,
    SHADER_MIX_CHAIN_TEMPLATES,
    SHADER_NODE_REFERENCES,
    SHADER_NODE_TYPES,
    SHADER_SOCKET_NAMES,
    TEXTURE_BAKE_PASS_TYPES,
    TEXTURE_BLEND_MODES,
    TEXTURE_EXTENSION_MODES,
    TEXTURE_PROJECTION_MODES,
)

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


def _result_reference() -> dict[str, Any]:
    return {
        "type": "string",
        "pattern": "^result:[A-Za-z][A-Za-z0-9_-]*$",
        "maxLength": MAX_STRING_LENGTH,
    }


def _image_reference() -> dict[str, Any]:
    return _result_reference()


def _texture_set_reference() -> dict[str, Any]:
    return _result_reference()


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


def _node_reference() -> dict[str, Any]:
    return {
        "anyOf": [
            {
                "type": "string",
                "pattern": "^result:[A-Za-z][A-Za-z0-9_-]*$",
                "maxLength": MAX_STRING_LENGTH,
            },
            {
                "type": "string",
                "enum": list(SHADER_NODE_REFERENCES),
            },
        ]
    }


def _shader_socket() -> dict[str, Any]:
    return {"type": "string", "enum": sorted(set(SHADER_SOCKET_NAMES))}


def _shader_value() -> dict[str, Any]:
    return {
        "anyOf": [
            _bounded_number(-1_000_000.0, 1_000_000.0),
            _vector(3, -1_000_000.0, 1_000_000.0),
            _vector(4, -1_000_000.0, 1_000_000.0),
            {"type": "boolean"},
        ]
    }


def _color_space() -> dict[str, Any]:
    return {"type": "string", "enum": ["sRGB", "Non-Color", "Linear"]}


def _image_dimension() -> dict[str, Any]:
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": MESH_PROCESSING_LIMITS["texture_image_max_dimension"],
    }


def _pbr_texture_role() -> dict[str, Any]:
    return {"type": "string", "enum": list(PBR_TEXTURE_ROLES)}


def _blend_mode() -> dict[str, Any]:
    return {"type": "string", "enum": list(TEXTURE_BLEND_MODES)}


def _material_preset_properties() -> dict[str, Any]:
    return {
        "name": _name(),
        "material_family": {"type": "string", "enum": list(MATERIAL_FAMILIES)},
        "base_color": _vector(3, 0.0, 1.0),
        "secondary_color": _vector(3, 0.0, 1.0),
        "metallic": _bounded_number(0.0, 1.0),
        "roughness": _bounded_number(0.0, 1.0),
        "alpha": _bounded_number(0.0, 1.0),
        "transmission": _bounded_number(0.0, 1.0),
        "emission_strength": _bounded_number(0.0, 1_000.0),
        "texture_scale": _bounded_number(0.001, 10_000.0),
        "detail_strength": _bounded_number(0.0, 1.0),
        "bump_strength": _bounded_number(0.0, 1.0),
    }


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
        OperationType.CREATE_MATERIAL_PRESET: _operation_schema(
            OperationType.CREATE_MATERIAL_PRESET,
            _material_preset_properties(),
        ),
        OperationType.CREATE_PROCEDURAL_MATERIAL: _operation_schema(
            OperationType.CREATE_PROCEDURAL_MATERIAL,
            {
                "name": _name(),
                "material_family": {"type": "string", "enum": list(MATERIAL_FAMILIES)},
                "pattern": {"type": "string", "enum": list(PROCEDURAL_PATTERNS)},
                "base_color": _vector(3, 0.0, 1.0),
                "secondary_color": _vector(3, 0.0, 1.0),
                "metallic": _bounded_number(0.0, 1.0),
                "roughness": _bounded_number(0.0, 1.0),
                "alpha": _bounded_number(0.0, 1.0),
                "texture_scale": _bounded_number(0.001, 10_000.0),
                "detail_strength": _bounded_number(0.0, 1.0),
                "bump_strength": _bounded_number(0.0, 1.0),
            },
        ),
        OperationType.CREATE_SHADER_NODE: _operation_schema(
            OperationType.CREATE_SHADER_NODE,
            {
                "material_id": _reference("mat"),
                "node_type": {"type": "string", "enum": list(SHADER_NODE_TYPES)},
                "node_label": _name(),
            },
        ),
        OperationType.SET_SHADER_NODE_VALUE: _operation_schema(
            OperationType.SET_SHADER_NODE_VALUE,
            {
                "material_id": _reference("mat"),
                "node_ref": _node_reference(),
                "input_name": _shader_socket(),
                "value": _shader_value(),
            },
        ),
        OperationType.CONNECT_SHADER_NODES: _operation_schema(
            OperationType.CONNECT_SHADER_NODES,
            {
                "material_id": _reference("mat"),
                "from_node": _node_reference(),
                "from_socket": _shader_socket(),
                "to_node": _node_reference(),
                "to_socket": _shader_socket(),
            },
        ),
        OperationType.REMOVE_SHADER_NODE: _operation_schema(
            OperationType.REMOVE_SHADER_NODE,
            {
                "material_id": _reference("mat"),
                "node_ref": _node_reference(),
                "assistant_created_only": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.DISCONNECT_SHADER_LINK: _operation_schema(
            OperationType.DISCONNECT_SHADER_LINK,
            {
                "material_id": _reference("mat"),
                "from_node": _node_reference(),
                "from_socket": _shader_socket(),
                "to_node": _node_reference(),
                "to_socket": _shader_socket(),
            },
        ),
        OperationType.CREATE_SHADER_COLOR_RAMP: _operation_schema(
            OperationType.CREATE_SHADER_COLOR_RAMP,
            {
                "material_id": _reference("mat"),
                "node_label": _name(),
                "stops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "position": _bounded_number(0.0, 1.0),
                            "color": _vector(4, 0.0, 1.0),
                        },
                        "required": ["position", "color"],
                        "additionalProperties": False,
                    },
                    "minItems": 2,
                    "maxItems": 8,
                },
            },
        ),
        OperationType.SET_SHADER_COLOR_RAMP: _operation_schema(
            OperationType.SET_SHADER_COLOR_RAMP,
            {
                "material_id": _reference("mat"),
                "node_ref": _node_reference(),
                "stops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "position": _bounded_number(0.0, 1.0),
                            "color": _vector(4, 0.0, 1.0),
                        },
                        "required": ["position", "color"],
                        "additionalProperties": False,
                    },
                    "minItems": 2,
                    "maxItems": 8,
                },
            },
        ),
        OperationType.CREATE_SHADER_MIX_CHAIN: _operation_schema(
            OperationType.CREATE_SHADER_MIX_CHAIN,
            {
                "material_id": _reference("mat"),
                "chain_label": _name(),
                "template": {
                    "type": "string",
                    "enum": list(SHADER_MIX_CHAIN_TEMPLATES),
                },
                "base_color": _vector(4, 0.0, 1.0),
                "secondary_color": _vector(4, 0.0, 1.0),
                "strength": _bounded_number(0.0, 1.0),
                "scale": _bounded_number(0.001, 10_000.0),
            },
        ),
        OperationType.CREATE_SHADER_GRAPH_TEMPLATE: _operation_schema(
            OperationType.CREATE_SHADER_GRAPH_TEMPLATE,
            {
                "material_id": _reference("mat"),
                "graph_label": _name(),
                "template": {"type": "string", "enum": list(SHADER_GRAPH_TEMPLATES)},
                "base_color": _vector(4, 0.0, 1.0),
                "secondary_color": _vector(4, 0.0, 1.0),
                "strength": _bounded_number(0.0, 1.0),
                "scale": _bounded_number(0.001, 10_000.0),
            },
        ),
        OperationType.VALIDATE_MATERIAL_OUTPUT: _operation_schema(
            OperationType.VALIDATE_MATERIAL_OUTPUT,
            {
                "material_id": _reference("mat"),
                "repair": {"type": "boolean"},
            },
        ),
        OperationType.LOAD_IMAGE_TEXTURE: _operation_schema(
            OperationType.LOAD_IMAGE_TEXTURE,
            {
                "source": _asset_source(),
                "image_name": _name(),
                "color_space": _color_space(),
                "max_size_mb": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        ),
        OperationType.CREATE_IMAGE_TEXTURE_NODE: _operation_schema(
            OperationType.CREATE_IMAGE_TEXTURE_NODE,
            {
                "material_id": _reference("mat"),
                "image_id": _image_reference(),
                "node_label": _name(),
                "connect_to": _shader_socket(),
                "projection": {"type": "string", "enum": list(TEXTURE_PROJECTION_MODES)},
                "extension": {"type": "string", "enum": list(TEXTURE_EXTENSION_MODES)},
            },
        ),
        OperationType.SET_TEXTURE_MAPPING: _operation_schema(
            OperationType.SET_TEXTURE_MAPPING,
            {
                "material_id": _reference("mat"),
                "texture_node_ref": _node_reference(),
                "translation": _vector(3, -1_000_000.0, 1_000_000.0),
                "rotation": _vector(3, -1_000_000.0, 1_000_000.0),
                "scale": _vector(3, 0.001, 10_000.0),
                "projection": {"type": "string", "enum": list(TEXTURE_PROJECTION_MODES)},
                "extension": {"type": "string", "enum": list(TEXTURE_EXTENSION_MODES)},
            },
        ),
        OperationType.ASSIGN_UV_MAP: _operation_schema(
            OperationType.ASSIGN_UV_MAP,
            {
                "target_id": _reference("obj"),
                "material_id": _reference("mat"),
                "texture_node_ref": _node_reference(),
                "uv_map_name": _name(),
            },
        ),
        OperationType.CREATE_UV_MAP: _operation_schema(
            OperationType.CREATE_UV_MAP,
            {
                "target_ids": _target_ids(targets),
                "uv_map_name": _name(),
                "set_active": {"type": "boolean"},
                "set_render": {"type": "boolean"},
            },
        ),
        OperationType.UNWRAP_UV_MAP: _operation_schema(
            OperationType.UNWRAP_UV_MAP,
            {
                "target_ids": _target_ids(targets),
                "uv_map_name": _name(),
                "method": {
                    "type": "string",
                    "enum": ["angle_based", "conformal", "smart_project", "cube_project"],
                },
                "create_if_missing": {"type": "boolean"},
                "overwrite_existing": {"type": "boolean"},
                "margin": _bounded_number(0.0, 0.25),
            },
        ),
        OperationType.PACK_UV_ISLANDS: _operation_schema(
            OperationType.PACK_UV_ISLANDS,
            {
                "target_ids": _target_ids(targets),
                "uv_map_name": _name(),
                "margin": _bounded_number(0.0, 0.25),
                "rotate": {"type": "boolean"},
            },
        ),
        OperationType.IMPORT_PBR_TEXTURE_SET: _operation_schema(
            OperationType.IMPORT_PBR_TEXTURE_SET,
            {
                "name_prefix": _name(),
                "textures": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": _pbr_texture_role(),
                            "source": _asset_source(),
                            "color_space": _color_space(),
                            "max_size_mb": {"type": "integer", "minimum": 1, "maximum": 50},
                        },
                        "required": ["role", "source", "color_space", "max_size_mb"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": len(PBR_TEXTURE_ROLES),
                },
            },
        ),
        OperationType.CREATE_PBR_MATERIAL: _operation_schema(
            OperationType.CREATE_PBR_MATERIAL,
            {
                "name": _name(),
                "texture_set_id": _nullable(_texture_set_reference()),
                "base_color_image_id": _nullable(_image_reference()),
                "roughness_image_id": _nullable(_image_reference()),
                "metallic_image_id": _nullable(_image_reference()),
                "normal_image_id": _nullable(_image_reference()),
                "ambient_occlusion_image_id": _nullable(_image_reference()),
                "displacement_image_id": _nullable(_image_reference()),
                "alpha_image_id": _nullable(_image_reference()),
                "emission_image_id": _nullable(_image_reference()),
                "base_color": _vector(3, 0.0, 1.0),
                "metallic": _bounded_number(0.0, 1.0),
                "roughness": _bounded_number(0.0, 1.0),
                "alpha": _bounded_number(0.0, 1.0),
            },
        ),
        OperationType.SET_PBR_TEXTURE_ROLE: _operation_schema(
            OperationType.SET_PBR_TEXTURE_ROLE,
            {
                "texture_set_id": _texture_set_reference(),
                "image_id": _image_reference(),
                "role": _pbr_texture_role(),
                "color_space": _color_space(),
            },
        ),
        OperationType.GENERATE_TEXTURE_IMAGE: _operation_schema(
            OperationType.GENERATE_TEXTURE_IMAGE,
            {
                "prompt": {"type": "string", "minLength": 1, "maxLength": 1_000},
                "image_name": _name(),
                "width": _image_dimension(),
                "height": _image_dimension(),
                "pattern": {"type": "string", "enum": list(GENERATED_TEXTURE_PATTERNS)},
                "base_color": _vector(4, 0.0, 1.0),
                "secondary_color": _vector(4, 0.0, 1.0),
                "color_space": _color_space(),
                "pack": {"type": "boolean"},
            },
        ),
        OperationType.SAVE_GENERATED_TEXTURE: _operation_schema(
            OperationType.SAVE_GENERATED_TEXTURE,
            {
                "image_id": _image_reference(),
                "filepath": _file_path(),
                "file_format": {"type": "string", "enum": ["PNG", "JPEG", "TIFF"]},
                "pack_after_save": {"type": "boolean"},
            },
        ),
        OperationType.ATTACH_GENERATED_TEXTURE: _operation_schema(
            OperationType.ATTACH_GENERATED_TEXTURE,
            {
                "material_id": _reference("mat"),
                "image_id": _image_reference(),
                "node_label": _name(),
                "connect_to": _shader_socket(),
                "uv_map_name": _nullable(_name()),
            },
        ),
        OperationType.CREATE_PAINT_IMAGE: _operation_schema(
            OperationType.CREATE_PAINT_IMAGE,
            {
                "image_name": _name(),
                "width": _image_dimension(),
                "height": _image_dimension(),
                "fill_color": _vector(4, 0.0, 1.0),
                "color_space": _color_space(),
                "pack": {"type": "boolean"},
            },
        ),
        OperationType.ASSIGN_PAINT_SLOT: _operation_schema(
            OperationType.ASSIGN_PAINT_SLOT,
            {
                "target_id": _reference("obj"),
                "material_id": _reference("mat"),
                "image_id": _image_reference(),
                "uv_map_name": _name(),
                "node_label": _name(),
                "connect_to": _shader_socket(),
            },
        ),
        OperationType.APPLY_TEXTURE_PAINT_STROKES: _operation_schema(
            OperationType.APPLY_TEXTURE_PAINT_STROKES,
            {
                "image_id": _image_reference(),
                "blend_mode": _blend_mode(),
                "strokes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "uv": _vector(2, 0.0, 1.0),
                            "color": _vector(4, 0.0, 1.0),
                            "radius": _bounded_number(0.001, 1.0),
                            "strength": _bounded_number(0.0, 1.0),
                        },
                        "required": ["uv", "color", "radius", "strength"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": MESH_PROCESSING_LIMITS["texture_paint_stroke_max_count"],
                },
            },
        ),
        OperationType.FILL_TEXTURE_REGION: _operation_schema(
            OperationType.FILL_TEXTURE_REGION,
            {
                "image_id": _image_reference(),
                "region": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["full", "rect"]},
                        "min_uv": _nullable(_vector(2, 0.0, 1.0)),
                        "max_uv": _nullable(_vector(2, 0.0, 1.0)),
                    },
                    "required": ["kind", "min_uv", "max_uv"],
                    "additionalProperties": False,
                },
                "color": _vector(4, 0.0, 1.0),
                "strength": _bounded_number(0.0, 1.0),
                "blend_mode": _blend_mode(),
            },
        ),
        OperationType.CREATE_BAKE_TARGET_IMAGE: _operation_schema(
            OperationType.CREATE_BAKE_TARGET_IMAGE,
            {
                "image_name": _name(),
                "width": _image_dimension(),
                "height": _image_dimension(),
                "fill_color": _vector(4, 0.0, 1.0),
                "color_space": _color_space(),
                "pack": {"type": "boolean"},
            },
        ),
        OperationType.BAKE_TEXTURE_PASS: _operation_schema(
            OperationType.BAKE_TEXTURE_PASS,
            {
                "target_id": _reference("obj"),
                "image_id": _image_reference(),
                "uv_map_name": _name(),
                "pass_type": {"type": "string", "enum": list(TEXTURE_BAKE_PASS_TYPES)},
                "samples": {"type": "integer", "minimum": 1, "maximum": 256},
                "margin": _bounded_number(0.0, 0.25),
            },
        ),
        OperationType.ASSIGN_BAKED_TEXTURE: _operation_schema(
            OperationType.ASSIGN_BAKED_TEXTURE,
            {
                "material_id": _reference("mat"),
                "image_id": _image_reference(),
                "node_label": _name(),
                "connect_to": _shader_socket(),
                "uv_map_name": _nullable(_name()),
            },
        ),
        OperationType.ADD_DISPLACE_MODIFIER: _operation_schema(
            OperationType.ADD_DISPLACE_MODIFIER,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "texture_pattern": {
                    "type": "string",
                    "enum": ["noise", "clouds", "voronoi", "wood"],
                },
                "strength": _bounded_number(-100.0, 100.0),
                "midlevel": _bounded_number(0.0, 1.0),
                "texture_scale": _bounded_number(0.001, 10_000.0),
                "coordinates": {"type": "string", "enum": ["local", "global", "uv"]},
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.ADD_SMOOTH_MODIFIER: _operation_schema(
            OperationType.ADD_SMOOTH_MODIFIER,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "factor": _bounded_number(0.0, 1.0),
                "iterations": {"type": "integer", "minimum": 1, "maximum": 100},
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.ADD_REMESH_MODIFIER: _operation_schema(
            OperationType.ADD_REMESH_MODIFIER,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "mode": {"type": "string", "enum": ["voxel", "blocks", "smooth", "sharp"]},
                "voxel_size": _bounded_number(0.001, 1_000.0),
                "adaptivity": _bounded_number(0.0, 1.0),
                "preserve_volume": {"type": "boolean"},
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.SCULPT_SMOOTH_REGION: _operation_schema(
            OperationType.SCULPT_SMOOTH_REGION,
            {
                "target_id": _reference("obj"),
                "region": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["all", "material", "vertex_group"],
                        },
                        "material_id": _nullable(_reference("mat")),
                        "vertex_group": _nullable(_name()),
                    },
                    "required": ["kind", "material_id", "vertex_group"],
                    "additionalProperties": False,
                },
                "strength": _bounded_number(0.0, 1.0),
                "radius": _bounded_number(0.001, 1_000.0),
                "iterations": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        ),
        OperationType.APPLY_SCULPT_BRUSH_STROKES: _operation_schema(
            OperationType.APPLY_SCULPT_BRUSH_STROKES,
            {
                "target_id": _reference("obj"),
                "brush_type": {
                    "type": "string",
                    "enum": ["smooth", "inflate", "draw", "flatten"],
                },
                "radius": _bounded_number(0.001, 1_000.0),
                "strength": _bounded_number(0.0, 1.0),
                "falloff": {"type": "string", "enum": ["smooth", "linear", "sharp"]},
                "strokes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "location": _vector(3, -1_000_000.0, 1_000_000.0),
                            "normal": _vector(3, -1.0, 1.0),
                            "pressure": _bounded_number(0.0, 1.0),
                        },
                        "required": ["location", "normal", "pressure"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 500,
                },
            },
        ),
        OperationType.CREATE_GEOMETRY_NODES_PRESET: _operation_schema(
            OperationType.CREATE_GEOMETRY_NODES_PRESET,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "preset": {"type": "string", "enum": list(GEOMETRY_NODES_PRESETS)},
                "inputs": {
                    "type": "object",
                    "properties": {
                        input_name: _nullable(_bounded_number(-10_000.0, 10_000.0))
                        for input_name in GEOMETRY_NODE_INPUTS
                    },
                    "required": list(GEOMETRY_NODE_INPUTS),
                    "additionalProperties": False,
                },
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.SET_GEOMETRY_NODE_INPUT: _operation_schema(
            OperationType.SET_GEOMETRY_NODE_INPUT,
            {
                "target_id": _reference("obj"),
                "modifier_name": _name(),
                "input_name": {"type": "string", "enum": list(GEOMETRY_NODE_INPUTS)},
                "value": _bounded_number(-10_000.0, 10_000.0),
            },
        ),
        OperationType.CREATE_GEOMETRY_NODE_GROUP_TEMPLATE: _operation_schema(
            OperationType.CREATE_GEOMETRY_NODE_GROUP_TEMPLATE,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "template": {"type": "string", "enum": list(GEOMETRY_NODE_GROUP_TEMPLATES)},
                "inputs": {
                    "type": "object",
                    "properties": {
                        input_name: _nullable(_bounded_number(-10_000.0, 10_000.0))
                        for input_name in GEOMETRY_NODE_INPUTS
                    },
                    "required": list(GEOMETRY_NODE_INPUTS),
                    "additionalProperties": False,
                },
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.REMOVE_GEOMETRY_NODES_MODIFIER: _operation_schema(
            OperationType.REMOVE_GEOMETRY_NODES_MODIFIER,
            {
                "target_id": _reference("obj"),
                "modifier_name": _name(),
                "assistant_created_only": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.CREATE_GENERATED_GEOMETRY_COPY: _operation_schema(
            OperationType.CREATE_GENERATED_GEOMETRY_COPY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "variant": {"type": "string", "enum": list(GENERATED_MESH_VARIANTS)},
                "preserve_original": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.CREATE_SMOOTHED_COPY: _operation_schema(
            OperationType.CREATE_SMOOTHED_COPY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "strength": _bounded_number(0.0, 1.0),
                "iterations": {"type": "integer", "minimum": 1, "maximum": 50},
                "preserve_original": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.CREATE_DISPLACED_COPY: _operation_schema(
            OperationType.CREATE_DISPLACED_COPY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "strength": _bounded_number(-100.0, 100.0),
                "direction": _vector(3, -1.0, 1.0),
                "preserve_original": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.CREATE_REMESHED_COPY: _operation_schema(
            OperationType.CREATE_REMESHED_COPY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "mode": {"type": "string", "enum": ["copy", "triangulate"]},
                "preserve_original": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.CREATE_DYNAMIC_TOPOLOGY_COPY: _operation_schema(
            OperationType.CREATE_DYNAMIC_TOPOLOGY_COPY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "detail_level": {"type": "integer", "minimum": 1, "maximum": 3},
                "preserve_original": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.REPLACE_OBJECT_WITH_GENERATED_COPY: _operation_schema(
            OperationType.REPLACE_OBJECT_WITH_GENERATED_COPY,
            {
                "target_id": _reference("obj", allow_result=False),
                "generated_object_id": _reference("obj"),
                "hide_original": {"type": "boolean"},
            },
        ),
        OperationType.APPLY_GENERATED_MESH_TO_OBJECT: _operation_schema(
            OperationType.APPLY_GENERATED_MESH_TO_OBJECT,
            {
                "target_id": _reference("obj", allow_result=False),
                "generated_object_id": _reference("obj"),
                "preserve_original_data": {"type": "boolean", "enum": [True]},
                "hide_generated": {"type": "boolean"},
            },
        ),
        OperationType.CREATE_SCULPT_REGION_FROM_MATERIAL: _operation_schema(
            OperationType.CREATE_SCULPT_REGION_FROM_MATERIAL,
            {
                "target_id": _reference("obj"),
                "material_id": _reference("mat"),
                "region_name": _name(),
            },
        ),
        OperationType.CREATE_SCULPT_REGION_FROM_VERTEX_GROUP: _operation_schema(
            OperationType.CREATE_SCULPT_REGION_FROM_VERTEX_GROUP,
            {
                "target_id": _reference("obj"),
                "vertex_group": _name(),
                "region_name": _name(),
            },
        ),
        OperationType.CREATE_SCULPT_MASK: _operation_schema(
            OperationType.CREATE_SCULPT_MASK,
            {
                "region_id": _result_reference(),
                "mask_name": _name(),
                "strength": _bounded_number(0.0, 1.0),
            },
        ),
        OperationType.CREATE_FACE_SET_FROM_MATERIAL: _operation_schema(
            OperationType.CREATE_FACE_SET_FROM_MATERIAL,
            {
                "target_id": _reference("obj"),
                "material_id": _reference("mat"),
                "face_set_name": _name(),
            },
        ),
        OperationType.CREATE_FACE_SET_FROM_VERTEX_GROUP: _operation_schema(
            OperationType.CREATE_FACE_SET_FROM_VERTEX_GROUP,
            {
                "target_id": _reference("obj"),
                "vertex_group": _name(),
                "face_set_name": _name(),
            },
        ),
        OperationType.APPLY_SCULPT_REGION_OPERATION: _operation_schema(
            OperationType.APPLY_SCULPT_REGION_OPERATION,
            {
                "region_id": _result_reference(),
                "operation": {"type": "string", "enum": list(SCULPT_REGION_OPERATIONS)},
                "strength": _bounded_number(0.0, 1.0),
                "iterations": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        ),
        OperationType.ADD_MULTIRES_MODIFIER: _operation_schema(
            OperationType.ADD_MULTIRES_MODIFIER,
            {
                "target_ids": _target_ids(targets),
                "name": _name(),
                "levels": {"type": "integer", "minimum": 0, "maximum": 6},
                "render_levels": {"type": "integer", "minimum": 0, "maximum": 6},
                "apply": {"type": "boolean", "enum": [False]},
            },
        ),
        OperationType.CREATE_SHAPE_KEY: _operation_schema(
            OperationType.CREATE_SHAPE_KEY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "value": _bounded_number(0.0, 1.0),
                "from_generated_object_id": _nullable(_reference("obj")),
            },
        ),
        OperationType.CREATE_RIG_SAFE_SHAPE_KEY: _operation_schema(
            OperationType.CREATE_RIG_SAFE_SHAPE_KEY,
            {
                "target_id": _reference("obj"),
                "name": _name(),
                "value": _bounded_number(0.0, 1.0),
                "from_generated_object_id": _nullable(_reference("obj")),
                "allow_rigged": {"type": "boolean"},
                "preserve_animation": {"type": "boolean", "enum": [True]},
            },
        ),
        OperationType.SET_SHAPE_KEY_VALUE: _operation_schema(
            OperationType.SET_SHAPE_KEY_VALUE,
            {
                "target_id": _reference("obj"),
                "shape_key_name": _name(),
                "value": _bounded_number(0.0, 1.0),
            },
        ),
        OperationType.CREATE_PREVIEW_IMAGE: _operation_schema(
            OperationType.CREATE_PREVIEW_IMAGE,
            {
                "preview_name": _name(),
                "preview_kind": {"type": "string", "enum": list(PREVIEW_IMAGE_KINDS)},
                "target_id": _nullable(_reference("obj")),
                "material_id": _nullable(_reference("mat")),
                "width": {
                    "type": "integer",
                    "minimum": 16,
                    "maximum": MESH_PROCESSING_LIMITS["preview_image_max_dimension"],
                },
                "height": {
                    "type": "integer",
                    "minimum": 16,
                    "maximum": MESH_PROCESSING_LIMITS["preview_image_max_dimension"],
                },
            },
        ),
        OperationType.CREATE_RENDER_PREVIEW_IMAGE: _operation_schema(
            OperationType.CREATE_RENDER_PREVIEW_IMAGE,
            {
                "preview_name": _name(),
                "mode": {"type": "string", "enum": list(RENDER_PREVIEW_MODES)},
                "target_id": _nullable(_reference("obj")),
                "camera_id": _nullable(_reference("obj")),
                "width": {
                    "type": "integer",
                    "minimum": 16,
                    "maximum": MESH_PROCESSING_LIMITS["preview_image_max_dimension"],
                },
                "height": {
                    "type": "integer",
                    "minimum": 16,
                    "maximum": MESH_PROCESSING_LIMITS["preview_image_max_dimension"],
                },
                "samples": {"type": "integer", "minimum": 1, "maximum": 128},
                "pack": {"type": "boolean"},
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
