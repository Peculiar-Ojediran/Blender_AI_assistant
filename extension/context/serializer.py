"""Serialize scene records into a provider-safe JSON-compatible payload."""

import json
from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType

from .errors import ContextBudgetError
from .models import (
    CollectionContext,
    JsonValue,
    MaterialContext,
    ObjectContext,
    ObjectSummary,
    SceneContext,
    SceneContextSnapshot,
    SerializedSceneContext,
)


def serialize_scene_context(snapshot: SceneContextSnapshot) -> SerializedSceneContext:
    context = snapshot.context
    payload: dict[str, JsonValue] = {
        "snapshot_id": snapshot.snapshot_id,
        "schema_version": context.schema_version,
        "character_budget": context.character_budget,
        "blender_version": context.blender_version,
        "scene": {
            "name": context.scene_name,
            "file_path": context.file_path,
            "unit_system": context.unit_system,
            "unit_scale": context.unit_scale,
            "total_object_count": context.total_scene_objects,
        },
        "scope": context.scope.value,
        "active_object_id": context.active_object_id,
        "active_collection_id": context.active_collection_id,
        "scoped_object_count": context.scoped_object_count,
        "object_summaries": [_serialize_object_summary(item) for item in context.object_summaries],
        "detailed_objects": [_serialize_object(item) for item in context.detailed_objects],
        "materials": [_serialize_material(item) for item in context.materials],
        "collections": [_serialize_collection(item) for item in context.collections],
        "omissions": {
            "object_summaries": context.omissions.object_summaries,
            "object_details": context.omissions.object_details,
            "materials": context.omissions.materials,
            "collections": context.omissions.collections,
            "custom_properties": context.omissions.custom_properties,
            "file_paths": context.omissions.file_paths,
            "viewport_images": context.omissions.viewport_images,
        },
        "privacy": {
            "custom_properties_included": context.include_custom_properties,
            "file_paths_included": context.include_file_paths,
            "viewport_image_included": context.include_viewport_image,
        },
        "warnings": list(context.warnings),
    }
    json_text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return SerializedSceneContext(payload, json_text, len(json_text))


def fit_scene_context_to_budget(
    snapshot: SceneContextSnapshot,
    max_characters: int,
) -> SceneContextSnapshot:
    """Deterministically reduce a snapshot until its provider payload fits."""

    if max_characters < 1_024:
        raise ContextBudgetError("The serialized context budget must be at least 1024 characters.")
    if serialize_scene_context(snapshot).character_count <= max_characters:
        return snapshot

    context = snapshot.context
    stripped_property_count = sum(
        len(item.custom_properties) for item in context.detailed_objects
    ) + sum(
        len(item.custom_properties) for item in context.materials
    )
    if stripped_property_count:
        context = replace(
            context,
            detailed_objects=tuple(
                replace(item, custom_properties=MappingProxyType({}))
                for item in context.detailed_objects
            ),
            materials=tuple(
                replace(item, custom_properties=MappingProxyType({}))
                for item in context.materials
            ),
            omissions=replace(
                context.omissions,
                custom_properties=(
                    context.omissions.custom_properties + stripped_property_count
                ),
            ),
        )
        snapshot = _normalize_snapshot(snapshot, context)

    reducers: tuple[Callable[[SceneContext], SceneContext | None], ...] = (
        _remove_last_collection,
        _remove_last_material,
        _remove_last_detail,
        _remove_last_summary,
    )
    for reducer in reducers:
        while serialize_scene_context(snapshot).character_count > max_characters:
            reduced_context = reducer(snapshot.context)
            if reduced_context is None:
                break
            snapshot = _normalize_snapshot(snapshot, reduced_context)

    if serialize_scene_context(snapshot).character_count > max_characters:
        raise ContextBudgetError(
            "Minimal scene metadata exceeds the configured serialized context budget."
        )

    warning = "Context was reduced to fit the serialized character budget."
    if warning not in snapshot.context.warnings:
        context = replace(snapshot.context, warnings=(*snapshot.context.warnings, warning))
        snapshot = _normalize_snapshot(snapshot, context)
        if serialize_scene_context(snapshot).character_count > max_characters:
            context = replace(
                snapshot.context,
                warnings=tuple(item for item in snapshot.context.warnings if item != warning),
            )
            snapshot = _normalize_snapshot(snapshot, context)
    return snapshot


def _remove_last_collection(context: SceneContext) -> SceneContext | None:
    if not context.collections:
        return None
    return replace(
        context,
        collections=context.collections[:-1],
        omissions=replace(
            context.omissions,
            collections=context.omissions.collections + 1,
        ),
    )


def _remove_last_material(context: SceneContext) -> SceneContext | None:
    if not context.materials:
        return None
    return replace(
        context,
        materials=context.materials[:-1],
        omissions=replace(
            context.omissions,
            materials=context.omissions.materials + 1,
        ),
    )


def _remove_last_detail(context: SceneContext) -> SceneContext | None:
    if not context.detailed_objects:
        return None
    return replace(
        context,
        detailed_objects=context.detailed_objects[:-1],
        omissions=replace(
            context.omissions,
            object_details=context.omissions.object_details + 1,
        ),
    )


def _remove_last_summary(context: SceneContext) -> SceneContext | None:
    if not context.object_summaries:
        return None
    removed_id = context.object_summaries[-1].target_id
    removed_details = sum(
        item.target_id == removed_id for item in context.detailed_objects
    )
    return replace(
        context,
        object_summaries=context.object_summaries[:-1],
        detailed_objects=tuple(
            item for item in context.detailed_objects if item.target_id != removed_id
        ),
        omissions=replace(
            context.omissions,
            object_summaries=context.omissions.object_summaries + 1,
            object_details=context.omissions.object_details + removed_details,
        ),
    )


def _normalize_snapshot(
    snapshot: SceneContextSnapshot,
    context: SceneContext,
) -> SceneContextSnapshot:
    object_ids = {item.target_id for item in context.object_summaries}
    material_ids = {item.target_id for item in context.materials}
    collection_ids = {item.target_id for item in context.collections}

    detailed_objects = tuple(
        replace(
            item,
            parent_id=item.parent_id if item.parent_id in object_ids else None,
            material_ids=tuple(value for value in item.material_ids if value in material_ids),
            collection_ids=tuple(value for value in item.collection_ids if value in collection_ids),
        )
        for item in context.detailed_objects
        if item.target_id in object_ids
    )
    collections = tuple(
        replace(
            item,
            parent_id=item.parent_id if item.parent_id in collection_ids else None,
            object_ids=tuple(value for value in item.object_ids if value in object_ids),
        )
        for item in context.collections
    )
    context = replace(
        context,
        active_object_id=(
            context.active_object_id if context.active_object_id in object_ids else None
        ),
        active_collection_id=(
            context.active_collection_id
            if context.active_collection_id in collection_ids
            else None
        ),
        detailed_objects=detailed_objects,
        collections=collections,
    )
    retained_ids = object_ids | material_ids | collection_ids
    target_index = MappingProxyType(
        {
            target_id: reference
            for target_id, reference in snapshot.target_index.items()
            if target_id in retained_ids
        }
    )
    return SceneContextSnapshot(snapshot.snapshot_id, context, target_index)


def _serialize_object_summary(item: ObjectSummary) -> dict[str, JsonValue]:
    return {
        "id": item.target_id,
        "name": item.name,
        "type": item.object_type,
        "selected": item.selected,
        "active": item.active,
    }


def _serialize_object(item: ObjectContext) -> dict[str, JsonValue]:
    return {
        "id": item.target_id,
        "name": item.name,
        "type": item.object_type,
        "selected": item.selected,
        "active": item.active,
        "collection_ids": list(item.collection_ids),
        "parent_id": item.parent_id,
        "transform": {
            "location": list(item.location),
            "rotation_euler": list(item.rotation_euler),
            "scale": list(item.scale),
            "dimensions": list(item.dimensions),
        },
        "material_ids": list(item.material_ids),
        "modifiers": list(item.modifiers),
        "custom_properties": dict(item.custom_properties),
        "data": dict(item.data),
    }


def _serialize_material(item: MaterialContext) -> dict[str, JsonValue]:
    return {
        "id": item.target_id,
        "name": item.name,
        "use_nodes": item.use_nodes,
        "diffuse_color": list(item.diffuse_color),
        "metallic": item.metallic,
        "roughness": item.roughness,
        "custom_properties": dict(item.custom_properties),
    }


def _serialize_collection(item: CollectionContext) -> dict[str, JsonValue]:
    return {
        "id": item.target_id,
        "name": item.name,
        "parent_id": item.parent_id,
        "object_ids": list(item.object_ids),
    }
