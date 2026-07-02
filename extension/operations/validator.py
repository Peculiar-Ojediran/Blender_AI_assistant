"""Validate provider plans against the controlled-operation contract."""

import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlparse

import fastjsonschema

from .limits import DEFAULT_OPERATION_LIMITS, OperationLimits
from .models import Operation, OperationPlan, OperationType, PlanStatus
from .registries import (
    GEOMETRY_NODE_GROUP_TEMPLATES,
    MATERIAL_FAMILIES,
    PBR_NON_COLOR_ROLES,
    PBR_TEXTURE_ROLES,
    PROCEDURAL_PATTERNS,
    SHADER_GRAPH_TEMPLATES,
    SHADER_MIX_CHAIN_TEMPLATES,
    SHADER_NODE_TYPES,
    SHADER_SOCKET_NAMES,
    TEXTURE_BAKE_PASS_TYPES,
    TEXTURE_BLEND_MODES,
)
from .schema import (
    build_operation_plan_schema,
)

RESULT_REFERENCE_PREFIX = "result:"

_RESULT_KINDS = {
    OperationType.CREATE_PRIMITIVE: "object",
    OperationType.CREATE_MATERIAL: "material",
    OperationType.CREATE_MATERIAL_PRESET: "material",
    OperationType.CREATE_PROCEDURAL_MATERIAL: "material",
    OperationType.ADD_LIGHT: "object",
    OperationType.ADD_CAMERA: "object",
    OperationType.CREATE_COLLECTION: "collection",
    OperationType.CREATE_TEXT_OBJECT: "object",
    OperationType.JOIN_OBJECTS: "object",
    OperationType.CREATE_SHADER_NODE: "shader_node",
    OperationType.CREATE_SHADER_COLOR_RAMP: "shader_node",
    OperationType.CREATE_SHADER_MIX_CHAIN: "shader_node",
    OperationType.CREATE_SHADER_GRAPH_TEMPLATE: "shader_node",
    OperationType.LOAD_IMAGE_TEXTURE: "image",
    OperationType.CREATE_IMAGE_TEXTURE_NODE: "shader_node",
    OperationType.IMPORT_PBR_TEXTURE_SET: "texture_set",
    OperationType.CREATE_PBR_MATERIAL: "material",
    OperationType.GENERATE_TEXTURE_IMAGE: "image",
    OperationType.CREATE_PAINT_IMAGE: "image",
    OperationType.CREATE_BAKE_TARGET_IMAGE: "image",
    OperationType.ASSIGN_PAINT_SLOT: "shader_node",
    OperationType.ATTACH_GENERATED_TEXTURE: "shader_node",
    OperationType.ASSIGN_BAKED_TEXTURE: "shader_node",
    OperationType.CREATE_GENERATED_GEOMETRY_COPY: "object",
    OperationType.CREATE_SMOOTHED_COPY: "object",
    OperationType.CREATE_DISPLACED_COPY: "object",
    OperationType.CREATE_REMESHED_COPY: "object",
    OperationType.CREATE_DYNAMIC_TOPOLOGY_COPY: "object",
    OperationType.CREATE_SCULPT_REGION_FROM_MATERIAL: "sculpt_region",
    OperationType.CREATE_SCULPT_REGION_FROM_VERTEX_GROUP: "sculpt_region",
    OperationType.CREATE_SCULPT_MASK: "sculpt_mask",
    OperationType.CREATE_FACE_SET_FROM_MATERIAL: "face_set",
    OperationType.CREATE_FACE_SET_FROM_VERTEX_GROUP: "face_set",
    OperationType.CREATE_PREVIEW_IMAGE: "image",
    OperationType.CREATE_RENDER_PREVIEW_IMAGE: "image",
}

_IMAGE_TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".exr"}
_SAVE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


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
        hint = _schema_error_hint(plan_data)
        message = hint if hint is not None else exc.message
        raise OperationContractError(f"Plan schema validation failed: {message}") from exc

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


def _schema_error_hint(data: Mapping[str, Any]) -> str | None:
    operations = data.get("operations")
    if not isinstance(operations, list):
        return None
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        raw_type = operation.get("type")
        if not isinstance(raw_type, str):
            continue
        if raw_type in {
            OperationType.CREATE_MATERIAL_PRESET.value,
            OperationType.CREATE_PROCEDURAL_MATERIAL.value,
        }:
            family = operation.get("material_family")
            if family not in MATERIAL_FAMILIES:
                return f"{raw_type} material_family is not supported."
        if raw_type == OperationType.CREATE_PROCEDURAL_MATERIAL.value:
            pattern = operation.get("pattern")
            if pattern not in PROCEDURAL_PATTERNS:
                return "CREATE_PROCEDURAL_MATERIAL pattern is not supported."
        if raw_type == OperationType.CREATE_SHADER_NODE.value:
            node_type = operation.get("node_type")
            if node_type not in SHADER_NODE_TYPES:
                return "CREATE_SHADER_NODE node_type is not supported."
        if raw_type == OperationType.CREATE_SHADER_MIX_CHAIN.value:
            template = operation.get("template")
            if template not in SHADER_MIX_CHAIN_TEMPLATES:
                return "CREATE_SHADER_MIX_CHAIN template is not supported."
        if raw_type == OperationType.CREATE_SHADER_GRAPH_TEMPLATE.value:
            template = operation.get("template")
            if template not in SHADER_GRAPH_TEMPLATES:
                return "CREATE_SHADER_GRAPH_TEMPLATE template is not supported."
        if raw_type == OperationType.CREATE_GEOMETRY_NODE_GROUP_TEMPLATE.value:
            template = operation.get("template")
            if template not in GEOMETRY_NODE_GROUP_TEMPLATES:
                return "CREATE_GEOMETRY_NODE_GROUP_TEMPLATE template is not supported."
        if raw_type == OperationType.IMPORT_PBR_TEXTURE_SET.value:
            textures = operation.get("textures")
            if isinstance(textures, list):
                for texture in textures:
                    if (
                        isinstance(texture, Mapping)
                        and texture.get("role") not in PBR_TEXTURE_ROLES
                    ):
                        return "IMPORT_PBR_TEXTURE_SET texture role is not supported."
        if (
            raw_type == OperationType.BAKE_TEXTURE_PASS.value
            and operation.get("pass_type") not in TEXTURE_BAKE_PASS_TYPES
        ):
            return "BAKE_TEXTURE_PASS pass_type is not supported."
        if raw_type in {
            OperationType.APPLY_TEXTURE_PAINT_STROKES.value,
            OperationType.FILL_TEXTURE_REGION.value,
        } and operation.get("blend_mode") not in TEXTURE_BLEND_MODES:
            return f"{raw_type} blend_mode is not supported."
        if raw_type == OperationType.CONNECT_SHADER_NODES.value:
            for field in ("from_socket", "to_socket"):
                if operation.get(field) not in SHADER_SOCKET_NAMES:
                    return f"CONNECT_SHADER_NODES {field} socket is not supported."
        if (
            raw_type == OperationType.SET_SHADER_NODE_VALUE.value
            and operation.get("input_name") not in SHADER_SOCKET_NAMES
        ):
            return "SET_SHADER_NODE_VALUE input_name socket is not supported."
        if raw_type == OperationType.APPLY_SCULPT_BRUSH_STROKES.value:
            strokes = operation.get("strokes")
            if isinstance(strokes, list) and len(strokes) > 500:
                return "APPLY_SCULPT_BRUSH_STROKES stroke count cannot exceed 500."
    return None


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

        if operation_type is OperationType.SET_MATERIAL_PROPERTIES:
            material_values = (
                operation["base_color"],
                operation["metallic"],
                operation["roughness"],
                operation["alpha"],
            )
            if all(value is None for value in material_values):
                raise OperationContractError(
                    "SET_MATERIAL_PROPERTIES must change at least one material property."
                )

        if operation_type is OperationType.SET_LIGHT_PROPERTIES:
            light_values = (
                operation["color"],
                operation["energy"],
                operation["size"],
            )
            if all(value is None for value in light_values):
                raise OperationContractError(
                    "SET_LIGHT_PROPERTIES must change at least one light property."
                )

        if operation_type is OperationType.SET_CAMERA_PROPERTIES:
            camera_values = (
                operation["focal_length"],
                operation["make_active"],
            )
            if all(value is None for value in camera_values):
                raise OperationContractError(
                    "SET_CAMERA_PROPERTIES must change at least one camera property."
                )

        if operation_type is OperationType.SET_MODIFIER_PROPERTIES:
            modifier_values = (
                operation["width"],
                operation["segments"],
                operation["thickness"],
                operation["count"],
                operation["relative_offset"],
                operation["levels"],
                operation["axis"],
            )
            if all(value is None for value in modifier_values):
                raise OperationContractError(
                    "SET_MODIFIER_PROPERTIES must change at least one modifier property."
                )

        if operation_type is OperationType.SET_OBJECT_VISIBILITY:
            visibility_values = (
                operation["viewport_visible"],
                operation["render_visible"],
            )
            if all(value is None for value in visibility_values):
                raise OperationContractError(
                    "SET_OBJECT_VISIBILITY must change viewport or render visibility."
                )

        if operation_type is OperationType.LOAD_IMAGE_TEXTURE:
            _validate_load_image_texture_source(operation["source"])

        if operation_type is OperationType.IMPORT_PBR_TEXTURE_SET:
            _validate_pbr_texture_set(operation["textures"])

        if operation_type is OperationType.CREATE_PBR_MATERIAL:
            _validate_pbr_material_inputs(operation)

        if operation_type is OperationType.SET_PBR_TEXTURE_ROLE:
            _validate_pbr_role_color_space(operation["role"], operation["color_space"])

        if operation_type is OperationType.SAVE_GENERATED_TEXTURE:
            _validate_generated_texture_output_path(operation["filepath"])

        if operation_type is OperationType.APPLY_TEXTURE_PAINT_STROKES:
            _validate_texture_paint_strokes(operation["strokes"])

        if operation_type is OperationType.FILL_TEXTURE_REGION:
            _validate_texture_fill_region(operation["region"])

        if operation_type is OperationType.BAKE_TEXTURE_PASS and operation["samples"] < 1:
            raise OperationContractError("BAKE_TEXTURE_PASS samples must be positive.")

        if (
            operation_type is OperationType.CONNECT_SHADER_NODES
            and operation["from_node"] == operation["to_node"]
            and operation["from_socket"] == operation["to_socket"]
        ):
            raise OperationContractError(
                "CONNECT_SHADER_NODES cannot connect a shader socket to itself."
            )

        if operation_type in {
            OperationType.CREATE_SHADER_COLOR_RAMP,
            OperationType.SET_SHADER_COLOR_RAMP,
        }:
            _validate_color_ramp_stops(operation["stops"])

        if operation_type is OperationType.SCULPT_SMOOTH_REGION:
            _validate_sculpt_region(operation["region"])

        if operation_type is OperationType.APPLY_SCULPT_BRUSH_STROKES:
            _validate_sculpt_strokes(operation["strokes"])

        if operation_type is OperationType.CREATE_DISPLACED_COPY:
            direction = operation["direction"]
            if sum(float(component) * float(component) for component in direction) < 1e-12:
                raise OperationContractError("CREATE_DISPLACED_COPY direction cannot be zero.")

        if (
            operation_type is OperationType.REPLACE_OBJECT_WITH_GENERATED_COPY
            and operation["target_id"] == operation["generated_object_id"]
        ):
            raise OperationContractError(
                "REPLACE_OBJECT_WITH_GENERATED_COPY target and generated copy must differ."
            )

        if (
            operation_type is OperationType.APPLY_GENERATED_MESH_TO_OBJECT
            and operation["target_id"] == operation["generated_object_id"]
        ):
            raise OperationContractError(
                "APPLY_GENERATED_MESH_TO_OBJECT target and generated copy must differ."
            )

        if operation_type is OperationType.IMPORT_ASSET:
            _validate_file_extension(
                operation["filepath"],
                {f".{operation['format']}"},
                "IMPORT_ASSET",
            )

        if operation_type is OperationType.LINK_OR_APPEND_BLEND_DATA:
            _validate_file_extension(
                operation["filepath"],
                {".blend"},
                "LINK_OR_APPEND_BLEND_DATA",
            )
            names = operation["datablock_names"]
            if len(names) != len(set(names)):
                raise OperationContractError(
                    "LINK_OR_APPEND_BLEND_DATA datablock names must be unique."
                )

        if (
            operation_type is OperationType.BOOLEAN_OPERATION
            and operation["target_id"] == operation["cutter_id"]
        ):
            raise OperationContractError(
                "BOOLEAN_OPERATION target and cutter must be different objects."
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

    target_id = operation.get("target_id")
    if isinstance(target_id, str):
        references.append((target_id, "object"))

    cutter_id = operation.get("cutter_id")
    if isinstance(cutter_id, str):
        references.append((cutter_id, "object"))

    camera_id = operation.get("camera_id")
    if isinstance(camera_id, str):
        references.append((camera_id, "object"))

    material_id = operation.get("material_id")
    if isinstance(material_id, str):
        references.append((material_id, "material"))

    region = operation.get("region")
    if isinstance(region, Mapping):
        region_material_id = region.get("material_id")
        if isinstance(region_material_id, str):
            references.append((region_material_id, "material"))

    collection_id = operation.get("collection_id")
    if isinstance(collection_id, str):
        references.append((collection_id, "collection"))

    parent_collection_id = operation.get("parent_collection_id")
    if isinstance(parent_collection_id, str):
        references.append((parent_collection_id, "collection"))

    for key in ("from_node", "to_node", "node_ref"):
        node_ref = operation.get(key)
        if isinstance(node_ref, str):
            references.append((node_ref, "shader_node"))

    texture_node_ref = operation.get("texture_node_ref")
    if isinstance(texture_node_ref, str):
        references.append((texture_node_ref, "shader_node"))

    for key in (
        "image_id",
        "base_color_image_id",
        "roughness_image_id",
        "metallic_image_id",
        "normal_image_id",
        "ambient_occlusion_image_id",
        "displacement_image_id",
        "alpha_image_id",
        "emission_image_id",
    ):
        image_id = operation.get(key)
        if isinstance(image_id, str):
            references.append((image_id, "image"))

    texture_set_id = operation.get("texture_set_id")
    if isinstance(texture_set_id, str):
        references.append((texture_set_id, "texture_set"))

    generated_object_id = operation.get("generated_object_id")
    if isinstance(generated_object_id, str):
        references.append((generated_object_id, "object"))

    from_generated_object_id = operation.get("from_generated_object_id")
    if isinstance(from_generated_object_id, str):
        references.append((from_generated_object_id, "object"))

    region_id = operation.get("region_id")
    if isinstance(region_id, str):
        references.append((region_id, "sculpt_region"))

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


def _validate_file_extension(
    filepath: str,
    allowed_suffixes: set[str],
    operation_type: str,
) -> None:
    normalized = filepath.lower()
    is_url = "://" in normalized
    if operation_type == "IMPORT_ASSET":
        if is_url and not normalized.startswith("https://"):
            raise OperationContractError("IMPORT_ASSET URL sources must use HTTPS.")
    elif is_url:
        raise OperationContractError(f"{operation_type} only accepts local file paths.")
    if not any(normalized.endswith(suffix) for suffix in allowed_suffixes):
        suffixes = ", ".join(sorted(allowed_suffixes))
        raise OperationContractError(
            f"{operation_type} file path must end with one of: {suffixes}."
        )


def _validate_load_image_texture_source(source: str) -> None:
    normalized = source.lower()
    if "://" in normalized:
        parsed = urlparse(source)
        if parsed.scheme.lower() != "https":
            raise OperationContractError("LOAD_IMAGE_TEXTURE URL sources must use HTTPS.")
        if not parsed.netloc:
            raise OperationContractError("LOAD_IMAGE_TEXTURE URL sources require a host.")
        suffix = Path(unquote(parsed.path)).suffix.lower()
    else:
        suffix = Path(source).suffix.lower()
    if suffix not in _IMAGE_TEXTURE_SUFFIXES:
        suffixes = ", ".join(sorted(_IMAGE_TEXTURE_SUFFIXES))
        raise OperationContractError(
            f"LOAD_IMAGE_TEXTURE source must end with one of: {suffixes}."
        )


def _validate_pbr_texture_set(textures: list[Mapping[str, Any]]) -> None:
    roles = [str(texture["role"]) for texture in textures]
    if len(roles) != len(set(roles)):
        raise OperationContractError("IMPORT_PBR_TEXTURE_SET texture roles must be unique.")
    for texture in textures:
        _validate_load_image_texture_source(str(texture["source"]))
        _validate_pbr_role_color_space(str(texture["role"]), str(texture["color_space"]))


def _validate_pbr_role_color_space(role: str, color_space: str) -> None:
    if role in PBR_NON_COLOR_ROLES and color_space == "sRGB":
        raise OperationContractError(f"PBR texture role {role} must use non-color data.")
    if role in {"base_color", "emission"} and color_space == "Non-Color":
        raise OperationContractError(f"PBR texture role {role} should use color data.")


def _validate_pbr_material_inputs(operation: Mapping[str, Any]) -> None:
    texture_set_id = operation["texture_set_id"]
    image_ids = (
        operation["base_color_image_id"],
        operation["roughness_image_id"],
        operation["metallic_image_id"],
        operation["normal_image_id"],
        operation["ambient_occlusion_image_id"],
        operation["displacement_image_id"],
        operation["alpha_image_id"],
        operation["emission_image_id"],
    )
    if texture_set_id is None and all(image_id is None for image_id in image_ids):
        raise OperationContractError(
            "CREATE_PBR_MATERIAL needs texture_set_id or at least one image reference."
        )


def _validate_color_ramp_stops(stops: list[Mapping[str, Any]]) -> None:
    positions = [float(stop["position"]) for stop in stops]
    if len(positions) != len(set(positions)):
        raise OperationContractError("Color ramp stop positions must be unique.")
    if positions != sorted(positions):
        raise OperationContractError("Color ramp stop positions must be sorted.")


def _validate_generated_texture_output_path(filepath: str) -> None:
    normalized = filepath.lower()
    if "://" in normalized:
        raise OperationContractError("SAVE_GENERATED_TEXTURE only accepts local file paths.")
    suffix = Path(filepath).suffix.lower()
    if suffix not in _SAVE_IMAGE_SUFFIXES:
        suffixes = ", ".join(sorted(_SAVE_IMAGE_SUFFIXES))
        raise OperationContractError(
            f"SAVE_GENERATED_TEXTURE filepath must end with one of: {suffixes}."
        )


def _validate_texture_paint_strokes(strokes: list[Mapping[str, Any]]) -> None:
    for index, stroke in enumerate(strokes):
        radius = float(stroke["radius"])
        strength = float(stroke["strength"])
        if radius <= 0.0:
            raise OperationContractError(
                f"APPLY_TEXTURE_PAINT_STROKES stroke {index} radius must be positive."
            )
        if strength <= 0.0:
            raise OperationContractError(
                f"APPLY_TEXTURE_PAINT_STROKES stroke {index} strength must be positive."
            )


def _validate_texture_fill_region(region: Mapping[str, Any]) -> None:
    if region["kind"] == "full":
        if region["min_uv"] is not None or region["max_uv"] is not None:
            raise OperationContractError(
                "FILL_TEXTURE_REGION full regions must use null UV bounds."
            )
        return

    min_uv = region["min_uv"]
    max_uv = region["max_uv"]
    if min_uv is None or max_uv is None:
        raise OperationContractError("FILL_TEXTURE_REGION rect regions need min_uv and max_uv.")
    if min_uv[0] >= max_uv[0] or min_uv[1] >= max_uv[1]:
        raise OperationContractError("FILL_TEXTURE_REGION rect min_uv must be below max_uv.")


def _validate_sculpt_region(region: Mapping[str, Any]) -> None:
    kind = region["kind"]
    if kind == "material" and not isinstance(region.get("material_id"), str):
        raise OperationContractError("SCULPT_SMOOTH_REGION material regions need material_id.")
    if kind == "vertex_group" and not isinstance(region.get("vertex_group"), str):
        raise OperationContractError(
            "SCULPT_SMOOTH_REGION vertex_group regions need vertex_group."
        )


def _validate_sculpt_strokes(strokes: list[Mapping[str, Any]]) -> None:
    if len(strokes) > 500:
        raise OperationContractError(
            "APPLY_SCULPT_BRUSH_STROKES stroke count cannot exceed 500."
        )
    for index, stroke in enumerate(strokes):
        normal = stroke["normal"]
        magnitude = math.sqrt(sum(float(component) ** 2 for component in normal))
        if magnitude < 1e-9:
            raise OperationContractError(
                f"APPLY_SCULPT_BRUSH_STROKES stroke {index} has a zero normal."
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
