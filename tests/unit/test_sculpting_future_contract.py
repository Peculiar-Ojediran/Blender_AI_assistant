from collections.abc import Mapping
from typing import Any

import pytest

from extension.operations import validate_operation_plan
from extension.providers.instructions import SYSTEM_INSTRUCTIONS

SNAPSHOT_ID = "a" * 32


def ready_plan(*operations: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Apply planned sculpting changes.",
        "assumptions": [],
        "questions": [],
        "operations": list(operations),
    }


def assert_future_plan_valid(*operations: Mapping[str, Any]) -> None:
    plan = validate_operation_plan(ready_plan(*operations))

    assert tuple(operation.type.value for operation in plan.operations) == tuple(
        str(operation["type"]) for operation in operations
    )


def sculpt_stroke() -> dict[str, Any]:
    return {
        "location": [0.0, 0.0, 0.0],
        "normal": [0.0, 0.0, 1.0],
        "direction": [0.1, 0.0, 0.0],
        "pressure": 1.0,
    }


def advanced_brush_operation(brush_type: str) -> dict[str, Any]:
    return {
        "operation_id": f"advanced_{brush_type}",
        "type": "APPLY_ADVANCED_SCULPT_BRUSH_STROKES",
        "target_id": "obj_0001",
        "brush_type": brush_type,
        "radius": 0.35,
        "strength": 0.45,
        "falloff": "smooth",
        "strokes": [sculpt_stroke()],
        "region_id": None,
        "mask_id": None,
        "preserve_original": True,
    }


@pytest.mark.parametrize(
    "brush_type",
    [
        "clay",
        "clay_strips",
        "crease",
        "pinch",
        "scrape",
        "grab",
        "snake_hook",
        "pose",
    ],
)
def test_track_a_expanded_sculpt_brushes_validate(brush_type: str) -> None:
    assert_future_plan_valid(advanced_brush_operation(brush_type))


def test_track_b_symmetric_sculpt_strokes_validate() -> None:
    assert_future_plan_valid(
        {
            "operation_id": "symmetry_strokes",
            "type": "APPLY_SYMMETRIC_SCULPT_BRUSH_STROKES",
            "target_id": "obj_0001",
            "brush_type": "clay",
            "mirror_axes": ["x", "z"],
            "symmetry_origin": {
                "kind": "object_origin",
                "location": None,
            },
            "radius": 0.35,
            "strength": 0.45,
            "falloff": "smooth",
            "strokes": [sculpt_stroke()],
            "region_id": None,
            "mask_id": None,
        }
    )


def mask_operation(operation_type: str) -> dict[str, Any]:
    if operation_type == "COMBINE_SCULPT_MASKS":
        return {
            "operation_id": "combine_sculpt_masks",
            "type": operation_type,
            "target_id": "obj_0001",
            "source_mask_name": "RaisedDetails",
            "target_mask_name": "FaceMask",
            "result_mask_name": "CombinedMask",
            "combine_mode": "add",
        }
    return {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "target_id": "obj_0001",
        "mask_name": "FaceMask",
        "iterations": 2,
        "strength": 0.5,
    }


@pytest.mark.parametrize(
    "operation_type",
    [
        "INVERT_SCULPT_MASK",
        "CLEAR_SCULPT_MASK",
        "BLUR_SCULPT_MASK",
        "SHARPEN_SCULPT_MASK",
        "GROW_SCULPT_MASK",
        "SHRINK_SCULPT_MASK",
        "COMBINE_SCULPT_MASKS",
    ],
)
def test_track_c_sculpt_mask_operations_validate(operation_type: str) -> None:
    assert_future_plan_valid(mask_operation(operation_type))


def face_set_operation(operation_type: str) -> dict[str, Any]:
    if operation_type == "CREATE_FACE_SET_FROM_NORMAL_ANGLE":
        return {
            "operation_id": "face_set_from_normal",
            "type": operation_type,
            "target_id": "obj_0001",
            "face_set_name": "ForwardPlanes",
            "seed_face_index": 0,
            "angle_degrees": 35.0,
        }
    if operation_type == "CREATE_FACE_SET_FROM_POLYGON_AREA":
        return {
            "operation_id": "face_set_from_area",
            "type": operation_type,
            "target_id": "obj_0001",
            "face_set_name": "LargeFaces",
            "min_area": 0.05,
            "max_area": 10.0,
        }
    if operation_type == "MERGE_FACE_SETS":
        return {
            "operation_id": "merge_face_sets",
            "type": operation_type,
            "target_id": "obj_0001",
            "source_face_set_names": ["ForwardPlanes", "LargeFaces"],
            "merged_face_set_name": "EditableRegion",
        }
    if operation_type == "RENAME_FACE_SET":
        return {
            "operation_id": "rename_face_set",
            "type": operation_type,
            "target_id": "obj_0001",
            "face_set_name": "ForwardPlanes",
            "new_face_set_name": "FrontPlanes",
        }
    return {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "target_id": "obj_0001",
        "face_set_name": "ForwardPlanes",
        "iterations": 1,
    }


@pytest.mark.parametrize(
    "operation_type",
    [
        "CREATE_FACE_SET_FROM_NORMAL_ANGLE",
        "CREATE_FACE_SET_FROM_POLYGON_AREA",
        "EXPAND_FACE_SET",
        "SHRINK_FACE_SET",
        "MERGE_FACE_SETS",
        "RENAME_FACE_SET",
    ],
)
def test_track_d_face_set_tools_validate(operation_type: str) -> None:
    assert_future_plan_valid(face_set_operation(operation_type))


def test_track_e_voxel_remesh_generated_copy_plan_validates() -> None:
    create_copy = {
        "operation_id": "create_voxel_copy",
        "type": "CREATE_VOXEL_REMESH_COPY",
        "target_id": "obj_0001",
        "name": "Head_VoxelRemesh",
        "voxel_size": 0.08,
        "adaptivity": 0.1,
        "preserve_volume": True,
        "max_vertices": 80_000,
        "max_polygons": 80_000,
    }
    apply_to_copy = {
        "operation_id": "apply_voxel_to_copy",
        "type": "APPLY_VOXEL_REMESH_TO_GENERATED_COPY",
        "generated_object_id": "result:create_voxel_copy",
        "voxel_size": 0.1,
        "adaptivity": 0.0,
        "preserve_volume": True,
        "max_vertices": 80_000,
        "max_polygons": 80_000,
    }

    assert_future_plan_valid(create_copy, apply_to_copy)


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "create_quad_prep",
            "type": "CREATE_QUAD_REMESH_PREP_COPY",
            "target_id": "obj_0001",
            "name": "Head_QuadPrep",
            "target_face_count": 12_000,
            "preserve_sharp_edges": True,
            "preserve_original": True,
        },
        {
            "operation_id": "create_dyntopo_detail",
            "type": "CREATE_DYNAMIC_TOPOLOGY_DETAIL_COPY",
            "target_id": "obj_0001",
            "generated_name": "Head_DyntopoDetail",
            "detail_level": 16.0,
            "method": "relative_detail",
            "preserve_original": True,
        },
    ],
)
def test_track_e_remesh_preparation_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(operation)


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "subdivide_multires",
            "type": "SUBDIVIDE_MULTIRES_MODIFIER",
            "target_id": "obj_0001",
            "modifier_name": "AI_Multires",
            "levels": 1,
        },
        {
            "operation_id": "set_multires_levels",
            "type": "SET_MULTIRES_LEVELS",
            "target_id": "obj_0001",
            "modifier_name": "AI_Multires",
            "viewport_levels": 2,
            "sculpt_levels": 2,
            "render_levels": 2,
        },
        {
            "operation_id": "create_multires_copy",
            "type": "CREATE_MULTIRES_SCULPT_COPY",
            "target_id": "obj_0001",
            "generated_name": "Head_MultiresSculpt",
            "levels": 2,
            "preserve_original": True,
        },
        {
            "operation_id": "bake_multires_preview",
            "type": "BAKE_MULTIRES_DISPLACEMENT_PREVIEW",
            "target_id": "obj_0001",
            "modifier_name": "AI_Multires",
            "image_name": "Head_DisplacementPreview",
            "width": 512,
            "height": 512,
            "color_space": "Non-Color",
            "pack": True,
        },
    ],
)
def test_track_f_multires_workflow_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(operation)


def sculpt_variant_copy() -> dict[str, Any]:
    return {
        "operation_id": "create_variant",
        "type": "CREATE_SCULPT_VARIANT_COPY",
        "target_id": "obj_0001",
        "variant_name": "Head_SculptVariant",
        "variant_label": "Sharper cheek forms",
        "preserve_original": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "tag_variant",
            "type": "TAG_SCULPT_VARIANT",
            "variant_id": "result:create_variant",
            "label": "Review Candidate",
            "prompt_summary": "Sharpen cheek and brow planes.",
        },
        {
            "operation_id": "preview_variant",
            "type": "CREATE_SCULPT_COMPARISON_PREVIEW",
            "target_id": "obj_0001",
            "variant_id": "result:create_variant",
            "preview_name": "Head_SculptComparison",
            "width": 512,
            "height": 512,
            "mode": "material",
            "pack": True,
        },
        {
            "operation_id": "accept_variant",
            "type": "ACCEPT_SCULPT_VARIANT",
            "original_target_id": "obj_0001",
            "variant_id": "result:create_variant",
            "hide_original": True,
            "preserve_original_data": True,
        },
        {
            "operation_id": "reject_variant",
            "type": "REJECT_SCULPT_VARIANT",
            "variant_id": "result:create_variant",
        },
    ],
)
def test_track_g_sculpt_variant_review_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(sculpt_variant_copy(), operation)


def test_provider_instructions_describe_future_sculpting_tracks() -> None:
    expected_terms = (
        "APPLY_ADVANCED_SCULPT_BRUSH_STROKES",
        "APPLY_SYMMETRIC_SCULPT_BRUSH_STROKES",
        "SCULPT_MASK",
        "FACE_SET",
        "CREATE_VOXEL_REMESH_COPY",
        "CREATE_MULTIRES_SCULPT_COPY",
        "CREATE_SCULPT_VARIANT_COPY",
    )

    for term in expected_terms:
        assert term in SYSTEM_INSTRUCTIONS
