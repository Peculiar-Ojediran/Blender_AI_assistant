"""Preflight and execute approved plans on Blender's main thread."""

import math
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from types import MappingProxyType
from typing import Any, cast

from ..context import SceneContextSnapshot, TargetKind
from .models import Operation, OperationPlan, OperationType, PlanStatus
from .targets import RESULT_REFERENCE_PREFIX, resolve_plan_targets

type ProgressCallback = Callable[[int, int], None]


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


@dataclass(frozen=True, slots=True)
class _StagedDeletion:
    operation_id: str
    target_id: str
    item: Any
    original_name: str


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
        self.light_data_names = {item.name for item in data.lights}
        self.camera_data_names = {item.name for item in data.cameras}
        self.duplicate_names: dict[str, tuple[str, ...]] = {}
        self.scene_collections = set(_scene_collections(context.scene.collection))

    def apply(self, operation: Operation) -> None:
        handlers: dict[OperationType, Callable[[Operation], None]] = {
            OperationType.CREATE_PRIMITIVE: self._create_primitive,
            OperationType.DELETE_OBJECTS: self._delete_objects,
            OperationType.DUPLICATE_OBJECTS: self._duplicate_objects,
            OperationType.SET_TRANSFORM: self._set_transform,
            OperationType.CREATE_MATERIAL: self._create_material,
            OperationType.ASSIGN_MATERIAL: self._assign_material,
            OperationType.ADD_LIGHT: self._add_light,
            OperationType.ADD_CAMERA: self._add_camera,
            OperationType.RENAME_OBJECTS: self._rename_objects,
            OperationType.MOVE_TO_COLLECTION: self._move_to_collection,
        }
        handlers[operation.type](operation)

    def _create_primitive(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        self._create_object_result(
            operation,
            str(operation.payload["name"]),
            supports_materials=True,
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
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.material_names, name, reference)
        self.results[reference] = _SimTarget(TargetKind.MATERIAL, reference, name, None)

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
        self._create_object_result(operation, name)

    def _add_camera(self, operation: Operation) -> None:
        self._collection(operation.payload.get("collection_id"))
        name = str(operation.payload["name"])
        if name in self.camera_data_names:
            raise ExecutionPreflightError(f"A camera datablock named {name!r} already exists.")
        self.camera_data_names.add(name)
        self._create_object_result(operation, name)

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

    def _create_object_result(
        self,
        operation: Operation,
        name: str,
        *,
        supports_materials: bool = False,
    ) -> None:
        reference = f"{RESULT_REFERENCE_PREFIX}{operation.operation_id}"
        self._reserve_name(self.object_names, name, reference)
        self.results[reference] = _SimTarget(
            TargetKind.OBJECT,
            reference,
            name,
            None,
            supports_materials,
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
        else:
            collection = self._target(str(target_id), TargetKind.COLLECTION).live
        if collection not in self.scene_collections:
            raise ExecutionPreflightError("The destination collection is not in the active scene.")
        if getattr(collection, "library", None) is not None:
            raise ExecutionPreflightError("Linked collections cannot be modified.")
        return collection

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
            context, operation.payload.get("collection_id"), prepared
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
        original_name = item.name
        temporary_name = _temporary_object_name(operation.operation_id)
        item.name = temporary_name
        transaction.add_rollback(partial(_rename_exact, ((item, original_name),)))
        transaction.deletions.append(
            _StagedDeletion(operation.operation_id, target_id, item, original_name)
        )


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
            "Created Principled BSDF material",
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
            context, payload.get("collection_id"), prepared
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
            context, payload.get("collection_id"), prepared
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
) -> Any:
    if target_id is None:
        return _default_collection(context)
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


def _restore_collections(item: Any, collections: tuple[Any, ...]) -> None:
    for collection in collections:
        if collection not in item.users_collection:
            collection.objects.link(item)
    for collection in tuple(item.users_collection):
        if collection not in collections:
            collection.objects.unlink(item)


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


def _remove_orphan_datablock(data: Any) -> None:
    import bpy

    if data.users == 0:
        bpy.data.batch_remove(ids=(data,))


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
