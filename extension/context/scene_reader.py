"""Read a privacy-filtered context snapshot from Blender's main thread."""

import threading
import uuid
from collections.abc import Iterable
from types import MappingProxyType
from typing import Any, cast

import bpy

from .budget import apply_object_budget
from .errors import ContextThreadError
from .identity import target_state_fingerprint
from .models import (
    CollectionContext,
    ContextOptions,
    ContextScope,
    JsonValue,
    MaterialContext,
    ObjectContext,
    ObjectSummary,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
    TargetKind,
    TargetReference,
)
from .privacy import PrivacyStats, sanitize_custom_properties
from .serializer import fit_scene_context_to_budget

CONTEXT_SCHEMA_VERSION = 1


def read_scene_context(context: Any, options: ContextOptions) -> SceneContextSnapshot:
    _ensure_main_thread()
    scene = context.scene
    all_objects = sorted(scene.objects, key=lambda item: item.name.casefold())
    object_ids = {item.name: f"obj_{index:04d}" for index, item in enumerate(all_objects, 1)}

    all_materials = sorted(
        list(cast(Iterable[Any], bpy.data.materials)),
        key=lambda item: item.name.casefold(),
    )
    material_ids = {
        item.name: f"mat_{index:04d}" for index, item in enumerate(all_materials, 1)
    }

    all_collections, collection_parents = _scene_collections(scene.collection)
    collection_ids = {
        item.name: f"col_{index:04d}" for index, item in enumerate(all_collections, 1)
    }

    active_object = context.view_layer.objects.active
    active_object_id = object_ids.get(active_object.name) if active_object is not None else None
    selected_names = {item.name for item in context.selected_objects}
    selected_ids = frozenset(
        object_ids[name] for name in selected_names if name in object_ids
    )

    active_collection = _active_collection(context)
    active_collection_id = (
        collection_ids.get(active_collection.name) if active_collection is not None else None
    )
    scoped_objects = _scoped_objects(context, options.scope, active_collection)
    scoped_ids = tuple(object_ids[item.name] for item in scoped_objects if item.name in object_ids)
    object_by_id = {object_ids[item.name]: item for item in all_objects}

    budget = apply_object_budget(
        scoped_ids,
        active_id=active_object_id,
        selected_ids=selected_ids,
        detailed_limit=options.detailed_object_budget,
        summary_limit=options.summary_object_budget,
    )
    summary_objects = tuple(object_by_id[target_id] for target_id in budget.summary_ids)
    detailed_objects = tuple(object_by_id[target_id] for target_id in budget.detailed_ids)

    included_materials = _relevant_materials(
        all_materials,
        detailed_objects,
        options.material_budget,
    )
    included_material_names = {item.name for item in included_materials}
    included_collections = _prioritized_collections(
        all_collections,
        collection_parents,
        active_collection,
        summary_objects,
        options.scope,
        options.collection_budget,
    )
    included_collection_names = {item.name for item in included_collections}
    included_object_ids = set(budget.summary_ids)

    privacy_totals = PrivacyStats()
    object_details: list[ObjectContext] = []
    for item in detailed_objects:
        custom_properties, stats = _custom_properties(item, options)
        privacy_totals = _add_privacy_stats(privacy_totals, stats)
        object_details.append(
            _object_context(
                item,
                object_ids=object_ids,
                material_ids=material_ids,
                collection_ids=collection_ids,
                included_material_names=included_material_names,
                included_collection_names=included_collection_names,
                included_object_ids=included_object_ids,
                selected_names=selected_names,
                active_object=active_object,
                custom_properties=custom_properties,
            )
        )

    material_contexts: list[MaterialContext] = []
    for material in included_materials:
        custom_properties, stats = _custom_properties(material, options)
        privacy_totals = _add_privacy_stats(privacy_totals, stats)
        material_contexts.append(
            MaterialContext(
                target_id=material_ids[material.name],
                name=material.name,
                use_nodes=bool(material.use_nodes),
                diffuse_color=_float4(material.diffuse_color),
                metallic=float(getattr(material, "metallic", 0.0)),
                roughness=float(getattr(material, "roughness", 0.5)),
                custom_properties=MappingProxyType(custom_properties),
            )
        )

    collection_contexts = tuple(
        _collection_context(
            item,
            collection_ids=collection_ids,
            collection_parents=collection_parents,
            object_ids=object_ids,
            included_object_ids=included_object_ids,
            included_collection_names=included_collection_names,
        )
        for item in included_collections
    )

    warnings: list[str] = []
    if options.scope is ContextScope.SELECTION and not scoped_objects:
        warnings.append("No selected objects were available for detailed context.")
    if budget.omitted_summaries or budget.omitted_details:
        warnings.append("Object context was reduced to fit the configured budget.")
    if options.include_viewport_image:
        warnings.append("Viewport image context is not implemented and was omitted.")

    file_path = bpy.data.filepath or None
    file_paths_omitted = privacy_totals.file_paths_omitted
    if file_path and not options.include_file_paths:
        file_paths_omitted += 1
        file_path = None

    omissions = OmissionReport(
        object_summaries=budget.omitted_summaries,
        object_details=budget.omitted_details,
        materials=max(0, len(all_materials) - len(included_materials)),
        collections=max(0, len(all_collections) - len(included_collections)),
        custom_properties=privacy_totals.custom_properties_omitted,
        file_paths=file_paths_omitted,
        viewport_images=1 if options.include_viewport_image else 0,
    )

    object_summaries = tuple(
        ObjectSummary(
            target_id=object_ids[item.name],
            name=item.name,
            object_type=item.type.lower(),
            selected=item.name in selected_names,
            active=item == active_object,
        )
        for item in summary_objects
    )
    target_index = _target_index(
        summary_objects,
        included_materials,
        included_collections,
        object_ids,
        material_ids,
        collection_ids,
    )

    scene_context = SceneContext(
        schema_version=CONTEXT_SCHEMA_VERSION,
        blender_version=bpy.app.version_string,
        scene_name=scene.name,
        file_path=file_path if options.include_file_paths else None,
        unit_system=scene.unit_settings.system,
        unit_scale=float(scene.unit_settings.scale_length),
        scope=options.scope,
        active_object_id=active_object_id if active_object_id in included_object_ids else None,
        active_collection_id=(
            active_collection_id
            if active_collection is not None
            and active_collection.name in included_collection_names
            else None
        ),
        total_scene_objects=len(all_objects),
        scoped_object_count=len(scoped_objects),
        object_summaries=object_summaries,
        detailed_objects=tuple(object_details),
        materials=tuple(material_contexts),
        collections=collection_contexts,
        omissions=omissions,
        warnings=tuple(warnings),
        include_custom_properties=options.include_custom_properties,
        include_file_paths=options.include_file_paths,
        include_viewport_image=False,
        character_budget=options.max_serialized_characters,
    )
    snapshot = SceneContextSnapshot(
        snapshot_id=uuid.uuid4().hex,
        context=scene_context,
        target_index=MappingProxyType(target_index),
    )
    return fit_scene_context_to_budget(snapshot, options.max_serialized_characters)


def _ensure_main_thread() -> None:
    if threading.current_thread() is not threading.main_thread():
        raise ContextThreadError("Blender scene context must be read on the main thread.")


def _scoped_objects(context: Any, scope: ContextScope, active_collection: Any) -> tuple[Any, ...]:
    if scope is ContextScope.SELECTION:
        source = context.selected_objects
    elif scope is ContextScope.COLLECTION:
        source = active_collection.all_objects if active_collection is not None else ()
    else:
        source = context.scene.objects
    return tuple(sorted(source, key=lambda item: item.name.casefold()))


def _active_collection(context: Any) -> Any | None:
    layer_collection = getattr(context.view_layer, "active_layer_collection", None)
    return getattr(layer_collection, "collection", None)


def _scene_collections(root: Any) -> tuple[tuple[Any, ...], dict[str, str | None]]:
    collections: list[Any] = []
    parents: dict[str, str | None] = {}

    def visit(collection: Any, parent_name: str | None) -> None:
        collections.append(collection)
        parents[collection.name] = parent_name
        for child in sorted(collection.children, key=lambda item: item.name.casefold()):
            visit(child, collection.name)

    visit(root, None)
    return tuple(sorted(collections, key=lambda item: item.name.casefold())), parents


def _relevant_materials(
    materials: list[Any],
    detailed_objects: tuple[Any, ...],
    limit: int,
) -> tuple[Any, ...]:
    used_names = {
        slot.material.name
        for item in detailed_objects
        for slot in item.material_slots
        if slot.material is not None
    }
    relevant = [item for item in materials if item.name in used_names]
    return tuple(relevant[:limit])


def _prioritized_collections(
    collections: tuple[Any, ...],
    collection_parents: dict[str, str | None],
    active_collection: Any,
    summary_objects: tuple[Any, ...],
    scope: ContextScope,
    limit: int,
) -> tuple[Any, ...]:
    used_names = {
        collection.name for item in summary_objects for collection in item.users_collection
    }
    active_name = active_collection.name if active_collection is not None else None
    relevant_names = set(used_names)
    if active_name is not None:
        relevant_names.add(active_name)

    for name in tuple(relevant_names):
        parent_name = collection_parents.get(name)
        while parent_name is not None:
            relevant_names.add(parent_name)
            parent_name = collection_parents.get(parent_name)

    candidates = (
        collections
        if scope is ContextScope.SCENE
        else tuple(item for item in collections if item.name in relevant_names)
    )
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.name != active_name,
            item.name not in used_names,
            item.name.casefold(),
        ),
    )
    return tuple(ordered[:limit])


def _custom_properties(
    datablock: Any,
    options: ContextOptions,
) -> tuple[dict[str, JsonValue], PrivacyStats]:
    properties = dict(datablock.items())
    if not options.include_custom_properties:
        omitted = len([key for key in properties if key != "_RNA_UI"])
        return {}, PrivacyStats(custom_properties_omitted=omitted)
    return sanitize_custom_properties(
        properties,
        include_file_paths=options.include_file_paths,
    )


def _add_privacy_stats(left: PrivacyStats, right: PrivacyStats) -> PrivacyStats:
    return PrivacyStats(
        left.custom_properties_omitted + right.custom_properties_omitted,
        left.file_paths_omitted + right.file_paths_omitted,
    )


def _object_context(
    item: Any,
    *,
    object_ids: dict[str, str],
    material_ids: dict[str, str],
    collection_ids: dict[str, str],
    included_material_names: set[str],
    included_collection_names: set[str],
    included_object_ids: set[str],
    selected_names: set[str],
    active_object: Any,
    custom_properties: dict[str, JsonValue],
) -> ObjectContext:
    return ObjectContext(
        target_id=object_ids[item.name],
        name=item.name,
        object_type=item.type.lower(),
        selected=item.name in selected_names,
        active=item == active_object,
        collection_ids=tuple(
            collection_ids[collection.name]
            for collection in item.users_collection
            if collection.name in included_collection_names
        ),
        parent_id=(
            object_ids.get(item.parent.name)
            if item.parent is not None
            and object_ids.get(item.parent.name) in included_object_ids
            else None
        ),
        location=_float3(item.location),
        rotation_euler=_float3(item.rotation_euler),
        scale=_float3(item.scale),
        dimensions=_float3(item.dimensions),
        material_ids=tuple(
            material_ids[slot.material.name]
            for slot in item.material_slots
            if slot.material is not None and slot.material.name in included_material_names
        ),
        modifiers=tuple(modifier.type.lower() for modifier in item.modifiers),
        custom_properties=MappingProxyType(custom_properties),
        data=MappingProxyType(_object_type_data(item)),
    )


def _object_type_data(item: Any) -> dict[str, JsonValue]:
    data = item.data
    if item.type == "MESH":
        return {
            "vertex_count": len(data.vertices),
            "edge_count": len(data.edges),
            "polygon_count": len(data.polygons),
        }
    if item.type == "LIGHT":
        return {
            "light_type": data.type.lower(),
            "energy": float(data.energy),
            "color": list(_float3(data.color)),
        }
    if item.type == "CAMERA":
        return {
            "focal_length": float(data.lens),
            "sensor_width": float(data.sensor_width),
        }
    return {}


def _collection_context(
    item: Any,
    *,
    collection_ids: dict[str, str],
    collection_parents: dict[str, str | None],
    object_ids: dict[str, str],
    included_object_ids: set[str],
    included_collection_names: set[str],
) -> CollectionContext:
    parent_name = collection_parents[item.name]
    return CollectionContext(
        target_id=collection_ids[item.name],
        name=item.name,
        parent_id=(
            collection_ids.get(parent_name)
            if parent_name is not None and parent_name in included_collection_names
            else None
        ),
        object_ids=tuple(
            object_ids[obj.name]
            for obj in sorted(item.objects, key=lambda value: value.name.casefold())
            if object_ids.get(obj.name) in included_object_ids
        ),
    )


def _target_index(
    objects: Iterable[Any],
    materials: Iterable[Any],
    collections: Iterable[Any],
    object_ids: dict[str, str],
    material_ids: dict[str, str],
    collection_ids: dict[str, str],
) -> dict[str, TargetReference]:
    index: dict[str, TargetReference] = {}
    for item in objects:
        target_id = object_ids[item.name]
        index[target_id] = TargetReference(
            target_id,
            TargetKind.OBJECT,
            item.name,
            int(item.session_uid),
            target_state_fingerprint(item, TargetKind.OBJECT),
        )
    for item in materials:
        target_id = material_ids[item.name]
        index[target_id] = TargetReference(
            target_id,
            TargetKind.MATERIAL,
            item.name,
            int(item.session_uid),
            target_state_fingerprint(item, TargetKind.MATERIAL),
        )
    for item in collections:
        target_id = collection_ids[item.name]
        index[target_id] = TargetReference(
            target_id,
            TargetKind.COLLECTION,
            item.name,
            int(item.session_uid),
            target_state_fingerprint(item, TargetKind.COLLECTION),
        )
    return index


def _float3(values: Any) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


def _float4(values: Any) -> tuple[float, float, float, float]:
    return (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
    )
