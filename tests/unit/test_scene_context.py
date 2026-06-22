import json
from types import MappingProxyType

import pytest

from extension.context import (
    CollectionContext,
    ContextOptions,
    ContextScope,
    MaterialContext,
    ObjectContext,
    ObjectSummary,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
    TargetKind,
    TargetReference,
    apply_object_budget,
    fit_scene_context_to_budget,
    sanitize_custom_properties,
    serialize_scene_context,
)


def test_context_options_reject_invalid_budgets() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ContextOptions(detailed_object_budget=0)

    with pytest.raises(ValueError, match="cannot exceed"):
        ContextOptions(detailed_object_budget=3, summary_object_budget=2)

    with pytest.raises(ValueError, match="at least 1024"):
        ContextOptions(max_serialized_characters=1_023)


def test_object_budget_prioritizes_active_then_selected_objects() -> None:
    result = apply_object_budget(
        ("obj_0001", "obj_0002", "obj_0003", "obj_0004"),
        active_id="obj_0003",
        selected_ids=frozenset({"obj_0002", "obj_0003"}),
        detailed_limit=2,
        summary_limit=3,
    )

    assert result.summary_ids == ("obj_0003", "obj_0002", "obj_0001")
    assert result.detailed_ids == ("obj_0003", "obj_0002")
    assert result.omitted_summaries == 1
    assert result.omitted_details == 1


def test_custom_property_filter_redacts_paths_and_unsupported_values() -> None:
    properties = {
        "count": 3,
        "nested": {"path": "C:\\private\\asset.blend", "enabled": True},
        "path": "/home/user/private.blend",
        "unsupported": object(),
    }

    sanitized, stats = sanitize_custom_properties(properties, include_file_paths=False)

    assert sanitized == {"count": 3, "nested": {"enabled": True}}
    assert stats.custom_properties_omitted == 1
    assert stats.file_paths_omitted == 1


def test_custom_property_filter_can_include_paths() -> None:
    sanitized, stats = sanitize_custom_properties(
        {"path": "C:\\projects\\scene.blend"},
        include_file_paths=True,
    )

    assert sanitized == {"path": "C:\\projects\\scene.blend"}
    assert stats.file_paths_omitted == 0


def test_serializer_excludes_internal_target_index() -> None:
    snapshot = _snapshot()

    serialized = serialize_scene_context(snapshot)
    decoded = json.loads(serialized.json_text)

    assert "target_index" not in decoded
    assert decoded["detailed_objects"][0]["id"] == "obj_0001"
    assert decoded["materials"][0]["id"] == "mat_0001"
    assert serialized.character_count == len(serialized.json_text)
    assert serialized.json_text == json.dumps(
        serialized.payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_global_character_budget_reduces_context_and_target_index_together() -> None:
    snapshot = _snapshot()

    reduced = fit_scene_context_to_budget(snapshot, 1_024)
    serialized = serialize_scene_context(reduced)

    assert serialized.character_count <= 1_024
    retained_ids = {
        item.target_id
        for items in (
            reduced.context.object_summaries,
            reduced.context.materials,
            reduced.context.collections,
        )
        for item in items
    }
    assert set(reduced.target_index) == retained_ids
    assert reduced.context.omissions.total > snapshot.context.omissions.total


def _snapshot() -> SceneContextSnapshot:
    object_context = ObjectContext(
        target_id="obj_0001",
        name="Cube",
        object_type="mesh",
        selected=True,
        active=True,
        collection_ids=("col_0001",),
        parent_id=None,
        location=(0.0, 0.0, 0.0),
        rotation_euler=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        dimensions=(2.0, 2.0, 2.0),
        material_ids=("mat_0001",),
        modifiers=(),
        custom_properties=MappingProxyType({}),
        data=MappingProxyType({"vertex_count": 8}),
    )
    context = SceneContext(
        schema_version=1,
        blender_version="5.1.0",
        scene_name="Scene",
        file_path=None,
        unit_system="NONE",
        unit_scale=1.0,
        scope=ContextScope.SELECTION,
        active_object_id="obj_0001",
        active_collection_id="col_0001",
        total_scene_objects=1,
        scoped_object_count=1,
        object_summaries=(ObjectSummary("obj_0001", "Cube", "mesh", True, True),),
        detailed_objects=(object_context,),
        materials=(
            MaterialContext(
                "mat_0001",
                "Material",
                False,
                (0.8, 0.8, 0.8, 1.0),
                0.0,
                0.5,
                MappingProxyType({}),
            ),
        ),
        collections=(CollectionContext("col_0001", "Collection", None, ("obj_0001",)),),
        omissions=OmissionReport(),
        warnings=(),
        include_custom_properties=False,
        include_file_paths=False,
        include_viewport_image=False,
        character_budget=100_000,
    )
    target = TargetReference("obj_0001", TargetKind.OBJECT, "Cube", 1, "fingerprint")
    return SceneContextSnapshot(
        "snapshot_test",
        context,
        MappingProxyType({target.target_id: target}),
    )
