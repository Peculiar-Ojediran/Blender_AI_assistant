"""Preflight and execute approved plans on Blender's main thread."""

import math
import tempfile
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import unquote, urlparse

from ..context import SceneContextSnapshot, TargetKind
from .models import Operation, OperationPlan, OperationType, PlanStatus
from .targets import RESULT_REFERENCE_PREFIX, resolve_plan_targets

type ProgressCallback = Callable[[int, int], None]

MAX_URL_IMPORT_BYTES = 50 * 1024 * 1024
URL_IMPORT_TIMEOUT_SECONDS = 60.0


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

    def _set_modifier_properties(self, operation: Operation) -> None:
        for target_id in operation.target_ids:
            target = self._target(target_id, TargetKind.OBJECT)
            self._editable_object(target)
            if target.live is not None and getattr(target.live, "type", "") != "MESH":
                raise ExecutionPreflightError(f"Object target {target_id} is not a mesh.")
            modifier_name = str(operation.payload["modifier_name"])
            if target.live is not None and target.live.modifiers.get(modifier_name) is None:
                raise ExecutionPreflightError(
                    f"Object {target.live.name!r} has no modifier named {modifier_name!r}."
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


def _restore_object_visibility(item: Any, values: tuple[bool, bool]) -> None:
    hide_viewport, hide_render = values
    item.hide_viewport = hide_viewport
    item.hide_render = hide_render


def _remove_created_collection(collection: Any) -> None:
    import bpy

    current = cast(Any, bpy.data).collections.get(collection.name)
    if current == collection:
        for parent in tuple(collection.users_scene):
            parent.collection.children.unlink(collection)
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
