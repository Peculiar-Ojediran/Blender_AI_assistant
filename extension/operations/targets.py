"""Resolve snapshot references against unchanged Blender datablocks."""

import threading
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, cast

from ..context.identity import target_state_fingerprint
from ..context.models import SceneContextSnapshot, TargetKind, TargetReference
from .models import Operation, OperationPlan

RESULT_REFERENCE_PREFIX = "result:"


class TargetResolutionError(ValueError):
    """Raised when a plan target is missing, stale, or the wrong kind."""


def validate_plan_target_references(
    plan: OperationPlan,
    snapshot: SceneContextSnapshot,
) -> None:
    """Validate context-issued references without accessing Blender runtime data."""

    if plan.snapshot_id != snapshot.snapshot_id:
        raise TargetResolutionError("The plan does not match the retained scene snapshot.")

    for target_id, expected_kind in _plan_references(plan):
        if target_id.startswith(RESULT_REFERENCE_PREFIX):
            continue
        reference = snapshot.target_index.get(target_id)
        if reference is None:
            raise TargetResolutionError(f"Unknown snapshot target: {target_id}.")
        if reference.kind is not expected_kind:
            raise TargetResolutionError(
                f"Target {target_id} is {reference.kind.value}, not {expected_kind.value}."
            )


def resolve_plan_targets(
    plan: OperationPlan,
    snapshot: SceneContextSnapshot,
) -> Mapping[str, Any]:
    """Revalidate every existing plan target against the live Blender scene."""

    validate_plan_target_references(plan, snapshot)
    grouped: dict[TargetKind, list[str]] = {kind: [] for kind in TargetKind}
    for target_id, expected_kind in _plan_references(plan):
        if not target_id.startswith(RESULT_REFERENCE_PREFIX):
            grouped[expected_kind].append(target_id)

    resolved: dict[str, Any] = {}
    for kind, target_ids in grouped.items():
        resolved.update(
            resolve_snapshot_targets(snapshot, target_ids, expected_kind=kind)
        )
    return MappingProxyType(resolved)


def resolve_snapshot_targets(
    snapshot: SceneContextSnapshot,
    target_ids: Iterable[str],
    *,
    expected_kind: TargetKind,
) -> Mapping[str, Any]:
    """Resolve targets only when identity and planning-time state still match."""

    if threading.current_thread() is not threading.main_thread():
        raise TargetResolutionError("Blender targets must be resolved on the main thread.")

    resolved: dict[str, Any] = {}
    for target_id in dict.fromkeys(target_ids):
        reference = snapshot.target_index.get(target_id)
        if reference is None:
            raise TargetResolutionError(f"Unknown snapshot target: {target_id}.")
        if reference.kind is not expected_kind:
            raise TargetResolutionError(
                f"Target {target_id} is {reference.kind.value}, not {expected_kind.value}."
            )

        datablock = _find_datablock(snapshot, reference)
        if datablock is None:
            raise TargetResolutionError(f"Target {target_id} no longer exists.")
        if int(datablock.session_uid) != reference.session_uid:
            raise TargetResolutionError(f"Target {target_id} was replaced after planning.")
        if target_state_fingerprint(datablock, reference.kind) != reference.state_fingerprint:
            raise TargetResolutionError(f"Target {target_id} changed after planning.")
        resolved[target_id] = datablock

    return MappingProxyType(resolved)


def _find_datablock(
    snapshot: SceneContextSnapshot,
    reference: TargetReference,
) -> Any | None:
    import bpy

    data: Any = cast(Any, bpy.data)
    if reference.kind is TargetKind.OBJECT:
        return data.objects.get(reference.datablock_name)
    if reference.kind is TargetKind.MATERIAL:
        return data.materials.get(reference.datablock_name)
    collection = data.collections.get(reference.datablock_name)
    if collection is not None:
        return collection
    scene = data.scenes.get(snapshot.context.scene_name)
    if scene is not None and scene.collection.name == reference.datablock_name:
        return scene.collection
    return None


def _plan_references(plan: OperationPlan) -> tuple[tuple[str, TargetKind], ...]:
    references: list[tuple[str, TargetKind]] = []
    for operation in plan.operations:
        references.extend(_operation_references(operation))
    return tuple(references)


def _operation_references(operation: Operation) -> tuple[tuple[str, TargetKind], ...]:
    references = [(target_id, TargetKind.OBJECT) for target_id in operation.target_ids]

    target_id = operation.payload.get("target_id")
    if isinstance(target_id, str):
        references.append((target_id, TargetKind.OBJECT))

    cutter_id = operation.payload.get("cutter_id")
    if isinstance(cutter_id, str):
        references.append((cutter_id, TargetKind.OBJECT))

    material_id = operation.payload.get("material_id")
    if isinstance(material_id, str):
        references.append((material_id, TargetKind.MATERIAL))

    collection_id = operation.payload.get("collection_id")
    if isinstance(collection_id, str):
        references.append((collection_id, TargetKind.COLLECTION))

    parent_collection_id = operation.payload.get("parent_collection_id")
    if isinstance(parent_collection_id, str):
        references.append((parent_collection_id, TargetKind.COLLECTION))

    return tuple(references)
