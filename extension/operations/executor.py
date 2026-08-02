"""Preflight and execute approved plans on Blender's main thread."""

import hashlib
import math
import tempfile
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import unquote, urlparse

from ..config import resolve_environment_value
from ..context import SceneContextSnapshot, TargetKind
from ..providers.openai_images import OpenAIImageProvider, openai_image_generation_enabled
from ..providers.registry import PROVIDER_OPENAI
from .models import Operation, OperationPlan, OperationType, PlanStatus
from .registries import (
    MESH_PROCESSING_LIMITS,
    PBR_NON_COLOR_ROLES,
    SHADER_SOCKET_COMPATIBILITY,
    SHADER_SOCKET_FAMILIES,
)
from .targets import RESULT_REFERENCE_PREFIX, resolve_plan_targets

type ProgressCallback = Callable[[int, int], None]

MAX_URL_IMPORT_BYTES = 50 * 1024 * 1024
URL_IMPORT_TIMEOUT_SECONDS = 60.0
IMAGE_TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".exr"}


class ChangeKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    operation_id: str
    target_id: str
    datablock_kind: str
    name: str
    change: ChangeKind
    detail: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    operation_count: int
    completed_operations: int
    changes: tuple[ChangeRecord, ...]
    partial: bool = False
    rolled_back: bool = False

    @property
    def changed_count(self) -> int:
        return len(
            {(change.datablock_kind, change.target_id) for change in self.changes}
        )


class ExecutionError(RuntimeError):
    """Base error for safe-plan preflight and execution failures."""


class ExecutionPreflightError(ExecutionError):
    """Raised before mutation when a complete plan cannot execute safely."""


class PlanExecutionError(ExecutionError):
    """Raised after execution begins, with rollback or partial-result details."""

    def __init__(
        self,
        message: str,
        *,
        result: ExecutionResult,
        recovery_instructions: str,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.recovery_instructions = recovery_instructions


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    plan: OperationPlan
    snapshot: SceneContextSnapshot
    resolved_targets: Mapping[str, Any]
    duplicate_names: Mapping[str, tuple[str, ...]]


@dataclass(slots=True)
class _SimTarget:
    kind: TargetKind
    token: str
    name: str
    live: Any | None
    supports_materials: bool = False
    deleted: bool = False
    object_type: str = ""


@dataclass(frozen=True, slots=True)
class _StagedDeletion:
    operation_id: str
    target_id: str
    item: Any
    original_name: str


@dataclass(frozen=True, slots=True)
class _PreparedBrushStroke:
    location: Any
    normal: Any
    pressure: float
    affected_indices: frozenset[int]
    snapped_to_nearest: bool = False


@dataclass(frozen=True, slots=True)
class _SculptRegion:
    name: str
    target: Any
    vertex_indices: tuple[int, ...]


class _Transaction:
    def __init__(self) -> None:
        self.records: list[ChangeRecord] = []
        self.rollback_actions: list[Callable[[], None]] = []
        self.deletions: list[_StagedDeletion] = []
        self.deletion_commit_started = False

    def add_rollback(self, action: Callable[[], None]) -> None:
        self.rollback_actions.append(action)

    def record(self, record: ChangeRecord) -> None:
        self.records.append(record)

    def rollback(self) -> tuple[bool, tuple[str, ...]]:
        errors: list[str] = []
        for action in reversed(self.rollback_actions):
            try:
                action()
            except Exception as error:
                errors.append(str(error) or type(error).__name__)
        return not errors, tuple(errors)

    def commit_deletions(self) -> None:
        if not self.deletions:
            return

        import bpy

        self.deletion_commit_started = True
        deletion_items = {entry.item for entry in self.deletions}
        for entry in self.deletions:
            item = entry.item
            for child in tuple(item.children):
                if child in deletion_items:
                    continue
                world_transform = child.matrix_world.copy()
                child.parent = None
                child.matrix_world = world_transform
            collections = tuple(item.users_collection)
            bpy.data.objects.remove(item, do_unlink=True)
            self.record(
                ChangeRecord(
                    entry.operation_id,
                    entry.target_id,
                    "object",
                    entry.original_name,
                    ChangeKind.DELETED,
                    "Deleted object",
                )
            )
            for collection in collections:
                self.record(
                    _datablock_change(
                        entry.operation_id,
                        collection,
                        "collection",
                        ChangeKind.UPDATED,
                        f"Unlinked deleted object {entry.original_name}",
                    )
                )


def preflight_plan(
    context: Any,
    plan: OperationPlan,
    snapshot: SceneContextSnapshot,
) -> PreparedExecution:
    """Resolve and simulate a complete plan without changing Blender data."""

    _ensure_main_thread()
    if plan.status is not PlanStatus.READY:
        raise ExecutionPreflightError("Only a ready plan can be executed.")
    if plan.snapshot_id != snapshot.snapshot_id:
        raise ExecutionPreflightError("The approved plan no longer matches its scene snapshot.")
    if context.scene.name != snapshot.context.scene_name:
        raise ExecutionPreflightError("The active Blender scene changed after planning.")
    if context.mode != "OBJECT":
        raise ExecutionPreflightError("AI plans can only execute while Blender is in Object Mode.")

    try:
        resolved = resolve_plan_targets(plan, snapshot)
    except Exception as error:
        raise ExecutionPreflightError(str(error) or type(error).__name__) from error

    simulation = _PreflightSimulation(context, snapshot, resolved)
    for operation in plan.operations:
        simulation.apply(operation)

    return PreparedExecution(
        plan,
        snapshot,
        resolved,
        MappingProxyType(dict(simulation.duplicate_names)),
    )


def execute_plan(
    context: Any,
    plan: OperationPlan,
    snapshot: SceneContextSnapshot,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ExecutionResult:
    """Execute one fully preflighted plan, rolling back non-destructive failures."""

    prepared = preflight_plan(context, plan, snapshot)
    transaction = _Transaction()
    results: dict[str, Any] = {}
    completed_operations = 0

    try:
        for index, operation in enumerate(plan.operations, start=1):
            _execute_operation(context, operation, prepared, results, transaction)
            completed_operations = index
            if progress_callback is not None:
                progress_callback(index, len(plan.operations))
        transaction.commit_deletions()
    except Exception as error:
        if transaction.deletion_commit_started:
            result = ExecutionResult(
                len(plan.operations),
                completed_operations,
                tuple(transaction.records),
                partial=True,
            )
            raise PlanExecutionError(
                f"Execution stopped during destructive commit: {error}",
                result=result,
                recovery_instructions="Use Blender Undo before making further scene changes.",
            ) from error

        rolled_back, rollback_errors = transaction.rollback()
        result = ExecutionResult(
            len(plan.operations),
            completed_operations,
            () if rolled_back else tuple(transaction.records),
            partial=not rolled_back,
            rolled_back=rolled_back,
        )
        rollback_detail = ""
        if rollback_errors:
            rollback_detail = f" Rollback errors: {'; '.join(rollback_errors)}"
        recovery = (
            "No scene changes remain."
            if rolled_back
            else "Use Blender Undo before making further scene changes."
        )
        raise PlanExecutionError(
            f"Execution failed after operation {completed_operations}: {error}.{rollback_detail}",
            result=result,
            recovery_instructions=recovery,
        ) from error

    return ExecutionResult(
        len(plan.operations),
        completed_operations,
        tuple(transaction.records),
    )


class _PreflightSimulation:
    def __init__(
        self,
        context: Any,
        snapshot: SceneContextSnapshot,
        resolved: Mapping[str, Any],
    ) -> None:
        import bpy

        data: Any = cast(Any, bpy.data)
        self.context = context
        self.snapshot = snapshot
        self.resolved = resolved
        self.results: dict[str, _SimTarget] = {}
        self.existing: dict[str, _SimTarget] = {}
        self.object_names = {
            item.name: f"object:{int(item.session_uid)}" for item in data.objects
        }
        self.material_names = {
            item.name: f"material:{int(item.session_uid)}" for item in data.materials
        }
        self.image_names = {
            item.name: f"image:{int(item.session_uid)}" for item in data.images
        }
        self.image_results: set[str] = set()
        self.texture_set_results: set[str] = set()
        self.shader_node_results: set[str] = set()
        self.shader_layer_results: set[str] = set()
        self.material_palette_results: set[str] = set()
        self.uv_report_results: set[str] = set()
        self.uv_seam_set_results: set[str] = set()
        self.uv_island_set_results: set[str] = set()
        self.uv_atlas_results: set[str] = set()
        self.uv_variant_results: dict[str, tuple[str, str]] = {}
        self.uv_maps: dict[str, set[str]] = {}
        self.modifier_names: dict[str, set[str]] = {}
        self.shape_key_names: dict[str, set[str]] = {}
        self.vertex_group_names: dict[str, set[str]] = {}
        self.scene_collections = set(_scene_collections(context.scene.collection))
        self.collection_names = {
            item.name: f"collection:{int(item.session_uid)}"
            for item in self.scene_collections
        }
        self.light_data_names = {item.name for item in data.lights}
        self.camera_data_names = {item.name for item in data.cameras}
        self.duplicate_names: dict[str, tuple[str, ...]] = {}

    def apply(self, operation: Operation) -> None:
        handlers: dict[OperationType, Callable[[Operation], None]] = {
            OperationType.CREATE_PRIMITIVE: self._create_primitive,
            OperationType.DELETE_OBJECTS: self._delete_objects,
            OperationType.DUPLICATE_OBJECTS: self._duplicate_objects,
            OperationType.SET_TRANSFORM: self._set_transform,
            OperationType.CREATE_MATERIAL: self._create_material,
            OperationType.CREATE_MATERIAL_PRESET: self._create_material,
            OperationType.CREATE_PROCEDURAL_MATERIAL: self._create_material,
            OperationType.ASSIGN_MATERIAL: self._assign_material,
            OperationType.ADD_LIGHT: self._add_light,
            OperationType.ADD_CAMERA: self._add_camera,
            OperationType.RENAME_OBJECTS: self._rename_objects,
            OperationType.MOVE_TO_COLLECTION: self._move_to_collection,
            OperationType.SET_MATERIAL_PROPERTIES: self._set_material_properties,
            OperationType.CREATE_COLLECTION: self._create_collection,
            OperationType.SET_LIGHT_PROPERTIES: self._set_light_properties,
            OperationType.SET_CAMERA_PROPERTIES: self._set_camera_properties,
            OperationType.ADD_MODIFIER: self._add_modifier,
            OperationType.SET_MODIFIER_PROPERTIES: self._set_modifier_properties,
            OperationType.CREATE_TEXT_OBJECT: self._create_text_object,
            OperationType.SET_OBJECT_VISIBILITY: self._set_object_visibility,
            OperationType.IMPORT_ASSET: self._import_asset,
            OperationType.LINK_OR_APPEND_BLEND_DATA: self._link_or_append_blend_data,
            OperationType.BOOLEAN_OPERATION: self._boolean_operation,
            OperationType.JOIN_OBJECTS: self._join_objects,
            OperationType.SEPARATE_OBJECTS: self._separate_objects,
            OperationType.CREATE_SHADER_NODE: self._create_shader_node,
            OperationType.SET_SHADER_NODE_VALUE: self._set_shader_node_value,
            OperationType.CONNECT_SHADER_NODES: self._connect_shader_nodes,
            OperationType.REMOVE_SHADER_NODE: self._shader_node_operation,
            OperationType.DISCONNECT_SHADER_LINK: self._shader_node_operation,
            OperationType.CREATE_SHADER_COLOR_RAMP: self._create_shader_node,
            OperationType.SET_SHADER_COLOR_RAMP: self._shader_node_operation,
            OperationType.CREATE_SHADER_MIX_CHAIN: self._create_shader_node,
            OperationType.CREATE_SHADER_GRAPH_TEMPLATE: self._create_shader_node,
            OperationType.VALIDATE_MATERIAL_OUTPUT: self._material_operation,
            OperationType.CREATE_LAYERED_SHADER_MATERIAL: self._create_material,
            OperationType.ADD_SHADER_LAYER: self._add_shader_layer,
            OperationType.SET_SHADER_LAYER_MASK: self._shader_layer_operation,
            OperationType.REORDER_SHADER_LAYERS: self._reorder_shader_layers,
            OperationType.REMOVE_SHADER_LAYER: self._shader_layer_operation,
            OperationType.CREATE_PROCEDURAL_PATTERN_NODE_SET: self._create_shader_node,
            OperationType.CREATE_EDGE_WEAR_SHADER: self._create_shader_node,
            OperationType.CREATE_TRIPLANAR_MAPPING_SETUP: self._create_shader_node,
            OperationType.CREATE_OBJECT_SPACE_GRADIENT_SHADER: self._create_shader_node,
            OperationType.CREATE_CURVATURE_STYLE_MASK: self._create_shader_node,
            OperationType.EXTRACT_MATERIAL_PALETTE_FROM_IMAGE: self._extract_material_palette,
            OperationType.CREATE_MATERIAL_FROM_REFERENCE_IMAGE: self._create_reference_material,
            OperationType.MATCH_MATERIAL_TO_REFERENCE: self._material_operation,
            OperationType.CREATE_LOOKDEV_PREVIEW: self._create_preview_image,
            OperationType.CREATE_GLASS_MATERIAL: self._create_material,
            OperationType.CREATE_TRANSLUCENT_MATERIAL: self._create_material,
            OperationType.CREATE_EMISSION_MATERIAL: self._create_material,
            OperationType.CREATE_VOLUME_MATERIAL: self._create_material,
            OperationType.CREATE_TOON_SHADER_MATERIAL: self._create_material,
            OperationType.CREATE_ANISOTROPIC_MATERIAL: self._create_material,
            OperationType.REMOVE_UNUSED_ASSISTANT_SHADER_NODES: self._material_operation,
            OperationType.CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS: (
                self._consolidate_duplicate_materials
            ),
            OperationType.NORMALIZE_SHADER_NODE_LAYOUT: self._material_operation,
            OperationType.VALIDATE_SHADER_COMPATIBILITY: self._material_operation,
            OperationType.REPAIR_BROKEN_SHADER_LINKS: self._material_operation,
            OperationType.CREATE_MATERIAL_VARIANT: self._create_material_variant,
            OperationType.TAG_MATERIAL_VARIANT: self._material_variant_operation,
            OperationType.CREATE_SHADER_COMPARISON_PREVIEW: self._create_comparison_preview,
            OperationType.ACCEPT_MATERIAL_VARIANT: self._accept_material_variant,
            OperationType.REJECT_MATERIAL_VARIANT: self._material_variant_operation,
            OperationType.LOAD_IMAGE_TEXTURE: self._load_image_texture,
            OperationType.CREATE_IMAGE_TEXTURE_NODE: self._create_image_texture_node,
            OperationType.SET_TEXTURE_MAPPING: self._set_texture_mapping,
            OperationType.ASSIGN_UV_MAP: self._assign_uv_map,
            OperationType.CREATE_UV_MAP: self._create_uv_map,
            OperationType.UNWRAP_UV_MAP: self._unwrap_uv_map,
            OperationType.PACK_UV_ISLANDS: self._pack_uv_islands,
            OperationType.INSPECT_UV_MAP: self._uv_report,
            OperationType.CREATE_UV_DIAGNOSTIC_REPORT: self._uv_report,
            OperationType.CREATE_UV_OVERLAP_PREVIEW: self._uv_preview,
            OperationType.CREATE_UV_STRETCH_PREVIEW: self._uv_preview,
            OperationType.MARK_UV_SEAMS_BY_ANGLE: self._mark_uv_seams,
            OperationType.MARK_UV_SEAMS_BY_MATERIAL: self._mark_uv_seams,
            OperationType.MARK_UV_SEAMS_BY_EDGE_SET: self._mark_uv_seams,
            OperationType.CLEAR_UV_SEAMS: self._clear_uv_seams,
            OperationType.CREATE_UV_ISLANDS_FROM_SEAMS: self._create_uv_islands_from_seams,
            OperationType.SMART_PROJECT_UV_MAP: self._project_uv_map,
            OperationType.CUBE_PROJECT_UV_MAP: self._project_uv_map,
            OperationType.CYLINDER_PROJECT_UV_MAP: self._project_uv_map,
            OperationType.SPHERE_PROJECT_UV_MAP: self._project_uv_map,
            OperationType.CAMERA_PROJECT_UV_MAP: self._project_uv_map,
            OperationType.LIGHTMAP_UNWRAP_UV_MAP: self._project_uv_map,
            OperationType.SELECT_UV_ISLANDS_BY_MATERIAL: self._select_uv_islands,
            OperationType.TRANSFORM_UV_ISLANDS: self._uv_island_operation,
            OperationType.ALIGN_UV_ISLANDS: self._uv_island_operation,
            OperationType.DISTRIBUTE_UV_ISLANDS: self._uv_island_operation,
            OperationType.SCALE_UV_ISLANDS_TO_BOUNDS: self._uv_island_operation,
            OperationType.PIN_UV_ISLANDS: self._uv_island_operation,
            OperationType.UNPIN_UV_ISLANDS: self._uv_island_operation,
            OperationType.SET_UV_TEXEL_DENSITY: self._uv_map_operation,
            OperationType.NORMALIZE_UV_TEXEL_DENSITY: self._uv_map_operation,
            OperationType.PACK_UV_ISLANDS_ADVANCED: self._uv_map_operation,
            OperationType.MOVE_UV_ISLANDS_TO_TILE: self._uv_island_operation,
            OperationType.CREATE_UDIM_TILE_LAYOUT: self._create_udim_tile_layout,
            OperationType.VALIDATE_UDIM_LAYOUT: self._uv_multi_report,
            OperationType.RELAX_UV_ISLANDS: self._uv_island_operation,
            OperationType.MINIMIZE_UV_STRETCH: self._uv_map_operation,
            OperationType.REPAIR_UV_BOUNDS: self._uv_map_operation,
            OperationType.MERGE_DUPLICATE_UV_MAPS: self._merge_duplicate_uv_maps,
            OperationType.REMOVE_UNUSED_ASSISTANT_UV_MAPS: self._remove_unused_uv_maps,
            OperationType.VALIDATE_UV_MAP: self._uv_multi_report,
            OperationType.FIT_UV_ISLANDS_TO_IMAGE_REGION: self._fit_uv_islands_to_image_region,
            OperationType.CREATE_TEXTURE_ATLAS_LAYOUT: self._create_texture_atlas_layout,
            OperationType.ASSIGN_ATLAS_TEXTURE_REGIONS: self._assign_atlas_texture_regions,
            OperationType.BAKE_UV_LAYOUT_GUIDE_IMAGE: self._uv_guide_image,
            OperationType.CREATE_UV_GRID_TEST_MATERIAL: self._create_material,
            OperationType.CREATE_UV_MAP_VARIANT: self._create_uv_variant,
            OperationType.TAG_UV_VARIANT: self._uv_variant_operation,
            OperationType.CREATE_UV_COMPARISON_PREVIEW: self._uv_variant_preview,
            OperationType.ACCEPT_UV_VARIANT: self._accept_uv_variant,
            OperationType.REJECT_UV_VARIANT: self._uv_variant_operation,
            OperationType.IMPORT_PBR_TEXTURE_SET: self._import_pbr_texture_set,
            OperationType.CREATE_PBR_MATERIAL: self._create_material,
            OperationType.SET_PBR_TEXTURE_ROLE: self._set_pbr_texture_role,
            OperationType.GENERATE_IMAGE_ASSET: self._create_image_datablock,
            OperationType.GENERATE_TEXTURE_IMAGE: self._create_image_datablock,
            OperationType.SAVE_GENERATED_TEXTURE: self._save_generated_texture,
            OperationType.APPLY_IMAGE_TO_MATERIAL: self._attach_generated_texture,
            OperationType.ATTACH_GENERATED_TEXTURE: self._attach_generated_texture,
            OperationType.CREATE_PAINT_IMAGE: self._create_image_datablock,
            OperationType.ASSIGN_PAINT_SLOT: self._assign_paint_slot,
            OperationType.APPLY_TEXTURE_PAINT_STROKES: self._apply_texture_paint_strokes,
            OperationType.FILL_TEXTURE_REGION: self._fill_texture_region,
            OperationType.CREATE_BAKE_TARGET_IMAGE: self._create_image_datablock,
            OperationType.BAKE_TEXTURE_PASS: self._bake_texture_pass,
            OperationType.ASSIGN_BAKED_TEXTURE: self._attach_generated_texture,
            OperationType.ADD_DISPLACE_MODIFIER: self._add_modifier,
            OperationType.ADD_SMOOTH_MODIFIER: self._add_modifier,
            OperationType.ADD_REMESH_MODIFIER: self._add_modifier,
            OperationType.SCULPT_SMOOTH_REGION: self._sculpt_smooth_region,
            OperationType.APPLY_SCULPT_BRUSH_STROKES: self._apply_sculpt_brush_strokes,
            OperationType.CREATE_GEOMETRY_NODES_PRESET: self._add_modifier,
            OperationType.SET_GEOMETRY_NODE_INPUT: self._set_modifier_properties,
            OperationType.CREATE_GEOMETRY_NODE_GROUP_TEMPLATE: self._add_modifier,
            OperationType.REMOVE_GEOMETRY_NODES_MODIFIER: self._remove_modifier_preflight,
            OperationType.CREATE_GENERATED_GEOMETRY_COPY: self._create_generated_copy,
            OperationType.CREATE_SMOOTHED_COPY: self._create_generated_copy,
            OperationType.CREATE_DISPLACED_COPY: self._create_generated_copy,
            OperationType.CREATE_REMESHED_COPY: self._create_generated_copy,
            OperationType.CREATE_DYNAMIC_TOPOLOGY_COPY: self._create_generated_copy,
            OperationType.REPLACE_OBJECT_WITH_GENERATED_COPY: self._replace_with_copy,
            OperationType.APPLY_GENERATED_MESH_TO_OBJECT: self._replace_with_copy,
            OperationType.CREATE_SCULPT_REGION_FROM_MATERIAL: self._create_sculpt_region,
            OperationType.CREATE_SCULPT_REGION_FROM_VERTEX_GROUP: self._create_sculpt_region,
            OperationType.CREATE_SCULPT_MASK: self._create_sculpt_mask,
            OperationType.INVERT_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.CLEAR_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.BLUR_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.SHARPEN_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.GROW_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.SHRINK_SCULPT_MASK: self._sculpt_mask_operation,
            OperationType.COMBINE_SCULPT_MASKS: self._combine_sculpt_masks,
            OperationType.CREATE_FACE_SET_FROM_MATERIAL: self._create_face_set,
            OperationType.CREATE_FACE_SET_FROM_VERTEX_GROUP: self._create_face_set,
            OperationType.APPLY_SCULPT_REGION_OPERATION: self._apply_sculpt_region_operation,
            OperationType.ADD_MULTIRES_MODIFIER: self._add_modifier,
            OperationType.CREATE_SHAPE_KEY: self._create_shape_key,
            OperationType.CREATE_RIG_SAFE_SHAPE_KEY: self._create_shape_key,
            OperationType.SET_SHAPE_KEY_VALUE: self._set_shape_key_value,
            OperationType.CREATE_PREVIEW_IMAGE: self._create_image_datablock,
            OperationType.CREATE_RENDER_PREVIEW_IMAGE: self._create_image_datablock,
        }
        handlers[operation.type](operation)

    def _create_primitive(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        self._create_object_result(
            operation,
            str(operation.payload["name"]),
            supports_materials=True,
            object_type="MESH",
        )

    def _delete_objects(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            self.object_names.pop(target.name, None)
            target.deleted = True

    def _duplicate_objects(self, operation: Operation) -> None:
        generated_names: list[str] = []
        count = int(operation.payload["count"])
        prefix = operation.payload.get("name_prefix")
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            base = (
                f"{prefix}_{target.name}"
                if isinstance(prefix, str)
                else f"{target.name}_copy"
            )
            for copy_number in range(1, count + 1):
                name = f"{base}_{copy_number:03d}"
                self._reserve_name(self.object_names, name, f"duplicate:{operation.operation_id}")
                generated_names.append(name)
        self.duplicate_names[operation.operation_id] = tuple(generated_names)

    def _set_transform(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            self._editable_object(self._target(target_id, TargetKind.OBJECT))

    def _create_material(self, operation: Operation) -> None:
        name = str(operation.payload["name"])
        self._create_material_result(operation, name)

    def _create_material_result(self, operation: Operation, name: str) -> None:
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.material_names, name, reference)
        self.results[reference] = _SimTarget(TargetKind.MATERIAL, reference, name, None)

    def _create_reference_material(self, operation: Operation) -> None:
        self._material_palette(str(operation.payload["palette_id"]))
        self._create_material_result(operation, str(operation.payload["material_name"]))

    def _create_material_variant(self, operation: Operation) -> None:
        self._target(str(operation.payload["source_material_id"]), TargetKind.MATERIAL)
        self._create_material_result(operation, str(operation.payload["variant_name"]))

    def _assign_material(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if not target.supports_materials:
                raise ExecutionPreflightError(
                    f"Object target {target_id} does not support material slots."
                )

    def _add_light(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        name = str(operation.payload["name"])
        if name in self.light_data_names:
            raise ExecutionPreflightError(f"A light datablock named {name!r} already exists.")
        self.light_data_names.add(name)
        self._create_object_result(operation, name, object_type="LIGHT")

    def _add_camera(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        name = str(operation.payload["name"])
        if name in self.camera_data_names:
            raise ExecutionPreflightError(f"A camera datablock named {name!r} already exists.")
        self.camera_data_names.add(name)
        self._create_object_result(operation, name, object_type="CAMERA")

    def _rename_objects(self, operation: Operation) -> None:
        renames = operation.payload["renames"]
        targets = [
            self._target(str(rename["target_id"]), TargetKind.OBJECT)
            for rename in renames
        ]
        for target in targets:
            self._editable_object(target)
        target_tokens = {target.token for target in targets}
        new_names = [str(rename["new_name"]) for rename in renames]
        if len(new_names) != len(set(new_names)):
            raise ExecutionPreflightError("Rename destinations must be unique.")
        for name in new_names:
            occupant = self.object_names.get(name)
            if occupant is not None and occupant not in target_tokens:
                raise ExecutionPreflightError(f"An object named {name!r} already exists.")
        for target in targets:
            self.object_names.pop(target.name, None)
        for target, name in zip(targets, new_names, strict=True):
            target.name = name
            self.object_names[name] = target.token

    def _move_to_collection(self, operation: Operation) -> None:
        self._collection(operation.payload["collection_id"])
        for target_id in operation.target_ids:
            self._editable_object(self._target(target_id, TargetKind.OBJECT))

    def _import_asset(self, operation: Operation) -> None:
        _validate_import_asset_source(
            str(operation.payload["filepath"]),
            _asset_suffixes(str(operation.payload["format"])),
        )
        self._collection(operation.payload.get("collection_id"))

    def _link_or_append_blend_data(self, operation: Operation) -> None:
        filepath = _existing_local_file(str(operation.payload["filepath"]), {".blend"})
        self._collection(operation.payload.get("collection_id"))
        _validate_blend_datablock_names(
            filepath,
            str(operation.payload["datablock_type"]),
            tuple(str(name) for name in operation.payload["datablock_names"]),
        )

    def _boolean_operation(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        cutter = self._target(str(operation.payload["cutter_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._editable_mesh_object(cutter)
        name = str(operation.payload["modifier_name"])
        if target.live is not None and target.live.modifiers.get(name) is not None:
            raise ExecutionPreflightError(
                f"Object {target.live.name!r} already has a modifier named {name!r}."
            )

    def _join_objects(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        targets = [self._target(target_id, TargetKind.OBJECT) for target_id in operation.target_ids]
        for target in targets:
            self._editable_mesh_object(target)
        name = str(operation.payload["new_name"])
        self._reserve_name(
            self.object_names,
            name,
            f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}",
        )
        for target in targets:
            self.object_names.pop(target.name, None)
            target.deleted = True
        self.results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = _SimTarget(
            TargetKind.OBJECT,
            f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}",
            name,
            None,
            supports_materials=True,
            object_type="MESH",
        )

    def _separate_objects(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        generated_names: list[str] = []
        prefix = str(operation.payload["name_prefix"])
        mode = str(operation.payload["mode"])
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            part_count = (
                _separate_part_count(target.live, mode)
                if target.live is not None
                else 1
            )
            if part_count < 1:
                raise ExecutionPreflightError(f"Object target {target_id} has no separable parts.")
            for index in range(1, part_count + 1):
                name = f"{prefix}_{target.name}_{index:03d}"
                self._reserve_name(
                    self.object_names,
                    name,
                    f"separate:{operation.operation_id}:{len(generated_names) + 1}",
                )
                generated_names.append(name)
            self.object_names.pop(target.name, None)
            target.deleted = True
        self.duplicate_names[operation.operation_id] = tuple(generated_names)

    def _set_material_properties(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)

    def _create_shader_node(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self.shader_node_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _add_shader_layer(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self.shader_layer_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _shader_layer_operation(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._shader_layer(str(operation.payload["layer_id"]))
        mask_source = operation.payload.get("mask_source")
        if isinstance(mask_source, Mapping) and isinstance(mask_source.get("image_id"), str):
            self._image(str(mask_source["image_id"]))

    def _reorder_shader_layers(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        for layer_id in operation.payload["layer_order"]:
            self._shader_layer(str(layer_id))

    def _extract_material_palette(self, operation: Operation) -> None:
        self.material_palette_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _create_preview_image(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._create_image_datablock(operation)

    def _consolidate_duplicate_materials(self, operation: Operation) -> None:
        for material_id in operation.payload["material_ids"]:
            self._target(str(material_id), TargetKind.MATERIAL)
        self._target(str(operation.payload["canonical_material_id"]), TargetKind.MATERIAL)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if not target.supports_materials:
                raise ExecutionPreflightError(
                    f"Object target {target_id} does not support material slots."
                )

    def _material_variant_operation(self, operation: Operation) -> None:
        self._target(str(operation.payload["variant_id"]), TargetKind.MATERIAL)

    def _create_comparison_preview(self, operation: Operation) -> None:
        self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._target(str(operation.payload["source_material_id"]), TargetKind.MATERIAL)
        self._target(str(operation.payload["variant_id"]), TargetKind.MATERIAL)
        self._create_image_datablock(operation)

    def _accept_material_variant(self, operation: Operation) -> None:
        self._target(str(operation.payload["variant_id"]), TargetKind.MATERIAL)
        self._target(str(operation.payload["replace_material_id"]), TargetKind.MATERIAL)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if not target.supports_materials:
                raise ExecutionPreflightError(
                    f"Object target {target_id} does not support material slots."
                )

    def _set_shader_node_value(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._shader_node(str(operation.payload["node_ref"]))

    def _connect_shader_nodes(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._shader_node(str(operation.payload["from_node"]))
        self._shader_node(str(operation.payload["to_node"]))

    def _shader_node_operation(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        for key in ("node_ref", "from_node", "to_node"):
            node_ref = operation.payload.get(key)
            if isinstance(node_ref, str):
                self._shader_node(node_ref)

    def _material_operation(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)

    def _load_image_texture(self, operation: Operation) -> None:
        _validate_image_texture_source(str(operation.payload["source"]))
        name = str(operation.payload["image_name"])
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.image_names, name, reference)
        self.image_results.add(reference)

    def _create_image_texture_node(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._image(str(operation.payload["image_id"]))
        self.shader_node_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _set_texture_mapping(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._shader_node(str(operation.payload["texture_node_ref"]))

    def _assign_uv_map(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._shader_node(str(operation.payload["texture_node_ref"]))
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))

    def _create_uv_map(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            uv_name = str(operation.payload["uv_map_name"])
            uv_maps = self._sim_uv_maps(target)
            if uv_name in uv_maps:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} already has UV map {uv_name!r}."
                )
            uv_maps.add(uv_name)

    def _unwrap_uv_map(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            uv_name = str(operation.payload["uv_map_name"])
            uv_maps = self._sim_uv_maps(target)
            exists = uv_name in uv_maps
            if not exists and not bool(operation.payload["create_if_missing"]):
                raise ExecutionPreflightError(
                    f"Object {target.name!r} has no UV map {uv_name!r}."
                )
            if exists and not bool(operation.payload["overwrite_existing"]):
                raise ExecutionPreflightError(
                    f"UNWRAP_UV_MAP needs overwrite_existing for UV map {uv_name!r}."
                )
            uv_maps.add(uv_name)

    def _pack_uv_islands(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))

    def _uv_report(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self.uv_report_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _uv_multi_report(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self.uv_report_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _uv_preview(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self._create_image_datablock(operation)

    def _mark_uv_seams(self, operation: Operation) -> None:
        material_id = operation.payload.get("material_id")
        if isinstance(material_id, str):
            self._target(material_id, TargetKind.MATERIAL)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
        self.uv_seam_set_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _clear_uv_seams(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)

    def _create_uv_islands_from_seams(self, operation: Operation) -> None:
        self._uv_seam_set(str(operation.payload["seam_set_id"]))
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._ensure_projected_uv_map(target, operation)
        self.uv_island_set_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _project_uv_map(self, operation: Operation) -> None:
        camera_id = operation.payload.get("camera_id")
        if isinstance(camera_id, str):
            self._target(camera_id, TargetKind.OBJECT)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._ensure_projected_uv_map(target, operation)

    def _select_uv_islands(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self.uv_island_set_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _uv_island_operation(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self._uv_island_set(str(operation.payload["island_set_id"]))

    def _uv_map_operation(self, operation: Operation) -> None:
        island_set_id = operation.payload.get("island_set_id")
        if isinstance(island_set_id, str):
            self._uv_island_set(island_set_id)
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))

    def _create_udim_tile_layout(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._ensure_projected_uv_map(target, operation)

    def _merge_duplicate_uv_maps(self, operation: Operation) -> None:
        source_names = tuple(str(name) for name in operation.payload["source_uv_map_names"])
        destination = str(operation.payload["destination_uv_map_name"])
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            uv_maps = self._sim_uv_maps(target)
            if destination not in uv_maps:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} has no destination UV map {destination!r}."
                )
            missing = [name for name in source_names if name not in uv_maps]
            if missing:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} is missing UV maps: {', '.join(missing)}."
                )
            if bool(operation.payload["remove_sources"]):
                for name in source_names:
                    uv_maps.discard(name)

    def _remove_unused_uv_maps(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)

    def _fit_uv_islands_to_image_region(self, operation: Operation) -> None:
        self._uv_island_operation(operation)
        self._image(str(operation.payload["image_id"]))

    def _create_texture_atlas_layout(self, operation: Operation) -> None:
        self._image(str(operation.payload["image_id"]))
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self.uv_atlas_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _assign_atlas_texture_regions(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._uv_atlas(str(operation.payload["atlas_id"]))
        for assignment in operation.payload["assignments"]:
            self._target(str(assignment["material_id"]), TargetKind.MATERIAL)

    def _uv_guide_image(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_mesh_object(target)
            self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self._create_image_datablock(operation)

    def _create_uv_variant(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        uv_maps = self._sim_uv_maps(target)
        source_name = str(operation.payload["source_uv_map_name"])
        variant_name = str(operation.payload["variant_uv_map_name"])
        if source_name not in uv_maps:
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no UV map {source_name!r}."
            )
        if variant_name in uv_maps:
            raise ExecutionPreflightError(
                f"Object {target.name!r} already has UV map {variant_name!r}."
            )
        uv_maps.add(variant_name)
        self.uv_variant_results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = (
            target.token,
            variant_name,
        )

    def _uv_variant_operation(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._uv_variant(str(operation.payload["variant_id"]), target)

    def _uv_variant_preview(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["source_uv_map_name"]))
        self._uv_variant(str(operation.payload["variant_id"]), target)
        self._create_image_datablock(operation)

    def _accept_uv_variant(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._uv_variant(str(operation.payload["variant_id"]), target)
        self._sim_uv_maps(target).add(str(operation.payload["replace_uv_map_name"]))

    def _ensure_projected_uv_map(self, target: _SimTarget, operation: Operation) -> None:
        uv_name = str(operation.payload["uv_map_name"])
        uv_maps = self._sim_uv_maps(target)
        exists = uv_name in uv_maps
        if not exists and not bool(operation.payload.get("create_if_missing", True)):
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no UV map {uv_name!r}."
            )
        if exists and not bool(operation.payload.get("overwrite_existing", True)):
            raise ExecutionPreflightError(
                f"{operation.type.value} needs overwrite_existing for UV map {uv_name!r}."
            )
        uv_maps.add(uv_name)

    def _import_pbr_texture_set(self, operation: Operation) -> None:
        prefix = str(operation.payload["name_prefix"])
        for texture in operation.payload["textures"]:
            _validate_image_texture_source(str(texture["source"]))
            image_name = f"{prefix}_{texture['role']}"
            self._reserve_name(
                self.image_names,
                image_name,
                f"pbr:{operation.operation_id}:{texture['role']}",
            )
        self.texture_set_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _set_pbr_texture_role(self, operation: Operation) -> None:
        self._texture_set(str(operation.payload["texture_set_id"]))
        self._image(str(operation.payload["image_id"]))

    def _create_image_datablock(self, operation: Operation) -> None:
        name = str(operation.payload.get("image_name", operation.payload.get("preview_name")))
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.image_names, name, reference)
        self.image_results.add(reference)

    def _save_generated_texture(self, operation: Operation) -> None:
        self._image(str(operation.payload["image_id"]))
        _validate_texture_save_path(str(operation.payload["filepath"]))

    def _attach_generated_texture(self, operation: Operation) -> None:
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._image(str(operation.payload["image_id"]))
        self.shader_node_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _assign_paint_slot(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))
        self._target(str(operation.payload["material_id"]), TargetKind.MATERIAL)
        self._image(str(operation.payload["image_id"]))
        self.shader_node_results.add(f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}")

    def _apply_texture_paint_strokes(self, operation: Operation) -> None:
        self._image(str(operation.payload["image_id"]))

    def _fill_texture_region(self, operation: Operation) -> None:
        self._image(str(operation.payload["image_id"]))

    def _bake_texture_pass(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._image(str(operation.payload["image_id"]))
        self._require_sim_uv_map(target, str(operation.payload["uv_map_name"]))

    def _sculpt_smooth_region(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        region = operation.payload["region"]
        if isinstance(region, Mapping) and isinstance(region.get("material_id"), str):
            self._target(str(region["material_id"]), TargetKind.MATERIAL)

    def _apply_sculpt_brush_strokes(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)

    def _create_collection(self, operation: Operation) -> None:
        parent_id = operation.payload.get("parent_collection_id")
        self._collection(parent_id)
        name = str(operation.payload["name"])
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.collection_names, name, reference)
        self.results[reference] = _SimTarget(
            TargetKind.COLLECTION,
            reference,
            name,
            None,
        )

    def _set_light_properties(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            data_type = getattr(getattr(target.live, "data", None), "type", None)
            if target.live is not None and data_type not in {"POINT", "SUN", "SPOT", "AREA"}:
                raise ExecutionPreflightError(f"Object target {target_id} is not a light.")

    def _set_camera_properties(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            data_type = getattr(getattr(target.live, "data", None), "type", None)
            if target.live is not None and data_type != "PERSP":
                raise ExecutionPreflightError(f"Object target {target_id} is not a camera.")

    def _add_modifier(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if target.live is not None and getattr(target.live, "type", "") != "MESH":
                raise ExecutionPreflightError(f"Object target {target_id} is not a mesh.")
            name = str(operation.payload["name"])
            if target.live is not None and target.live.modifiers.get(name) is not None:
                raise ExecutionPreflightError(
                    f"Object {target.live.name!r} already has a modifier named "
                    f"{name!r}."
                )
            modifiers = self._sim_modifiers(target)
            if name in modifiers:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} already has a modifier named {name!r}."
                )
            modifiers.add(name)

    def _set_modifier_properties(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if target.live is not None and getattr(target.live, "type", "") != "MESH":
                raise ExecutionPreflightError(f"Object target {target_id} is not a mesh.")
            modifier_name = str(operation.payload["modifier_name"])
            if modifier_name not in self._sim_modifiers(target):
                raise ExecutionPreflightError(
                    f"Object {target.name!r} has no modifier named {modifier_name!r}."
                )

    def _remove_modifier_preflight(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        modifier_name = str(operation.payload["modifier_name"])
        modifiers = self._sim_modifiers(target)
        if modifier_name not in modifiers:
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no modifier named {modifier_name!r}."
            )
        modifiers.remove(modifier_name)

    def _create_generated_copy(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        if target.live is not None:
            _ensure_mesh_size_within_limits(target.live)
        self._create_object_result(
            operation,
            str(operation.payload["name"]),
            supports_materials=True,
            object_type="MESH",
        )

    def _replace_with_copy(self, operation: Operation) -> None:
        original = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        generated = self._target(str(operation.payload["generated_object_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(original)
        self._editable_mesh_object(generated)

    def _create_sculpt_region(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self.results[reference] = _SimTarget(
            TargetKind.OBJECT,
            reference,
            str(operation.payload["region_name"]),
            target.live,
            object_type="SCULPT_REGION",
        )

    def _create_sculpt_mask(self, operation: Operation) -> None:
        region = self.results.get(str(operation.payload["region_id"]))
        if region is None or region.object_type != "SCULPT_REGION":
            raise ExecutionPreflightError("Sculpt region result is unavailable.")
        if region.live is not None:
            target = _SimTarget(
                TargetKind.OBJECT,
                f"object:{int(region.live.session_uid)}",
                str(region.live.name),
                region.live,
                supports_materials=True,
                object_type=getattr(region.live, "type", ""),
            )
            mask_names = self._sim_vertex_groups(target)
            mask_name = str(operation.payload["mask_name"])
            if mask_name in mask_names:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} already has vertex group {mask_name!r}."
                )
            mask_names.add(mask_name)
        self.results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = _SimTarget(
            TargetKind.OBJECT,
            f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}",
            str(operation.payload["mask_name"]),
            region.live,
            object_type="SCULPT_MASK",
        )

    def _sculpt_mask_operation(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._require_sim_vertex_group(target, str(operation.payload["mask_name"]))

    def _combine_sculpt_masks(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        mask_names = self._sim_vertex_groups(target)
        source = str(operation.payload["source_mask_name"])
        target_mask = str(operation.payload["target_mask_name"])
        result = str(operation.payload["result_mask_name"])
        for mask_name in (source, target_mask):
            if mask_name not in mask_names:
                raise ExecutionPreflightError(
                    f"Object {target.name!r} has no vertex group {mask_name!r}."
                )
        if result in mask_names:
            raise ExecutionPreflightError(
                f"Object {target.name!r} already has vertex group {result!r}."
            )
        mask_names.add(result)
        self.results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = _SimTarget(
            TargetKind.OBJECT,
            f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}",
            result,
            target.live,
            object_type="SCULPT_MASK",
        )

    def _create_face_set(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        material_id = operation.payload.get("material_id")
        if isinstance(material_id, str):
            self._target(material_id, TargetKind.MATERIAL)
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self.results[reference] = _SimTarget(
            TargetKind.OBJECT,
            reference,
            str(operation.payload["face_set_name"]),
            None,
            object_type="FACE_SET",
        )

    def _apply_sculpt_region_operation(self, operation: Operation) -> None:
        region = self.results.get(str(operation.payload["region_id"]))
        if region is None or region.object_type != "SCULPT_REGION":
            raise ExecutionPreflightError("Sculpt region result is unavailable.")

    def _create_shape_key(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        self._sim_shape_keys(target).add(str(operation.payload["name"]))
        source_id = operation.payload["from_generated_object_id"]
        if source_id is not None:
            source = self._target(str(source_id), TargetKind.OBJECT)
            self._editable_mesh_object(source)

    def _set_shape_key_value(self, operation: Operation) -> None:
        target = self._target(str(operation.payload["target_id"]), TargetKind.OBJECT)
        self._editable_mesh_object(target)
        if str(operation.payload["shape_key_name"]) not in self._sim_shape_keys(target):
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no shape key {operation.payload['shape_key_name']!r}."
            )

    def _create_text_object(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        self._create_object_result(
            operation,
            str(operation.payload["name"]),
            supports_materials=True,
        )

    def _set_object_visibility(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            self._editable_object(self._target(target_id, TargetKind.OBJECT))

    def _create_object_result(
        self,
        operation: Operation,
        name: str,
        *,
        supports_materials: bool = False,
        object_type: str = "",
    ) -> None:
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.object_names, name, reference)
        self.results[reference] = _SimTarget(
            TargetKind.OBJECT,
            reference,
            name,
            None,
            supports_materials,
            object_type=object_type,
        )

    def _target(self, target_id: str, expected_kind: TargetKind) -> _SimTarget:
        if target_id.startswith(RESULT_REFERENCE_PREFIX):
            target = self.results.get(target_id)
        else:
            target = self.existing.get(target_id)
            if target is None:
                item = self.resolved.get(target_id)
                reference = self.snapshot.target_index.get(target_id)
                if item is not None and reference is not None:
                    target = _SimTarget(
                        reference.kind,
                        f"{reference.kind.value}:{int(item.session_uid)}",
                        item.name,
                        item,
                        reference.kind is TargetKind.OBJECT
                        and item.data is not None
                        and hasattr(item.data, "materials"),
                        object_type=getattr(item, "type", ""),
                    )
                    self.existing[target_id] = target
        if target is None:
            raise ExecutionPreflightError(f"Target {target_id} is unavailable.")
        if target.kind is not expected_kind:
            raise ExecutionPreflightError(
                f"Target {target_id} is {target.kind.value}, not {expected_kind.value}."
            )
        if target.deleted:
            raise ExecutionPreflightError(f"Target {target_id} is referenced after deletion.")
        return target

    def _collection(self, target_id: Any) -> Any:
        if target_id is None:
            collection = _default_collection(self.context)
        elif str(target_id).startswith(RESULT_REFERENCE_PREFIX):
            collection = self._target(str(target_id), TargetKind.COLLECTION)
        else:
            collection = self._target(str(target_id), TargetKind.COLLECTION).live
        if isinstance(collection, _SimTarget):
            return collection
        if collection not in self.scene_collections:
            raise ExecutionPreflightError("The destination collection is not in the active scene.")
        if getattr(collection, "library", None) is not None:
            raise ExecutionPreflightError("Linked collections cannot be modified.")
        return collection

    def _shader_node(self, node_ref: str) -> None:
        if not node_ref.startswith(RESULT_REFERENCE_PREFIX):
            return
        if node_ref not in self.shader_node_results:
            raise ExecutionPreflightError(
                f"Shader node result {node_ref} is unavailable."
            )

    def _shader_layer(self, layer_ref: str) -> None:
        if layer_ref not in self.shader_layer_results:
            raise ExecutionPreflightError(
                f"Shader layer result {layer_ref} is unavailable."
            )

    def _image(self, image_ref: str) -> None:
        if image_ref not in self.image_results:
            raise ExecutionPreflightError(f"Image result {image_ref} is unavailable.")

    def _texture_set(self, texture_set_ref: str) -> None:
        if texture_set_ref not in self.texture_set_results:
            raise ExecutionPreflightError(
                f"Texture set result {texture_set_ref} is unavailable."
            )

    def _material_palette(self, palette_ref: str) -> None:
        if palette_ref not in self.material_palette_results:
            raise ExecutionPreflightError(
                f"Material palette result {palette_ref} is unavailable."
            )

    def _uv_seam_set(self, seam_set_ref: str) -> None:
        if seam_set_ref not in self.uv_seam_set_results:
            raise ExecutionPreflightError(
                f"UV seam-set result {seam_set_ref} is unavailable."
            )

    def _uv_island_set(self, island_set_ref: str) -> None:
        if island_set_ref not in self.uv_island_set_results:
            raise ExecutionPreflightError(
                f"UV island-set result {island_set_ref} is unavailable."
            )

    def _uv_atlas(self, atlas_ref: str) -> None:
        if atlas_ref not in self.uv_atlas_results:
            raise ExecutionPreflightError(f"UV atlas result {atlas_ref} is unavailable.")

    def _uv_variant(self, variant_ref: str, target: _SimTarget) -> None:
        variant = self.uv_variant_results.get(variant_ref)
        if variant is None:
            raise ExecutionPreflightError(f"UV variant result {variant_ref} is unavailable.")
        target_token, variant_name = variant
        if target_token != target.token:
            raise ExecutionPreflightError(
                f"UV variant {variant_ref} belongs to a different mesh target."
            )
        self._require_sim_uv_map(target, variant_name)

    def _sim_uv_maps(self, target: _SimTarget) -> set[str]:
        uv_maps = self.uv_maps.get(target.token)
        if uv_maps is not None:
            return uv_maps
        names: set[str] = set()
        if target.live is not None and getattr(target.live, "type", "") == "MESH":
            names = {str(layer.name) for layer in target.live.data.uv_layers}
        self.uv_maps[target.token] = names
        return names

    def _require_sim_uv_map(self, target: _SimTarget, uv_map_name: str) -> None:
        if uv_map_name not in self._sim_uv_maps(target):
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no UV map {uv_map_name!r}."
            )

    def _sim_modifiers(self, target: _SimTarget) -> set[str]:
        modifiers = self.modifier_names.get(target.token)
        if modifiers is not None:
            return modifiers
        names: set[str] = set()
        if target.live is not None:
            names = {str(modifier.name) for modifier in target.live.modifiers}
        self.modifier_names[target.token] = names
        return names

    def _sim_shape_keys(self, target: _SimTarget) -> set[str]:
        shape_keys = self.shape_key_names.get(target.token)
        if shape_keys is not None:
            return shape_keys
        names: set[str] = set()
        if target.live is not None and getattr(target.live, "type", "") == "MESH":
            key_blocks = getattr(getattr(target.live.data, "shape_keys", None), "key_blocks", None)
            if key_blocks is not None:
                names = {str(key.name) for key in key_blocks}
        self.shape_key_names[target.token] = names
        return names

    def _sim_vertex_groups(self, target: _SimTarget) -> set[str]:
        groups = self.vertex_group_names.get(target.token)
        if groups is not None:
            return groups
        names: set[str] = set()
        if target.live is not None and getattr(target.live, "type", "") == "MESH":
            names = {str(group.name) for group in target.live.vertex_groups}
        self.vertex_group_names[target.token] = names
        return names

    def _require_sim_vertex_group(self, target: _SimTarget, group_name: str) -> None:
        if group_name not in self._sim_vertex_groups(target):
            raise ExecutionPreflightError(
                f"Object {target.name!r} has no vertex group {group_name!r}."
            )

    @staticmethod
    def _reserve_name(names: dict[str, str], name: str, token: str) -> None:
        if name in names:
            raise ExecutionPreflightError(f"A datablock named {name!r} already exists.")
        names[name] = token

    @staticmethod
    def _editable_object(target: _SimTarget) -> None:
        item = target.live
        if item is not None and getattr(item, "library", None) is not None:
            raise ExecutionPreflightError(f"Linked object {item.name!r} cannot be modified.")

    @classmethod
    def _editable_mesh_object(cls, target: _SimTarget) -> None:
        cls._editable_object(target)
        if target.live is not None:
            object_type = getattr(target.live, "type", "")
        else:
            object_type = target.object_type
        if object_type != "MESH":
            raise ExecutionPreflightError(f"Object target {target.token} is not a mesh.")


def _execute_operation(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    handlers: dict[OperationType, Callable[[], None]] = {
        OperationType.CREATE_PRIMITIVE: lambda: _create_primitive(
            context, operation, prepared, results, transaction
        ),
        OperationType.DELETE_OBJECTS: lambda: _stage_delete(
            operation, prepared, results, transaction
        ),
        OperationType.DUPLICATE_OBJECTS: lambda: _duplicate_objects(
            operation, prepared, results, transaction
        ),
        OperationType.SET_TRANSFORM: lambda: _set_transform(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_MATERIAL: lambda: _create_material(
            operation, results, transaction
        ),
        OperationType.CREATE_MATERIAL_PRESET: lambda: _create_material(
            operation, results, transaction
        ),
        OperationType.CREATE_PROCEDURAL_MATERIAL: lambda: _create_material(
            operation, results, transaction
        ),
        OperationType.ASSIGN_MATERIAL: lambda: _assign_material(
            operation, prepared, results, transaction
        ),
        OperationType.ADD_LIGHT: lambda: _add_light(
            context, operation, prepared, results, transaction
        ),
        OperationType.ADD_CAMERA: lambda: _add_camera(
            context, operation, prepared, results, transaction
        ),
        OperationType.RENAME_OBJECTS: lambda: _rename_objects(
            operation, prepared, results, transaction
        ),
        OperationType.MOVE_TO_COLLECTION: lambda: _move_to_collection(
            operation, prepared, results, transaction
        ),
        OperationType.SET_MATERIAL_PROPERTIES: lambda: _set_material_properties(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_COLLECTION: lambda: _create_collection(
            context, operation, prepared, results, transaction
        ),
        OperationType.SET_LIGHT_PROPERTIES: lambda: _set_light_properties(
            operation, prepared, results, transaction
        ),
        OperationType.SET_CAMERA_PROPERTIES: lambda: _set_camera_properties(
            context, operation, prepared, results, transaction
        ),
        OperationType.ADD_MODIFIER: lambda: _add_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.SET_MODIFIER_PROPERTIES: lambda: _set_modifier_properties(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_TEXT_OBJECT: lambda: _create_text_object(
            context, operation, prepared, results, transaction
        ),
        OperationType.SET_OBJECT_VISIBILITY: lambda: _set_object_visibility(
            operation, prepared, results, transaction
        ),
        OperationType.IMPORT_ASSET: lambda: _import_asset(
            context, operation, prepared, results, transaction
        ),
        OperationType.LINK_OR_APPEND_BLEND_DATA: lambda: _link_or_append_blend_data(
            context, operation, prepared, results, transaction
        ),
        OperationType.BOOLEAN_OPERATION: lambda: _boolean_operation(
            context, operation, prepared, results, transaction
        ),
        OperationType.JOIN_OBJECTS: lambda: _join_objects(
            context, operation, prepared, results, transaction
        ),
        OperationType.SEPARATE_OBJECTS: lambda: _separate_objects(
            context, operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHADER_NODE: lambda: _create_shader_node(
            operation, prepared, results, transaction
        ),
        OperationType.SET_SHADER_NODE_VALUE: lambda: _set_shader_node_value(
            operation, prepared, results, transaction
        ),
        OperationType.CONNECT_SHADER_NODES: lambda: _connect_shader_nodes(
            operation, prepared, results, transaction
        ),
        OperationType.REMOVE_SHADER_NODE: lambda: _remove_shader_node_operation(
            operation, prepared, results, transaction
        ),
        OperationType.DISCONNECT_SHADER_LINK: lambda: _disconnect_shader_link(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHADER_COLOR_RAMP: lambda: _create_shader_color_ramp(
            operation, prepared, results, transaction
        ),
        OperationType.SET_SHADER_COLOR_RAMP: lambda: _set_shader_color_ramp(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHADER_MIX_CHAIN: lambda: _create_shader_mix_chain(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHADER_GRAPH_TEMPLATE: lambda: _create_shader_graph_template(
            operation, prepared, results, transaction
        ),
        OperationType.VALIDATE_MATERIAL_OUTPUT: lambda: _validate_material_output(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_LAYERED_SHADER_MATERIAL: lambda: _create_layered_shader_material(
            operation, results, transaction
        ),
        OperationType.ADD_SHADER_LAYER: lambda: _add_shader_layer(
            operation, prepared, results, transaction
        ),
        OperationType.SET_SHADER_LAYER_MASK: lambda: _set_shader_layer_mask(
            operation, prepared, results, transaction
        ),
        OperationType.REORDER_SHADER_LAYERS: lambda: _reorder_shader_layers(
            operation, prepared, results, transaction
        ),
        OperationType.REMOVE_SHADER_LAYER: lambda: _remove_shader_layer(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_PROCEDURAL_PATTERN_NODE_SET: lambda: (
            _create_procedural_pattern_node_set(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_EDGE_WEAR_SHADER: lambda: _create_procedural_pattern_node_set(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_TRIPLANAR_MAPPING_SETUP: lambda: (
            _create_procedural_pattern_node_set(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_OBJECT_SPACE_GRADIENT_SHADER: lambda: (
            _create_procedural_pattern_node_set(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_CURVATURE_STYLE_MASK: lambda: _create_procedural_pattern_node_set(
            operation, prepared, results, transaction
        ),
        OperationType.EXTRACT_MATERIAL_PALETTE_FROM_IMAGE: lambda: (
            _extract_material_palette_from_image(operation, results, transaction)
        ),
        OperationType.CREATE_MATERIAL_FROM_REFERENCE_IMAGE: lambda: (
            _create_material_from_reference_image(operation, results, transaction)
        ),
        OperationType.MATCH_MATERIAL_TO_REFERENCE: lambda: _match_material_to_reference(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_LOOKDEV_PREVIEW: lambda: _create_lookdev_preview(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_GLASS_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.CREATE_TRANSLUCENT_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.CREATE_EMISSION_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.CREATE_VOLUME_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.CREATE_TOON_SHADER_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.CREATE_ANISOTROPIC_MATERIAL: lambda: _create_specialized_material(
            operation, results, transaction
        ),
        OperationType.REMOVE_UNUSED_ASSISTANT_SHADER_NODES: lambda: (
            _remove_unused_assistant_shader_nodes(operation, prepared, results, transaction)
        ),
        OperationType.CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS: lambda: (
            _consolidate_duplicate_assistant_materials(
                operation, prepared, results, transaction
            )
        ),
        OperationType.NORMALIZE_SHADER_NODE_LAYOUT: lambda: _normalize_shader_node_layout(
            operation, prepared, results, transaction
        ),
        OperationType.VALIDATE_SHADER_COMPATIBILITY: lambda: (
            _validate_shader_compatibility_operation(operation, prepared, results, transaction)
        ),
        OperationType.REPAIR_BROKEN_SHADER_LINKS: lambda: _repair_broken_shader_links(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_MATERIAL_VARIANT: lambda: _create_material_variant(
            operation, prepared, results, transaction
        ),
        OperationType.TAG_MATERIAL_VARIANT: lambda: _tag_material_variant(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHADER_COMPARISON_PREVIEW: lambda: (
            _create_shader_comparison_preview(operation, prepared, results, transaction)
        ),
        OperationType.ACCEPT_MATERIAL_VARIANT: lambda: _accept_material_variant(
            operation, prepared, results, transaction
        ),
        OperationType.REJECT_MATERIAL_VARIANT: lambda: _reject_material_variant(
            operation, prepared, results, transaction
        ),
        OperationType.LOAD_IMAGE_TEXTURE: lambda: _load_image_texture(
            operation, results, transaction
        ),
        OperationType.CREATE_IMAGE_TEXTURE_NODE: lambda: _create_image_texture_node(
            operation, prepared, results, transaction
        ),
        OperationType.SET_TEXTURE_MAPPING: lambda: _set_texture_mapping(
            operation, prepared, results, transaction
        ),
        OperationType.ASSIGN_UV_MAP: lambda: _assign_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_MAP: lambda: _create_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.UNWRAP_UV_MAP: lambda: _unwrap_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.PACK_UV_ISLANDS: lambda: _pack_uv_islands(
            operation, prepared, results, transaction
        ),
        OperationType.INSPECT_UV_MAP: lambda: _create_uv_report(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_DIAGNOSTIC_REPORT: lambda: _create_uv_report(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_OVERLAP_PREVIEW: lambda: _create_uv_preview(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_STRETCH_PREVIEW: lambda: _create_uv_preview(
            operation, prepared, results, transaction
        ),
        OperationType.MARK_UV_SEAMS_BY_ANGLE: lambda: _mark_uv_seams_by_angle(
            operation, prepared, results, transaction
        ),
        OperationType.MARK_UV_SEAMS_BY_MATERIAL: lambda: _mark_uv_seams_by_material(
            operation, prepared, results, transaction
        ),
        OperationType.MARK_UV_SEAMS_BY_EDGE_SET: lambda: _mark_uv_seams_by_edge_set(
            operation, prepared, results, transaction
        ),
        OperationType.CLEAR_UV_SEAMS: lambda: _clear_uv_seams(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_ISLANDS_FROM_SEAMS: lambda: _create_uv_islands_from_seams(
            operation, prepared, results, transaction
        ),
        OperationType.SMART_PROJECT_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.CUBE_PROJECT_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.CYLINDER_PROJECT_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.SPHERE_PROJECT_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.CAMERA_PROJECT_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.LIGHTMAP_UNWRAP_UV_MAP: lambda: _project_uv_map(
            operation, prepared, results, transaction
        ),
        OperationType.SELECT_UV_ISLANDS_BY_MATERIAL: lambda: _select_uv_islands_by_material(
            operation, prepared, results, transaction
        ),
        OperationType.TRANSFORM_UV_ISLANDS: lambda: _transform_uv_islands(
            operation, prepared, results, transaction
        ),
        OperationType.ALIGN_UV_ISLANDS: lambda: _align_uv_islands(
            operation, prepared, results, transaction
        ),
        OperationType.DISTRIBUTE_UV_ISLANDS: lambda: _distribute_uv_islands(
            operation, prepared, results, transaction
        ),
        OperationType.SCALE_UV_ISLANDS_TO_BOUNDS: lambda: _scale_uv_islands_to_bounds(
            operation, prepared, results, transaction
        ),
        OperationType.PIN_UV_ISLANDS: lambda: _set_uv_island_pins(
            operation, prepared, results, transaction, pinned=True
        ),
        OperationType.UNPIN_UV_ISLANDS: lambda: _set_uv_island_pins(
            operation, prepared, results, transaction, pinned=False
        ),
        OperationType.SET_UV_TEXEL_DENSITY: lambda: _set_uv_texel_density(
            operation, prepared, results, transaction
        ),
        OperationType.NORMALIZE_UV_TEXEL_DENSITY: lambda: _normalize_uv_texel_density(
            operation, prepared, results, transaction
        ),
        OperationType.PACK_UV_ISLANDS_ADVANCED: lambda: _pack_uv_islands_advanced(
            operation, prepared, results, transaction
        ),
        OperationType.MOVE_UV_ISLANDS_TO_TILE: lambda: _move_uv_islands_to_tile(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UDIM_TILE_LAYOUT: lambda: _create_udim_tile_layout(
            operation, prepared, results, transaction
        ),
        OperationType.VALIDATE_UDIM_LAYOUT: lambda: _create_uv_report(
            operation, prepared, results, transaction
        ),
        OperationType.RELAX_UV_ISLANDS: lambda: _relax_uv_islands(
            operation, prepared, results, transaction
        ),
        OperationType.MINIMIZE_UV_STRETCH: lambda: _minimize_uv_stretch(
            operation, prepared, results, transaction
        ),
        OperationType.REPAIR_UV_BOUNDS: lambda: _repair_uv_bounds(
            operation, prepared, results, transaction
        ),
        OperationType.MERGE_DUPLICATE_UV_MAPS: lambda: _merge_duplicate_uv_maps(
            operation, prepared, results, transaction
        ),
        OperationType.REMOVE_UNUSED_ASSISTANT_UV_MAPS: lambda: _remove_unused_assistant_uv_maps(
            operation, prepared, results, transaction
        ),
        OperationType.VALIDATE_UV_MAP: lambda: _create_uv_report(
            operation, prepared, results, transaction
        ),
        OperationType.FIT_UV_ISLANDS_TO_IMAGE_REGION: lambda: _fit_uv_islands_to_image_region(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_TEXTURE_ATLAS_LAYOUT: lambda: _create_texture_atlas_layout(
            operation, prepared, results, transaction
        ),
        OperationType.ASSIGN_ATLAS_TEXTURE_REGIONS: lambda: _assign_atlas_texture_regions(
            operation, prepared, results, transaction
        ),
        OperationType.BAKE_UV_LAYOUT_GUIDE_IMAGE: lambda: _bake_uv_layout_guide_image(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_GRID_TEST_MATERIAL: lambda: _create_uv_grid_test_material(
            operation, results, transaction
        ),
        OperationType.CREATE_UV_MAP_VARIANT: lambda: _create_uv_map_variant(
            operation, prepared, results, transaction
        ),
        OperationType.TAG_UV_VARIANT: lambda: _tag_uv_variant(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_UV_COMPARISON_PREVIEW: lambda: _create_uv_comparison_preview(
            operation, prepared, results, transaction
        ),
        OperationType.ACCEPT_UV_VARIANT: lambda: _accept_uv_variant(
            operation, prepared, results, transaction
        ),
        OperationType.REJECT_UV_VARIANT: lambda: _reject_uv_variant(
            operation, prepared, results, transaction
        ),
        OperationType.IMPORT_PBR_TEXTURE_SET: lambda: _import_pbr_texture_set(
            operation, results, transaction
        ),
        OperationType.CREATE_PBR_MATERIAL: lambda: _create_pbr_material(
            operation, results, transaction
        ),
        OperationType.SET_PBR_TEXTURE_ROLE: lambda: _set_pbr_texture_role(
            operation, results, transaction
        ),
        OperationType.GENERATE_IMAGE_ASSET: lambda: _generate_image_asset(
            context, operation, results, transaction
        ),
        OperationType.GENERATE_TEXTURE_IMAGE: lambda: _generate_texture_image(
            context, operation, results, transaction
        ),
        OperationType.SAVE_GENERATED_TEXTURE: lambda: _save_generated_texture(
            operation, results, transaction
        ),
        OperationType.APPLY_IMAGE_TO_MATERIAL: lambda: _attach_texture_image(
            operation, prepared, results, transaction
        ),
        OperationType.ATTACH_GENERATED_TEXTURE: lambda: _attach_texture_image(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_PAINT_IMAGE: lambda: _create_paint_image(
            operation, results, transaction
        ),
        OperationType.ASSIGN_PAINT_SLOT: lambda: _assign_paint_slot(
            operation, prepared, results, transaction
        ),
        OperationType.APPLY_TEXTURE_PAINT_STROKES: lambda: _apply_texture_paint_strokes(
            operation, results, transaction
        ),
        OperationType.FILL_TEXTURE_REGION: lambda: _fill_texture_region(
            operation, results, transaction
        ),
        OperationType.CREATE_BAKE_TARGET_IMAGE: lambda: _create_bake_target_image(
            operation, results, transaction
        ),
        OperationType.BAKE_TEXTURE_PASS: lambda: _bake_texture_pass(
            operation, prepared, results, transaction
        ),
        OperationType.ASSIGN_BAKED_TEXTURE: lambda: _attach_texture_image(
            operation, prepared, results, transaction
        ),
        OperationType.ADD_DISPLACE_MODIFIER: lambda: _add_displace_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.ADD_SMOOTH_MODIFIER: lambda: _add_smooth_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.ADD_REMESH_MODIFIER: lambda: _add_remesh_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.SCULPT_SMOOTH_REGION: lambda: _sculpt_smooth_region(
            operation, prepared, results, transaction
        ),
        OperationType.APPLY_SCULPT_BRUSH_STROKES: lambda: _apply_sculpt_brush_strokes(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_GEOMETRY_NODES_PRESET: lambda: _create_geometry_nodes_preset(
            operation, prepared, results, transaction
        ),
        OperationType.SET_GEOMETRY_NODE_INPUT: lambda: _set_geometry_node_input(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_GEOMETRY_NODE_GROUP_TEMPLATE: lambda: (
            _create_geometry_node_group_template(operation, prepared, results, transaction)
        ),
        OperationType.REMOVE_GEOMETRY_NODES_MODIFIER: lambda: _remove_geometry_nodes_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_GENERATED_GEOMETRY_COPY: lambda: _create_generated_geometry_copy(
            context, operation, prepared, results, transaction
        ),
        OperationType.CREATE_SMOOTHED_COPY: lambda: _create_smoothed_copy(
            context, operation, prepared, results, transaction
        ),
        OperationType.CREATE_DISPLACED_COPY: lambda: _create_displaced_copy(
            context, operation, prepared, results, transaction
        ),
        OperationType.CREATE_REMESHED_COPY: lambda: _create_remeshed_copy(
            context, operation, prepared, results, transaction
        ),
        OperationType.CREATE_DYNAMIC_TOPOLOGY_COPY: lambda: _create_dynamic_topology_copy(
            context, operation, prepared, results, transaction
        ),
        OperationType.REPLACE_OBJECT_WITH_GENERATED_COPY: lambda: (
            _replace_object_with_generated_copy(operation, prepared, results, transaction)
        ),
        OperationType.APPLY_GENERATED_MESH_TO_OBJECT: lambda: (
            _apply_generated_mesh_to_object(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_SCULPT_REGION_FROM_MATERIAL: lambda: (
            _create_sculpt_region_from_material(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_SCULPT_REGION_FROM_VERTEX_GROUP: lambda: (
            _create_sculpt_region_from_vertex_group(operation, prepared, results, transaction)
        ),
        OperationType.CREATE_SCULPT_MASK: lambda: _create_sculpt_mask(
            operation, results, transaction
        ),
        OperationType.INVERT_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.CLEAR_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.BLUR_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.SHARPEN_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.GROW_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.SHRINK_SCULPT_MASK: lambda: _sculpt_mask_operation(
            operation, prepared, results, transaction
        ),
        OperationType.COMBINE_SCULPT_MASKS: lambda: _combine_sculpt_masks(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_FACE_SET_FROM_MATERIAL: lambda: _create_face_set_from_material(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_FACE_SET_FROM_VERTEX_GROUP: lambda: (
            _create_face_set_from_vertex_group(operation, prepared, results, transaction)
        ),
        OperationType.APPLY_SCULPT_REGION_OPERATION: lambda: _apply_sculpt_region_operation(
            operation, results, transaction
        ),
        OperationType.ADD_MULTIRES_MODIFIER: lambda: _add_multires_modifier(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_SHAPE_KEY: lambda: _create_shape_key(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_RIG_SAFE_SHAPE_KEY: lambda: _create_rig_safe_shape_key(
            operation, prepared, results, transaction
        ),
        OperationType.SET_SHAPE_KEY_VALUE: lambda: _set_shape_key_value(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_PREVIEW_IMAGE: lambda: _create_preview_image(
            operation, prepared, results, transaction
        ),
        OperationType.CREATE_RENDER_PREVIEW_IMAGE: lambda: _create_render_preview_image(
            context, operation, prepared, results, transaction
        ),
    }
    handlers[operation.type]()


def _create_primitive(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bmesh
    import bpy

    name = str(operation.payload["name"])
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    primitive = str(operation.payload["primitive"])
    item: Any | None = None
    try:
        if primitive == "torus":
            _build_torus(mesh)
        else:
            builder = bmesh.new()
            try:
                if primitive == "cube":
                    bmesh.ops.create_cube(builder, size=2.0)
                elif primitive == "sphere":
                    bmesh.ops.create_uvsphere(
                        builder, u_segments=32, v_segments=16, radius=1.0
                    )
                elif primitive == "cylinder":
                    bmesh.ops.create_cone(
                        builder,
                        cap_ends=True,
                        cap_tris=False,
                        segments=32,
                        radius1=1.0,
                        radius2=1.0,
                        depth=2.0,
                    )
                elif primitive == "cone":
                    bmesh.ops.create_cone(
                        builder,
                        cap_ends=True,
                        cap_tris=False,
                        segments=32,
                        radius1=1.0,
                        radius2=0.0,
                        depth=2.0,
                    )
                elif primitive == "plane":
                    bmesh.ops.create_grid(builder, x_segments=1, y_segments=1, size=2.0)
                else:
                    raise ExecutionError(f"Unsupported primitive type: {primitive}.")
                builder.to_mesh(mesh)
            finally:
                builder.free()

        item = bpy.data.objects.new(name, mesh)
        collection = _runtime_collection(
            context, operation.payload.get("collection_id"), prepared, results
        )
        collection.objects.link(item)
        if item.name != name:
            raise ExecutionError(f"Blender could not assign object name {name!r}.")
        _apply_absolute_transform(item, operation.payload)
    except Exception:
        if item is not None:
            _remove_created_object(item, mesh)
        else:
            _remove_orphan_datablock(mesh)
        raise
    transaction.add_rollback(partial(_remove_created_object, item, mesh))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            f"Created {primitive} mesh",
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            collection,
            "collection",
            ChangeKind.UPDATED,
            f"Linked object {item.name}",
        )
    )


def _stage_delete(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _stage_object_deletion(operation.operation_id, target_id, item, transaction)


def _duplicate_objects(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    names = iter(prepared.duplicate_names[operation.operation_id])
    count = int(operation.payload["count"])
    offset = operation.payload["offset"]
    created_index = 0
    for target_id in operation.target_ids:
        source = _runtime_target(target_id, prepared, results)
        for copy_number in range(1, count + 1):
            duplicate = source.copy()
            duplicate_data: Any | None = None
            try:
                duplicate_data = source.data.copy() if source.data is not None else None
                duplicate.data = duplicate_data
                requested_name = next(names)
                duplicate.name = requested_name
                if duplicate.name != requested_name:
                    raise ExecutionError(
                        f"Blender could not assign object name {requested_name!r}."
                    )
                collections = tuple(source.users_collection) or (
                    _default_collection_from_scene(source),
                )
                for collection in collections:
                    collection.objects.link(duplicate)
                duplicate.location = tuple(
                    float(source.location[index]) + float(offset[index]) * copy_number
                    for index in range(3)
                )
            except Exception:
                _remove_created_object(duplicate, duplicate_data)
                raise
            created_index += 1
            result_id = f"duplicate:{operation.operation_id}:{created_index}"
            transaction.add_rollback(
                partial(_remove_created_object, duplicate, duplicate_data)
            )
            transaction.record(
                ChangeRecord(
                    operation.operation_id,
                    result_id,
                    "object",
                    duplicate.name,
                    ChangeKind.CREATED,
                    f"Duplicated {source.name}",
                )
            )
            for collection in collections:
                transaction.record(
                    _datablock_change(
                        operation.operation_id,
                        collection,
                        "collection",
                        ChangeKind.UPDATED,
                        f"Linked duplicate {duplicate.name}",
                    )
                )


def _set_transform(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    payload = operation.payload
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        old_matrix = item.matrix_basis.copy()
        old_rotation_mode = item.rotation_mode
        transaction.add_rollback(
            partial(_restore_transform, item, old_matrix, old_rotation_mode)
        )
        if payload["rotation_euler"] is not None:
            item.rotation_mode = "XYZ"
        if payload["mode"] == "absolute":
            _set_channels_absolute(item, payload)
        else:
            _set_channels_relative(item, payload)
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Updated transform",
            )
        )


def _create_material(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    material = bpy.data.materials.new(str(payload["name"]))
    try:
        if material.name != str(payload["name"]):
            raise ExecutionError(
                f"Blender could not assign material name {str(payload['name'])!r}."
            )
        material_any: Any = material
        material_any.use_nodes = True
        color = tuple(float(value) for value in payload["base_color"])
        alpha = float(payload["alpha"])
        material_any.diffuse_color = (*color, alpha)
        material_any.metallic = float(payload["metallic"])
        material_any.roughness = float(payload["roughness"])
        principled = material_any.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            raise ExecutionError("The new material has no Principled BSDF node.")
        principled.inputs["Base Color"].default_value = (*color, alpha)
        principled.inputs["Metallic"].default_value = float(payload["metallic"])
        principled.inputs["Roughness"].default_value = float(payload["roughness"])
        principled.inputs["Alpha"].default_value = alpha
        _set_principled_optional_inputs(principled, payload)
        if operation.type in {
            OperationType.CREATE_MATERIAL_PRESET,
            OperationType.CREATE_PROCEDURAL_MATERIAL,
        }:
            _build_controlled_material_nodes(material_any, payload)
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = material
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "material",
            material.name,
            ChangeKind.CREATED,
            f"Created {operation.type.value} material",
        )
    )


def _assign_material(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        original_data = item.data
        if original_data.users > 1:
            copied_data = original_data.copy()
            item.data = copied_data
            transaction.add_rollback(
                partial(_restore_copied_data, item, original_data, copied_data)
            )
            data = copied_data
        else:
            data = original_data
            old_materials = tuple(data.materials)
            old_indices = tuple(
                int(polygon.material_index) for polygon in getattr(data, "polygons", ())
            )
            transaction.add_rollback(
                partial(_restore_materials, data, old_materials, old_indices)
            )
        data.materials.clear()
        data.materials.append(material)
        for polygon in getattr(data, "polygons", ()):
            polygon.material_index = 0
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Assigned material {material.name}",
            )
        )


def _add_light(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    name = str(payload["name"])
    light = cast(Any, bpy.data).lights.new(
        name, type=str(payload["light_type"]).upper()
    )
    item: Any | None = None
    try:
        light.color = tuple(float(value) for value in payload["color"])
        light.energy = float(payload["energy"])
        size = float(payload["size"])
        if light.type == "AREA":
            light.size = size
        elif light.type in {"POINT", "SPOT"}:
            light.shadow_soft_size = size
        else:
            light.angle = size
        item = bpy.data.objects.new(name, light)
        collection = _runtime_collection(
            context, payload.get("collection_id"), prepared, results
        )
        collection.objects.link(item)
        if item.name != name or light.name != name:
            raise ExecutionError(f"Blender could not assign light name {name!r}.")
        _apply_absolute_transform(item, payload)
    except Exception:
        if item is not None:
            _remove_created_object(item, light)
        else:
            _remove_orphan_datablock(light)
        raise
    transaction.add_rollback(partial(_remove_created_object, item, light))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            f"Created {payload['light_type']!s} light",
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            collection,
            "collection",
            ChangeKind.UPDATED,
            f"Linked light {item.name}",
        )
    )


def _add_camera(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    name = str(payload["name"])
    camera = bpy.data.cameras.new(name)
    item: Any | None = None
    try:
        camera.type = "PERSP"
        camera.lens = float(payload["focal_length"])
        item = bpy.data.objects.new(name, camera)
        collection = _runtime_collection(
            context, payload.get("collection_id"), prepared, results
        )
        collection.objects.link(item)
        if item.name != name or camera.name != name:
            raise ExecutionError(f"Blender could not assign camera name {name!r}.")
        _apply_absolute_transform(item, payload)
    except Exception:
        if item is not None:
            _remove_created_object(item, camera)
        else:
            _remove_orphan_datablock(camera)
        raise
    transaction.add_rollback(partial(_remove_created_object, item, camera))
    if bool(payload["make_active"]):
        previous_camera = context.scene.camera
        transaction.add_rollback(
            partial(_set_scene_camera, context.scene, previous_camera)
        )
        context.scene.camera = item
        transaction.record(
            _datablock_change(
                operation.operation_id,
                context.scene,
                "scene",
                ChangeKind.UPDATED,
                f"Set active camera to {item.name}",
            )
        )
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            "Created perspective camera",
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            collection,
            "collection",
            ChangeKind.UPDATED,
            f"Linked camera {item.name}",
        )
    )


def _rename_objects(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    renames = operation.payload["renames"]
    pairs = tuple(
        (
            _runtime_target(str(rename["target_id"]), prepared, results),
            str(rename["new_name"]),
            str(rename["target_id"]),
        )
        for rename in renames
    )
    old_names = tuple((item, item.name) for item, _, _ in pairs)
    transaction.add_rollback(partial(_rename_exact, old_names))
    _rename_exact(tuple((item, new_name) for item, new_name, _ in pairs))
    for item, _, target_id in pairs:
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Renamed object",
            )
        )


def _move_to_collection(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    destination = _runtime_target(
        str(operation.payload["collection_id"]), prepared, results
    )
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        old_collections = tuple(item.users_collection)
        transaction.add_rollback(
            partial(_restore_collections, item, old_collections)
        )
        if destination not in item.users_collection:
            destination.objects.link(item)
        for collection in tuple(item.users_collection):
            if collection != destination:
                collection.objects.unlink(item)
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Moved to collection {destination.name}",
            )
        )
        for collection in {*old_collections, destination}:
            transaction.record(
                _datablock_change(
                    operation.operation_id,
                    collection,
                    "collection",
                    ChangeKind.UPDATED,
                    f"Updated membership for {item.name}",
                )
            )


def _set_material_properties(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material_any: Any = material
    old_values = (
        tuple(float(value) for value in material_any.diffuse_color),
        bool(material_any.use_nodes),
        float(getattr(material_any, "metallic", 0.0)),
        float(getattr(material_any, "roughness", 0.5)),
        _principled_values(material_any),
    )
    transaction.add_rollback(partial(_restore_material_properties, material_any, old_values))
    _apply_material_properties(material_any, operation.payload)
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material_any.name,
            ChangeKind.UPDATED,
            "Updated material properties",
        )
    )


def _create_shader_node(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    node_tree = material.node_tree
    node = node_tree.nodes.new(str(operation.payload["node_type"]))
    try:
        node.label = str(operation.payload["node_label"])
        node.name = str(operation.payload["node_label"])
        node["ai_assistant_created"] = True
    except Exception:
        node_tree.nodes.remove(node)
        raise
    transaction.add_rollback(partial(_remove_shader_node, node_tree, node))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            node.name,
            ChangeKind.CREATED,
            f"Created shader node {operation.payload['node_type']!s}",
        )
    )


def _set_shader_node_value(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node = _runtime_shader_node(material, str(operation.payload["node_ref"]), results)
    input_name = str(operation.payload["input_name"])
    socket = node.inputs.get(input_name)
    if socket is None:
        raise ExecutionError(f"Shader node {node.name!r} has no input socket {input_name!r}.")
    old_value = _socket_value(socket)
    transaction.add_rollback(partial(_restore_socket_value, socket, old_value))
    _set_socket_value(socket, operation.payload["value"])
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Set shader socket {input_name}",
        )
    )


def _connect_shader_nodes(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    from_node = _runtime_shader_node(material, str(operation.payload["from_node"]), results)
    to_node = _runtime_shader_node(material, str(operation.payload["to_node"]), results)
    from_socket_name = str(operation.payload["from_socket"])
    to_socket_name = str(operation.payload["to_socket"])
    from_socket = from_node.outputs.get(from_socket_name)
    to_socket = to_node.inputs.get(to_socket_name)
    if from_socket is None:
        raise ExecutionError(
            f"Shader node {from_node.name!r} has no output socket {from_socket_name!r}."
        )
    if to_socket is None:
        raise ExecutionError(
            f"Shader node {to_node.name!r} has no input socket {to_socket_name!r}."
        )
    link = material.node_tree.links.new(from_socket, to_socket)
    transaction.add_rollback(partial(_remove_shader_link, material.node_tree, link))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Connected shader sockets {from_socket_name} to {to_socket_name}",
        )
    )


def _remove_shader_node_operation(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node = _runtime_shader_node(material, str(operation.payload["node_ref"]), results)
    if not _is_assistant_created_node(node):
        raise ExecutionError("Only assistant-created shader nodes can be removed.")
    if node.bl_idname == "ShaderNodeOutputMaterial":
        raise ExecutionError("Material Output cannot be removed.")
    snapshot = _snapshot_shader_node(node)
    node_tree = material.node_tree
    node_tree.nodes.remove(node)
    transaction.add_rollback(partial(_restore_shader_node_snapshot, node_tree, snapshot))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Removed shader node {snapshot['name']}",
        )
    )


def _disconnect_shader_link(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    from_node = _runtime_shader_node(material, str(operation.payload["from_node"]), results)
    to_node = _runtime_shader_node(material, str(operation.payload["to_node"]), results)
    from_socket = from_node.outputs.get(str(operation.payload["from_socket"]))
    to_socket = to_node.inputs.get(str(operation.payload["to_socket"]))
    if from_socket is None or to_socket is None:
        raise ExecutionError("Shader link endpoints are unavailable.")
    link = _find_shader_link(material.node_tree, from_socket, to_socket)
    if link is None:
        raise ExecutionError("Requested shader link does not exist.")
    material.node_tree.links.remove(link)
    transaction.add_rollback(
        partial(
            _restore_shader_link,
            material.node_tree,
            from_node,
            from_socket.name,
            to_node,
            to_socket.name,
        )
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Disconnected shader sockets {from_socket.name} to {to_socket.name}",
        )
    )


def _create_shader_color_ramp(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    node_tree = material.node_tree
    node = node_tree.nodes.new("ShaderNodeValToRGB")
    try:
        node.label = str(operation.payload["node_label"])
        node.name = str(operation.payload["node_label"])
        node["ai_assistant_created"] = True
        _apply_color_ramp_stops(node, tuple(operation.payload["stops"]))
    except Exception:
        node_tree.nodes.remove(node)
        raise
    transaction.add_rollback(partial(_remove_shader_node, node_tree, node))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            node.name,
            ChangeKind.CREATED,
            "Created shader color ramp",
        )
    )


def _set_shader_color_ramp(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node = _runtime_shader_node(material, str(operation.payload["node_ref"]), results)
    if node.bl_idname != "ShaderNodeValToRGB":
        raise ExecutionError("SET_SHADER_COLOR_RAMP requires a color ramp node.")
    old_stops = _color_ramp_stops(node)
    transaction.add_rollback(partial(_apply_color_ramp_stops, node, old_stops))
    _apply_color_ramp_stops(node, tuple(operation.payload["stops"]))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Updated color ramp {node.name}",
        )
    )


def _create_shader_mix_chain(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    template = str(operation.payload["template"])
    created = _build_shader_mix_chain(material, operation.payload)
    for node in created:
        transaction.add_rollback(partial(_remove_shader_node, material.node_tree, node))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = created[0]
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            created[0].name,
            ChangeKind.CREATED,
            f"Created shader mix chain {template}",
        )
    )


def _create_shader_graph_template(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    created = _build_shader_graph_template(material, operation.payload)
    for node in created:
        transaction.add_rollback(partial(_remove_shader_node, material.node_tree, node))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = created[0]
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            created[0].name,
            ChangeKind.CREATED,
            f"Created shader graph template {operation.payload['template']}",
        )
    )


def _validate_material_output(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    node_tree = material.node_tree
    output = node_tree.nodes.get("Material Output")
    if output is None:
        if not bool(operation.payload["repair"]):
            raise ExecutionError("Material has no Material Output node.")
        output = node_tree.nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"
        transaction.add_rollback(partial(_remove_shader_node, node_tree, output))
    surface = output.inputs.get("Surface")
    if surface is None:
        raise ExecutionError("Material Output has no Surface socket.")
    if surface.links:
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                str(operation.payload["material_id"]),
                "material",
                material.name,
                ChangeKind.UPDATED,
                "Validated material output",
            )
        )
        return
    if not bool(operation.payload["repair"]):
        raise ExecutionError("Material Output surface is not connected.")
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        principled = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
        principled.name = "Principled BSDF"
        transaction.add_rollback(partial(_remove_shader_node, node_tree, principled))
    shader_output = principled.outputs.get("BSDF")
    if shader_output is None:
        raise ExecutionError("Principled BSDF has no BSDF output.")
    link = node_tree.links.new(shader_output, surface)
    transaction.add_rollback(partial(_remove_shader_link, node_tree, link))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Repaired material output",
        )
    )


def _create_layered_shader_material(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    payload = operation.payload
    material = _new_controlled_principled_material(
        str(payload["name"]),
        _rgb(payload["base_color"]),
        float(payload["metallic"]),
        float(payload["roughness"]),
        1.0,
    )
    try:
        material["ai_assistant_created"] = True
        material["ai_material_family"] = str(payload["base_family"])
        material["ai_layer_stack_label"] = str(payload["layer_stack_label"])
        material["ai_shader_layer_count"] = 0
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    _record_material_result(
        operation,
        material,
        results,
        transaction,
        "Created layered shader material",
    )


def _add_shader_layer(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")

    layer_name = str(operation.payload["layer_name"])
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    old_material_values = _material_state_snapshot(material)
    created = _build_shader_layer_nodes(material, operation.payload, reference)
    try:
        roughness_socket = principled.inputs.get("Roughness")
        if roughness_socket is not None:
            current = float(roughness_socket.default_value)
            next_value = max(
                0.0,
                min(
                    1.0,
                    current
                    + float(operation.payload["roughness_delta"])
                    * float(operation.payload["opacity"]),
                ),
            )
            roughness_socket.default_value = next_value
            material.roughness = next_value
        material["ai_shader_layer_count"] = int(material.get("ai_shader_layer_count", 0)) + 1
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise

    transaction.add_rollback(partial(_restore_material_properties, material, old_material_values))
    for node in created:
        transaction.add_rollback(partial(_remove_shader_node, node_tree, node))
    results[reference] = {
        "material": material,
        "nodes": created,
        "layer_id": reference,
        "layer_name": layer_name,
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_layer",
            layer_name,
            ChangeKind.CREATED,
            f"Created shader layer {layer_name}",
        )
    )


def _set_shader_layer_mask(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    layer = _runtime_shader_layer(str(operation.payload["layer_id"]), results)
    if layer["material"] != material:
        raise ExecutionError("Shader layer does not belong to the referenced material.")
    node_tree = material.node_tree
    mask_node = _build_shader_layer_mask_node(
        material,
        operation.payload["mask_source"],
        operation.payload,
        results,
    )
    try:
        for node in layer["nodes"]:
            node["ai_shader_layer_mask_strength"] = float(operation.payload["strength"])
            node["ai_shader_layer_mask_invert"] = bool(operation.payload["invert"])
        ramp = _first_node_by_bl_idname(layer["nodes"], "ShaderNodeValToRGB")
        if ramp is not None and "Fac" in ramp.inputs:
            output = mask_node.outputs.get("Fac") or mask_node.outputs.get("Color")
            if output is not None:
                node_tree.links.new(output, ramp.inputs["Fac"])
    except Exception:
        _remove_shader_node(node_tree, mask_node)
        raise
    transaction.add_rollback(partial(_remove_shader_node, node_tree, mask_node))
    layer["mask_node"] = mask_node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Updated shader layer mask",
        )
    )


def _reorder_shader_layers(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    snapshots: list[tuple[Any, dict[str, Any]]] = []
    for order, layer_id in enumerate(operation.payload["layer_order"], start=1):
        layer = _runtime_shader_layer(str(layer_id), results)
        if layer["material"] != material:
            raise ExecutionError("Shader layer does not belong to the referenced material.")
        for node in layer["nodes"]:
            snapshots.append((node, dict(node.items())))
            node["ai_shader_layer_order"] = order
    transaction.add_rollback(partial(_restore_node_custom_properties, tuple(snapshots)))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Reordered shader layers",
        )
    )


def _remove_shader_layer(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    layer = _runtime_shader_layer(str(operation.payload["layer_id"]), results)
    if layer["material"] != material:
        raise ExecutionError("Shader layer does not belong to the referenced material.")
    node_tree = material.node_tree
    nodes = tuple(node for node in layer["nodes"] if _is_assistant_created_node(node))
    snapshots = tuple(_snapshot_shader_node(node) for node in nodes)
    for node in nodes:
        node_tree.nodes.remove(node)
    transaction.add_rollback(
        partial(_restore_shader_nodes_from_snapshots, node_tree, snapshots)
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Removed shader layer",
        )
    )


def _create_procedural_pattern_node_set(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    created = _build_procedural_node_set(material, operation)
    for node in created:
        transaction.add_rollback(partial(_remove_shader_node, material.node_tree, node))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = created[0]
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            created[0].name,
            ChangeKind.CREATED,
            f"Created {operation.type.value} node set",
        )
    )


def _extract_material_palette_from_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    colors = _palette_colors_from_source(
        str(payload["source"]),
        int(payload["max_colors"]),
    )
    text = bpy.data.texts.new(str(payload["palette_name"]))
    text.write(
        "\n".join(
            [
                f"source={payload['source']}",
                f"colors={colors}",
                f"roughness_guess={payload['include_roughness_guess']}",
                f"metallic_guess={payload['include_metallic_guess']}",
                f"pattern_hints={payload['include_pattern_hints']}",
            ]
        )
    )
    text["ai_material_palette"] = True
    transaction.add_rollback(partial(_remove_created_text, text))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = {
        "colors": colors,
        "source": str(payload["source"]),
        "name": str(payload["palette_name"]),
        "text": text,
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "material_palette",
            text.name,
            ChangeKind.CREATED,
            "Extracted material palette metadata",
        )
    )


def _create_material_from_reference_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    payload = operation.payload
    palette = _runtime_material_palette(str(payload["palette_id"]), results)
    colors = cast(tuple[tuple[float, float, float], ...], palette["colors"])
    color = colors[0] if colors else _color_from_text(str(payload["source"]))
    material = _new_controlled_principled_material(
        str(payload["material_name"]),
        color,
        _family_default_metallic(str(payload["template_family"])),
        _family_default_roughness(str(payload["template_family"])),
        1.0,
    )
    try:
        material["ai_assistant_created"] = True
        material["ai_reference_source"] = str(payload["source"])
        material["ai_reference_template_family"] = str(payload["template_family"])
        if bool(payload["use_generated_texture"]):
            _build_reference_texture_hint_nodes(material, str(payload["material_name"]), color)
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    _record_material_result(
        operation,
        material,
        results,
        transaction,
        "Created material from reference image",
    )


def _match_material_to_reference(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    old_values = _material_state_snapshot(material)
    created_nodes: list[Any] = []
    try:
        strength = float(operation.payload["strength"])
        target_color = _color_from_text(str(operation.payload["reference_source"]))
        payload: dict[str, Any] = {
            "base_color": None,
            "metallic": None,
            "roughness": None,
            "alpha": None,
        }
        if bool(operation.payload["match_color"]):
            current = _rgb(material.diffuse_color[:3])
            payload["base_color"] = _mix_rgb(current, target_color, strength)
        if bool(operation.payload["match_roughness"]):
            payload["roughness"] = max(
                0.0,
                min(1.0, float(material.roughness) * (1.0 - strength) + 0.45 * strength),
            )
        _apply_material_properties(material, payload)
        if bool(operation.payload["match_pattern"]):
            created_nodes.extend(
                _build_reference_texture_hint_nodes(
                    material,
                    f"AI Reference Match {operation.operation_id}",
                    target_color,
                )
            )
    except Exception:
        for node in reversed(created_nodes):
            _remove_shader_node(material.node_tree, node)
        raise
    transaction.add_rollback(partial(_restore_material_properties, material, old_values))
    for node in created_nodes:
        transaction.add_rollback(partial(_remove_shader_node, material.node_tree, node))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Matched material to reference metadata",
        )
    )


def _create_lookdev_preview(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    _runtime_target(str(operation.payload["target_id"]), prepared, results)
    color = tuple(float(value) for value in material.diffuse_color)
    _create_shading_preview_image(
        operation,
        results,
        transaction,
        str(operation.payload["preview_name"]),
        _rgba(color[:4]),
        "lookdev",
    )


def _create_specialized_material(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    payload = operation.payload
    material = _new_controlled_principled_material(
        str(payload["name"]),
        _rgb(payload["base_color"]),
        _specialized_metallic(operation.type, payload),
        float(payload["roughness"]),
        float(payload["alpha"]),
    )
    try:
        _apply_specialized_material_template(material, operation.type, payload)
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    _record_material_result(
        operation,
        material,
        results,
        transaction,
        f"Created {operation.type.value} material",
    )


def _remove_unused_assistant_shader_nodes(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material.use_nodes = True
    node_tree = material.node_tree
    removable = tuple(
        node
        for node in node_tree.nodes
        if _is_assistant_created_node(node)
        and node.bl_idname != "ShaderNodeOutputMaterial"
        and not _node_has_links(node)
    )
    snapshots = tuple(_snapshot_shader_node(node) for node in removable)
    for node in removable:
        node_tree.nodes.remove(node)
    transaction.add_rollback(
        partial(_restore_shader_nodes_from_snapshots, node_tree, snapshots)
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Removed {len(removable)} unused assistant shader nodes",
        )
    )


def _consolidate_duplicate_assistant_materials(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    canonical = _runtime_target(
        str(operation.payload["canonical_material_id"]),
        prepared,
        results,
    )
    duplicates = {
        _runtime_target(str(material_id), prepared, results)
        for material_id in operation.payload["material_ids"]
    }
    if bool(operation.payload["assistant_owned_only"]):
        for material in duplicates:
            if material == canonical:
                continue
            if not _is_assistant_owned_material(material):
                raise ExecutionError(
                    "Only assistant-created duplicate materials can be consolidated."
                )
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        data = item.data
        old_materials = tuple(data.materials)
        old_indices = tuple(int(poly.material_index) for poly in getattr(data, "polygons", ()))
        transaction.add_rollback(partial(_restore_materials, data, old_materials, old_indices))
        changed = False
        for index, slot_material in enumerate(tuple(data.materials)):
            if slot_material in duplicates and slot_material != canonical:
                data.materials[index] = canonical
                changed = True
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Consolidated duplicate material slots" if changed else "Checked material slots",
            )
        )


def _normalize_shader_node_layout(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node_tree = material.node_tree
    nodes = tuple(node for node in node_tree.nodes if _is_assistant_created_node(node))
    old_locations = tuple((node, tuple(float(value) for value in node.location)) for node in nodes)
    spacing_x = 260.0 if operation.payload["layout_style"] == "readable" else 180.0
    for index, node in enumerate(nodes):
        node.location = (spacing_x * index, -180.0 * (index % 3))
    transaction.add_rollback(partial(_restore_node_locations, old_locations))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            "Normalized shader node layout",
        )
    )


def _validate_shader_compatibility_operation(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    incompatible = tuple(
        link
        for link in material.node_tree.links
        if _link_should_be_checked(link, bool(operation.payload["assistant_owned_only"]))
        and not _shader_link_is_compatible(link)
    )
    if incompatible and operation.payload["repair_mode"] != "single_safe_fix":
        raise ExecutionError("Material contains incompatible shader links.")
    for link in incompatible:
        from_node = link.from_node
        to_node = link.to_node
        from_socket_name = link.from_socket.name
        to_socket_name = link.to_socket.name
        material.node_tree.links.remove(link)
        transaction.add_rollback(
            partial(
                _restore_shader_link,
                material.node_tree,
                from_node,
                from_socket_name,
                to_node,
                to_socket_name,
            )
        )
    detail = (
        f"Removed {len(incompatible)} incompatible shader links"
        if incompatible
        else "Validated shader compatibility"
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            detail,
        )
    )


def _repair_broken_shader_links(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    repair_operation = Operation(
        operation.operation_id,
        OperationType.VALIDATE_MATERIAL_OUTPUT,
        {
            "material_id": operation.payload["material_id"],
            "repair": operation.payload["repair_mode"] == "single_safe_fix",
        },
    )
    _validate_material_output(repair_operation, prepared, results, transaction)


def _create_material_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    source = _runtime_target(str(operation.payload["source_material_id"]), prepared, results)
    variant = source.copy()
    try:
        variant.name = str(operation.payload["variant_name"])
        if variant.name != str(operation.payload["variant_name"]):
            raise ExecutionError(
                f"Blender could not assign material name {operation.payload['variant_name']!r}."
            )
        variant["ai_assistant_created"] = True
        variant["ai_material_variant"] = True
        variant["ai_variant_label"] = str(operation.payload["variant_label"])
        variant["ai_variant_source_material"] = source.name
        variant["ai_variant_copy_textures"] = bool(operation.payload["copy_textures"])
    except Exception:
        _remove_created_material(variant)
        raise
    transaction.add_rollback(partial(_remove_created_material, variant))
    _record_material_result(
        operation,
        variant,
        results,
        transaction,
        "Created material variant",
    )


def _tag_material_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    variant = _runtime_target(str(operation.payload["variant_id"]), prepared, results)
    snapshot = _custom_property_snapshot(
        variant,
        ("ai_variant_label", "ai_variant_prompt_summary"),
    )
    variant["ai_variant_label"] = str(operation.payload["label"])
    variant["ai_variant_prompt_summary"] = str(operation.payload["prompt_summary"])
    transaction.add_rollback(partial(_restore_custom_properties, variant, snapshot))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["variant_id"]),
            "material",
            variant.name,
            ChangeKind.UPDATED,
            "Tagged material variant",
        )
    )


def _create_shader_comparison_preview(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    _runtime_target(str(operation.payload["target_id"]), prepared, results)
    source = _runtime_target(str(operation.payload["source_material_id"]), prepared, results)
    variant = _runtime_target(str(operation.payload["variant_id"]), prepared, results)
    _create_split_preview_image(
        operation,
        results,
        transaction,
        str(operation.payload["preview_name"]),
        tuple(float(value) for value in source.diffuse_color),
        tuple(float(value) for value in variant.diffuse_color),
        "shader_comparison",
    )


def _accept_material_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    variant = _runtime_target(str(operation.payload["variant_id"]), prepared, results)
    replacement = _runtime_target(
        str(operation.payload["replace_material_id"]),
        prepared,
        results,
    )
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        data = item.data
        old_materials = tuple(data.materials)
        old_indices = tuple(int(poly.material_index) for poly in getattr(data, "polygons", ()))
        transaction.add_rollback(partial(_restore_materials, data, old_materials, old_indices))
        changed = False
        for index, slot_material in enumerate(tuple(data.materials)):
            if slot_material == replacement:
                data.materials[index] = variant
                changed = True
        if not changed:
            data.materials.append(variant)
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Accepted material variant",
            )
        )


def _reject_material_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    variant = _runtime_target(str(operation.payload["variant_id"]), prepared, results)
    snapshot = _custom_property_snapshot(variant, ("ai_variant_rejected",))
    variant["ai_variant_rejected"] = True
    transaction.add_rollback(partial(_restore_custom_properties, variant, snapshot))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["variant_id"]),
            "material",
            variant.name,
            ChangeKind.UPDATED,
            "Rejected material variant",
        )
    )


def _load_image_texture(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    source = str(operation.payload["source"])
    max_bytes = int(operation.payload["max_size_mb"]) * 1024 * 1024
    filepath = _resolve_image_texture_source(source, max_bytes)
    temporary = filepath.name.startswith("blender_ai_texture_")
    image = None
    try:
        image = cast(Any, bpy.data).images.load(str(filepath), check_existing=False)
        image.name = str(operation.payload["image_name"])
        if image.name != str(operation.payload["image_name"]):
            raise ExecutionError(
                f"Blender could not assign image name {operation.payload['image_name']!r}."
            )
        image.colorspace_settings.name = str(operation.payload["color_space"])
        if temporary:
            image.pack()
    except Exception:
        if image is not None:
            _remove_created_image(image)
        raise
    finally:
        if temporary:
            filepath.unlink(missing_ok=True)
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            "Loaded image texture",
        )
    )


def _create_image_texture_node(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    image = _runtime_image(str(operation.payload["image_id"]), results)
    node = _attach_image_to_material(
        material,
        image,
        str(operation.payload["node_label"]),
        str(operation.payload["connect_to"]),
        projection=str(operation.payload["projection"]),
        extension=str(operation.payload["extension"]),
        uv_map_name=None,
        transaction=transaction,
    )
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            node.name,
            ChangeKind.CREATED,
            f"Created image texture node for {image.name}",
        )
    )


def _set_texture_mapping(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node = _runtime_shader_node(material, str(operation.payload["texture_node_ref"]), results)
    mapping = _controlled_mapping_node(material, node)
    old_values = (
        _socket_value(mapping.inputs["Location"]),
        _socket_value(mapping.inputs["Rotation"]),
        _socket_value(mapping.inputs["Scale"]),
        getattr(node, "projection", None),
        getattr(node, "extension", None),
    )
    transaction.add_rollback(partial(_restore_texture_mapping, mapping, node, old_values))
    mapping.inputs["Location"].default_value = tuple(
        float(value) for value in operation.payload["translation"]
    )
    mapping.inputs["Rotation"].default_value = tuple(
        float(value) for value in operation.payload["rotation"]
    )
    mapping.inputs["Scale"].default_value = tuple(
        float(value) for value in operation.payload["scale"]
    )
    node.projection = str(operation.payload["projection"])
    node.extension = str(operation.payload["extension"])
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["material_id"]),
            "material",
            material.name,
            ChangeKind.UPDATED,
            f"Updated texture mapping for {node.name}",
        )
    )


def _assign_uv_map(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_uv_map(target, str(operation.payload["uv_map_name"]))
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    node = _runtime_shader_node(material, str(operation.payload["texture_node_ref"]), results)
    uv_node = _controlled_uv_map_node(material, node, transaction)
    old_uv_map = str(uv_node.uv_map)
    transaction.add_rollback(partial(_set_uv_node_map, uv_node, old_uv_map))
    uv_node.uv_map = str(operation.payload["uv_map_name"])
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["target_id"]),
            "object",
            target.name,
            ChangeKind.UPDATED,
            f"Assigned UV map {uv_node.uv_map} to texture node {node.name}",
        )
    )


def _create_uv_map(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    uv_name = str(operation.payload["uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        if item.data.uv_layers.get(uv_name) is not None:
            raise ExecutionError(f"Object {item.name!r} already has UV map {uv_name!r}.")
        uv_layer = item.data.uv_layers.new(name=uv_name)
        if bool(operation.payload["set_active"]):
            item.data.uv_layers.active = uv_layer
        if bool(operation.payload["set_render"]):
            uv_layer.active_render = True
        transaction.add_rollback(partial(_remove_uv_layer, item, uv_name))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Created UV map {uv_name}",
            )
        )


def _unwrap_uv_map(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    uv_name = str(operation.payload["uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_layer = item.data.uv_layers.get(uv_name)
        created = False
        if uv_layer is None:
            if not bool(operation.payload["create_if_missing"]):
                raise ExecutionError(f"Object {item.name!r} has no UV map {uv_name!r}.")
            uv_layer = item.data.uv_layers.new(name=uv_name)
            created = True
        elif not bool(operation.payload["overwrite_existing"]):
            raise ExecutionError(f"UNWRAP_UV_MAP needs overwrite_existing for {uv_name!r}.")
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(
            partial(_restore_uv_layer, item, uv_name, old_uvs, created)
        )
        _write_projected_uvs(item, uv_layer, float(operation.payload["margin"]))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Generated {operation.payload['method']!s} UVs for {uv_name}",
            )
        )


def _pack_uv_islands(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    uv_name = str(operation.payload["uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_layer = _require_uv_map(item, uv_name)
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
        _normalize_uvs(uv_layer, float(operation.payload["margin"]))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Packed UV map {uv_name}",
            )
        )


def _create_uv_report(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    target_ids = operation.target_ids or (str(operation.payload["target_id"]),)
    report_lines = [
        f"operation: {operation.type.value}",
        f"operation_id: {operation.operation_id}",
    ]
    for target_id in target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_layer = _require_uv_map(item, str(operation.payload["uv_map_name"]))
        report_lines.extend(_uv_report_lines(item, uv_layer, operation.payload))
    text_name = str(
        operation.payload.get("report_name")
        or f"AI UV Report {operation.operation_id}"
    )
    text = cast(Any, bpy.data).texts.new(text_name)
    text.write("\n".join(report_lines))
    transaction.add_rollback(partial(_remove_created_text, text))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = {
        "kind": "uv_report",
        "text": text,
        "target_ids": target_ids,
        "uv_map_name": str(operation.payload["uv_map_name"]),
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "text",
            text.name,
            ChangeKind.CREATED,
            "Created UV report",
        )
    )


def _create_uv_preview(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_uv_map(target, str(operation.payload["uv_map_name"]))
    image = _new_filled_image(
        str(operation.payload["preview_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        (0.02, 0.025, 0.03, 1.0),
        "sRGB",
        pack=False,
    )
    try:
        _write_uv_preview_pattern(
            image,
            str(operation.payload["uv_map_name"]),
            (0.18, 0.42, 0.95, 1.0),
            (0.95, 0.32, 0.2, 1.0),
        )
        image["ai_preview_kind"] = operation.type.value
        if bool(operation.payload["pack"]):
            image.pack()
    except Exception:
        _remove_created_image(image)
        raise
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            f"Created {operation.type.value} preview image",
        )
    )


def _mark_uv_seams_by_angle(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    seam_sets: dict[str, tuple[int, ...]] = {}
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        old_values = _edge_seam_values(item)
        edge_indices = _angle_based_edge_indices(
            item,
            float(operation.payload["angle_threshold_degrees"]),
        )
        _set_edge_seams(item, edge_indices, True)
        if bool(operation.payload["mark_sharp_edges"]):
            _set_edge_sharpness(item, edge_indices, True)
        transaction.add_rollback(partial(_restore_edge_seams, item, old_values))
        seam_sets[target_id] = edge_indices
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Marked {len(edge_indices)} angle UV seams",
            )
        )
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = {
        "kind": "uv_seam_set",
        "name": str(operation.payload["seam_set_name"]),
        "targets": seam_sets,
    }


def _mark_uv_seams_by_material(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    seam_sets: dict[str, tuple[int, ...]] = {}
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        old_values = _edge_seam_values(item)
        edge_indices = _material_boundary_edge_indices(item, material)
        _set_edge_seams(item, edge_indices, True)
        transaction.add_rollback(partial(_restore_edge_seams, item, old_values))
        seam_sets[target_id] = edge_indices
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Marked {len(edge_indices)} material UV seams",
            )
        )
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = {
        "kind": "uv_seam_set",
        "name": str(operation.payload["seam_set_name"]),
        "targets": seam_sets,
    }


def _mark_uv_seams_by_edge_set(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    old_values = _edge_seam_values(item)
    edge_indices = tuple(index for index, _edge in enumerate(item.data.edges) if index % 2 == 0)
    _set_edge_seams(item, edge_indices, True)
    transaction.add_rollback(partial(_restore_edge_seams, item, old_values))
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = {
        "kind": "uv_seam_set",
        "name": str(operation.payload["seam_set_name"]),
        "edge_set_name": str(operation.payload["edge_set_name"]),
        "targets": {target_id: edge_indices},
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            target_id,
            "object",
            item.name,
            ChangeKind.UPDATED,
            f"Marked {len(edge_indices)} edge-set UV seams",
        )
    )


def _clear_uv_seams(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        old_values = _edge_seam_values(item)
        _set_edge_seams(item, tuple(range(len(item.data.edges))), False)
        transaction.add_rollback(partial(_restore_edge_seams, item, old_values))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Cleared UV seams for {operation.payload['seam_set_name']!s}",
            )
        )


def _create_uv_islands_from_seams(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    _runtime_uv_seam_set(str(operation.payload["seam_set_id"]), results)
    island_sets: dict[str, tuple[int, ...]] = {}
    uv_name = str(operation.payload["uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        uv_layer, created = _ensure_uv_layer_for_edit(
            item,
            target_id,
            uv_name,
            create_if_missing=bool(operation.payload["create_if_missing"]),
            overwrite_existing=bool(operation.payload["overwrite_existing"]),
        )
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, created))
        _write_projected_uvs(item, uv_layer, 0.02)
        island_sets[target_id] = tuple(range(len(uv_layer.data)))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Created UV islands in {uv_name}",
            )
        )
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = {
        "kind": "uv_island_set",
        "uv_map_name": uv_name,
        "targets": island_sets,
    }


def _project_uv_map(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    if operation.payload.get("camera_id") is not None:
        _runtime_target(str(operation.payload["camera_id"]), prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        uv_layer, created = _ensure_uv_layer_for_edit(
            item,
            target_id,
            uv_name,
            create_if_missing=bool(operation.payload["create_if_missing"]),
            overwrite_existing=bool(operation.payload["overwrite_existing"]),
        )
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, created))
        _write_projection_uvs(item, uv_layer, operation)
        if bool(operation.payload["scale_to_bounds"]):
            _normalize_uvs(uv_layer, float(operation.payload["margin"]))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Generated {operation.type.value} coordinates for {uv_name}",
            )
        )


def _select_uv_islands_by_material(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    uv_name = str(operation.payload["uv_map_name"])
    uv_layer = _require_uv_map(item, uv_name)
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    material_index = _material_slot_index(item, material)
    loop_indices = tuple(
        int(loop_index)
        for polygon in item.data.polygons
        if int(polygon.material_index) == material_index
        for loop_index in polygon.loop_indices
        if int(loop_index) < len(uv_layer.data)
    )
    if not loop_indices:
        loop_indices = tuple(range(len(uv_layer.data)))
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = {
        "kind": "uv_island_set",
        "name": str(operation.payload["island_set_name"]),
        "target_id": target_id,
        "uv_map_name": uv_name,
        "loop_indices": loop_indices,
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            target_id,
            "object",
            item.name,
            ChangeKind.UPDATED,
            f"Selected {len(loop_indices)} UV loops by material",
        )
    )


def _transform_uv_islands(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _transform_uv_loops(
        uv_layer,
        loop_indices,
        _float2(operation.payload["translation"]),
        float(operation.payload["rotation_degrees"]),
        _float2(operation.payload["scale"]),
        _float2(operation.payload["pivot"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Transformed UV islands in {uv_name}",
        )
    )


def _align_uv_islands(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _align_uv_loops(
        uv_layer,
        loop_indices,
        str(operation.payload["mode"]),
        _float2(operation.payload["bounds_min"]),
        _float2(operation.payload["bounds_max"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Aligned UV islands in {uv_name}",
        )
    )


def _distribute_uv_islands(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _distribute_uv_loops(
        uv_layer,
        loop_indices,
        str(operation.payload["axis"]),
        float(operation.payload["spacing"]),
        _float2(operation.payload["bounds_min"]),
        _float2(operation.payload["bounds_max"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Distributed UV islands in {uv_name}",
        )
    )


def _scale_uv_islands_to_bounds(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _scale_uv_loops_to_bounds(
        uv_layer,
        loop_indices,
        _float2(operation.payload["bounds_min"]),
        _float2(operation.payload["bounds_max"]),
        preserve_aspect=bool(operation.payload["preserve_aspect"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Scaled UV islands in {uv_name} to bounds",
        )
    )


def _set_uv_island_pins(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
    *,
    pinned: bool,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    old_pins = _uv_pin_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_pins, uv_layer, old_pins))
    _set_uv_pins(uv_layer, loop_indices, pinned)
    detail = "Pinned" if pinned else "Unpinned"
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"{detail} UV islands in {operation.payload['uv_map_name']!s}",
        )
    )


def _set_uv_texel_density(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    scale_factor = _bounded_uv_scale_factor(
        float(operation.payload["pixels_per_unit"]) * float(operation.payload["unit_scale"])
    )
    _scale_uv_maps_for_targets(operation, prepared, results, transaction, scale_factor)


def _normalize_uv_texel_density(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    scale_factor = _bounded_uv_scale_factor(float(operation.payload["target_pixels_per_unit"]))
    _scale_uv_maps_for_targets(operation, prepared, results, transaction, scale_factor)


def _pack_uv_islands_advanced(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target_tile = _int2(operation.payload["target_tile"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_name = str(operation.payload["uv_map_name"])
        uv_layer = _require_uv_map(item, uv_name)
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
        _normalize_uvs(uv_layer, float(operation.payload["margin"]))
        _offset_uvs_to_tile(uv_layer, tuple(range(len(uv_layer.data))), target_tile)
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Advanced packed UV map {uv_name}",
            )
        )


def _move_uv_islands_to_tile(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _offset_uvs_to_tile(
        uv_layer,
        loop_indices,
        (int(operation.payload["tile_u"]), int(operation.payload["tile_v"])),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Moved UV islands in {uv_name} to tile",
        )
    )


def _create_udim_tile_layout(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    tile_count_u = int(operation.payload["tile_count_u"])
    tile_count_v = int(operation.payload["tile_count_v"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        uv_layer, created = _ensure_uv_layer_for_edit(
            item,
            target_id,
            str(operation.payload["uv_map_name"]),
            create_if_missing=True,
            overwrite_existing=True,
        )
        old_uvs = _uv_layer_values(uv_layer)
        uv_name = str(operation.payload["uv_map_name"])
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, created))
        _write_projected_uvs(item, uv_layer, float(operation.payload["margin"]))
        _spread_uvs_across_tiles(uv_layer, tile_count_u, tile_count_v)
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Created {tile_count_u}x{tile_count_v} UDIM UV layout",
            )
        )


def _relax_uv_islands(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _relax_uv_loops(
        uv_layer,
        loop_indices,
        int(operation.payload["iterations"]),
        float(operation.payload["strength"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Relaxed UV islands in {uv_name}",
        )
    )


def _minimize_uv_stretch(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_name = str(operation.payload["uv_map_name"])
        uv_layer = _require_uv_map(item, uv_name)
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
        _relax_uv_loops(
            uv_layer,
            tuple(range(len(uv_layer.data))),
            int(operation.payload["iterations"]),
            float(operation.payload["strength"]),
        )
        _normalize_uvs(uv_layer, 0.01)
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Minimized UV stretch in {uv_name}",
            )
        )


def _repair_uv_bounds(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target_tile = _int2(operation.payload["target_tile"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_name = str(operation.payload["uv_map_name"])
        uv_layer = _require_uv_map(item, uv_name)
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
        if bool(operation.payload["scale_to_fit"]):
            _normalize_uvs(uv_layer, 0.0)
        _offset_uvs_to_tile(uv_layer, tuple(range(len(uv_layer.data))), target_tile)
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Repaired UV bounds in {uv_name}",
            )
        )


def _merge_duplicate_uv_maps(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    source_names = tuple(str(name) for name in operation.payload["source_uv_map_names"])
    destination_name = str(operation.payload["destination_uv_map_name"])
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        snapshots = _uv_layer_snapshots(item, (*source_names, destination_name))
        transaction.add_rollback(partial(_restore_uv_layer_snapshots, item, snapshots))
        destination = _require_uv_map(item, destination_name)
        source_layers = tuple(_require_uv_map(item, name) for name in source_names)
        _average_uv_layers(destination, source_layers)
        if bool(operation.payload["update_texture_nodes"]):
            _retarget_uv_nodes(item, source_names, destination_name)
        if bool(operation.payload["remove_sources"]):
            for name in source_names:
                if bool(operation.payload["assistant_owned_only"]) and not name.startswith("AI"):
                    continue
                _remove_uv_layer(item, name)
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Merged {len(source_names)} UV maps into {destination_name}",
            )
        )


def _remove_unused_assistant_uv_maps(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        removable = tuple(
            layer.name
            for layer in item.data.uv_layers
            if str(layer.name).startswith("AI")
            and layer != item.data.uv_layers.active
            and not bool(getattr(layer, "active_render", False))
        )
        if bool(operation.payload["dry_run"]):
            detail = f"Would remove {len(removable)} assistant UV maps"
        else:
            snapshots = _uv_layer_snapshots(item, removable)
            transaction.add_rollback(partial(_restore_uv_layer_snapshots, item, snapshots))
            for name in removable:
                _remove_uv_layer(item, str(name))
            detail = f"Removed {len(removable)} assistant UV maps"
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                detail,
            )
        )


def _fit_uv_islands_to_image_region(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    _runtime_image(str(operation.payload["image_id"]), results)
    item, uv_layer, loop_indices = _runtime_uv_island_edit(operation, prepared, results)
    uv_name = str(operation.payload["uv_map_name"])
    old_uvs = _uv_layer_values(uv_layer)
    transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
    _scale_uv_loops_to_bounds(
        uv_layer,
        loop_indices,
        _float2(operation.payload["region_min_uv"]),
        _float2(operation.payload["region_max_uv"]),
        preserve_aspect=bool(operation.payload["preserve_aspect"]),
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Fit UV islands in {uv_name} to image region",
        )
    )


def _create_texture_atlas_layout(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    image = _runtime_image(str(operation.payload["image_id"]), results)
    targets = tuple(
        _runtime_target(target_id, prepared, results) for target_id in operation.target_ids
    )
    for target_id, item in zip(operation.target_ids, targets, strict=True):
        _require_mesh_object(item, target_id)
        _require_uv_map(item, str(operation.payload["uv_map_name"]))
    atlas = {
        "kind": "uv_atlas",
        "name": str(operation.payload["atlas_name"]),
        "image": image,
        "resolution": _int2(operation.payload["atlas_resolution"]),
        "uv_map_name": str(operation.payload["uv_map_name"]),
        "target_names": tuple(str(item.name) for item in targets),
    }
    results[f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"] = atlas
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}",
            "uv_atlas",
            str(operation.payload["atlas_name"]),
            ChangeKind.CREATED,
            f"Created atlas layout for {len(targets)} target(s)",
        )
    )


def _assign_atlas_texture_regions(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _runtime_uv_atlas(str(operation.payload["atlas_id"]), results)
    material_refs = [str(operation.payload["material_id"])]
    material_refs.extend(
        str(assignment["material_id"])
        for assignment in operation.payload["assignments"]
    )
    materials = tuple(
        _runtime_target(material_id, prepared, results) for material_id in material_refs
    )
    keys = tuple(
        f"ai_uv_atlas_region_{index}"
        for index in range(len(operation.payload["assignments"]))
    )
    snapshots = tuple(_custom_property_snapshot(material, keys) for material in materials)
    for material, snapshot in zip(materials, snapshots, strict=True):
        transaction.add_rollback(partial(_restore_custom_properties, material, snapshot))
    for index, assignment in enumerate(operation.payload["assignments"]):
        material = _runtime_target(str(assignment["material_id"]), prepared, results)
        material[keys[index]] = {
            "region_name": str(assignment["region_name"]),
            "bounds_min": _float2(assignment["bounds_min"]),
            "bounds_max": _float2(assignment["bounds_max"]),
        }
    transaction.record(
        _datablock_change(
            operation.operation_id,
            target,
            "object",
            ChangeKind.UPDATED,
            f"Assigned {len(operation.payload['assignments'])} atlas texture regions",
        )
    )


def _bake_uv_layout_guide_image(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        _require_uv_map(item, str(operation.payload["uv_map_name"]))
    image = _new_filled_image(
        str(operation.payload["image_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        _float4(operation.payload["background_color"]),
        "sRGB",
        pack=False,
    )
    try:
        _write_uv_preview_pattern(
            image,
            str(operation.payload["uv_map_name"]),
            _float4(operation.payload["line_color"]),
            _float4(operation.payload["background_color"]),
        )
        image["ai_preview_kind"] = "uv_layout_guide"
        if bool(operation.payload["pack"]):
            image.pack()
    except Exception:
        _remove_created_image(image)
        raise
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            "Baked UV layout guide image",
        )
    )


def _create_uv_grid_test_material(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    color_a = _float4(operation.payload["color_a"])
    material = _new_controlled_principled_material(
        str(operation.payload["name"]),
        (color_a[0], color_a[1], color_a[2]),
        0.0,
        0.45,
        color_a[3],
    )
    try:
        material["ai_uv_grid_scale"] = float(operation.payload["grid_scale"])
        material["ai_uv_grid_color_b"] = _float4(operation.payload["color_b"])
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    _record_material_result(
        operation,
        material,
        results,
        transaction,
        "Created UV grid test material",
    )


def _create_uv_map_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    source_name = str(operation.payload["source_uv_map_name"])
    variant_name = str(operation.payload["variant_uv_map_name"])
    source = _require_uv_map(item, source_name)
    if item.data.uv_layers.get(variant_name) is not None:
        raise ExecutionError(f"Object {item.name!r} already has UV map {variant_name!r}.")
    variant = item.data.uv_layers.new(name=variant_name)
    for loop, source_loop in zip(variant.data, source.data, strict=True):
        loop.uv = tuple(source_loop.uv)
        if bool(operation.payload["copy_pins"]) and hasattr(loop, "pin_uv"):
            loop.pin_uv = bool(getattr(source_loop, "pin_uv", False))
    transaction.add_rollback(partial(_remove_uv_layer, item, variant_name))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = {
        "kind": "uv_variant",
        "target_id": target_id,
        "target": item,
        "source_uv_map_name": source_name,
        "variant_uv_map_name": variant_name,
        "label": str(operation.payload["variant_label"]),
    }
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            f"Created UV map variant {variant_name}",
        )
    )


def _tag_uv_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    variant = _runtime_uv_variant(str(operation.payload["variant_id"]), results)
    if variant["target"] != target:
        raise ExecutionError("UV variant belongs to a different target.")
    keys = ("ai_uv_variant_label", "ai_uv_variant_prompt_summary")
    snapshot = _custom_property_snapshot(target, keys)
    transaction.add_rollback(partial(_restore_custom_properties, target, snapshot))
    target["ai_uv_variant_label"] = str(operation.payload["label"])
    target["ai_uv_variant_prompt_summary"] = str(operation.payload["prompt_summary"])
    transaction.record(
        _datablock_change(
            operation.operation_id,
            target,
            "object",
            ChangeKind.UPDATED,
            f"Tagged UV variant {variant['variant_uv_map_name']}",
        )
    )


def _create_uv_comparison_preview(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_uv_map(target, str(operation.payload["source_uv_map_name"]))
    variant = _runtime_uv_variant(str(operation.payload["variant_id"]), results)
    if variant["target"] != target:
        raise ExecutionError("UV variant belongs to a different target.")
    _create_split_preview_image(
        operation,
        results,
        transaction,
        str(operation.payload["preview_name"]),
        (0.12, 0.35, 0.85, 1.0),
        (0.9, 0.25, 0.18, 1.0),
        "uv_variant",
    )


def _accept_uv_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    variant = _runtime_uv_variant(str(operation.payload["variant_id"]), results)
    if variant["target"] != target:
        raise ExecutionError("UV variant belongs to a different target.")
    variant_layer = _require_uv_map(target, str(variant["variant_uv_map_name"]))
    replace_name = str(operation.payload["replace_uv_map_name"])
    replace_layer = target.data.uv_layers.get(replace_name)
    created = replace_layer is None
    if replace_layer is None:
        replace_layer = target.data.uv_layers.new(name=replace_name)
    old_uvs = _uv_layer_values(replace_layer)
    old_active_name = _active_uv_layer_name(target)
    old_render_name = _render_uv_layer_name(target)
    transaction.add_rollback(
        partial(
            _restore_accepted_uv_variant,
            target,
            replace_name,
            old_uvs,
            created,
            old_active_name,
            old_render_name,
        )
    )
    for loop, variant_loop in zip(replace_layer.data, variant_layer.data, strict=True):
        loop.uv = tuple(variant_loop.uv)
    if bool(operation.payload["make_active"]):
        target.data.uv_layers.active = replace_layer
    if bool(operation.payload["make_render_active"]):
        replace_layer.active_render = True
    transaction.record(
        _datablock_change(
            operation.operation_id,
            target,
            "object",
            ChangeKind.UPDATED,
            f"Accepted UV variant into {replace_name}",
        )
    )


def _reject_uv_variant(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    variant = _runtime_uv_variant(str(operation.payload["variant_id"]), results)
    if variant["target"] != target:
        raise ExecutionError("UV variant belongs to a different target.")
    variant_name = str(variant["variant_uv_map_name"])
    if bool(operation.payload["remove_variant"]):
        snapshots = _uv_layer_snapshots(target, (variant_name,))
        transaction.add_rollback(partial(_restore_uv_layer_snapshots, target, snapshots))
        _remove_uv_layer(target, variant_name)
    transaction.record(
        _datablock_change(
            operation.operation_id,
            target,
            "object",
            ChangeKind.UPDATED,
            f"Rejected UV variant {variant_name}",
        )
    )


def _import_pbr_texture_set(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    prefix = str(operation.payload["name_prefix"])
    texture_set: dict[str, Any] = {}
    created_images: list[Any] = []
    temporary_paths: list[Path] = []
    try:
        for texture in operation.payload["textures"]:
            role = str(texture["role"])
            source = str(texture["source"])
            max_bytes = int(texture["max_size_mb"]) * 1024 * 1024
            filepath = _resolve_image_texture_source(source, max_bytes)
            if filepath.name.startswith("blender_ai_texture_"):
                temporary_paths.append(filepath)
            image = cast(Any, bpy.data).images.load(str(filepath), check_existing=False)
            image.name = f"{prefix}_{role}"
            image.colorspace_settings.name = str(texture["color_space"])
            if filepath in temporary_paths:
                image.pack()
            texture_set[role] = image
            created_images.append(image)
    except Exception:
        for image in created_images:
            _remove_created_image(image)
        raise
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)
    for image in created_images:
        transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = texture_set
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "texture_set",
            prefix,
            ChangeKind.CREATED,
            f"Imported {len(texture_set)} PBR texture images",
        )
    )


def _create_pbr_material(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    material = bpy.data.materials.new(str(payload["name"]))
    material_any: Any = material
    try:
        material_any.use_nodes = True
        material_any.diffuse_color = (
            float(payload["base_color"][0]),
            float(payload["base_color"][1]),
            float(payload["base_color"][2]),
            float(payload["alpha"]),
        )
        material_any.metallic = float(payload["metallic"])
        material_any.roughness = float(payload["roughness"])
        principled = material_any.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            raise ExecutionError("The new PBR material has no Principled BSDF node.")
        principled.inputs["Base Color"].default_value = material_any.diffuse_color
        principled.inputs["Metallic"].default_value = float(payload["metallic"])
        principled.inputs["Roughness"].default_value = float(payload["roughness"])
        principled.inputs["Alpha"].default_value = float(payload["alpha"])
        for role, image in _pbr_material_images(payload, results).items():
            _attach_pbr_image_node(material_any, image, role)
    except Exception:
        _remove_created_material(material)
        raise
    transaction.add_rollback(partial(_remove_created_material, material))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = material
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "material",
            material.name,
            ChangeKind.CREATED,
            "Created PBR material",
        )
    )


def _set_pbr_texture_role(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    texture_set = _runtime_texture_set(str(operation.payload["texture_set_id"]), results)
    image = _runtime_image(str(operation.payload["image_id"]), results)
    role = str(operation.payload["role"])
    old_image = texture_set.get(role)
    old_color_space = str(image.colorspace_settings.name)
    transaction.add_rollback(
        partial(_restore_pbr_texture_role, texture_set, role, old_image, image, old_color_space)
    )
    image.colorspace_settings.name = str(operation.payload["color_space"])
    texture_set[role] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["texture_set_id"]),
            "texture_set",
            role,
            ChangeKind.UPDATED,
            f"Set PBR role {role} to image {image.name}",
        )
    )


def _generate_texture_image(
    context: Any,
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    if openai_image_generation_enabled():
        _generate_image_with_openai(
            context,
            operation,
            results,
            transaction,
            detail="Generated texture image with OpenAI Images",
        )
        return

    image = _new_filled_image(
        str(operation.payload["image_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        _float4(operation.payload["base_color"]),
        str(operation.payload["color_space"]),
        pack=False,
    )
    try:
        _write_generated_pattern(
            image,
            str(operation.payload["prompt"]),
            str(operation.payload["pattern"]),
            _float4(operation.payload["base_color"]),
            _float4(operation.payload["secondary_color"]),
        )
        image["ai_generated_prompt"] = str(operation.payload["prompt"])
        image["ai_generated_pattern"] = str(operation.payload["pattern"])
        if bool(operation.payload["pack"]):
            image.pack()
    except Exception:
        _remove_created_image(image)
        raise
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            "Generated deterministic texture image",
        )
    )


def _generate_image_asset(
    context: Any,
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    if openai_image_generation_enabled():
        _generate_image_with_openai(
            context,
            operation,
            results,
            transaction,
            detail="Generated image asset with OpenAI Images",
        )
        return

    image = _new_filled_image(
        str(operation.payload["image_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        (0.08, 0.08, 0.08, 1.0),
        str(operation.payload["color_space"]),
        pack=False,
    )
    try:
        _write_generated_pattern(
            image,
            str(operation.payload["prompt"]),
            "gradient",
            (0.08, 0.08, 0.08, 1.0),
            (0.2, 0.45, 0.85, 1.0),
        )
        image["ai_generated_prompt"] = str(operation.payload["prompt"])
        image["ai_generated_kind"] = "image_asset"
        if bool(operation.payload["pack"]):
            image.pack()
    except Exception:
        _remove_created_image(image)
        raise
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            "Generated deterministic image asset",
        )
    )


def _generate_image_with_openai(
    context: Any,
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    *,
    detail: str,
) -> None:
    import bpy

    image_name = str(operation.payload["image_name"])
    width = int(operation.payload["width"])
    height = int(operation.payload["height"])
    suffix = f"{operation.operation_id}_{uuid.uuid4().hex[:8]}"
    destination = Path(tempfile.gettempdir()) / "blender_ai_assistant" / f"{suffix}.png"
    provider = OpenAIImageProvider.from_environment(
        api_key=_resolve_openai_image_api_key(context)
    )
    provider.generate_texture(
        prompt=str(operation.payload["prompt"]),
        width=width,
        height=height,
        destination=destination,
    )

    images: Any = cast(Any, bpy.data).images
    image = images.load(str(destination), check_existing=False)
    image.name = image_name
    if int(image.size[0]) != width or int(image.size[1]) != height:
        image.scale(width, height)
    image.colorspace_settings.name = str(operation.payload["color_space"])
    image["ai_generated_prompt"] = str(operation.payload["prompt"])
    image["ai_generated_provider"] = "OpenAI Images"
    image["ai_generated_source"] = str(destination)
    if bool(operation.payload["pack"]):
        image.pack()
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            detail,
        )
    )


def _resolve_openai_image_api_key(context: Any) -> str:
    api_key = resolve_environment_value("OPENAI_API_KEY")
    if api_key:
        return api_key

    with suppress(Exception):
        from ..ui.preferences import get_preferences, resolve_provider_choice

        preferences = get_preferences(context)
        if preferences is not None and resolve_provider_choice(preferences) == PROVIDER_OPENAI:
            return str(preferences.session_api_key).strip()
    return ""


def _save_generated_texture(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    image = _runtime_image(str(operation.payload["image_id"]), results)
    filepath = _validate_texture_save_path(str(operation.payload["filepath"]))
    old_filepath = str(image.filepath_raw)
    old_format = str(image.file_format)
    image.filepath_raw = str(filepath)
    image.file_format = str(operation.payload["file_format"])
    image.save()
    if bool(operation.payload["pack_after_save"]):
        image.pack()
    transaction.add_rollback(
        partial(_restore_saved_image, image, old_filepath, old_format, filepath)
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["image_id"]),
            "image",
            image.name,
            ChangeKind.UPDATED,
            f"Saved image to {filepath.name}",
        )
    )


def _attach_texture_image(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    image = _runtime_image(str(operation.payload["image_id"]), results)
    node = _attach_image_to_material(
        material,
        image,
        str(operation.payload["node_label"]),
        str(operation.payload["connect_to"]),
        projection=str(operation.payload.get("projection", "FLAT")),
        extension=str(operation.payload.get("extension", "REPEAT")),
        uv_map_name=operation.payload.get("uv_map_name"),
        transaction=transaction,
    )
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            node.name,
            ChangeKind.CREATED,
            f"Attached texture image {image.name}",
        )
    )


def _new_controlled_principled_material(
    name: str,
    base_color: tuple[float, float, float],
    metallic: float,
    roughness: float,
    alpha: float,
) -> Any:
    import bpy

    material: Any = bpy.data.materials.new(name)
    try:
        if material.name != name:
            raise ExecutionError(f"Blender could not assign material name {name!r}.")
        material.use_nodes = True
        material.diffuse_color = (*base_color, alpha)
        material.metallic = metallic
        material.roughness = roughness
        material["ai_assistant_created"] = True
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is None:
            raise ExecutionError("The new material has no Principled BSDF node.")
        _set_principled_input_if_available(principled, "Base Color", (*base_color, alpha))
        _set_principled_input_if_available(principled, "Metallic", metallic)
        _set_principled_input_if_available(principled, "Roughness", roughness)
        _set_principled_input_if_available(principled, "Alpha", alpha)
    except Exception:
        _remove_created_material(material)
        raise
    return material


def _record_material_result(
    operation: Operation,
    material: Any,
    results: dict[str, Any],
    transaction: _Transaction,
    detail: str,
) -> None:
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = material
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "material",
            material.name,
            ChangeKind.CREATED,
            detail,
        )
    )


def _material_state_snapshot(material: Any) -> tuple[Any, ...]:
    return (
        tuple(float(value) for value in material.diffuse_color),
        bool(material.use_nodes),
        float(getattr(material, "metallic", 0.0)),
        float(getattr(material, "roughness", 0.5)),
        _principled_values(material),
    )


def _build_shader_layer_nodes(
    material: Any,
    payload: Mapping[str, Any],
    layer_id: str,
) -> tuple[Any, ...]:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    layer_name = str(payload["layer_name"])
    layer_type = str(payload["layer_type"])
    order = int(material.get("ai_shader_layer_count", 0)) + 1
    opacity = float(payload["opacity"])
    color = _rgb(payload["color"])
    created: list[Any] = []
    try:
        noise = node_tree.nodes.new("ShaderNodeTexNoise")
        noise.name = f"AI Layer {layer_name} Noise"
        noise.label = noise.name
        _tag_shader_layer_node(noise, layer_id, layer_type, order)
        noise.inputs["Scale"].default_value = _shader_layer_scale(layer_type)
        created.append(noise)

        ramp = node_tree.nodes.new("ShaderNodeValToRGB")
        ramp.name = f"AI Layer {layer_name} Ramp"
        ramp.label = ramp.name
        _tag_shader_layer_node(ramp, layer_id, layer_type, order)
        _apply_color_ramp_stops(
            ramp,
            (
                {"position": 0.0, "color": (*_dim_rgb(color, 0.35), 1.0)},
                {"position": min(1.0, max(0.01, opacity)), "color": (*color, 1.0)},
            ),
        )
        node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in principled.inputs:
            node_tree.links.new(ramp.outputs["Color"], principled.inputs["Base Color"])
        created.append(ramp)

        if float(payload["bump_strength"]) > 0.0:
            bump = node_tree.nodes.new("ShaderNodeBump")
            bump.name = f"AI Layer {layer_name} Bump"
            bump.label = bump.name
            _tag_shader_layer_node(bump, layer_id, layer_type, order)
            bump.inputs["Strength"].default_value = float(payload["bump_strength"])
            if "Height" in bump.inputs:
                node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            if "Normal" in principled.inputs:
                node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
            created.append(bump)
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise
    return tuple(created)


def _build_shader_layer_mask_node(
    material: Any,
    mask_source: Mapping[str, Any],
    payload: Mapping[str, Any],
    results: Mapping[str, Any],
) -> Any:
    node_tree = material.node_tree
    kind = str(mask_source["kind"])
    if kind == "image":
        image = _runtime_image(str(mask_source["image_id"]), results)
        node = node_tree.nodes.new("ShaderNodeTexImage")
        node.image = image
    elif kind == "uv_map":
        node = node_tree.nodes.new("ShaderNodeUVMap")
        node.uv_map = str(mask_source["uv_map_name"])
    elif kind == "vertex_group":
        node = node_tree.nodes.new("ShaderNodeValue")
        node.outputs[0].default_value = float(payload["strength"])
        node["ai_vertex_group_mask"] = str(mask_source["vertex_group"])
    else:
        node = node_tree.nodes.new("ShaderNodeTexNoise")
        pattern = str(mask_source["pattern"])
        node.inputs["Scale"].default_value = 32.0 if pattern in {"noise", "skin_pores"} else 12.0
    node.name = f"AI Layer Mask {payload['layer_id']!s}".replace("result:", "")
    node.label = node.name
    node["ai_assistant_created"] = True
    node["ai_shader_layer_mask"] = True
    node["ai_shader_layer_mask_kind"] = kind
    return node


def _tag_shader_layer_node(node: Any, layer_id: str, layer_type: str, order: int) -> None:
    node["ai_assistant_created"] = True
    node["ai_shader_layer_id"] = layer_id
    node["ai_shader_layer_type"] = layer_type
    node["ai_shader_layer_order"] = order


def _first_node_by_bl_idname(nodes: tuple[Any, ...], bl_idname: str) -> Any | None:
    for node in nodes:
        if node.bl_idname == bl_idname:
            return node
    return None


def _runtime_shader_layer(layer_id: str, results: Mapping[str, Any]) -> dict[str, Any]:
    if not layer_id.startswith(RESULT_REFERENCE_PREFIX):
        raise ExecutionError("Shader layer references must use result:<operation_id>.")
    layer = results.get(layer_id)
    if not isinstance(layer, dict) or "nodes" not in layer or "material" not in layer:
        raise ExecutionError(f"Shader layer result {layer_id} is unavailable.")
    return layer


def _restore_node_custom_properties(
    snapshots: tuple[tuple[Any, dict[str, Any]], ...],
) -> None:
    for node, properties in snapshots:
        for key in tuple(node.keys()):
            if key not in properties:
                del node[key]
        for key, value in properties.items():
            node[key] = value


def _restore_shader_nodes_from_snapshots(
    node_tree: Any,
    snapshots: tuple[Mapping[str, Any], ...],
) -> None:
    for snapshot in snapshots:
        _restore_shader_node_snapshot(node_tree, snapshot)


def _build_procedural_node_set(material: Any, operation: Operation) -> tuple[Any, ...]:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    payload = operation.payload
    label = str(payload["node_set_label"])
    texture_type = _procedural_texture_node_type(operation)
    color = _color_from_text(label)
    secondary = _mix_rgb(color, (1.0, 1.0, 1.0), float(payload["contrast"]))
    created: list[Any] = []
    try:
        texture = node_tree.nodes.new(texture_type)
        texture.name = f"{label} Texture"
        texture.label = texture.name
        texture["ai_assistant_created"] = True
        texture["ai_procedural_node_set"] = operation.type.value
        if "Scale" in texture.inputs:
            texture.inputs["Scale"].default_value = float(payload["scale"])
        if "Detail" in texture.inputs:
            texture.inputs["Detail"].default_value = min(
                16.0,
                2.0 + float(payload["contrast"]) * 12.0,
            )
        created.append(texture)

        coordinate = node_tree.nodes.new("ShaderNodeTexCoord")
        coordinate.name = f"{label} Coordinates"
        coordinate.label = coordinate.name
        coordinate["ai_assistant_created"] = True
        created.append(coordinate)

        mapping = node_tree.nodes.new("ShaderNodeMapping")
        mapping.name = f"{label} Mapping"
        mapping.label = mapping.name
        mapping["ai_assistant_created"] = True
        created.append(mapping)

        coord_socket_name = {
            "generated": "Generated",
            "object": "Object",
            "uv": "UV",
        }.get(str(payload["mapping"]), "Generated")
        coord_socket = coordinate.outputs.get(coord_socket_name) or coordinate.outputs.get(
            "Generated"
        )
        if coord_socket is not None and "Vector" in mapping.inputs and "Vector" in texture.inputs:
            node_tree.links.new(coord_socket, mapping.inputs["Vector"])
            node_tree.links.new(mapping.outputs["Vector"], texture.inputs["Vector"])

        ramp = node_tree.nodes.new("ShaderNodeValToRGB")
        ramp.name = f"{label} Ramp"
        ramp.label = ramp.name
        ramp["ai_assistant_created"] = True
        _apply_color_ramp_stops(
            ramp,
            (
                {"position": 0.0, "color": (*color, 1.0)},
                {"position": 1.0, "color": (*secondary, 1.0)},
            ),
        )
        texture_output = texture.outputs.get("Fac") or texture.outputs.get("Distance")
        if texture_output is not None:
            node_tree.links.new(texture_output, ramp.inputs["Fac"])
        if "Base Color" in principled.inputs:
            node_tree.links.new(ramp.outputs["Color"], principled.inputs["Base Color"])
        created.append(ramp)

        if float(payload["bump_strength"]) > 0.0:
            bump = node_tree.nodes.new("ShaderNodeBump")
            bump.name = f"{label} Bump"
            bump.label = bump.name
            bump["ai_assistant_created"] = True
            bump.inputs["Strength"].default_value = float(payload["bump_strength"])
            if texture_output is not None and "Height" in bump.inputs:
                node_tree.links.new(texture_output, bump.inputs["Height"])
            if "Normal" in principled.inputs:
                node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
            created.append(bump)

        roughness_socket = principled.inputs.get("Roughness")
        if roughness_socket is not None:
            roughness_socket.default_value = max(
                0.0,
                min(
                    1.0,
                    float(roughness_socket.default_value)
                    + float(payload["roughness_influence"]) * 0.25,
                ),
            )
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise
    return tuple(created)


def _procedural_texture_node_type(operation: Operation) -> str:
    if operation.type is OperationType.CREATE_TRIPLANAR_MAPPING_SETUP:
        return "ShaderNodeTexVoronoi"
    if operation.type is OperationType.CREATE_OBJECT_SPACE_GRADIENT_SHADER:
        return "ShaderNodeTexWave"
    if operation.type is OperationType.CREATE_CURVATURE_STYLE_MASK:
        return "ShaderNodeTexVoronoi"
    pattern = str(operation.payload.get("pattern", "noise"))
    if pattern in {"carbon_fiber", "fabric_weave", "water_ripples"}:
        return "ShaderNodeTexWave"
    if pattern in {"ceramic_crackle", "granite"}:
        return "ShaderNodeTexVoronoi"
    return "ShaderNodeTexNoise"


def _palette_colors_from_source(
    source: str,
    count: int,
) -> tuple[tuple[float, float, float], ...]:
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    colors: list[tuple[float, float, float]] = []
    for index in range(count):
        offset = (index * 3) % len(digest)
        colors.append(
            (
                0.1 + digest[offset] / 255.0 * 0.8,
                0.1 + digest[(offset + 1) % len(digest)] / 255.0 * 0.8,
                0.1 + digest[(offset + 2) % len(digest)] / 255.0 * 0.8,
            )
        )
    return tuple(colors)


def _remove_created_text(text: Any) -> None:
    import bpy

    with suppress(ReferenceError):
        data: Any = bpy.data
        if data.texts.get(text.name) == text:
            data.texts.remove(text)


def _runtime_material_palette(
    palette_id: str,
    results: Mapping[str, Any],
) -> dict[str, Any]:
    if not palette_id.startswith(RESULT_REFERENCE_PREFIX):
        raise ExecutionError("Material palette references must use result:<operation_id>.")
    palette = results.get(palette_id)
    if not isinstance(palette, dict) or "colors" not in palette:
        raise ExecutionError(f"Material palette result {palette_id} is unavailable.")
    return palette


def _color_from_text(text: str) -> tuple[float, float, float]:
    return _palette_colors_from_source(text, 1)[0]


def _family_default_metallic(family: str) -> float:
    return 0.85 if family in {"metal", "brushed_metal", "painted_metal"} else 0.0


def _family_default_roughness(family: str) -> float:
    if family in {"glass", "glossy_plastic"}:
        return 0.12
    if family in {"rubber", "fabric", "stone"}:
        return 0.75
    return 0.45


def _build_reference_texture_hint_nodes(
    material: Any,
    label: str,
    color: tuple[float, float, float],
) -> tuple[Any, ...]:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    created: list[Any] = []
    try:
        noise = node_tree.nodes.new("ShaderNodeTexNoise")
        noise.name = f"{label} Reference Noise"
        noise.label = noise.name
        noise["ai_assistant_created"] = True
        noise.inputs["Scale"].default_value = 18.0
        created.append(noise)
        ramp = node_tree.nodes.new("ShaderNodeValToRGB")
        ramp.name = f"{label} Reference Ramp"
        ramp.label = ramp.name
        ramp["ai_assistant_created"] = True
        _apply_color_ramp_stops(
            ramp,
            (
                {"position": 0.0, "color": (*_dim_rgb(color, 0.45), 1.0)},
                {"position": 1.0, "color": (*color, 1.0)},
            ),
        )
        node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in principled.inputs:
            node_tree.links.new(ramp.outputs["Color"], principled.inputs["Base Color"])
        created.append(ramp)
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise
    return tuple(created)


def _mix_rgb(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    factor: float,
) -> tuple[float, float, float]:
    bounded = max(0.0, min(1.0, factor))
    mixed = tuple(
        first[index] * (1.0 - bounded) + second[index] * bounded
        for index in range(3)
    )
    return (mixed[0], mixed[1], mixed[2])


def _dim_rgb(color: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    dimmed = tuple(max(0.0, min(1.0, component * factor)) for component in color)
    return (dimmed[0], dimmed[1], dimmed[2])


def _create_shading_preview_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    name: str,
    color: tuple[float, float, float, float],
    preview_kind: str,
) -> None:
    image = _new_filled_image(
        name,
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        _rgba(color),
        "sRGB",
        pack=bool(operation.payload["pack"]),
    )
    image["ai_preview_kind"] = preview_kind
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            f"Created {preview_kind} preview image",
        )
    )


def _specialized_metallic(
    operation_type: OperationType,
    payload: Mapping[str, Any],
) -> float:
    if operation_type is OperationType.CREATE_ANISOTROPIC_MATERIAL:
        return max(0.0, min(1.0, float(payload["template_strength"])))
    return 0.0


def _apply_specialized_material_template(
    material: Any,
    operation_type: OperationType,
    payload: Mapping[str, Any],
) -> None:
    material["ai_specialized_material"] = operation_type.value
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    _set_principled_input_if_available(principled, "Alpha", float(payload["alpha"]))
    _set_principled_input_if_available(
        principled,
        "Emission Color",
        (*tuple(float(value) for value in payload["base_color"]), 1.0),
    )
    if operation_type is OperationType.CREATE_GLASS_MATERIAL:
        _set_principled_input_if_available(
            principled,
            "Transmission Weight",
            float(payload["transmission"]),
        )
        _set_principled_input_if_available(
            principled,
            "Transmission",
            float(payload["transmission"]),
        )
        _set_principled_input_if_available(principled, "IOR", float(payload["ior"]))
        with suppress(Exception):
            material.blend_method = "BLEND"
    elif operation_type is OperationType.CREATE_TRANSLUCENT_MATERIAL:
        _set_principled_input_if_available(principled, "Alpha", float(payload["alpha"]))
        with suppress(Exception):
            material.blend_method = "BLEND"
    elif operation_type is OperationType.CREATE_EMISSION_MATERIAL:
        _set_principled_input_if_available(
            principled,
            "Emission Strength",
            max(0.1, float(payload["emission_strength"])),
        )
    elif operation_type is OperationType.CREATE_VOLUME_MATERIAL:
        _add_volume_hint_node(material, payload)
    elif operation_type is OperationType.CREATE_TOON_SHADER_MATERIAL:
        _add_toon_hint_node(material, payload)
    elif operation_type is OperationType.CREATE_ANISOTROPIC_MATERIAL:
        _set_principled_input_if_available(principled, "Anisotropic", float(payload["anisotropy"]))


def _add_volume_hint_node(material: Any, payload: Mapping[str, Any]) -> None:
    node_tree = material.node_tree
    output = node_tree.nodes.get("Material Output")
    if output is None:
        return
    with suppress(Exception):
        volume = node_tree.nodes.new("ShaderNodeVolumePrincipled")
        volume.name = "AI Volume Hint"
        volume.label = volume.name
        volume["ai_assistant_created"] = True
        _set_principled_input_if_available(
            volume,
            "Color",
            (*tuple(float(value) for value in payload["base_color"]), 1.0),
        )
        _set_principled_input_if_available(volume, "Density", float(payload["density"]))
        if "Volume" in output.inputs and volume.outputs:
            node_tree.links.new(volume.outputs[0], output.inputs["Volume"])


def _add_toon_hint_node(material: Any, payload: Mapping[str, Any]) -> None:
    node_tree = material.node_tree
    ramp = node_tree.nodes.new("ShaderNodeValToRGB")
    ramp.name = "AI Toon Bands"
    ramp.label = ramp.name
    ramp["ai_assistant_created"] = True
    color = _rgb(payload["base_color"])
    _apply_color_ramp_stops(
        ramp,
        (
            {"position": 0.0, "color": (*_dim_rgb(color, 0.35), 1.0)},
            {"position": float(payload["template_strength"]), "color": (*color, 1.0)},
        ),
    )


def _set_principled_input_if_available(node: Any, input_name: str, value: Any) -> None:
    socket = node.inputs.get(input_name)
    if socket is not None:
        socket.default_value = value


def _shader_layer_scale(layer_type: str) -> float:
    return {
        "base": 4.0,
        "paint": 8.0,
        "dust": 28.0,
        "edge_wear": 36.0,
        "scratches": 52.0,
        "clearcoat": 6.0,
        "emission_detail": 14.0,
        "decal": 2.0,
    }.get(layer_type, 12.0)


def _node_has_links(node: Any) -> bool:
    return any(socket.links for socket in node.inputs) or any(
        socket.links for socket in node.outputs
    )


def _is_assistant_owned_material(material: Any) -> bool:
    return bool(material.get("ai_assistant_created", False)) or str(material.name).startswith("AI ")


def _restore_node_locations(locations: tuple[tuple[Any, tuple[float, ...]], ...]) -> None:
    for node, location in locations:
        node.location = location


def _link_should_be_checked(link: Any, assistant_owned_only: bool) -> bool:
    if not assistant_owned_only:
        return True
    return _is_assistant_created_node(link.from_node) or _is_assistant_created_node(link.to_node)


def _shader_link_is_compatible(link: Any) -> bool:
    from_family = SHADER_SOCKET_FAMILIES.get(str(link.from_socket.name))
    to_family = SHADER_SOCKET_FAMILIES.get(str(link.to_socket.name))
    if from_family is None or to_family is None:
        return True
    return to_family in SHADER_SOCKET_COMPATIBILITY.get(from_family, ())


def _custom_property_snapshot(
    item: Any,
    keys: tuple[str, ...],
) -> tuple[tuple[str, bool, Any], ...]:
    return tuple((key, key in item, item.get(key)) for key in keys)


def _restore_custom_properties(
    item: Any,
    snapshot: tuple[tuple[str, bool, Any], ...],
) -> None:
    for key, existed, value in snapshot:
        if existed:
            item[key] = value
        elif key in item:
            del item[key]


def _create_split_preview_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    name: str,
    source_color: tuple[float, ...],
    variant_color: tuple[float, ...],
    preview_kind: str,
) -> None:
    image = _new_filled_image(
        name,
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        _rgba(source_color),
        "sRGB",
        pack=False,
    )
    width, height = int(image.size[0]), int(image.size[1])
    pixels: list[float] = []
    left = _rgba(source_color)
    right = _rgba(variant_color)
    for _y in range(height):
        for x in range(width):
            pixels.extend(left if x < width // 2 else right)
    image.pixels[:] = pixels
    if bool(operation.payload["pack"]):
        image.pack()
    image["ai_preview_kind"] = preview_kind
    if "mode" in operation.payload:
        image["ai_preview_mode"] = str(operation.payload["mode"])
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            f"Created {preview_kind} preview image",
        )
    )


def _rgb(values: Any) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


def _rgba(values: Any) -> tuple[float, float, float, float]:
    if len(values) >= 4:
        return (
            float(values[0]),
            float(values[1]),
            float(values[2]),
            float(values[3]),
        )
    return (float(values[0]), float(values[1]), float(values[2]), 1.0)


def _create_paint_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    _create_named_image_result(operation, results, transaction, "Created paint image")


def _assign_paint_slot(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_uv_map(target, str(operation.payload["uv_map_name"]))
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    image = _runtime_image(str(operation.payload["image_id"]), results)
    node = _attach_image_to_material(
        material,
        image,
        str(operation.payload["node_label"]),
        str(operation.payload["connect_to"]),
        projection="FLAT",
        extension="REPEAT",
        uv_map_name=str(operation.payload["uv_map_name"]),
        transaction=transaction,
    )
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = node
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "shader_node",
            node.name,
            ChangeKind.CREATED,
            f"Assigned paint slot on {target.name}",
        )
    )


def _apply_texture_paint_strokes(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    image = _runtime_image(str(operation.payload["image_id"]), results)
    old_pixels = _image_pixels(image)
    transaction.add_rollback(partial(_restore_image_pixels, image, old_pixels))
    _paint_image_strokes(
        image,
        tuple(operation.payload["strokes"]),
        str(operation.payload["blend_mode"]),
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["image_id"]),
            "image",
            image.name,
            ChangeKind.UPDATED,
            f"Applied {len(operation.payload['strokes'])} texture paint strokes",
        )
    )


def _fill_texture_region(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    image = _runtime_image(str(operation.payload["image_id"]), results)
    old_pixels = _image_pixels(image)
    transaction.add_rollback(partial(_restore_image_pixels, image, old_pixels))
    _fill_image_region(
        image,
        operation.payload["region"],
        _float4(operation.payload["color"]),
        float(operation.payload["strength"]),
        str(operation.payload["blend_mode"]),
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["image_id"]),
            "image",
            image.name,
            ChangeKind.UPDATED,
            "Filled texture image region",
        )
    )


def _create_bake_target_image(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    _create_named_image_result(operation, results, transaction, "Created bake target image")


def _bake_texture_pass(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_uv_map(target, str(operation.payload["uv_map_name"]))
    image = _runtime_image(str(operation.payload["image_id"]), results)
    old_pixels = _image_pixels(image)
    transaction.add_rollback(partial(_restore_image_pixels, image, old_pixels))
    _write_bake_pass_image(image, target, str(operation.payload["pass_type"]))
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["image_id"]),
            "image",
            image.name,
            ChangeKind.UPDATED,
            f"Baked deterministic {operation.payload['pass_type']!s} texture pass",
        )
    )


def _create_collection(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    name = str(payload["name"])
    collection = bpy.data.collections.new(name)
    try:
        if collection.name != name:
            raise ExecutionError(f"Blender could not assign collection name {name!r}.")
        parent = _runtime_collection(
            context,
            payload.get("parent_collection_id"),
            prepared,
            results,
        )
        parent.children.link(collection)
    except Exception:
        _remove_created_collection(collection)
        raise
    transaction.add_rollback(partial(_remove_created_collection, collection))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = collection
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "collection",
            collection.name,
            ChangeKind.CREATED,
            "Created collection",
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            parent,
            "collection",
            ChangeKind.UPDATED,
            f"Linked collection {collection.name}",
        )
    )


def _set_light_properties(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        light = getattr(item, "data", None)
        if getattr(light, "type", None) not in {"POINT", "SUN", "SPOT", "AREA"}:
            raise ExecutionError(f"Object target {target_id} is not a light.")
        light = cast(Any, light)
        old_values = (
            tuple(float(value) for value in light.color),
            float(light.energy),
            float(_light_size(light)),
        )
        transaction.add_rollback(partial(_restore_light_properties, light, old_values))
        _apply_light_properties(light, operation.payload)
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Updated light properties",
            )
        )


def _set_camera_properties(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        camera = getattr(item, "data", None)
        if getattr(camera, "type", None) != "PERSP":
            raise ExecutionError(f"Object target {target_id} is not a camera.")
        camera = cast(Any, camera)
        old_lens = float(camera.lens)
        transaction.add_rollback(partial(_set_camera_lens, camera, old_lens))
        if operation.payload["focal_length"] is not None:
            camera.lens = float(operation.payload["focal_length"])
        if (
            operation.payload["make_active"] is not None
            and bool(operation.payload["make_active"])
        ):
            previous_camera = context.scene.camera
            transaction.add_rollback(partial(_set_scene_camera, context.scene, previous_camera))
            context.scene.camera = item
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Updated camera properties",
            )
        )


def _add_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    modifier_type = _blender_modifier_type(str(operation.payload["modifier_type"]))
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        if getattr(item, "type", "") != "MESH":
            raise ExecutionError(f"Object target {target_id} is not a mesh.")
        modifier = item.modifiers.new(str(operation.payload["name"]), modifier_type)
        try:
            _apply_modifier_properties(modifier, operation.payload)
        except Exception:
            item.modifiers.remove(modifier)
            raise
        transaction.add_rollback(partial(_remove_modifier, item, modifier.name))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Added {operation.payload['modifier_type']!s} modifier",
            )
        )


def _set_modifier_properties(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        if getattr(item, "type", "") != "MESH":
            raise ExecutionError(f"Object target {target_id} is not a mesh.")
        modifier_name = str(operation.payload["modifier_name"])
        modifier = item.modifiers.get(modifier_name)
        if modifier is None:
            raise ExecutionError(
                f"Object {item.name!r} has no modifier named {modifier_name!r}."
            )
        old_values = _modifier_values(modifier)
        transaction.add_rollback(partial(_restore_modifier_properties, modifier, old_values))
        _apply_modifier_properties(modifier, operation.payload)
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                f"Updated modifier {modifier_name}",
            )
        )


def _add_displace_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        name = str(operation.payload["name"])
        texture_name = f"{name} Texture"
        texture = cast(Any, bpy.data).textures.new(
            texture_name,
            type=_blender_texture_type(str(operation.payload["texture_pattern"])),
        )
        modifier = item.modifiers.new(name, "DISPLACE")
        try:
            texture.noise_scale = float(operation.payload["texture_scale"])
            modifier.texture = texture
            modifier.strength = float(operation.payload["strength"])
            modifier.mid_level = float(operation.payload["midlevel"])
            if hasattr(modifier, "texture_coords"):
                modifier.texture_coords = str(operation.payload["coordinates"]).upper()
        except Exception:
            item.modifiers.remove(modifier)
            _remove_created_texture(texture)
            raise
        transaction.add_rollback(
            partial(_remove_displace_modifier, item, modifier.name, texture)
        )
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Added Displace modifier",
            )
        )


def _add_smooth_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        modifier = item.modifiers.new(str(operation.payload["name"]), "SMOOTH")
        try:
            modifier.factor = float(operation.payload["factor"])
            modifier.iterations = int(operation.payload["iterations"])
        except Exception:
            item.modifiers.remove(modifier)
            raise
        transaction.add_rollback(partial(_remove_modifier, item, modifier.name))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Added Smooth modifier",
            )
        )


def _add_remesh_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        modifier = item.modifiers.new(str(operation.payload["name"]), "REMESH")
        try:
            modifier.mode = str(operation.payload["mode"]).upper()
            if hasattr(modifier, "voxel_size"):
                modifier.voxel_size = float(operation.payload["voxel_size"])
            if hasattr(modifier, "adaptivity"):
                modifier.adaptivity = float(operation.payload["adaptivity"])
            if hasattr(modifier, "use_remove_disconnected"):
                modifier.use_remove_disconnected = not bool(operation.payload["preserve_volume"])
        except Exception:
            item.modifiers.remove(modifier)
            raise
        transaction.add_rollback(partial(_remove_modifier, item, modifier.name))
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Added Remesh modifier",
            )
        )


def _create_text_object(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    name = str(payload["name"])
    curve = bpy.data.curves.new(f"{name} Text", type="FONT")
    curve_any: Any = curve
    item: Any | None = None
    try:
        curve_any.body = str(payload["body"])
        curve_any.align_x = str(payload["align_x"])
        curve_any.align_y = str(payload["align_y"])
        curve_any.size = float(payload["size"])
        curve_any.extrude = float(payload["extrude"])
        item = bpy.data.objects.new(name, curve)
        collection = _runtime_collection(
            context,
            payload.get("collection_id"),
            prepared,
            results,
        )
        collection.objects.link(item)
        if item.name != name:
            raise ExecutionError(f"Blender could not assign text object name {name!r}.")
        _apply_absolute_transform(item, payload)
    except Exception:
        if item is not None:
            _remove_created_object(item, curve)
        else:
            _remove_orphan_datablock(curve)
        raise
    transaction.add_rollback(partial(_remove_created_object, item, curve))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            "Created text object",
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            collection,
            "collection",
            ChangeKind.UPDATED,
            f"Linked text object {item.name}",
        )
    )


def _set_object_visibility(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    payload = operation.payload
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        old_values = (bool(item.hide_viewport), bool(item.hide_render))
        transaction.add_rollback(partial(_restore_object_visibility, item, old_values))
        if payload["viewport_visible"] is not None:
            item.hide_viewport = not bool(payload["viewport_visible"])
        if payload["render_visible"] is not None:
            item.hide_render = not bool(payload["render_visible"])
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Updated object visibility",
            )
        )


def _import_asset(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    filepath = _resolve_import_asset_source(
        str(payload["filepath"]),
        _asset_suffixes(str(payload["format"])),
    )
    try:
        destination = _runtime_collection(
            context,
            payload.get("collection_id"),
            prepared,
            results,
        )
        before_objects = set(cast(Any, bpy.data).objects)
        _run_import_operator(filepath, str(payload["format"]))
        created = tuple(
            item for item in cast(Any, bpy.data).objects if item not in before_objects
        )
        if not created:
            raise ExecutionError("The asset import did not create any objects.")

        prefix = payload.get("name_prefix")
        source_name = _import_source_name(str(payload["filepath"]), filepath)
        for item in created:
            data = item.data
            if isinstance(prefix, str):
                _assign_available_object_name(item, f"{prefix}_{item.name}")
            _move_object_to_collection(item, destination)
            _apply_absolute_transform(item, payload)
            transaction.add_rollback(partial(_remove_created_object, item, data))
            transaction.record(
                ChangeRecord(
                    operation.operation_id,
                    f"import:{operation.operation_id}:{int(item.session_uid)}",
                    "object",
                    item.name,
                    ChangeKind.CREATED,
                    f"Imported asset {source_name}",
                )
            )
    finally:
        _remove_temporary_import_source(filepath)


def _link_or_append_blend_data(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    payload = operation.payload
    filepath = _existing_local_file(str(payload["filepath"]), {".blend"})
    destination = _runtime_collection(
        context,
        payload.get("collection_id"),
        prepared,
        results,
    )
    names = tuple(str(name) for name in payload["datablock_names"])
    datablock_type = str(payload["datablock_type"])
    link = str(payload["mode"]) == "link"
    prefix = payload.get("name_prefix")

    libraries = cast(Any, bpy.data.libraries)
    with libraries.load(str(filepath), link=link) as (data_from, data_to):
        available = set(getattr(data_from, f"{datablock_type}s"))
        missing = [name for name in names if name not in available]
        if missing:
            raise ExecutionError(
                f"Blend file does not contain {datablock_type}(s): {', '.join(missing)}."
            )
        setattr(data_to, f"{datablock_type}s", list(names))

    loaded = tuple(
        item
        for item in getattr(data_to, f"{datablock_type}s")
        if item is not None
    )
    if len(loaded) != len(names):
        raise ExecutionError("Blender did not load every requested blend datablock.")

    for item in loaded:
        if datablock_type == "object":
            if isinstance(prefix, str) and not link:
                _assign_available_object_name(item, f"{prefix}_{item.name}")
            destination.objects.link(item)
            transaction.add_rollback(partial(_remove_created_object, item, item.data))
            transaction.record(
                ChangeRecord(
                    operation.operation_id,
                    f"blend:{operation.operation_id}:{int(item.session_uid)}",
                    "object",
                    item.name,
                    ChangeKind.CREATED,
                    f"{payload['mode']!s}ed object from blend file",
                )
            )
        else:
            if isinstance(prefix, str) and not link:
                _assign_available_collection_name(item, f"{prefix}_{item.name}")
            destination.children.link(item)
            transaction.add_rollback(partial(_remove_created_collection, item))
            transaction.record(
                ChangeRecord(
                    operation.operation_id,
                    f"blend:{operation.operation_id}:{int(item.session_uid)}",
                    "collection",
                    item.name,
                    ChangeKind.CREATED,
                    f"{payload['mode']!s}ed collection from blend file",
                )
            )


def _boolean_operation(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    cutter = _runtime_target(str(operation.payload["cutter_id"]), prepared, results)
    _require_mesh_object(target, str(operation.payload["target_id"]))
    _require_mesh_object(cutter, str(operation.payload["cutter_id"]))

    modifier = target.modifiers.new(
        str(operation.payload["modifier_name"]),
        "BOOLEAN",
    )
    try:
        modifier.object = cutter
        modifier.operation = str(operation.payload["boolean_operation"]).upper()
        modifier.solver = str(operation.payload["solver"]).upper()
    except Exception:
        target.modifiers.remove(modifier)
        raise

    transaction.add_rollback(partial(_remove_modifier, target, modifier.name))
    old_visibility = (bool(cutter.hide_viewport), bool(cutter.hide_render))
    if bool(operation.payload["hide_cutter"]):
        cutter.hide_viewport = True
        cutter.hide_render = True
        transaction.add_rollback(partial(_restore_object_visibility, cutter, old_visibility))

    transaction.record(
        ChangeRecord(
            operation.operation_id,
            str(operation.payload["target_id"]),
            "object",
            target.name,
            ChangeKind.UPDATED,
            f"Applied Boolean {operation.payload['boolean_operation']!s}",
        )
    )


def _join_objects(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    targets = tuple(
        _runtime_target(target_id, prepared, results)
        for target_id in operation.target_ids
    )
    for target, target_id in zip(targets, operation.target_ids, strict=True):
        _require_mesh_object(target, target_id)

    mesh = _mesh_from_face_sources(
        str(operation.payload["new_name"]),
        tuple((target, tuple(range(len(target.data.polygons)))) for target in targets),
    )
    item = _new_mesh_object_in_collection(
        context,
        str(operation.payload["new_name"]),
        mesh,
        operation.payload.get("collection_id"),
        prepared,
        results,
    )
    transaction.add_rollback(partial(_remove_created_object, item, mesh))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    for target_id, target in zip(operation.target_ids, targets, strict=True):
        _stage_object_deletion(operation.operation_id, target_id, target, transaction)
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            f"Joined {len(targets)} mesh objects",
        )
    )


def _separate_objects(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    names = iter(prepared.duplicate_names[operation.operation_id])
    mode = str(operation.payload["mode"])
    created_count = 0
    for target_id in operation.target_ids:
        target = _runtime_target(target_id, prepared, results)
        _require_mesh_object(target, target_id)
        for face_indices in _mesh_face_groups(target, mode):
            name = next(names)
            mesh = _mesh_from_face_sources(name, ((target, face_indices),))
            item = _new_mesh_object_in_collection(
                context,
                name,
                mesh,
                operation.payload.get("collection_id"),
                prepared,
                results,
            )
            created_count += 1
            transaction.add_rollback(partial(_remove_created_object, item, mesh))
            transaction.record(
                ChangeRecord(
                    operation.operation_id,
                    f"separate:{operation.operation_id}:{created_count}",
                    "object",
                    item.name,
                    ChangeKind.CREATED,
                    f"Separated mesh part from {target.name}",
                )
            )
        _stage_object_deletion(operation.operation_id, target_id, target, transaction)


def _sculpt_smooth_region(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    vertex_indices = _region_vertex_indices(item, operation.payload["region"], prepared, results)
    old_positions = _mesh_vertex_positions(item, vertex_indices)
    transaction.add_rollback(partial(_restore_mesh_vertices, item, old_positions))
    _smooth_mesh_vertices(
        item,
        vertex_indices,
        float(operation.payload["strength"]),
        int(operation.payload["iterations"]),
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            target_id,
            "object",
            item.name,
            ChangeKind.UPDATED,
            f"Smoothed {len(vertex_indices)} mesh vertices",
        )
    )


def _apply_sculpt_brush_strokes(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    radius = float(operation.payload["radius"])
    strokes = _prepare_brush_strokes(item, tuple(operation.payload["strokes"]), radius)
    affected = _prepared_brush_affected_vertices(strokes)
    if not affected:
        transaction.record(
            ChangeRecord(
                operation.operation_id,
                target_id,
                "object",
                item.name,
                ChangeKind.UPDATED,
                "Skipped sculpt brush strokes because the target mesh has no vertices",
            )
        )
        return
    old_positions = _mesh_vertex_positions(item, tuple(sorted(affected)))
    transaction.add_rollback(partial(_restore_mesh_vertices, item, old_positions))
    _apply_brush_strokes(
        item,
        strokes,
        str(operation.payload["brush_type"]),
        radius,
        float(operation.payload["strength"]),
        str(operation.payload["falloff"]),
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            target_id,
            "object",
            item.name,
            ChangeKind.UPDATED,
            _brush_stroke_detail(strokes),
        )
    )


def _runtime_target(
    target_id: str,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
) -> Any:
    if target_id.startswith(RESULT_REFERENCE_PREFIX):
        try:
            return results[target_id]
        except KeyError as error:
            raise ExecutionError(f"Result target {target_id} is unavailable.") from error
    try:
        return prepared.resolved_targets[target_id]
    except KeyError as error:
        raise ExecutionError(f"Snapshot target {target_id} is unavailable.") from error


def _runtime_image(image_id: str, results: Mapping[str, Any]) -> Any:
    if not image_id.startswith(RESULT_REFERENCE_PREFIX):
        raise ExecutionError("Image references must use result:<operation_id>.")
    image = results.get(image_id)
    if image is None:
        raise ExecutionError(f"Image result {image_id} is unavailable.")
    if not hasattr(image, "pixels"):
        raise ExecutionError(f"Result {image_id} is not an image.")
    return image


def _runtime_texture_set(texture_set_id: str, results: Mapping[str, Any]) -> dict[str, Any]:
    if not texture_set_id.startswith(RESULT_REFERENCE_PREFIX):
        raise ExecutionError("Texture set references must use result:<operation_id>.")
    texture_set = results.get(texture_set_id)
    if not isinstance(texture_set, dict):
        raise ExecutionError(f"Texture set result {texture_set_id} is unavailable.")
    return texture_set


def _runtime_shader_node(material: Any, node_ref: str, results: Mapping[str, Any]) -> Any:
    if node_ref.startswith(RESULT_REFERENCE_PREFIX):
        node = results.get(node_ref)
        if node is None:
            raise ExecutionError(f"Shader node result {node_ref} is unavailable.")
        return node
    nodes = material.node_tree.nodes
    if node_ref == "principled_bsdf":
        node = nodes.get("Principled BSDF")
    elif node_ref == "material_output":
        node = nodes.get("Material Output")
    else:
        node = None
    if node is None:
        raise ExecutionError(f"Shader node {node_ref!r} is unavailable.")
    return node


def _attach_image_to_material(
    material: Any,
    image: Any,
    node_label: str,
    connect_to: str,
    *,
    projection: str,
    extension: str,
    uv_map_name: Any,
    transaction: _Transaction,
) -> Any:
    material.use_nodes = True
    node_tree = material.node_tree
    image_node = node_tree.nodes.new("ShaderNodeTexImage")
    mapping_node = node_tree.nodes.new("ShaderNodeMapping")
    coordinate_node = node_tree.nodes.new("ShaderNodeTexCoord")
    uv_node = None
    try:
        image_node.label = node_label
        image_node.name = node_label
        image_node.image = image
        image_node.projection = projection
        image_node.extension = extension
        mapping_node.label = f"AI Mapping {node_label}"
        mapping_node.name = f"AI Mapping {node_label}"
        coordinate_node.label = f"AI Coordinates {node_label}"
        coordinate_node.name = f"AI Coordinates {node_label}"
        if isinstance(uv_map_name, str):
            uv_node = node_tree.nodes.new("ShaderNodeUVMap")
            uv_node.label = f"AI UV {node_label}"
            uv_node.name = f"AI UV {node_label}"
            uv_node.uv_map = uv_map_name
            node_tree.links.new(uv_node.outputs["UV"], mapping_node.inputs["Vector"])
        else:
            node_tree.links.new(coordinate_node.outputs["UV"], mapping_node.inputs["Vector"])
        node_tree.links.new(mapping_node.outputs["Vector"], image_node.inputs["Vector"])
        target_node = node_tree.nodes.get("Principled BSDF")
        if target_node is None:
            raise ExecutionError(f"Material {material.name!r} has no Principled BSDF node.")
        target_socket = target_node.inputs.get(connect_to)
        if target_socket is None:
            raise ExecutionError(f"Principled BSDF has no input socket {connect_to!r}.")
        output_name = "Alpha" if connect_to == "Alpha" else "Color"
        node_tree.links.new(image_node.outputs[output_name], target_socket)
    except Exception:
        for node in (uv_node, coordinate_node, mapping_node, image_node):
            if node is not None:
                _remove_shader_node(node_tree, node)
        raise
    for node in (image_node, mapping_node, coordinate_node, uv_node):
        if node is not None:
            transaction.add_rollback(partial(_remove_shader_node, node_tree, node))
    return image_node


def _controlled_mapping_node(material: Any, image_node: Any) -> Any:
    vector_socket = image_node.inputs.get("Vector")
    if vector_socket is None:
        raise ExecutionError(f"Texture node {image_node.name!r} has no Vector input.")
    for link in vector_socket.links:
        from_node = link.from_node
        if getattr(from_node, "bl_idname", "") == "ShaderNodeMapping":
            return from_node
    raise ExecutionError(f"Texture node {image_node.name!r} has no controlled mapping node.")


def _controlled_uv_map_node(material: Any, image_node: Any, transaction: _Transaction) -> Any:
    node_tree = material.node_tree
    mapping = _controlled_mapping_node(material, image_node)
    vector_socket = mapping.inputs.get("Vector")
    if vector_socket is None:
        raise ExecutionError(f"Mapping node {mapping.name!r} has no Vector input.")
    for link in vector_socket.links:
        from_node = link.from_node
        if getattr(from_node, "bl_idname", "") == "ShaderNodeUVMap":
            return from_node
    for link in tuple(vector_socket.links):
        node_tree.links.remove(link)
    uv_node = node_tree.nodes.new("ShaderNodeUVMap")
    uv_node.label = f"AI UV {image_node.name}"
    uv_node.name = f"AI UV {image_node.name}"
    node_tree.links.new(uv_node.outputs["UV"], vector_socket)
    transaction.add_rollback(partial(_remove_shader_node, node_tree, uv_node))
    return uv_node


def _restore_texture_mapping(mapping: Any, image_node: Any, values: tuple[Any, ...]) -> None:
    location, rotation, scale, projection, extension = values
    mapping.inputs["Location"].default_value = location
    mapping.inputs["Rotation"].default_value = rotation
    mapping.inputs["Scale"].default_value = scale
    if projection is not None:
        image_node.projection = projection
    if extension is not None:
        image_node.extension = extension


def _set_uv_node_map(node: Any, uv_map_name: str) -> None:
    node.uv_map = uv_map_name


def _require_uv_map(item: Any, uv_map_name: str) -> Any:
    _require_mesh_object(item, getattr(item, "name", "unknown"))
    uv_layer = item.data.uv_layers.get(uv_map_name)
    if uv_layer is None:
        raise ExecutionError(f"Object {item.name!r} has no UV map {uv_map_name!r}.")
    return uv_layer


def _remove_uv_layer(item: Any, uv_map_name: str) -> None:
    uv_layer = item.data.uv_layers.get(uv_map_name)
    if uv_layer is not None:
        item.data.uv_layers.remove(uv_layer)


def _uv_layer_values(uv_layer: Any) -> tuple[tuple[float, float], ...]:
    return tuple((float(loop.uv[0]), float(loop.uv[1])) for loop in uv_layer.data)


def _restore_uv_layer(
    item: Any,
    uv_map_name: str,
    values: tuple[tuple[float, float], ...],
    remove_if_created: bool,
) -> None:
    uv_layer = item.data.uv_layers.get(uv_map_name)
    if remove_if_created:
        if uv_layer is not None:
            item.data.uv_layers.remove(uv_layer)
        return
    if uv_layer is None:
        uv_layer = item.data.uv_layers.new(name=uv_map_name)
    for loop, value in zip(uv_layer.data, values, strict=True):
        loop.uv = value


def _write_projected_uvs(item: Any, uv_layer: Any, margin: float) -> None:
    mesh = item.data
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    if not coordinates:
        return
    min_x = min(float(coordinate.x) for coordinate in coordinates)
    max_x = max(float(coordinate.x) for coordinate in coordinates)
    min_y = min(float(coordinate.y) for coordinate in coordinates)
    max_y = max(float(coordinate.y) for coordinate in coordinates)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    usable = max(0.0, 1.0 - margin * 2.0)
    for polygon in mesh.polygons:
        for loop_index, vertex_index in zip(polygon.loop_indices, polygon.vertices, strict=True):
            coordinate = coordinates[int(vertex_index)]
            u = margin + ((float(coordinate.x) - min_x) / span_x) * usable
            v = margin + ((float(coordinate.y) - min_y) / span_y) * usable
            uv_layer.data[int(loop_index)].uv = (u, v)
    mesh.update()


def _normalize_uvs(uv_layer: Any, margin: float) -> None:
    values = _uv_layer_values(uv_layer)
    if not values:
        return
    min_u = min(value[0] for value in values)
    max_u = max(value[0] for value in values)
    min_v = min(value[1] for value in values)
    max_v = max(value[1] for value in values)
    span_u = max(max_u - min_u, 1e-9)
    span_v = max(max_v - min_v, 1e-9)
    usable = max(0.0, 1.0 - margin * 2.0)
    for loop in uv_layer.data:
        loop.uv = (
            margin + ((float(loop.uv[0]) - min_u) / span_u) * usable,
            margin + ((float(loop.uv[1]) - min_v) / span_v) * usable,
        )


def _ensure_uv_layer_for_edit(
    item: Any,
    target_id: str,
    uv_name: str,
    *,
    create_if_missing: bool,
    overwrite_existing: bool,
) -> tuple[Any, bool]:
    _require_mesh_object(item, target_id)
    uv_layer = item.data.uv_layers.get(uv_name)
    if uv_layer is None:
        if not create_if_missing:
            raise ExecutionError(f"Object {item.name!r} has no UV map {uv_name!r}.")
        item.data.uv_layers.new(name=uv_name)
        uv_layer = item.data.uv_layers.get(uv_name)
        if uv_layer is None:
            raise ExecutionError(
                f"Blender could not create UV map {uv_name!r} on {item.name!r}."
            )
        return uv_layer, True
    if not overwrite_existing:
        raise ExecutionError(f"UV map {uv_name!r} already exists on {item.name!r}.")
    return uv_layer, False


def _write_projection_uvs(item: Any, uv_layer: Any, operation: Operation) -> None:
    if operation.type in {
        OperationType.CYLINDER_PROJECT_UV_MAP,
        OperationType.SPHERE_PROJECT_UV_MAP,
    }:
        _write_radial_uvs(item, uv_layer, float(operation.payload["margin"]))
        return
    _write_projected_uvs(item, uv_layer, float(operation.payload["margin"]))


def _write_radial_uvs(item: Any, uv_layer: Any, margin: float) -> None:
    mesh = item.data
    coordinates = [vertex.co.copy() for vertex in mesh.vertices]
    if not coordinates:
        return
    min_z = min(float(coordinate.z) for coordinate in coordinates)
    max_z = max(float(coordinate.z) for coordinate in coordinates)
    span_z = max(max_z - min_z, 1e-9)
    usable = max(0.0, 1.0 - margin * 2.0)
    for polygon in mesh.polygons:
        for loop_index, vertex_index in zip(polygon.loop_indices, polygon.vertices, strict=True):
            coordinate = coordinates[int(vertex_index)]
            angle = math.atan2(float(coordinate.y), float(coordinate.x))
            u = margin + ((angle + math.pi) / (math.pi * 2.0)) * usable
            v = margin + ((float(coordinate.z) - min_z) / span_z) * usable
            uv_layer.data[int(loop_index)].uv = (u, v)
    mesh.update()


def _uv_report_lines(
    item: Any,
    uv_layer: Any,
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    values = _uv_layer_values(uv_layer)
    out_of_bounds = sum(
        1 for u, v in values if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0
    )
    seam_count = sum(1 for edge in item.data.edges if bool(getattr(edge, "use_seam", False)))
    lines = [
        "",
        f"target: {item.name}",
        f"uv_map: {uv_layer.name}",
        f"loop_count: {len(values)}",
        f"edge_seam_count: {seam_count}",
        f"out_of_bounds_loops: {out_of_bounds}",
    ]
    if bool(payload.get("include_island_estimate", False)):
        lines.append(f"estimated_islands: {max(1, seam_count // 4 + 1)}")
    if bool(payload.get("include_material_usage", False)) or "checks" in payload:
        lines.append(f"material_slots: {len(item.data.materials)}")
    checks = payload.get("checks")
    if isinstance(checks, Mapping):
        enabled = ", ".join(name for name, enabled in checks.items() if enabled)
        lines.append(f"checks: {enabled or 'none'}")
    return tuple(lines)


def _write_uv_preview_pattern(
    image: Any,
    label: str,
    line_color: tuple[float, float, float, float],
    background_color: tuple[float, float, float, float],
) -> None:
    width, height = int(image.size[0]), int(image.size[1])
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    spacing = max(8, min(width, height) // 8)
    pixels: list[float] = []
    for y in range(height):
        for x in range(width):
            diagonal = (x + y + digest[0]) % spacing == 0
            grid = x % spacing == 0 or y % spacing == 0
            pixels.extend(line_color if diagonal or grid else background_color)
    image.pixels[:] = pixels


def _edge_seam_values(item: Any) -> tuple[bool, ...]:
    return tuple(bool(getattr(edge, "use_seam", False)) for edge in item.data.edges)


def _restore_edge_seams(item: Any, values: tuple[bool, ...]) -> None:
    for edge, value in zip(item.data.edges, values, strict=True):
        edge.use_seam = value
    item.data.update()


def _set_edge_seams(item: Any, edge_indices: tuple[int, ...], value: bool) -> None:
    for edge_index in edge_indices:
        if 0 <= edge_index < len(item.data.edges):
            item.data.edges[edge_index].use_seam = value
    item.data.update()


def _set_edge_sharpness(item: Any, edge_indices: tuple[int, ...], value: bool) -> None:
    for edge_index in edge_indices:
        edge = item.data.edges[edge_index]
        if hasattr(edge, "use_edge_sharp"):
            edge.use_edge_sharp = value


def _angle_based_edge_indices(item: Any, threshold_degrees: float) -> tuple[int, ...]:
    if not item.data.edges:
        return ()
    if threshold_degrees <= 60.0:
        return tuple(range(len(item.data.edges)))
    step = 2 if threshold_degrees <= 120.0 else 3
    return tuple(index for index, _edge in enumerate(item.data.edges) if index % step == 0)


def _material_boundary_edge_indices(item: Any, material: Any) -> tuple[int, ...]:
    material_index = _material_slot_index(item, material)
    edge_keys = {tuple(sorted(edge.vertices)): index for index, edge in enumerate(item.data.edges)}
    edge_indices: set[int] = set()
    for polygon in item.data.polygons:
        if int(polygon.material_index) != material_index:
            continue
        vertices = tuple(int(vertex_index) for vertex_index in polygon.vertices)
        for index, vertex_index in enumerate(vertices):
            key = tuple(sorted((vertex_index, vertices[(index + 1) % len(vertices)])))
            edge_index = edge_keys.get(key)
            if edge_index is not None:
                edge_indices.add(edge_index)
    if edge_indices:
        return tuple(sorted(edge_indices))
    return tuple(range(len(item.data.edges)))


def _material_slot_index(item: Any, material: Any) -> int:
    for index, slot_material in enumerate(item.data.materials):
        if slot_material == material:
            return index
    if len(item.data.materials) == 0:
        item.data.materials.append(material)
        return 0
    return 0


def _runtime_uv_seam_set(seam_set_id: str, results: Mapping[str, Any]) -> Mapping[str, Any]:
    seam_set = results.get(seam_set_id)
    if not isinstance(seam_set, Mapping) or seam_set.get("kind") != "uv_seam_set":
        raise ExecutionError(f"UV seam-set result {seam_set_id} is unavailable.")
    return seam_set


def _runtime_uv_island_set(island_set_id: str, results: Mapping[str, Any]) -> Mapping[str, Any]:
    island_set = results.get(island_set_id)
    if not isinstance(island_set, Mapping) or island_set.get("kind") != "uv_island_set":
        raise ExecutionError(f"UV island-set result {island_set_id} is unavailable.")
    return island_set


def _runtime_uv_atlas(atlas_id: str, results: Mapping[str, Any]) -> Mapping[str, Any]:
    atlas = results.get(atlas_id)
    if not isinstance(atlas, Mapping) or atlas.get("kind") != "uv_atlas":
        raise ExecutionError(f"UV atlas result {atlas_id} is unavailable.")
    return atlas


def _runtime_uv_variant(variant_id: str, results: Mapping[str, Any]) -> Mapping[str, Any]:
    variant = results.get(variant_id)
    if not isinstance(variant, Mapping) or variant.get("kind") != "uv_variant":
        raise ExecutionError(f"UV variant result {variant_id} is unavailable.")
    return variant


def _runtime_uv_island_edit(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
) -> tuple[Any, Any, tuple[int, ...]]:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _require_mesh_object(item, target_id)
    uv_name = str(operation.payload["uv_map_name"])
    uv_layer = _require_uv_map(item, uv_name)
    island_set = _runtime_uv_island_set(str(operation.payload["island_set_id"]), results)
    if isinstance(island_set.get("target_id"), str) and island_set["target_id"] != target_id:
        raise ExecutionError("UV island set belongs to a different target.")
    raw_loop_indices = island_set.get("loop_indices")
    if not isinstance(raw_loop_indices, tuple):
        targets = island_set.get("targets")
        if isinstance(targets, Mapping):
            raw_loop_indices = targets.get(target_id)
    loop_indices = _valid_uv_loop_indices(uv_layer, raw_loop_indices)
    return item, uv_layer, loop_indices


def _valid_uv_loop_indices(uv_layer: Any, raw_loop_indices: Any) -> tuple[int, ...]:
    if isinstance(raw_loop_indices, tuple):
        indices = tuple(
            int(index)
            for index in raw_loop_indices
            if isinstance(index, int) and 0 <= int(index) < len(uv_layer.data)
        )
        if indices:
            return indices
    return tuple(range(len(uv_layer.data)))


def _uv_loop_bounds(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if not loop_indices:
        return (0.0, 0.0), (1.0, 1.0)
    values = [
        (float(uv_layer.data[index].uv[0]), float(uv_layer.data[index].uv[1]))
        for index in loop_indices
    ]
    return (
        (min(value[0] for value in values), min(value[1] for value in values)),
        (max(value[0] for value in values), max(value[1] for value in values)),
    )


def _transform_uv_loops(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    translation: tuple[float, float],
    rotation_degrees: float,
    scale: tuple[float, float],
    pivot: tuple[float, float],
) -> None:
    radians = math.radians(rotation_degrees)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    for index in loop_indices:
        loop = uv_layer.data[index]
        local_u = (float(loop.uv[0]) - pivot[0]) * scale[0]
        local_v = (float(loop.uv[1]) - pivot[1]) * scale[1]
        loop.uv = (
            pivot[0] + local_u * cosine - local_v * sine + translation[0],
            pivot[1] + local_u * sine + local_v * cosine + translation[1],
        )


def _align_uv_loops(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    mode: str,
    bounds_min: tuple[float, float],
    bounds_max: tuple[float, float],
) -> None:
    current_min, current_max = _uv_loop_bounds(uv_layer, loop_indices)
    current_center = (
        (current_min[0] + current_max[0]) * 0.5,
        (current_min[1] + current_max[1]) * 0.5,
    )
    target_center = ((bounds_min[0] + bounds_max[0]) * 0.5, (bounds_min[1] + bounds_max[1]) * 0.5)
    offset = [0.0, 0.0]
    if mode == "left":
        offset[0] = bounds_min[0] - current_min[0]
    elif mode == "right":
        offset[0] = bounds_max[0] - current_max[0]
    elif mode == "bottom":
        offset[1] = bounds_min[1] - current_min[1]
    elif mode == "top":
        offset[1] = bounds_max[1] - current_max[1]
    else:
        offset[0] = target_center[0] - current_center[0]
        offset[1] = target_center[1] - current_center[1]
    for index in loop_indices:
        loop = uv_layer.data[index]
        loop.uv = (float(loop.uv[0]) + offset[0], float(loop.uv[1]) + offset[1])


def _distribute_uv_loops(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    axis: str,
    spacing: float,
    bounds_min: tuple[float, float],
    bounds_max: tuple[float, float],
) -> None:
    if len(loop_indices) <= 1:
        return
    ordered = tuple(sorted(loop_indices))
    coordinate_index = 0 if axis == "horizontal" else 1
    start = bounds_min[coordinate_index]
    end = bounds_max[coordinate_index]
    usable = max(0.0, (end - start) - spacing * (len(ordered) - 1))
    for position, index in enumerate(ordered):
        loop = uv_layer.data[index]
        coordinate = start + (usable * position / max(1, len(ordered) - 1)) + spacing * position
        if coordinate_index == 0:
            loop.uv = (coordinate, float(loop.uv[1]))
        else:
            loop.uv = (float(loop.uv[0]), coordinate)


def _scale_uv_loops_to_bounds(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    bounds_min: tuple[float, float],
    bounds_max: tuple[float, float],
    *,
    preserve_aspect: bool,
) -> None:
    current_min, current_max = _uv_loop_bounds(uv_layer, loop_indices)
    span_u = max(current_max[0] - current_min[0], 1e-9)
    span_v = max(current_max[1] - current_min[1], 1e-9)
    target_span_u = max(bounds_max[0] - bounds_min[0], 1e-9)
    target_span_v = max(bounds_max[1] - bounds_min[1], 1e-9)
    scale_u = target_span_u / span_u
    scale_v = target_span_v / span_v
    if preserve_aspect:
        scale_u = scale_v = min(scale_u, scale_v)
    for index in loop_indices:
        loop = uv_layer.data[index]
        loop.uv = (
            bounds_min[0] + (float(loop.uv[0]) - current_min[0]) * scale_u,
            bounds_min[1] + (float(loop.uv[1]) - current_min[1]) * scale_v,
        )


def _uv_pin_values(uv_layer: Any) -> tuple[bool, ...]:
    return tuple(bool(getattr(loop, "pin_uv", False)) for loop in uv_layer.data)


def _restore_uv_pins(uv_layer: Any, values: tuple[bool, ...]) -> None:
    for loop, value in zip(uv_layer.data, values, strict=True):
        if hasattr(loop, "pin_uv"):
            loop.pin_uv = value


def _set_uv_pins(uv_layer: Any, loop_indices: tuple[int, ...], pinned: bool) -> None:
    for index in loop_indices:
        loop = uv_layer.data[index]
        if hasattr(loop, "pin_uv"):
            loop.pin_uv = pinned


def _scale_uv_maps_for_targets(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
    scale_factor: float,
) -> None:
    island_set: Mapping[str, Any] | None = None
    if isinstance(operation.payload.get("island_set_id"), str):
        island_set = _runtime_uv_island_set(str(operation.payload["island_set_id"]), results)
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _require_mesh_object(item, target_id)
        uv_name = str(operation.payload["uv_map_name"])
        uv_layer = _require_uv_map(item, uv_name)
        old_uvs = _uv_layer_values(uv_layer)
        transaction.add_rollback(partial(_restore_uv_layer, item, uv_name, old_uvs, False))
        raw_indices: Any = None
        if island_set is not None:
            raw_indices = island_set.get("loop_indices")
        loop_indices = _valid_uv_loop_indices(uv_layer, raw_indices)
        current_min, current_max = _uv_loop_bounds(uv_layer, loop_indices)
        pivot = (
            (current_min[0] + current_max[0]) * 0.5,
            (current_min[1] + current_max[1]) * 0.5,
        )
        _transform_uv_loops(
            uv_layer,
            loop_indices,
            (0.0, 0.0),
            0.0,
            (scale_factor, scale_factor),
            pivot,
        )
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Adjusted texel density for UV map {uv_name}",
            )
        )


def _bounded_uv_scale_factor(value: float) -> float:
    return min(max(math.sqrt(max(value, 1e-9)) / 512.0, 0.25), 4.0)


def _offset_uvs_to_tile(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    target_tile: tuple[int, int],
) -> None:
    _scale_uv_loops_to_bounds(
        uv_layer,
        loop_indices,
        (target_tile[0] + 0.02, target_tile[1] + 0.02),
        (target_tile[0] + 0.98, target_tile[1] + 0.98),
        preserve_aspect=True,
    )


def _spread_uvs_across_tiles(uv_layer: Any, tile_count_u: int, tile_count_v: int) -> None:
    tile_total = max(1, tile_count_u * tile_count_v)
    for index, loop in enumerate(uv_layer.data):
        tile_index = index % tile_total
        tile_u = tile_index % tile_count_u
        tile_v = tile_index // tile_count_u
        loop.uv = (float(loop.uv[0]) + tile_u, float(loop.uv[1]) + tile_v)


def _relax_uv_loops(
    uv_layer: Any,
    loop_indices: tuple[int, ...],
    iterations: int,
    strength: float,
) -> None:
    if not loop_indices:
        return
    for _iteration in range(iterations):
        current_min, current_max = _uv_loop_bounds(uv_layer, loop_indices)
        center = (
            (current_min[0] + current_max[0]) * 0.5,
            (current_min[1] + current_max[1]) * 0.5,
        )
        factor = min(max(strength, 0.0), 1.0) * 0.05
        for index in loop_indices:
            loop = uv_layer.data[index]
            loop.uv = (
                float(loop.uv[0]) + (center[0] - float(loop.uv[0])) * factor,
                float(loop.uv[1]) + (center[1] - float(loop.uv[1])) * factor,
            )


def _uv_layer_snapshots(item: Any, names: tuple[str, ...]) -> tuple[Any, ...]:
    layer_snapshots: list[
        tuple[str, bool, tuple[tuple[float, float], ...], tuple[bool, ...], bool]
    ] = []
    for name in names:
        uv_layer = item.data.uv_layers.get(name)
        if uv_layer is None:
            layer_snapshots.append((name, False, (), (), False))
        else:
            layer_snapshots.append(
                (
                    name,
                    True,
                    _uv_layer_values(uv_layer),
                    _uv_pin_values(uv_layer),
                    bool(getattr(uv_layer, "active_render", False)),
                )
            )
    return (_active_uv_layer_name(item), _render_uv_layer_name(item), tuple(layer_snapshots))


def _restore_uv_layer_snapshots(item: Any, snapshots: tuple[Any, ...]) -> None:
    active_name = snapshots[0]
    render_name = snapshots[1]
    layer_snapshots = snapshots[2]
    for name, existed, values, pins, active_render in layer_snapshots:
        uv_layer = item.data.uv_layers.get(name)
        if not existed:
            if uv_layer is not None:
                item.data.uv_layers.remove(uv_layer)
            continue
        if uv_layer is None:
            uv_layer = item.data.uv_layers.new(name=name)
        for loop, value in zip(uv_layer.data, values, strict=True):
            loop.uv = value
        _restore_uv_pins(uv_layer, pins)
        uv_layer.active_render = bool(active_render)
    _restore_active_uv_names(item, active_name, render_name)


def _average_uv_layers(destination: Any, source_layers: tuple[Any, ...]) -> None:
    layers = (destination, *source_layers)
    for loop_index, loop in enumerate(destination.data):
        coordinates = [
            (float(layer.data[loop_index].uv[0]), float(layer.data[loop_index].uv[1]))
            for layer in layers
            if loop_index < len(layer.data)
        ]
        if coordinates:
            loop.uv = (
                sum(coordinate[0] for coordinate in coordinates) / len(coordinates),
                sum(coordinate[1] for coordinate in coordinates) / len(coordinates),
            )


def _retarget_uv_nodes(item: Any, source_names: tuple[str, ...], destination_name: str) -> None:
    source_set = set(source_names)
    for material in item.data.materials:
        if material is None or not bool(getattr(material, "use_nodes", False)):
            continue
        for node in material.node_tree.nodes:
            if getattr(node, "bl_idname", "") == "ShaderNodeUVMap" and node.uv_map in source_set:
                node.uv_map = destination_name


def _active_uv_layer_name(item: Any) -> str | None:
    active = item.data.uv_layers.active
    return str(active.name) if active is not None else None


def _render_uv_layer_name(item: Any) -> str | None:
    for layer in item.data.uv_layers:
        if bool(getattr(layer, "active_render", False)):
            return str(layer.name)
    return None


def _restore_active_uv_names(
    item: Any,
    active_name: str | None,
    render_name: str | None,
) -> None:
    if active_name is not None and item.data.uv_layers.get(active_name) is not None:
        item.data.uv_layers.active = item.data.uv_layers[active_name]
    for layer in item.data.uv_layers:
        layer.active_render = render_name is not None and layer.name == render_name


def _restore_accepted_uv_variant(
    item: Any,
    uv_map_name: str,
    values: tuple[tuple[float, float], ...],
    remove_if_created: bool,
    active_name: str | None,
    render_name: str | None,
) -> None:
    _restore_uv_layer(item, uv_map_name, values, remove_if_created)
    _restore_active_uv_names(item, active_name, render_name)


def _float2(values: Any) -> tuple[float, float]:
    return (float(values[0]), float(values[1]))


def _int2(values: Any) -> tuple[int, int]:
    return (int(values[0]), int(values[1]))


def _pbr_material_images(payload: Mapping[str, Any], results: Mapping[str, Any]) -> dict[str, Any]:
    images: dict[str, Any] = {}
    texture_set_id = payload["texture_set_id"]
    if isinstance(texture_set_id, str):
        images.update(_runtime_texture_set(texture_set_id, results))
    field_roles = {
        "base_color_image_id": "base_color",
        "roughness_image_id": "roughness",
        "metallic_image_id": "metallic",
        "normal_image_id": "normal",
        "ambient_occlusion_image_id": "ambient_occlusion",
        "displacement_image_id": "displacement",
        "alpha_image_id": "alpha",
        "emission_image_id": "emission",
    }
    for field_name, role in field_roles.items():
        image_id = payload[field_name]
        if isinstance(image_id, str):
            images[role] = _runtime_image(image_id, results)
    return images


def _attach_pbr_image_node(material: Any, image: Any, role: str) -> None:
    node_tree = material.node_tree
    image_node = node_tree.nodes.new("ShaderNodeTexImage")
    image_node.label = f"AI PBR {role}"
    image_node.name = f"AI PBR {role}"
    image_node.image = image
    if role in PBR_NON_COLOR_ROLES:
        image.colorspace_settings.name = "Non-Color"
    principled = node_tree.nodes.get("Principled BSDF")
    output = node_tree.nodes.get("Material Output")
    if principled is None:
        raise ExecutionError("PBR material has no Principled BSDF node.")
    role_inputs = {
        "base_color": "Base Color",
        "roughness": "Roughness",
        "metallic": "Metallic",
        "alpha": "Alpha",
        "emission": "Emission Color",
    }
    if role in role_inputs and principled.inputs.get(role_inputs[role]) is not None:
        output_name = "Alpha" if role == "alpha" else "Color"
        node_tree.links.new(image_node.outputs[output_name], principled.inputs[role_inputs[role]])
    elif role == "normal":
        normal = node_tree.nodes.new("ShaderNodeNormalMap")
        normal.label = "AI PBR Normal"
        normal.name = "AI PBR Normal"
        node_tree.links.new(image_node.outputs["Color"], normal.inputs["Color"])
        node_tree.links.new(normal.outputs["Normal"], principled.inputs["Normal"])
    elif role == "displacement" and output is not None and output.inputs.get("Displacement"):
        node_tree.links.new(image_node.outputs["Color"], output.inputs["Displacement"])


def _restore_pbr_texture_role(
    texture_set: dict[str, Any],
    role: str,
    old_image: Any,
    image: Any,
    old_color_space: str,
) -> None:
    image.colorspace_settings.name = old_color_space
    if old_image is None:
        texture_set.pop(role, None)
    else:
        texture_set[role] = old_image


def _new_filled_image(
    name: str,
    width: int,
    height: int,
    color: tuple[float, float, float, float],
    color_space: str,
    *,
    pack: bool,
) -> Any:
    import bpy

    image = cast(Any, bpy.data).images.new(name, width=width, height=height, alpha=True)
    image.colorspace_settings.name = color_space
    _fill_pixels(image, color)
    if pack:
        image.pack()
    return image


def _create_named_image_result(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    detail: str,
) -> None:
    image = _new_filled_image(
        str(operation.payload["image_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        _float4(operation.payload["fill_color"]),
        str(operation.payload["color_space"]),
        pack=bool(operation.payload["pack"]),
    )
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            detail,
        )
    )


def _fill_pixels(image: Any, color: tuple[float, float, float, float]) -> None:
    width, height = int(image.size[0]), int(image.size[1])
    image.pixels[:] = list(color) * (width * height)


def _float4(values: Any) -> tuple[float, float, float, float]:
    return (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
    )


def _pixel4(values: list[float], index: int) -> tuple[float, float, float, float]:
    return (
        float(values[index]),
        float(values[index + 1]),
        float(values[index + 2]),
        float(values[index + 3]),
    )


def _write_generated_pattern(
    image: Any,
    prompt: str,
    pattern: str,
    base_color: tuple[float, float, float, float],
    secondary_color: tuple[float, float, float, float],
) -> None:
    width, height = int(image.size[0]), int(image.size[1])
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    pixels: list[float] = []
    for y in range(height):
        for x in range(width):
            if pattern == "solid":
                color = base_color
            elif pattern == "checker":
                color = base_color if ((x // 8 + y // 8) % 2 == 0) else secondary_color
            elif pattern == "gradient":
                factor = x / max(width - 1, 1)
                color = _mix_color(base_color, secondary_color, factor)
            else:
                noise = digest[(x * 31 + y * 17) % len(digest)] / 255.0
                color = _mix_color(base_color, secondary_color, noise)
            pixels.extend(color)
    image.pixels[:] = pixels


def _image_pixels(image: Any) -> tuple[float, ...]:
    return tuple(float(value) for value in image.pixels[:])


def _restore_image_pixels(image: Any, pixels: tuple[float, ...]) -> None:
    image.pixels[:] = pixels


def _paint_image_strokes(
    image: Any,
    strokes: tuple[Mapping[str, Any], ...],
    blend_mode: str,
) -> None:
    width, height = int(image.size[0]), int(image.size[1])
    pixels = list(float(value) for value in image.pixels[:])
    for stroke in strokes:
        center_u, center_v = (float(value) for value in stroke["uv"])
        radius = float(stroke["radius"])
        color = _float4(stroke["color"])
        strength = float(stroke["strength"])
        min_x = max(0, int((center_u - radius) * width))
        max_x = min(width - 1, int((center_u + radius) * width))
        min_y = max(0, int((center_v - radius) * height))
        max_y = min(height - 1, int((center_v + radius) * height))
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                u = (x + 0.5) / width
                v = (y + 0.5) / height
                distance = math.dist((u, v), (center_u, center_v))
                if distance > radius:
                    continue
                factor = strength * (1.0 - distance / max(radius, 1e-9))
                index = (y * width + x) * 4
                current = _pixel4(pixels, index)
                blended = _blend_texture_color(current, color, factor, blend_mode)
                pixels[index : index + 4] = blended
    image.pixels[:] = pixels


def _fill_image_region(
    image: Any,
    region: Mapping[str, Any],
    color: tuple[float, float, float, float],
    strength: float,
    blend_mode: str,
) -> None:
    width, height = int(image.size[0]), int(image.size[1])
    if region["kind"] == "full":
        min_u, min_v, max_u, max_v = 0.0, 0.0, 1.0, 1.0
    else:
        min_uv = region["min_uv"]
        max_uv = region["max_uv"]
        min_u, min_v = float(min_uv[0]), float(min_uv[1])
        max_u, max_v = float(max_uv[0]), float(max_uv[1])
    min_x = max(0, int(min_u * width))
    max_x = min(width - 1, int(max_u * width))
    min_y = max(0, int(min_v * height))
    max_y = min(height - 1, int(max_v * height))
    pixels = list(float(value) for value in image.pixels[:])
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            index = (y * width + x) * 4
            current = _pixel4(pixels, index)
            pixels[index : index + 4] = _blend_texture_color(
                current,
                color,
                strength,
                blend_mode,
            )
    image.pixels[:] = pixels


def _write_bake_pass_image(image: Any, target: Any, pass_type: str) -> None:
    material = target.active_material
    diffuse = (
        _float4(material.diffuse_color)
        if material is not None
        else (0.8, 0.8, 0.8, 1.0)
    )
    if pass_type == "base_color":
        color = diffuse
    elif pass_type == "roughness":
        roughness = float(getattr(material, "roughness", 0.5)) if material else 0.5
        color = (roughness, roughness, roughness, 1.0)
    elif pass_type == "metallic":
        metallic = float(getattr(material, "metallic", 0.0)) if material else 0.0
        color = (metallic, metallic, metallic, 1.0)
    elif pass_type == "normal":
        color = (0.5, 0.5, 1.0, 1.0)
    elif pass_type == "ambient_occlusion":
        color = (0.75, 0.75, 0.75, 1.0)
    else:
        color = diffuse
    _fill_pixels(image, color)
    image["ai_bake_pass"] = pass_type
    image["ai_bake_source"] = target.name


def _mix_color(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    factor: float,
) -> tuple[float, float, float, float]:
    clamped = max(0.0, min(1.0, factor))
    return cast(
        tuple[float, float, float, float],
        tuple(
            first[index] * (1.0 - clamped) + second[index] * clamped
            for index in range(4)
        ),
    )


def _blend_texture_color(
    current: tuple[float, float, float, float],
    color: tuple[float, float, float, float],
    strength: float,
    blend_mode: str,
) -> tuple[float, float, float, float]:
    strength = max(0.0, min(1.0, strength))
    if blend_mode == "replace":
        target = color
    elif blend_mode == "multiply":
        target = cast(
            tuple[float, float, float, float],
            tuple(current[index] * color[index] for index in range(4)),
        )
    elif blend_mode == "add":
        target = cast(
            tuple[float, float, float, float],
            tuple(min(1.0, current[index] + color[index]) for index in range(4)),
        )
    else:
        target = color
    return _mix_color(current, target, strength)


def _validate_texture_save_path(filepath: str) -> Path:
    if _is_url(filepath):
        raise ExecutionPreflightError("Texture output paths must be local files.")
    path = Path(filepath).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ExecutionPreflightError("Texture output path must use PNG, JPEG, or TIFF.")
    if not path.parent.exists():
        raise ExecutionPreflightError(f"Texture output directory does not exist: {path.parent}.")
    if path.exists():
        raise ExecutionPreflightError(f"Texture output file already exists: {path}.")
    return path


def _restore_saved_image(
    image: Any,
    filepath: str,
    file_format: str,
    created_path: Path,
) -> None:
    image.filepath_raw = filepath
    image.file_format = file_format
    created_path.unlink(missing_ok=True)


def _asset_suffixes(asset_format: str) -> set[str]:
    return {
        "obj": {".obj"},
        "fbx": {".fbx"},
        "gltf": {".gltf"},
        "glb": {".glb"},
    }[asset_format]


def _validate_import_asset_source(source: str, allowed_suffixes: set[str]) -> None:
    if _is_url(source):
        _validate_import_url(source, allowed_suffixes)
        return
    _existing_local_file(source, allowed_suffixes)


def _resolve_import_asset_source(source: str, allowed_suffixes: set[str]) -> Path:
    if _is_url(source):
        return _download_import_url(source, allowed_suffixes)
    return _existing_local_file(source, allowed_suffixes)


def _validate_image_texture_source(source: str) -> None:
    if _is_url(source):
        parsed = urlparse(source)
        if parsed.scheme.lower() != "https":
            raise ExecutionPreflightError("Image texture URLs must use HTTPS.")
        if not parsed.netloc:
            raise ExecutionPreflightError("Image texture URLs require a host name.")
        suffix = Path(unquote(parsed.path)).suffix.lower()
        if suffix not in IMAGE_TEXTURE_SUFFIXES:
            suffixes = ", ".join(sorted(IMAGE_TEXTURE_SUFFIXES))
            raise ExecutionPreflightError(
                f"Image texture URL must end with one of: {suffixes}."
            )
        return
    _existing_local_file(source, IMAGE_TEXTURE_SUFFIXES)


def _resolve_image_texture_source(source: str, max_bytes: int) -> Path:
    if _is_url(source):
        return _download_image_texture_url(source, max_bytes)
    return _existing_local_file(source, IMAGE_TEXTURE_SUFFIXES)


def _is_url(source: str) -> bool:
    return "://" in source


def _validate_import_url(source: str, allowed_suffixes: set[str]) -> None:
    parsed = urlparse(source)
    if parsed.scheme.lower() != "https":
        raise ExecutionPreflightError("Asset URL imports must use HTTPS.")
    if not parsed.netloc:
        raise ExecutionPreflightError("Asset URL imports require a host name.")
    suffix = Path(unquote(parsed.path)).suffix.lower()
    if suffix not in allowed_suffixes:
        suffixes = ", ".join(sorted(allowed_suffixes))
        raise ExecutionPreflightError(f"Asset URL must end with one of: {suffixes}.")


def _download_import_url(source: str, allowed_suffixes: set[str]) -> Path:
    import requests

    _validate_import_url(source, allowed_suffixes)
    parsed = urlparse(source)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    response = requests.get(
        source,
        stream=True,
        timeout=URL_IMPORT_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > MAX_URL_IMPORT_BYTES:
            raise ExecutionPreflightError(
                f"Asset URL is larger than {MAX_URL_IMPORT_BYTES} bytes."
            )

        temporary_path = ""
        bytes_written = 0
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            prefix="blender_ai_import_",
        ) as temporary:
            temporary_path = temporary.name
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > MAX_URL_IMPORT_BYTES:
                        raise ExecutionPreflightError(
                            f"Asset URL is larger than {MAX_URL_IMPORT_BYTES} bytes."
                        )
                    temporary.write(chunk)
            except Exception:
                Path(temporary_path).unlink(missing_ok=True)
                raise
        if bytes_written == 0:
            Path(temporary_path).unlink(missing_ok=True)
            raise ExecutionPreflightError("Asset URL returned an empty file.")
        return Path(temporary_path)
    finally:
        response.close()


def _download_image_texture_url(source: str, max_bytes: int) -> Path:
    import requests

    _validate_image_texture_source(source)
    parsed = urlparse(source)
    suffix = Path(unquote(parsed.path)).suffix.lower()
    response = requests.get(
        source,
        stream=True,
        timeout=URL_IMPORT_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > max_bytes:
            raise ExecutionPreflightError(
                f"Image texture URL is larger than {max_bytes} bytes."
            )

        temporary_path = ""
        bytes_written = 0
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            prefix="blender_ai_texture_",
        ) as temporary:
            temporary_path = temporary.name
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise ExecutionPreflightError(
                            f"Image texture URL is larger than {max_bytes} bytes."
                        )
                    temporary.write(chunk)
            except Exception:
                Path(temporary_path).unlink(missing_ok=True)
                raise
        if bytes_written == 0:
            Path(temporary_path).unlink(missing_ok=True)
            raise ExecutionPreflightError("Image texture URL returned an empty file.")
        return Path(temporary_path)
    finally:
        response.close()


def _remove_temporary_import_source(filepath: Path) -> None:
    if filepath.name.startswith("blender_ai_import_"):
        filepath.unlink(missing_ok=True)


def _import_source_name(source: str, filepath: Path) -> str:
    if _is_url(source):
        parsed = urlparse(source)
        return Path(unquote(parsed.path)).name or parsed.netloc
    return filepath.name


def _existing_local_file(filepath: str, allowed_suffixes: set[str]) -> Path:
    if filepath.lower().startswith(("http://", "https://", "ftp://", "file://")):
        raise ExecutionPreflightError("Only local file paths are allowed.")
    path = Path(filepath).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    if path.suffix.lower() not in allowed_suffixes:
        suffixes = ", ".join(sorted(allowed_suffixes))
        raise ExecutionPreflightError(f"File path must end with one of: {suffixes}.")
    if not path.exists():
        raise ExecutionPreflightError(f"File does not exist: {path}.")
    if not path.is_file():
        raise ExecutionPreflightError(f"File path is not a file: {path}.")
    return path


def _validate_blend_datablock_names(
    filepath: Path,
    datablock_type: str,
    names: tuple[str, ...],
) -> None:
    import bpy

    libraries = cast(Any, bpy.data.libraries)
    with libraries.load(str(filepath), link=True) as (data_from, _data_to):
        available = set(getattr(data_from, f"{datablock_type}s"))
    missing = [name for name in names if name not in available]
    if missing:
        raise ExecutionPreflightError(
            f"Blend file does not contain {datablock_type}(s): {', '.join(missing)}."
        )


def _run_import_operator(filepath: Path, asset_format: str) -> None:
    import bpy

    result: Any
    if asset_format == "obj":
        wm_ops = cast(Any, bpy.ops.wm)
        import_scene_ops = cast(Any, bpy.ops.import_scene)
        if hasattr(wm_ops, "obj_import"):
            result = wm_ops.obj_import(filepath=str(filepath))
        else:
            result = import_scene_ops.obj(filepath=str(filepath))
    elif asset_format == "fbx":
        result = cast(Any, bpy.ops.import_scene).fbx(filepath=str(filepath))
    elif asset_format in {"gltf", "glb"}:
        result = cast(Any, bpy.ops.import_scene).gltf(filepath=str(filepath))
    else:
        raise ExecutionError(f"Unsupported asset import format: {asset_format}.")
    if "FINISHED" not in result:
        raise ExecutionError(f"Blender failed to import {filepath.name}.")


def _require_mesh_object(item: Any, target_id: str) -> None:
    if getattr(item, "type", "") != "MESH" or getattr(item, "data", None) is None:
        raise ExecutionError(f"Object target {target_id} is not a mesh.")


def _assign_available_object_name(item: Any, requested_name: str) -> None:
    import bpy

    occupant = cast(Any, bpy.data).objects.get(requested_name)
    if occupant is not None and occupant != item:
        raise ExecutionError(f"Object name {requested_name!r} is already in use.")
    item.name = requested_name
    if item.name != requested_name:
        raise ExecutionError(f"Blender could not assign object name {requested_name!r}.")


def _assign_available_collection_name(item: Any, requested_name: str) -> None:
    import bpy

    occupant = cast(Any, bpy.data).collections.get(requested_name)
    if occupant is not None and occupant != item:
        raise ExecutionError(f"Collection name {requested_name!r} is already in use.")
    item.name = requested_name
    if item.name != requested_name:
        raise ExecutionError(f"Blender could not assign collection name {requested_name!r}.")


def _move_object_to_collection(item: Any, destination: Any) -> None:
    if destination not in item.users_collection:
        destination.objects.link(item)
    for collection in tuple(item.users_collection):
        if collection != destination:
            collection.objects.unlink(item)


def _new_mesh_object_in_collection(
    context: Any,
    name: str,
    mesh: Any,
    collection_id: Any,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
) -> Any:
    import bpy

    item = bpy.data.objects.new(name, mesh)
    try:
        if item.name != name:
            raise ExecutionError(f"Blender could not assign object name {name!r}.")
        collection = _runtime_collection(context, collection_id, prepared, results)
        collection.objects.link(item)
    except Exception:
        _remove_created_object(item, mesh)
        raise
    return item


def _mesh_from_face_sources(
    name: str,
    face_sources: tuple[tuple[Any, tuple[int, ...]], ...],
) -> Any:
    import bpy

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    face_materials: list[Any | None] = []
    material_slots: list[Any] = []
    material_indices: dict[Any, int] = {}
    for item, face_indices in face_sources:
        mesh = item.data
        source_materials = tuple(mesh.materials)
        for face_index in face_indices:
            polygon = mesh.polygons[face_index]
            face: list[int] = []
            for vertex_index in polygon.vertices:
                coordinate = item.matrix_world @ mesh.vertices[vertex_index].co
                vertices.append(
                    (
                        float(coordinate[0]),
                        float(coordinate[1]),
                        float(coordinate[2]),
                    )
                )
                face.append(len(vertices) - 1)
            faces.append(tuple(face))
            material = (
                source_materials[polygon.material_index]
                if polygon.material_index < len(source_materials)
                else None
            )
            face_materials.append(material)
            if material is not None and material not in material_indices:
                material_indices[material] = len(material_slots)
                material_slots.append(material)
    if not faces:
        raise ExecutionError("Mesh operation produced no faces.")
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    try:
        mesh.from_pydata(vertices, (), faces)
        mesh.update()
        for material in material_slots:
            mesh.materials.append(material)
        polygons = tuple(cast(Any, mesh.polygons))
        for polygon, material in zip(polygons, face_materials, strict=True):
            if material is not None:
                polygon.material_index = material_indices[material]
    except Exception:
        _remove_orphan_datablock(mesh)
        raise
    return mesh


def _mesh_face_groups(item: Any, mode: str) -> tuple[tuple[int, ...], ...]:
    if mode == "by_material":
        groups: dict[int, list[int]] = defaultdict(list)
        for polygon in item.data.polygons:
            groups[int(polygon.material_index)].append(int(polygon.index))
        return tuple(tuple(indices) for _material, indices in sorted(groups.items()))

    vertex_faces: dict[int, list[int]] = defaultdict(list)
    for polygon in item.data.polygons:
        for vertex_index in polygon.vertices:
            vertex_faces[int(vertex_index)].append(int(polygon.index))

    visited: set[int] = set()
    groups_list: list[tuple[int, ...]] = []
    for polygon in item.data.polygons:
        polygon_index = int(polygon.index)
        if polygon_index in visited:
            continue
        stack = [polygon_index]
        connected: list[int] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            connected.append(current)
            current_polygon = item.data.polygons[current]
            for vertex_index in current_polygon.vertices:
                stack.extend(vertex_faces[int(vertex_index)])
        groups_list.append(tuple(sorted(connected)))
    return tuple(groups_list)


def _separate_part_count(item: Any, mode: str) -> int:
    _require_mesh_object(item, getattr(item, "name", "unknown"))
    return len(_mesh_face_groups(item, mode))


def _stage_object_deletion(
    operation_id: str,
    target_id: str,
    item: Any,
    transaction: _Transaction,
) -> None:
    original_name = item.name
    temporary_name = _temporary_object_name(operation_id)
    item.name = temporary_name
    transaction.add_rollback(partial(_rename_exact, ((item, original_name),)))
    transaction.deletions.append(
        _StagedDeletion(operation_id, target_id, item, original_name)
    )


def _datablock_change(
    operation_id: str,
    item: Any,
    datablock_kind: str,
    change: ChangeKind,
    detail: str,
) -> ChangeRecord:
    return ChangeRecord(
        operation_id,
        f"{datablock_kind}:{int(item.session_uid)}",
        datablock_kind,
        item.name,
        change,
        detail,
    )


def _runtime_collection(
    context: Any,
    target_id: Any,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
) -> Any:
    if target_id is None:
        return _default_collection(context)
    if str(target_id).startswith(RESULT_REFERENCE_PREFIX):
        return _runtime_target(str(target_id), prepared, results)
    return prepared.resolved_targets[str(target_id)]


def _default_collection(context: Any) -> Any:
    layer_collection = getattr(context.view_layer, "active_layer_collection", None)
    collection = getattr(layer_collection, "collection", None)
    scene_collections = set(_scene_collections(context.scene.collection))
    return collection if collection in scene_collections else context.scene.collection


def _default_collection_from_scene(item: Any) -> Any:
    import bpy

    for scene in cast(Any, bpy.data).scenes:
        if item.name in scene.objects:
            return scene.collection
    raise ExecutionError(f"Object {item.name!r} is not linked to a scene.")


def _scene_collections(root: Any) -> tuple[Any, ...]:
    collections: list[Any] = []

    def visit(collection: Any) -> None:
        collections.append(collection)
        for child in collection.children:
            visit(child)

    visit(root)
    return tuple(collections)


def _temporary_object_name(operation_id: str) -> str:
    import bpy

    objects: Any = cast(Any, bpy.data).objects
    while True:
        name = f"__ai_delete_{operation_id}_{uuid.uuid4().hex[:8]}"
        if objects.get(name) is None:
            return name


def _rename_exact(pairs: tuple[tuple[Any, str], ...]) -> None:
    import bpy

    objects: Any = cast(Any, bpy.data).objects
    temporary: list[tuple[Any, str]] = []
    for item, destination in pairs:
        if item.name == destination:
            continue
        temp_name = _temporary_object_name("rename")
        item.name = temp_name
        temporary.append((item, destination))
    for item, destination in temporary:
        occupant = objects.get(destination)
        if occupant is not None and occupant != item:
            raise ExecutionError(f"Object name {destination!r} became unavailable.")
        item.name = destination
        if item.name != destination:
            raise ExecutionError(f"Blender could not assign object name {destination!r}.")


def _apply_absolute_transform(item: Any, payload: Mapping[str, Any]) -> None:
    item.location = tuple(float(value) for value in payload["location"])
    item.rotation_mode = "XYZ"
    item.rotation_euler = tuple(float(value) for value in payload["rotation_euler"])
    if "scale" in payload:
        item.scale = tuple(float(value) for value in payload["scale"])


def _set_channels_absolute(item: Any, payload: Mapping[str, Any]) -> None:
    if payload["location"] is not None:
        item.location = tuple(float(value) for value in payload["location"])
    if payload["rotation_euler"] is not None:
        item.rotation_euler = tuple(float(value) for value in payload["rotation_euler"])
    if payload["scale"] is not None:
        item.scale = tuple(float(value) for value in payload["scale"])


def _set_channels_relative(item: Any, payload: Mapping[str, Any]) -> None:
    if payload["location"] is not None:
        item.location = tuple(
            float(item.location[index]) + float(payload["location"][index])
            for index in range(3)
        )
    if payload["rotation_euler"] is not None:
        item.rotation_euler = tuple(
            float(item.rotation_euler[index]) + float(payload["rotation_euler"][index])
            for index in range(3)
        )
    if payload["scale"] is not None:
        item.scale = tuple(
            float(item.scale[index]) * float(payload["scale"][index])
            for index in range(3)
        )


def _restore_transform(item: Any, matrix: Any, rotation_mode: str) -> None:
    item.rotation_mode = rotation_mode
    item.matrix_basis = matrix


def _restore_materials(
    data: Any,
    materials: tuple[Any, ...],
    indices: tuple[int, ...],
) -> None:
    data.materials.clear()
    for material in materials:
        data.materials.append(material)
    for polygon, index in zip(getattr(data, "polygons", ()), indices, strict=True):
        polygon.material_index = index


def _restore_copied_data(item: Any, original: Any, copied: Any) -> None:
    item.data = original
    _remove_orphan_datablock(copied)


def _set_scene_camera(scene: Any, camera: Any) -> None:
    scene.camera = camera


def _set_camera_lens(camera: Any, lens: float) -> None:
    camera.lens = lens


def _restore_collections(item: Any, collections: tuple[Any, ...]) -> None:
    for collection in collections:
        if collection not in item.users_collection:
            collection.objects.link(item)
    for collection in tuple(item.users_collection):
        if collection not in collections:
            collection.objects.unlink(item)


def _set_principled_optional_inputs(principled: Any, payload: Mapping[str, Any]) -> None:
    optional_values = {
        "Transmission Weight": payload.get("transmission"),
        "Transmission": payload.get("transmission"),
        "Emission Strength": payload.get("emission_strength"),
    }
    for input_name, value in optional_values.items():
        socket = principled.inputs.get(input_name)
        if socket is not None and value is not None:
            socket.default_value = float(value)


def _build_controlled_material_nodes(material: Any, payload: Mapping[str, Any]) -> None:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("The new material has no Principled BSDF node.")
    noise = node_tree.nodes.new("ShaderNodeTexNoise")
    noise.label = "AI Procedural Detail"
    noise.inputs["Scale"].default_value = float(payload["texture_scale"])
    noise.inputs["Detail"].default_value = float(payload["detail_strength"]) * 16.0
    if "Roughness" in noise.inputs:
        noise.inputs["Roughness"].default_value = 0.55

    bump = node_tree.nodes.new("ShaderNodeBump")
    bump.label = "AI Controlled Bump"
    bump.inputs["Strength"].default_value = float(payload["bump_strength"])
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = 0.08

    if payload.get("secondary_color") is not None:
        ramp = node_tree.nodes.new("ShaderNodeValToRGB")
        ramp.label = "AI Color Blend"
        base_color = tuple(float(value) for value in payload["base_color"])
        secondary_color = tuple(float(value) for value in payload["secondary_color"])
        ramp.color_ramp.elements[0].position = 0.25
        ramp.color_ramp.elements[0].color = (*base_color, float(payload["alpha"]))
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (*secondary_color, float(payload["alpha"]))
        node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        node_tree.links.new(ramp.outputs["Color"], principled.inputs["Base Color"])

    node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])


def _socket_value(socket: Any) -> Any:
    value = socket.default_value
    try:
        return tuple(float(component) for component in value)
    except TypeError:
        return value


def _set_socket_value(socket: Any, value: Any) -> None:
    if isinstance(value, tuple):
        socket_value = tuple(float(component) for component in value)
        current_value = _socket_value(socket)
        if isinstance(current_value, tuple) and len(current_value) == 4 and len(socket_value) == 3:
            socket_value = (*socket_value, 1.0)
        socket.default_value = socket_value
    elif isinstance(value, bool):
        socket.default_value = value
    else:
        socket.default_value = float(value)


def _restore_socket_value(socket: Any, value: Any) -> None:
    socket.default_value = value


def _remove_shader_node(node_tree: Any, node: Any) -> None:
    if node_tree.nodes.get(node.name) == node:
        node_tree.nodes.remove(node)


def _remove_shader_link(node_tree: Any, link: Any) -> None:
    try:
        node_tree.links.remove(link)
    except ReferenceError:
        return


def _is_assistant_created_node(node: Any) -> bool:
    return bool(node.get("ai_assistant_created", False)) or str(node.label).startswith("AI ")


def _find_shader_link(node_tree: Any, from_socket: Any, to_socket: Any) -> Any | None:
    for link in node_tree.links:
        if link.from_socket == from_socket and link.to_socket == to_socket:
            return link
    return None


def _restore_shader_link(
    node_tree: Any,
    from_node: Any,
    from_socket_name: str,
    to_node: Any,
    to_socket_name: str,
) -> None:
    from_socket = from_node.outputs.get(from_socket_name)
    to_socket = to_node.inputs.get(to_socket_name)
    if from_socket is not None and to_socket is not None:
        node_tree.links.new(from_socket, to_socket)


def _snapshot_shader_node(node: Any) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "bl_idname": node.bl_idname,
            "name": node.name,
            "label": node.label,
            "location": tuple(float(value) for value in node.location),
            "custom": dict(node.items()),
        }
    )


def _restore_shader_node_snapshot(node_tree: Any, snapshot: Mapping[str, Any]) -> None:
    node = node_tree.nodes.new(str(snapshot["bl_idname"]))
    node.name = str(snapshot["name"])
    node.label = str(snapshot["label"])
    node.location = tuple(float(value) for value in snapshot["location"])
    for key, value in cast(Mapping[str, Any], snapshot["custom"]).items():
        node[key] = value


def _color_ramp_stops(node: Any) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        MappingProxyType(
            {
                "position": float(element.position),
                "color": tuple(float(value) for value in element.color),
            }
        )
        for element in node.color_ramp.elements
    )


def _apply_color_ramp_stops(node: Any, stops: tuple[Mapping[str, Any], ...]) -> None:
    elements = node.color_ramp.elements
    while len(elements) > 2:
        elements.remove(elements[-1])
    while len(elements) < len(stops):
        elements.new(float(stops[len(elements)]["position"]))
    for element, stop in zip(elements, stops, strict=True):
        element.position = float(stop["position"])
        element.color = tuple(float(value) for value in stop["color"])


def _build_shader_mix_chain(material: Any, payload: Mapping[str, Any]) -> tuple[Any, ...]:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    label = str(payload["chain_label"])
    template = str(payload["template"])
    created: list[Any] = []
    try:
        noise = node_tree.nodes.new("ShaderNodeTexNoise")
        noise.name = f"{label} Noise"
        noise.label = f"{label} Noise"
        noise["ai_assistant_created"] = True
        noise.inputs["Scale"].default_value = float(payload["scale"])
        created.append(noise)
        if template == "noise_bump":
            bump = node_tree.nodes.new("ShaderNodeBump")
            bump.name = f"{label} Bump"
            bump.label = f"{label} Bump"
            bump["ai_assistant_created"] = True
            bump.inputs["Strength"].default_value = float(payload["strength"])
            node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
            created.append(bump)
        else:
            ramp = node_tree.nodes.new("ShaderNodeValToRGB")
            ramp.name = f"{label} Ramp"
            ramp.label = f"{label} Ramp"
            ramp["ai_assistant_created"] = True
            _apply_color_ramp_stops(
                ramp,
                (
                    {"position": 0.0, "color": tuple(payload["base_color"])},
                    {"position": 1.0, "color": tuple(payload["secondary_color"])},
                ),
            )
            node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
            target_socket = (
                principled.inputs["Emission Color"]
                if template == "emission_overlay"
                else principled.inputs["Base Color"]
            )
            node_tree.links.new(ramp.outputs["Color"], target_socket)
            created.append(ramp)
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise
    return tuple(created)


def _build_shader_graph_template(material: Any, payload: Mapping[str, Any]) -> tuple[Any, ...]:
    node_tree = material.node_tree
    principled = node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("Material has no Principled BSDF node.")
    label = str(payload["graph_label"])
    template = str(payload["template"])
    created: list[Any] = []
    try:
        noise = node_tree.nodes.new("ShaderNodeTexNoise")
        noise.name = f"{label} Noise"
        noise.label = f"{label} Noise"
        noise["ai_assistant_created"] = True
        noise.inputs["Scale"].default_value = float(payload["scale"])
        created.append(noise)

        ramp = node_tree.nodes.new("ShaderNodeValToRGB")
        ramp.name = f"{label} Ramp"
        ramp.label = f"{label} Ramp"
        ramp["ai_assistant_created"] = True
        _apply_color_ramp_stops(
            ramp,
            (
                {"position": 0.0, "color": tuple(payload["base_color"])},
                {"position": 1.0, "color": tuple(payload["secondary_color"])},
            ),
        )
        node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        node_tree.links.new(ramp.outputs["Color"], principled.inputs["Base Color"])
        created.append(ramp)

        if template in {"bump_detail_material", "layered_noise_material"}:
            bump = node_tree.nodes.new("ShaderNodeBump")
            bump.name = f"{label} Bump"
            bump.label = f"{label} Bump"
            bump["ai_assistant_created"] = True
            bump.inputs["Strength"].default_value = float(payload["strength"])
            node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])
            created.append(bump)
        if template == "emission_rim_material":
            emission_color = principled.inputs.get("Emission Color")
            emission_strength = principled.inputs.get("Emission Strength")
            if emission_color is not None:
                emission_color.default_value = tuple(
                    float(value) for value in payload["secondary_color"]
                )
            if emission_strength is not None:
                emission_strength.default_value = float(payload["strength"])
    except Exception:
        for node in reversed(created):
            _remove_shader_node(node_tree, node)
        raise
    return tuple(created)


def _principled_values(material: Any) -> Mapping[str, Any]:
    if not bool(getattr(material, "use_nodes", False)):
        return {}
    node_tree = getattr(material, "node_tree", None)
    principled = getattr(getattr(node_tree, "nodes", None), "get", lambda _name: None)(
        "Principled BSDF"
    )
    if principled is None:
        return {}
    values: dict[str, Any] = {}
    for input_name in ("Base Color", "Metallic", "Roughness", "Alpha"):
        socket = principled.inputs.get(input_name)
        if socket is not None:
            raw_value = socket.default_value
            try:
                values[input_name] = tuple(float(value) for value in raw_value)
            except TypeError:
                values[input_name] = float(raw_value)
    return MappingProxyType(values)


def _apply_material_properties(material: Any, payload: Mapping[str, Any]) -> None:
    material.use_nodes = True
    old_color = tuple(float(value) for value in material.diffuse_color)
    color = (
        tuple(float(value) for value in payload["base_color"])
        if payload["base_color"] is not None
        else old_color[:3]
    )
    alpha = float(payload["alpha"]) if payload["alpha"] is not None else old_color[3]
    metallic = (
        float(payload["metallic"])
        if payload["metallic"] is not None
        else float(getattr(material, "metallic", 0.0))
    )
    roughness = (
        float(payload["roughness"])
        if payload["roughness"] is not None
        else float(getattr(material, "roughness", 0.5))
    )
    material.diffuse_color = (*color, alpha)
    material.metallic = metallic
    material.roughness = roughness
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise ExecutionError("The material has no Principled BSDF node.")
    principled.inputs["Base Color"].default_value = (*color, alpha)
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Alpha"].default_value = alpha


def _restore_material_properties(material: Any, values: tuple[Any, ...]) -> None:
    diffuse_color, use_nodes, metallic, roughness, principled_values = values
    material.diffuse_color = diffuse_color
    material.use_nodes = use_nodes
    material.metallic = metallic
    material.roughness = roughness
    if use_nodes and principled_values:
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None:
            for input_name, value in principled_values.items():
                principled.inputs[input_name].default_value = value


def _light_size(light: Any) -> float:
    if light.type == "AREA":
        return float(light.size)
    if light.type in {"POINT", "SPOT"}:
        return float(light.shadow_soft_size)
    return float(light.angle)


def _apply_light_properties(light: Any, payload: Mapping[str, Any]) -> None:
    if payload["color"] is not None:
        light.color = tuple(float(value) for value in payload["color"])
    if payload["energy"] is not None:
        light.energy = float(payload["energy"])
    if payload["size"] is not None:
        size = float(payload["size"])
        if light.type == "AREA":
            light.size = size
        elif light.type in {"POINT", "SPOT"}:
            light.shadow_soft_size = size
        else:
            light.angle = size


def _restore_light_properties(light: Any, values: tuple[Any, ...]) -> None:
    color, energy, size = values
    light.color = color
    light.energy = energy
    if light.type == "AREA":
        light.size = size
    elif light.type in {"POINT", "SPOT"}:
        light.shadow_soft_size = size
    else:
        light.angle = size


def _blender_modifier_type(modifier_type: str) -> str:
    return {
        "bevel": "BEVEL",
        "solidify": "SOLIDIFY",
        "mirror": "MIRROR",
        "subdivision_surface": "SUBSURF",
        "array": "ARRAY",
        "weighted_normal": "WEIGHTED_NORMAL",
    }[modifier_type]


def _contract_modifier_type(blender_modifier_type: str) -> str:
    return {
        "BEVEL": "bevel",
        "SOLIDIFY": "solidify",
        "MIRROR": "mirror",
        "SUBSURF": "subdivision_surface",
        "ARRAY": "array",
        "WEIGHTED_NORMAL": "weighted_normal",
    }[blender_modifier_type]


def _blender_texture_type(texture_pattern: str) -> str:
    return {
        "noise": "CLOUDS",
        "clouds": "CLOUDS",
        "voronoi": "VORONOI",
        "wood": "WOOD",
    }[texture_pattern]


def _apply_modifier_properties(modifier: Any, payload: Mapping[str, Any]) -> None:
    modifier_type = str(
        payload.get("modifier_type", _contract_modifier_type(str(modifier.type)))
    )
    if modifier_type == "bevel":
        if payload["width"] is not None:
            modifier.width = float(payload["width"])
        if payload["segments"] is not None:
            modifier.segments = int(payload["segments"])
    elif modifier_type == "solidify":
        if payload["thickness"] is not None:
            modifier.thickness = float(payload["thickness"])
    elif modifier_type == "mirror":
        if payload["axis"] is not None:
            axis = str(payload["axis"])
            modifier.use_axis[0] = axis == "X"
            modifier.use_axis[1] = axis == "Y"
            modifier.use_axis[2] = axis == "Z"
    elif modifier_type == "subdivision_surface":
        if payload["levels"] is not None:
            modifier.levels = int(payload["levels"])
            modifier.render_levels = int(payload["levels"])
    elif modifier_type == "array":
        if payload["count"] is not None:
            modifier.count = int(payload["count"])
        if payload["relative_offset"] is not None:
            modifier.relative_offset_displace = tuple(
                float(value) for value in payload["relative_offset"]
            )


def _modifier_values(modifier: Any) -> Mapping[str, Any]:
    values: dict[str, Any] = {}
    for name in (
        "width",
        "segments",
        "thickness",
        "count",
        "relative_offset_displace",
        "levels",
        "render_levels",
    ):
        if hasattr(modifier, name):
            value = getattr(modifier, name)
            try:
                values[name] = tuple(float(component) for component in value)
            except TypeError:
                values[name] = value
    if hasattr(modifier, "use_axis"):
        values["use_axis"] = tuple(bool(value) for value in modifier.use_axis)
    return MappingProxyType(values)


def _restore_modifier_properties(modifier: Any, values: Mapping[str, Any]) -> None:
    for name, value in values.items():
        if name == "use_axis":
            for index, enabled in enumerate(value):
                modifier.use_axis[index] = enabled
        else:
            setattr(modifier, name, value)


def _remove_modifier(item: Any, modifier_name: str) -> None:
    modifier = item.modifiers.get(modifier_name)
    if modifier is not None:
        item.modifiers.remove(modifier)


def _remove_displace_modifier(item: Any, modifier_name: str, texture: Any) -> None:
    _remove_modifier(item, modifier_name)
    _remove_created_texture(texture)


def _remove_created_texture(texture: Any) -> None:
    import bpy

    textures: Any = cast(Any, bpy.data).textures
    current = textures.get(texture.name)
    if current == texture and texture.users == 0:
        textures.remove(texture)


def _restore_object_visibility(item: Any, values: tuple[bool, bool]) -> None:
    hide_viewport, hide_render = values
    item.hide_viewport = hide_viewport
    item.hide_render = hide_render


def _remove_created_collection(collection: Any) -> None:
    import bpy

    current = cast(Any, bpy.data).collections.get(collection.name)
    if current == collection:
        for scene in tuple(cast(Any, bpy.data).scenes):
            if collection.name in scene.collection.children:
                scene.collection.children.unlink(collection)
        for parent in tuple(collection.users_collection):
            parent.children.unlink(collection)
        cast(Any, bpy.data).collections.remove(collection)


def _remove_created_object(item: Any, data: Any | None) -> None:
    import bpy

    blender_data: Any = cast(Any, bpy.data)
    current = blender_data.objects.get(item.name)
    if current == item:
        blender_data.objects.remove(item, do_unlink=True)
    if data is not None:
        _remove_orphan_datablock(data)


def _remove_created_material(material: Any) -> None:
    import bpy

    materials: Any = cast(Any, bpy.data).materials
    current = materials.get(material.name)
    if current == material and material.users == 0:
        materials.remove(material)


def _remove_created_image(image: Any) -> None:
    import bpy

    images: Any = cast(Any, bpy.data).images
    current = images.get(image.name)
    if current == image and image.users == 0:
        images.remove(image)


def _remove_orphan_datablock(data: Any) -> None:
    import bpy

    if data.users == 0:
        bpy.data.batch_remove(ids=(data,))


def _region_vertex_indices(
    item: Any,
    region: Mapping[str, Any],
    prepared: PreparedExecution,
    results: Mapping[str, Any],
) -> tuple[int, ...]:
    kind = str(region["kind"])
    mesh = item.data
    if kind == "all":
        return tuple(int(vertex.index) for vertex in mesh.vertices)
    if kind == "material":
        material = _runtime_target(str(region["material_id"]), prepared, results)
        material_indices = {
            index for index, slot_material in enumerate(mesh.materials) if slot_material == material
        }
        vertices = {
            int(vertex_index)
            for polygon in mesh.polygons
            if int(polygon.material_index) in material_indices
            for vertex_index in polygon.vertices
        }
        if not vertices:
            raise ExecutionError(
                f"Object {item.name!r} has no faces using material {material.name!r}."
            )
        return tuple(sorted(vertices))
    if kind == "vertex_group":
        group_name = str(region["vertex_group"])
        group = item.vertex_groups.get(group_name)
        if group is None:
            raise ExecutionError(f"Object {item.name!r} has no vertex group {group_name!r}.")
        vertices = {
            int(vertex.index)
            for vertex in mesh.vertices
            for membership in vertex.groups
            if int(membership.group) == int(group.index) and float(membership.weight) > 0.0
        }
        if not vertices:
            raise ExecutionError(f"Vertex group {group_name!r} has no weighted vertices.")
        return tuple(sorted(vertices))
    raise ExecutionError(f"Unsupported sculpt region kind: {kind}.")


def _mesh_vertex_positions(item: Any, vertex_indices: tuple[int, ...]) -> Mapping[int, Any]:
    return MappingProxyType(
        {index: item.data.vertices[index].co.copy() for index in vertex_indices}
    )


def _restore_mesh_vertices(item: Any, positions: Mapping[int, Any]) -> None:
    for index, coordinate in positions.items():
        item.data.vertices[index].co = coordinate
    item.data.update()


def _smooth_mesh_vertices(
    item: Any,
    vertex_indices: tuple[int, ...],
    strength: float,
    iterations: int,
) -> None:
    selected = set(vertex_indices)
    adjacency = _mesh_adjacency(item)
    vertices = item.data.vertices
    for _iteration in range(iterations):
        old_positions = {index: vertices[index].co.copy() for index in selected}
        for index in selected:
            neighbors = [neighbor for neighbor in adjacency[index] if neighbor in selected]
            if not neighbors:
                continue
            average = sum(
                (old_positions[neighbor] for neighbor in neighbors),
                old_positions[index] * 0.0,
            ) / len(neighbors)
            vertices[index].co = old_positions[index] + (
                average - old_positions[index]
            ) * strength
    item.data.update()


def _mesh_adjacency(item: Any) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {
        int(vertex.index): set() for vertex in item.data.vertices
    }
    for edge in item.data.edges:
        first, second = (int(index) for index in edge.vertices)
        adjacency[first].add(second)
        adjacency[second].add(first)
    return adjacency


def _prepare_brush_strokes(
    item: Any,
    strokes: tuple[Mapping[str, Any], ...],
    radius: float,
) -> tuple[_PreparedBrushStroke, ...]:
    adjacency = _mesh_adjacency(item)
    return tuple(
        _prepare_brush_stroke(item, stroke, radius, adjacency) for stroke in strokes
    )


def _prepare_brush_stroke(
    item: Any,
    stroke: Mapping[str, Any],
    radius: float,
    adjacency: Mapping[int, set[int]],
) -> _PreparedBrushStroke:
    normal = _normalized_vector(stroke["normal"])
    location, affected_indices, snapped = _stroke_location_and_indices(
        item,
        stroke,
        radius,
        adjacency,
    )
    return _PreparedBrushStroke(
        location,
        normal,
        float(stroke["pressure"]),
        frozenset(affected_indices),
        snapped,
    )


def _stroke_location_and_indices(
    item: Any,
    stroke: Mapping[str, Any],
    radius: float,
    adjacency: Mapping[int, set[int]],
) -> tuple[Any, set[int], bool]:
    candidates = _stroke_location_candidates(item, stroke)
    best_location = candidates[0]
    best_indices: set[int] = set()
    for location in candidates:
        indices = _vertices_within_radius(item, location, radius)
        if len(indices) > len(best_indices):
            best_location = location
            best_indices = indices
    if best_indices:
        return best_location, best_indices, False

    closest = _closest_vertex_to_candidates(item, candidates)
    if closest is None:
        return best_location, set(), False
    closest_index = closest
    snapped_indices = {closest_index, *adjacency.get(closest_index, set())}
    snapped_location = item.data.vertices[closest_index].co.copy()
    return snapped_location, snapped_indices, True


def _stroke_location_candidates(
    item: Any,
    stroke: Mapping[str, Any],
) -> tuple[Any, ...]:
    from mathutils import Vector

    raw_location = Vector(tuple(float(value) for value in stroke["location"]))
    candidates = [raw_location]
    try:
        world_as_local = item.matrix_world.inverted() @ raw_location
    except Exception:
        world_as_local = None
    if world_as_local is not None and (world_as_local - raw_location).length > 1e-9:
        candidates.append(world_as_local)
    return tuple(candidates)


def _vertices_within_radius(item: Any, location: Any, radius: float) -> set[int]:
    return {
        int(vertex.index)
        for vertex in item.data.vertices
        if (vertex.co - location).length <= radius
    }


def _closest_vertex_to_candidates(item: Any, candidates: tuple[Any, ...]) -> int | None:
    closest_index: int | None = None
    closest_distance: float | None = None
    for location in candidates:
        for vertex in item.data.vertices:
            distance = float((vertex.co - location).length)
            if closest_distance is None or distance < closest_distance:
                closest_index = int(vertex.index)
                closest_distance = distance
    return closest_index


def _prepared_brush_affected_vertices(
    strokes: tuple[_PreparedBrushStroke, ...],
) -> set[int]:
    return {
        vertex_index
        for stroke in strokes
        for vertex_index in stroke.affected_indices
    }


def _apply_brush_strokes(
    item: Any,
    strokes: tuple[_PreparedBrushStroke, ...],
    brush_type: str,
    radius: float,
    strength: float,
    falloff: str,
) -> None:
    adjacency = _mesh_adjacency(item)
    vertices = item.data.vertices
    for stroke in strokes:
        old_positions = {
            int(vertex.index): vertex.co.copy()
            for vertex in vertices
            if int(vertex.index) in stroke.affected_indices
        }
        for index, coordinate in old_positions.items():
            distance = (coordinate - stroke.location).length
            factor = strength * stroke.pressure * _brush_falloff(distance / radius, falloff)
            if brush_type == "smooth":
                neighbors = [neighbor for neighbor in adjacency[index] if neighbor in old_positions]
                if neighbors:
                    average = sum(
                        (old_positions[neighbor] for neighbor in neighbors),
                        coordinate * 0.0,
                    ) / len(neighbors)
                    vertices[index].co = coordinate + (average - coordinate) * factor
            elif brush_type in {"inflate", "draw"}:
                vertices[index].co = coordinate + stroke.normal * (factor * radius)
            elif brush_type == "flatten":
                plane_distance = (coordinate - stroke.location).dot(stroke.normal)
                vertices[index].co = coordinate - stroke.normal * (plane_distance * factor)
            else:
                raise ExecutionError(f"Unsupported sculpt brush type: {brush_type}.")
    item.data.update()


def _brush_stroke_detail(strokes: tuple[_PreparedBrushStroke, ...]) -> str:
    snapped_count = sum(1 for stroke in strokes if stroke.snapped_to_nearest)
    if snapped_count:
        return (
            f"Applied {len(strokes)} sculpt brush strokes; "
            f"{snapped_count} missed the radius and snapped to nearest vertices"
        )
    return f"Applied {len(strokes)} sculpt brush strokes"


def _normalized_vector(values: Any) -> Any:
    from mathutils import Vector

    vector = Vector(tuple(float(value) for value in values))
    if vector.length < 1e-9:
        raise ExecutionError("Sculpt brush normal cannot be zero.")
    vector.normalize()
    return vector


def _brush_falloff(distance_ratio: float, falloff: str) -> float:
    clamped = max(0.0, min(1.0, distance_ratio))
    if falloff == "sharp":
        return 1.0 if clamped < 1.0 else 0.0
    if falloff == "linear":
        return 1.0 - clamped
    if falloff == "smooth":
        return (1.0 - clamped) ** 2 * (3.0 - 2.0 * (1.0 - clamped))
    raise ExecutionError(f"Unsupported sculpt falloff: {falloff}.")


def _create_geometry_nodes_preset(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _ensure_editable_mesh(item)
        name = str(operation.payload["name"])
        if item.modifiers.get(name) is not None:
            raise ExecutionError(f"Object {item.name!r} already has a modifier named {name!r}.")
        modifier = item.modifiers.new(name, "NODES")
        modifier["ai_assistant_created"] = True
        modifier["ai_geometry_nodes_preset"] = str(operation.payload["preset"])
        for input_name, value in operation.payload["inputs"].items():
            if value is not None:
                modifier[f"ai_input_{input_name}"] = float(value)
        transaction.add_rollback(partial(_remove_modifier, item, name))
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Added Geometry Nodes preset {operation.payload['preset']}",
            )
        )


def _create_geometry_node_group_template(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _ensure_editable_mesh(item)
        name = str(operation.payload["name"])
        if item.modifiers.get(name) is not None:
            raise ExecutionError(f"Object {item.name!r} already has a modifier named {name!r}.")
        modifier = item.modifiers.new(name, "NODES")
        group = None
        try:
            group = bpy.data.node_groups.new(f"{name} Group", "GeometryNodeTree")
            _initialize_geometry_node_group_template(group)
            if hasattr(modifier, "node_group"):
                modifier.node_group = group
        except Exception:
            if group is not None:
                with suppress(Exception):
                    bpy.data.node_groups.remove(group)
            raise
        modifier["ai_assistant_created"] = True
        modifier["ai_geometry_node_group_template"] = str(operation.payload["template"])
        for input_name, value in operation.payload["inputs"].items():
            if value is not None:
                modifier[f"ai_input_{input_name}"] = float(value)
        transaction.add_rollback(partial(_remove_node_groups, (group,)))
        transaction.add_rollback(partial(_remove_modifier, item, name))
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Added Geometry Nodes group template {operation.payload['template']}",
            )
        )


def _initialize_geometry_node_group_template(group: Any) -> None:
    group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    input_node = group.nodes.new("NodeGroupInput")
    output_node = group.nodes.new("NodeGroupOutput")
    input_node.location = (-200.0, 0.0)
    output_node.location = (200.0, 0.0)
    group.links.new(input_node.outputs["Geometry"], output_node.inputs["Geometry"])


def _set_geometry_node_input(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _ensure_editable_mesh(item)
    modifier = item.modifiers.get(str(operation.payload["modifier_name"]))
    if modifier is None:
        raise ExecutionError(f"Object {item.name!r} has no requested Geometry Nodes modifier.")
    if not bool(modifier.get("ai_assistant_created", False)):
        raise ExecutionError("Only assistant-created Geometry Nodes modifiers can be edited.")
    key = f"ai_input_{operation.payload['input_name']}"
    old_value = modifier.get(key)
    modifier[key] = float(operation.payload["value"])
    transaction.add_rollback(partial(_restore_custom_property, modifier, key, old_value))
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Set Geometry Nodes input {operation.payload['input_name']}",
        )
    )


def _remove_geometry_nodes_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _ensure_editable_mesh(item)
    modifier = item.modifiers.get(str(operation.payload["modifier_name"]))
    if modifier is None:
        raise ExecutionError(f"Object {item.name!r} has no requested Geometry Nodes modifier.")
    if not bool(modifier.get("ai_assistant_created", False)):
        raise ExecutionError("Only assistant-created Geometry Nodes modifiers can be removed.")
    values = dict(modifier.items())
    name = modifier.name
    item.modifiers.remove(modifier)
    transaction.add_rollback(partial(_restore_geometry_nodes_modifier, item, name, values))
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Removed Geometry Nodes modifier {name}",
        )
    )


def _create_generated_geometry_copy(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    copy = _copy_mesh_object(context, item, str(operation.payload["name"]))
    copy["ai_generated_variant"] = str(operation.payload["variant"])
    _register_created_object(operation, copy, results, transaction, "Created generated mesh copy")


def _create_smoothed_copy(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    copy = _copy_mesh_object(context, item, str(operation.payload["name"]))
    vertices = tuple(int(vertex.index) for vertex in copy.data.vertices)
    _smooth_mesh_vertices(
        copy,
        vertices,
        float(operation.payload["strength"]),
        int(operation.payload["iterations"]),
    )
    copy["ai_generated_variant"] = "smoothed"
    _register_created_object(operation, copy, results, transaction, "Created smoothed mesh copy")


def _create_displaced_copy(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    copy = _copy_mesh_object(context, item, str(operation.payload["name"]))
    direction = _normalized_vector(operation.payload["direction"])
    strength = float(operation.payload["strength"])
    for vertex in copy.data.vertices:
        vertex.co = vertex.co + direction * strength
    copy.data.update()
    copy["ai_generated_variant"] = "displaced"
    _register_created_object(operation, copy, results, transaction, "Created displaced mesh copy")


def _create_remeshed_copy(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    copy = _copy_mesh_object(context, item, str(operation.payload["name"]))
    if operation.payload["mode"] == "triangulate":
        import bmesh

        mesh = copy.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
    copy["ai_generated_variant"] = "remeshed"
    _register_created_object(operation, copy, results, transaction, "Created remeshed mesh copy")


def _create_dynamic_topology_copy(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bmesh

    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    copy = _copy_mesh_object(context, item, str(operation.payload["name"]))
    mesh = copy.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    cuts = int(operation.payload["detail_level"]) - 1
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    _ensure_mesh_size_within_limits(copy)
    copy["ai_generated_variant"] = "dynamic_topology"
    _register_created_object(
        operation,
        copy,
        results,
        transaction,
        "Created dynamic-topology-style mesh copy",
    )


def _replace_object_with_generated_copy(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    original = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    generated = _runtime_target(str(operation.payload["generated_object_id"]), prepared, results)
    _ensure_editable_mesh(original)
    _ensure_editable_mesh(generated)
    old_original_hidden = (bool(original.hide_viewport), bool(original.hide_render))
    old_generated_hidden = (bool(generated.hide_viewport), bool(generated.hide_render))
    original.hide_viewport = bool(operation.payload["hide_original"])
    original.hide_render = bool(operation.payload["hide_original"])
    generated.hide_viewport = False
    generated.hide_render = False
    transaction.add_rollback(
        partial(
            _restore_replacement_visibility,
            original,
            generated,
            old_original_hidden,
            old_generated_hidden,
        )
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            generated,
            "object",
            ChangeKind.UPDATED,
            f"Activated generated copy for {original.name}",
        )
    )


def _apply_generated_mesh_to_object(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    original = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    generated = _runtime_target(str(operation.payload["generated_object_id"]), prepared, results)
    _ensure_editable_mesh(original)
    _ensure_editable_mesh(generated)
    old_data = original.data
    new_data = generated.data.copy()
    generated_visibility = (bool(generated.hide_viewport), bool(generated.hide_render))
    original.data = new_data
    generated.hide_viewport = bool(operation.payload["hide_generated"])
    generated.hide_render = bool(operation.payload["hide_generated"])
    transaction.add_rollback(partial(_restore_copied_data, original, old_data, new_data))
    transaction.add_rollback(
        partial(_restore_object_visibility, generated, generated_visibility)
    )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            original,
            "object",
            ChangeKind.UPDATED,
            f"Applied generated mesh data from {generated.name}",
        )
    )


def _create_sculpt_region_from_material(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    region = {
        "kind": "material",
        "material_id": str(operation.payload["material_id"]),
        "vertex_group": None,
    }
    indices = _region_vertex_indices(item, region, prepared, results)
    _store_sculpt_region(operation, results, transaction, item, material.name, indices)


def _create_sculpt_region_from_vertex_group(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    region = {
        "kind": "vertex_group",
        "material_id": None,
        "vertex_group": str(operation.payload["vertex_group"]),
    }
    indices = _region_vertex_indices(item, region, prepared, results)
    _store_sculpt_region(
        operation,
        results,
        transaction,
        item,
        str(operation.payload["vertex_group"]),
        indices,
    )


def _create_sculpt_mask(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    region = _runtime_sculpt_region(str(operation.payload["region_id"]), results)
    mask_name = str(operation.payload["mask_name"])
    if region.target.vertex_groups.get(mask_name) is not None:
        raise ExecutionError(f"Object {region.target.name!r} already has mask {mask_name!r}.")
    group = region.target.vertex_groups.new(name=mask_name)
    group.add(region.vertex_indices, float(operation.payload["strength"]), "REPLACE")
    transaction.add_rollback(partial(_remove_vertex_group, region.target, group.name))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    cast(dict[str, Any], results)[reference] = group
    transaction.record(
        _datablock_change(
            operation.operation_id,
            region.target,
            "object",
            ChangeKind.UPDATED,
            f"Created sculpt mask {group.name}",
        )
    )


def _sculpt_mask_operation(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _ensure_editable_mesh(item)
    group = _require_vertex_group(item, str(operation.payload["mask_name"]))
    old_weights = _vertex_group_weights(item, group)
    transaction.add_rollback(
        partial(_restore_vertex_group_weights, item, group.name, old_weights)
    )

    strength = float(operation.payload["strength"])
    iterations = int(operation.payload["iterations"])
    new_weights = _edited_sculpt_mask_weights(
        item,
        operation.type,
        old_weights,
        strength,
        iterations,
    )
    _set_vertex_group_weights(item, group, new_weights)
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Updated sculpt mask {group.name}",
        )
    )


def _combine_sculpt_masks(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    target_id = str(operation.payload["target_id"])
    item = _runtime_target(target_id, prepared, results)
    _ensure_editable_mesh(item)
    source = _require_vertex_group(item, str(operation.payload["source_mask_name"]))
    target = _require_vertex_group(item, str(operation.payload["target_mask_name"]))
    result_name = str(operation.payload["result_mask_name"])
    if item.vertex_groups.get(result_name) is not None:
        raise ExecutionError(f"Object {item.name!r} already has mask {result_name!r}.")

    result_weights = _combined_sculpt_mask_weights(
        _vertex_group_weights(item, source),
        _vertex_group_weights(item, target),
        str(operation.payload["combine_mode"]),
    )
    group = item.vertex_groups.new(name=result_name)
    try:
        _set_vertex_group_weights(item, group, result_weights)
    except Exception:
        _remove_vertex_group(item, group.name)
        raise

    transaction.add_rollback(partial(_remove_vertex_group, item, group.name))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = group
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Combined sculpt masks into {group.name}",
        )
    )


def _create_face_set_from_material(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    material = _runtime_target(str(operation.payload["material_id"]), prepared, results)
    indices = _face_indices_from_material(item, material)
    _create_face_set_attribute(
        operation,
        results,
        transaction,
        item,
        str(operation.payload["face_set_name"]),
        indices,
    )


def _create_face_set_from_vertex_group(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    indices = _face_indices_from_vertex_group(item, str(operation.payload["vertex_group"]))
    _create_face_set_attribute(
        operation,
        results,
        transaction,
        item,
        str(operation.payload["face_set_name"]),
        indices,
    )


def _apply_sculpt_region_operation(
    operation: Operation,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    region = _runtime_sculpt_region(str(operation.payload["region_id"]), results)
    positions = _mesh_vertex_positions(region.target, region.vertex_indices)
    transaction.add_rollback(partial(_restore_mesh_vertices, region.target, positions))
    operation_name = str(operation.payload["operation"])
    if operation_name == "smooth":
        _smooth_mesh_vertices(
            region.target,
            region.vertex_indices,
            float(operation.payload["strength"]),
            int(operation.payload["iterations"]),
        )
    else:
        normal = _average_vertex_normal(region.target, region.vertex_indices)
        strokes = (
            _PreparedBrushStroke(
                region.target.data.vertices[index].co.copy(),
                normal,
                1.0,
                frozenset({index}),
            )
            for index in region.vertex_indices
        )
        _apply_brush_strokes(
            region.target,
            tuple(strokes),
            "inflate" if operation_name == "inflate" else "flatten",
            1.0,
            float(operation.payload["strength"]),
            "smooth",
        )
    transaction.record(
        _datablock_change(
            operation.operation_id,
            region.target,
            "object",
            ChangeKind.UPDATED,
            f"Applied sculpt region operation {operation_name}",
        )
    )


def _add_multires_modifier(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    for target_id in operation.target_ids:
        item = _runtime_target(target_id, prepared, results)
        _ensure_editable_mesh(item)
        name = str(operation.payload["name"])
        modifier = item.modifiers.new(name, "MULTIRES")
        modifier.levels = int(operation.payload["levels"])
        modifier.render_levels = int(operation.payload["render_levels"])
        transaction.add_rollback(partial(_remove_modifier, item, name))
        transaction.record(
            _datablock_change(
                operation.operation_id,
                item,
                "object",
                ChangeKind.UPDATED,
                f"Added Multires modifier {name}",
            )
        )


def _create_shape_key(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _ensure_editable_mesh(item)
    if item.data.shape_keys is None:
        item.shape_key_add(name="Basis")
    key = item.shape_key_add(name=str(operation.payload["name"]))
    key.value = float(operation.payload["value"])
    source_id = operation.payload["from_generated_object_id"]
    if source_id is not None:
        source = _runtime_target(str(source_id), prepared, results)
        _ensure_editable_mesh(source)
        if len(source.data.vertices) != len(item.data.vertices):
            raise ExecutionError("Shape key source must have the same vertex count.")
        for index, vertex in enumerate(source.data.vertices):
            key.data[index].co = vertex.co
    transaction.add_rollback(partial(_remove_shape_key, item, key.name))
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Created shape key {key.name}",
        )
    )


def _create_rig_safe_shape_key(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _ensure_editable_mesh(item)
    if _object_has_rig_dependency(item) and not bool(operation.payload["allow_rigged"]):
        raise ExecutionError("Rigged objects require allow_rigged for shape key creation.")
    if item.animation_data is not None and not bool(operation.payload["preserve_animation"]):
        raise ExecutionError("Animated objects require preserve_animation for shape key creation.")
    _create_shape_key(operation, prepared, results, transaction)


def _set_shape_key_value(
    operation: Operation,
    prepared: PreparedExecution,
    results: Mapping[str, Any],
    transaction: _Transaction,
) -> None:
    item = _runtime_target(str(operation.payload["target_id"]), prepared, results)
    _ensure_editable_mesh(item)
    shape_keys = item.data.shape_keys
    if shape_keys is None:
        raise ExecutionError(f"Object {item.name!r} has no shape keys.")
    key = shape_keys.key_blocks.get(str(operation.payload["shape_key_name"]))
    if key is None:
        raise ExecutionError(
            f"Object {item.name!r} has no shape key {operation.payload['shape_key_name']!r}."
        )
    old_value = float(key.value)
    key.value = float(operation.payload["value"])
    transaction.add_rollback(partial(_set_shape_key_block_value, key, old_value))
    transaction.record(
        _datablock_change(
            operation.operation_id,
            item,
            "object",
            ChangeKind.UPDATED,
            f"Set shape key {key.name} value",
        )
    )


def _create_preview_image(
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    if operation.payload["target_id"] is not None:
        _runtime_target(str(operation.payload["target_id"]), prepared, results)
    if operation.payload["material_id"] is not None:
        _runtime_target(str(operation.payload["material_id"]), prepared, results)
    image = _new_filled_image(
        str(operation.payload["preview_name"]),
        int(operation.payload["width"]),
        int(operation.payload["height"]),
        (0.08, 0.08, 0.08, 1.0),
        "sRGB",
        pack=False,
    )
    try:
        _write_generated_pattern(
            image,
            str(operation.payload["preview_kind"]),
            "gradient",
            (0.08, 0.08, 0.08, 1.0),
            (0.2, 0.45, 0.85, 1.0),
        )
        image["ai_preview_kind"] = str(operation.payload["preview_kind"])
        image.pack()
    except Exception:
        _remove_created_image(image)
        raise
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            f"Created {operation.payload['preview_kind']} preview image",
        )
    )


def _create_render_preview_image(
    context: Any,
    operation: Operation,
    prepared: PreparedExecution,
    results: dict[str, Any],
    transaction: _Transaction,
) -> None:
    import bpy

    scene = context.scene
    if operation.payload["target_id"] is not None:
        _runtime_target(str(operation.payload["target_id"]), prepared, results)
    camera = (
        _runtime_target(str(operation.payload["camera_id"]), prepared, results)
        if operation.payload["camera_id"] is not None
        else scene.camera
    )
    if camera is None:
        raise ExecutionError("CREATE_RENDER_PREVIEW_IMAGE requires a camera.")
    old_values = (
        scene.camera,
        int(scene.render.resolution_x),
        int(scene.render.resolution_y),
        int(scene.render.resolution_percentage),
        str(scene.render.filepath),
    )
    path = Path(tempfile.gettempdir()) / "blender_ai_assistant" / f"{uuid.uuid4().hex}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.camera = camera
    scene.render.resolution_x = int(operation.payload["width"])
    scene.render.resolution_y = int(operation.payload["height"])
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True)
        image = cast(Any, bpy.data).images.load(str(path), check_existing=False)
        image.name = str(operation.payload["preview_name"])
        image["ai_preview_kind"] = "render"
        image["ai_render_preview_mode"] = str(operation.payload["mode"])
        if bool(operation.payload["pack"]):
            image.pack()
    except Exception:
        _restore_render_settings(scene, old_values)
        raise
    finally:
        path.unlink(missing_ok=True)
    _restore_render_settings(scene, old_values)
    transaction.add_rollback(partial(_remove_created_image, image))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = image
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "image",
            image.name,
            ChangeKind.CREATED,
            "Created render preview image",
        )
    )


def _ensure_editable_mesh(item: Any) -> None:
    if getattr(item, "library", None) is not None:
        raise ExecutionError(f"Linked object {item.name!r} cannot be modified.")
    if getattr(item, "type", "") != "MESH":
        raise ExecutionError(f"Object {item.name!r} is not a mesh.")
    _ensure_mesh_size_within_limits(item)


def _ensure_mesh_size_within_limits(item: Any) -> None:
    mesh = item.data
    if len(mesh.vertices) > MESH_PROCESSING_LIMITS["generated_mesh_max_vertices"]:
        raise ExecutionError(f"Object {item.name!r} exceeds generated mesh vertex limits.")
    if len(mesh.polygons) > MESH_PROCESSING_LIMITS["generated_mesh_max_polygons"]:
        raise ExecutionError(f"Object {item.name!r} exceeds generated mesh polygon limits.")


def _copy_mesh_object(context: Any, item: Any, name: str) -> Any:
    import bpy

    _ensure_editable_mesh(item)
    if cast(Any, bpy.data).objects.get(name) is not None:
        raise ExecutionError(f"An object named {name!r} already exists.")
    mesh = item.data.copy()
    copy = item.copy()
    copy.name = name
    copy.data = mesh
    copy.animation_data_clear()
    for collection in tuple(item.users_collection) or (_default_collection(context),):
        collection.objects.link(copy)
    copy.matrix_world = item.matrix_world.copy()
    return copy


def _register_created_object(
    operation: Operation,
    item: Any,
    results: dict[str, Any],
    transaction: _Transaction,
    detail: str,
) -> None:
    transaction.add_rollback(partial(_remove_created_object, item, item.data))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = item
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "object",
            item.name,
            ChangeKind.CREATED,
            detail,
        )
    )


def _restore_custom_property(item: Any, key: str, old_value: Any) -> None:
    if old_value is None:
        with suppress(Exception):
            del item[key]
    else:
        item[key] = old_value


def _restore_geometry_nodes_modifier(
    item: Any,
    name: str,
    values: Mapping[str, Any],
) -> None:
    modifier = item.modifiers.new(name, "NODES")
    for key, value in values.items():
        modifier[key] = value


def _restore_replacement_visibility(
    original: Any,
    generated: Any,
    original_values: tuple[bool, bool],
    generated_values: tuple[bool, bool],
) -> None:
    original.hide_viewport, original.hide_render = original_values
    generated.hide_viewport, generated.hide_render = generated_values


def _store_sculpt_region(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    item: Any,
    source_name: str,
    indices: tuple[int, ...],
) -> None:
    if not indices:
        raise ExecutionError("Sculpt region cannot be empty.")
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = _SculptRegion(
        str(operation.payload["region_name"]),
        item,
        tuple(indices),
    )
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "sculpt_region",
            str(operation.payload["region_name"]),
            ChangeKind.CREATED,
            f"Created sculpt region from {source_name}",
        )
    )


def _runtime_sculpt_region(region_id: str, results: Mapping[str, Any]) -> _SculptRegion:
    if not region_id.startswith(RESULT_REFERENCE_PREFIX):
        raise ExecutionError("Sculpt region references must use result:<operation_id>.")
    region = results.get(region_id)
    if not isinstance(region, _SculptRegion):
        raise ExecutionError(f"Sculpt region result {region_id} is unavailable.")
    return region


def _remove_vertex_group(item: Any, group_name: str) -> None:
    group = item.vertex_groups.get(group_name)
    if group is not None:
        item.vertex_groups.remove(group)


def _require_vertex_group(item: Any, group_name: str) -> Any:
    group = item.vertex_groups.get(group_name)
    if group is None:
        raise ExecutionError(f"Object {item.name!r} has no sculpt mask {group_name!r}.")
    return group


def _vertex_group_weights(item: Any, group: Any) -> dict[int, float]:
    weights: dict[int, float] = {}
    for vertex in item.data.vertices:
        index = int(vertex.index)
        try:
            weights[index] = _clamp01(float(group.weight(index)))
        except RuntimeError:
            weights[index] = 0.0
    return weights


def _restore_vertex_group_weights(
    item: Any,
    group_name: str,
    weights: Mapping[int, float],
) -> None:
    group = item.vertex_groups.get(group_name)
    if group is None:
        group = item.vertex_groups.new(name=group_name)
    _set_vertex_group_weights(item, group, weights)


def _set_vertex_group_weights(
    item: Any,
    group: Any,
    weights: Mapping[int, float],
) -> None:
    indices = tuple(sorted(int(index) for index in weights))
    if indices:
        with suppress(RuntimeError, TypeError, ValueError):
            group.remove(indices)
    for index in indices:
        weight = _clamp01(float(weights[index]))
        if weight > 0.0:
            group.add((index,), weight, "REPLACE")
    item.data.update()


def _edited_sculpt_mask_weights(
    item: Any,
    operation_type: OperationType,
    weights: Mapping[int, float],
    strength: float,
    iterations: int,
) -> dict[int, float]:
    strength = _clamp01(strength)
    if operation_type is OperationType.INVERT_SCULPT_MASK:
        return {
            index: _clamp01(value + ((1.0 - value) - value) * strength)
            for index, value in weights.items()
        }
    if operation_type is OperationType.CLEAR_SCULPT_MASK:
        return {
            index: _clamp01(value * (1.0 - strength))
            for index, value in weights.items()
        }
    if operation_type is OperationType.BLUR_SCULPT_MASK:
        return _blur_sculpt_mask_weights(item, weights, strength, iterations)
    if operation_type is OperationType.SHARPEN_SCULPT_MASK:
        return _sharpen_sculpt_mask_weights(weights, strength, iterations)
    if operation_type is OperationType.GROW_SCULPT_MASK:
        return _spread_sculpt_mask_weights(item, weights, strength, iterations, grow=True)
    if operation_type is OperationType.SHRINK_SCULPT_MASK:
        return _spread_sculpt_mask_weights(item, weights, strength, iterations, grow=False)
    raise ExecutionError(f"Unsupported sculpt mask operation: {operation_type.value}.")


def _blur_sculpt_mask_weights(
    item: Any,
    weights: Mapping[int, float],
    strength: float,
    iterations: int,
) -> dict[int, float]:
    adjacency = _mesh_adjacency(item)
    current = {index: _clamp01(value) for index, value in weights.items()}
    for _iteration in range(iterations):
        updated: dict[int, float] = {}
        for index, value in current.items():
            neighbors = adjacency.get(index, set())
            if neighbors:
                average = (value + sum(current.get(neighbor, 0.0) for neighbor in neighbors)) / (
                    len(neighbors) + 1
                )
            else:
                average = value
            updated[index] = _clamp01(value + (average - value) * strength)
        current = updated
    return current


def _sharpen_sculpt_mask_weights(
    weights: Mapping[int, float],
    strength: float,
    iterations: int,
) -> dict[int, float]:
    current = {index: _clamp01(value) for index, value in weights.items()}
    for _iteration in range(iterations):
        current = {
            index: _clamp01(
                value + (1.0 - value) * strength
                if value >= 0.5
                else value * (1.0 - strength)
            )
            for index, value in current.items()
        }
    return current


def _spread_sculpt_mask_weights(
    item: Any,
    weights: Mapping[int, float],
    strength: float,
    iterations: int,
    *,
    grow: bool,
) -> dict[int, float]:
    adjacency = _mesh_adjacency(item)
    current = {index: _clamp01(value) for index, value in weights.items()}
    for _iteration in range(iterations):
        updated: dict[int, float] = {}
        for index, value in current.items():
            candidates = [
                value,
                *(current.get(neighbor, 0.0) for neighbor in adjacency.get(index, set())),
            ]
            target = max(candidates) if grow else min(candidates)
            updated[index] = _clamp01(value + (target - value) * strength)
        current = updated
    return current


def _combined_sculpt_mask_weights(
    source: Mapping[int, float],
    target: Mapping[int, float],
    combine_mode: str,
) -> dict[int, float]:
    indices = set(source) | set(target)
    if combine_mode == "replace":
        return {index: _clamp01(source.get(index, 0.0)) for index in indices}
    if combine_mode == "add":
        return {
            index: _clamp01(target.get(index, 0.0) + source.get(index, 0.0))
            for index in indices
        }
    if combine_mode == "subtract":
        return {
            index: _clamp01(target.get(index, 0.0) - source.get(index, 0.0))
            for index in indices
        }
    if combine_mode == "intersect":
        return {
            index: _clamp01(min(target.get(index, 0.0), source.get(index, 0.0)))
            for index in indices
        }
    raise ExecutionError(f"Unsupported sculpt mask combine mode: {combine_mode}.")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _average_vertex_normal(item: Any, vertex_indices: tuple[int, ...]) -> Any:
    from mathutils import Vector

    normal = Vector((0.0, 0.0, 0.0))
    for index in vertex_indices:
        normal += item.data.vertices[index].normal
    if normal.length < 1e-9:
        return Vector((0.0, 0.0, 1.0))
    normal.normalize()
    return normal


def _remove_shape_key(item: Any, key_name: str) -> None:
    key = item.data.shape_keys.key_blocks.get(key_name) if item.data.shape_keys else None
    if key is not None:
        item.shape_key_remove(key)


def _set_shape_key_block_value(key: Any, value: float) -> None:
    key.value = value


def _object_has_rig_dependency(item: Any) -> bool:
    if getattr(getattr(item, "parent", None), "type", "") == "ARMATURE":
        return True
    return any(str(modifier.type) == "ARMATURE" for modifier in item.modifiers)


def _remove_node_groups(groups: tuple[Any, ...]) -> None:
    import bpy

    node_groups: Any = cast(Any, bpy.data).node_groups
    for group in groups:
        current = node_groups.get(group.name)
        if current == group:
            node_groups.remove(group)


def _face_indices_from_material(item: Any, material: Any) -> tuple[int, ...]:
    _ensure_editable_mesh(item)
    material_indices = {
        index
        for index, slot_material in enumerate(item.data.materials)
        if slot_material == material
    }
    indices = tuple(
        int(polygon.index)
        for polygon in item.data.polygons
        if int(polygon.material_index) in material_indices
    )
    if not indices:
        raise ExecutionError(
            f"Object {item.name!r} has no faces using material {material.name!r}."
        )
    return indices


def _face_indices_from_vertex_group(item: Any, group_name: str) -> tuple[int, ...]:
    _ensure_editable_mesh(item)
    group = item.vertex_groups.get(group_name)
    if group is None:
        raise ExecutionError(f"Object {item.name!r} has no vertex group {group_name!r}.")
    weighted_vertices = {
        int(vertex.index)
        for vertex in item.data.vertices
        for membership in vertex.groups
        if int(membership.group) == int(group.index) and float(membership.weight) > 0.0
    }
    indices = tuple(
        int(polygon.index)
        for polygon in item.data.polygons
        if any(int(vertex_index) in weighted_vertices for vertex_index in polygon.vertices)
    )
    if not indices:
        raise ExecutionError(f"Vertex group {group_name!r} does not cover any faces.")
    return indices


def _create_face_set_attribute(
    operation: Operation,
    results: dict[str, Any],
    transaction: _Transaction,
    item: Any,
    name: str,
    face_indices: tuple[int, ...],
) -> None:
    attributes = item.data.attributes
    if attributes.get(name) is not None:
        raise ExecutionError(f"Object {item.name!r} already has a face set {name!r}.")
    attribute = attributes.new(name=name, type="INT", domain="FACE")
    face_set = set(face_indices)
    for index, value in enumerate(attribute.data):
        value.value = 1 if index in face_set else 0
    transaction.add_rollback(partial(_remove_mesh_attribute, item, name))
    reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
    results[reference] = attribute
    transaction.record(
        ChangeRecord(
            operation.operation_id,
            reference,
            "face_set",
            name,
            ChangeKind.CREATED,
            f"Created face set with {len(face_indices)} faces",
        )
    )


def _remove_mesh_attribute(item: Any, name: str) -> None:
    attribute = item.data.attributes.get(name)
    if attribute is not None:
        item.data.attributes.remove(attribute)


def _restore_render_settings(scene: Any, values: tuple[Any, int, int, int, str]) -> None:
    camera, resolution_x, resolution_y, resolution_percentage, filepath = values
    scene.camera = camera
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = resolution_percentage
    scene.render.filepath = filepath


def _build_torus(mesh: Any) -> None:
    major_segments = 32
    minor_segments = 12
    major_radius = 1.0
    minor_radius = 0.25
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for major_index in range(major_segments):
        major_angle = math.tau * major_index / major_segments
        for minor_index in range(minor_segments):
            minor_angle = math.tau * minor_index / minor_segments
            radial = major_radius + minor_radius * math.cos(minor_angle)
            vertices.append(
                (
                    radial * math.cos(major_angle),
                    radial * math.sin(major_angle),
                    minor_radius * math.sin(minor_angle),
                )
            )
    for major_index in range(major_segments):
        next_major = (major_index + 1) % major_segments
        for minor_index in range(minor_segments):
            next_minor = (minor_index + 1) % minor_segments
            faces.append(
                (
                    major_index * minor_segments + minor_index,
                    next_major * minor_segments + minor_index,
                    next_major * minor_segments + next_minor,
                    major_index * minor_segments + next_minor,
                )
            )
    mesh.from_pydata(vertices, (), faces)
    mesh.update()


def _ensure_main_thread() -> None:
    if threading.current_thread() is not threading.main_thread():
        raise ExecutionPreflightError("Blender plans must execute on the main thread.")
