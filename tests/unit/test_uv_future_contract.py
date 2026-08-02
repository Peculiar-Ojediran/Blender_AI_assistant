from collections.abc import Mapping
from typing import Any

import pytest

from extension.operations import validate_operation_plan
from extension.providers.instructions import SYSTEM_INSTRUCTIONS

SNAPSHOT_ID = "b" * 32


def ready_plan(*operations: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Apply planned advanced UV editing changes.",
        "assumptions": [],
        "questions": [],
        "operations": list(operations),
    }


def assert_future_plan_valid(*operations: Mapping[str, Any]) -> None:
    plan = validate_operation_plan(ready_plan(*operations))

    assert tuple(operation.type.value for operation in plan.operations) == tuple(
        str(operation["type"]) for operation in operations
    )


def inspect_uv_operation() -> dict[str, Any]:
    return {
        "operation_id": "inspect_uv",
        "type": "INSPECT_UV_MAP",
        "target_id": "obj_0001",
        "uv_map_name": "UVMap",
        "include_island_estimate": True,
        "include_material_usage": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        inspect_uv_operation(),
        {
            "operation_id": "diagnostic_report",
            "type": "CREATE_UV_DIAGNOSTIC_REPORT",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "report_name": "AI UV Diagnostic",
            "checks": {
                "missing_uvs": True,
                "out_of_bounds": True,
                "overlaps": True,
                "stretch": True,
                "material_usage": True,
            },
        },
        {
            "operation_id": "overlap_preview",
            "type": "CREATE_UV_OVERLAP_PREVIEW",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "preview_name": "AI UV Overlap Preview",
            "width": 512,
            "height": 512,
            "pack": True,
        },
        {
            "operation_id": "stretch_preview",
            "type": "CREATE_UV_STRETCH_PREVIEW",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "preview_name": "AI UV Stretch Preview",
            "width": 512,
            "height": 512,
            "pack": True,
        },
    ],
)
def test_track_a_uv_context_and_diagnostic_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(operation)


def angle_seam_operation() -> dict[str, Any]:
    return {
        "operation_id": "angle_seams",
        "type": "MARK_UV_SEAMS_BY_ANGLE",
        "target_ids": ["obj_0001"],
        "seam_set_name": "AI Angle Seams",
        "angle_threshold_degrees": 45.0,
        "mark_sharp_edges": True,
        "assistant_owned_only": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        angle_seam_operation(),
        {
            "operation_id": "material_seams",
            "type": "MARK_UV_SEAMS_BY_MATERIAL",
            "target_ids": ["obj_0001"],
            "material_id": "mat_0001",
            "seam_set_name": "AI Material Seams",
            "assistant_owned_only": True,
        },
        {
            "operation_id": "edge_set_seams",
            "type": "MARK_UV_SEAMS_BY_EDGE_SET",
            "target_id": "obj_0001",
            "edge_set_name": "HardSurfaceEdges",
            "seam_set_name": "AI Edge Set Seams",
            "assistant_owned_only": True,
        },
        {
            "operation_id": "clear_seams",
            "type": "CLEAR_UV_SEAMS",
            "target_ids": ["obj_0001"],
            "seam_set_name": "AI Angle Seams",
            "assistant_owned_only": True,
        },
    ],
)
def test_track_b_seam_definition_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(operation)


def test_track_b_create_uv_islands_from_seams_validates_as_a_chain() -> None:
    create_islands = {
        "operation_id": "create_islands",
        "type": "CREATE_UV_ISLANDS_FROM_SEAMS",
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_Unwrap",
        "seam_set_id": "result:angle_seams",
        "create_if_missing": True,
        "overwrite_existing": False,
    }

    assert_future_plan_valid(angle_seam_operation(), create_islands)


def projection_operation(operation_type: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_Projection",
        "create_if_missing": True,
        "overwrite_existing": False,
        "margin": 0.02,
        "scale_to_bounds": True,
    }
    if operation_type == "SMART_PROJECT_UV_MAP":
        base.update(
            {
                "angle_limit_degrees": 66.0,
                "area_weight": 0.5,
                "correct_aspect": True,
            }
        )
    elif operation_type == "CUBE_PROJECT_UV_MAP":
        base.update({"cube_size": 1.0})
    elif operation_type == "CYLINDER_PROJECT_UV_MAP":
        base.update(
            {
                "axis": "z",
                "radius": 1.0,
                "height": 2.0,
                "seam_position_degrees": 180.0,
            }
        )
    elif operation_type == "SPHERE_PROJECT_UV_MAP":
        base.update({"axis": "z", "pole_axis": "y"})
    elif operation_type == "CAMERA_PROJECT_UV_MAP":
        base.update({"camera_id": "obj_0002"})
    elif operation_type == "LIGHTMAP_UNWRAP_UV_MAP":
        base.update(
            {
                "resolution": 1024,
                "pack": True,
                "new_uv_map_by_default": True,
            }
        )
    return base


@pytest.mark.parametrize(
    "operation_type",
    [
        "SMART_PROJECT_UV_MAP",
        "CUBE_PROJECT_UV_MAP",
        "CYLINDER_PROJECT_UV_MAP",
        "SPHERE_PROJECT_UV_MAP",
        "CAMERA_PROJECT_UV_MAP",
        "LIGHTMAP_UNWRAP_UV_MAP",
    ],
)
def test_track_c_projection_operations_validate(operation_type: str) -> None:
    assert_future_plan_valid(projection_operation(operation_type))


def island_selection_operation() -> dict[str, Any]:
    return {
        "operation_id": "select_islands",
        "type": "SELECT_UV_ISLANDS_BY_MATERIAL",
        "target_id": "obj_0001",
        "uv_map_name": "UVMap",
        "material_id": "mat_0001",
        "island_set_name": "AI Material Islands",
    }


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "transform_islands",
            "type": "TRANSFORM_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "translation": [0.1, 0.0],
            "rotation_degrees": 15.0,
            "scale": [1.1, 1.1],
            "pivot": [0.5, 0.5],
        },
        {
            "operation_id": "align_islands",
            "type": "ALIGN_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "mode": "center",
            "bounds_min": [0.0, 0.0],
            "bounds_max": [1.0, 1.0],
        },
        {
            "operation_id": "distribute_islands",
            "type": "DISTRIBUTE_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "axis": "horizontal",
            "spacing": 0.02,
            "bounds_min": [0.0, 0.0],
            "bounds_max": [1.0, 1.0],
        },
        {
            "operation_id": "scale_to_bounds",
            "type": "SCALE_UV_ISLANDS_TO_BOUNDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "bounds_min": [0.1, 0.1],
            "bounds_max": [0.9, 0.9],
            "preserve_aspect": True,
        },
        {
            "operation_id": "pin_islands",
            "type": "PIN_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
        },
        {
            "operation_id": "unpin_islands",
            "type": "UNPIN_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
        },
    ],
)
def test_track_d_island_transform_operations_validate_as_chains(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(island_selection_operation(), operation)


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "set_texel_density",
            "type": "SET_UV_TEXEL_DENSITY",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "texture_resolution": [2048, 2048],
            "pixels_per_unit": 256.0,
            "unit_scale": 1.0,
            "island_set_id": None,
        },
        {
            "operation_id": "normalize_texel_density",
            "type": "NORMALIZE_UV_TEXEL_DENSITY",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "texture_resolution": [2048, 2048],
            "target_pixels_per_unit": 256.0,
            "preserve_pinned": True,
        },
        {
            "operation_id": "advanced_pack",
            "type": "PACK_UV_ISLANDS_ADVANCED",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "margin": 0.02,
            "rotate": True,
            "preserve_orientation": False,
            "preserve_pinned": True,
            "target_tile": [0, 0],
        },
        {
            "operation_id": "move_to_tile",
            "type": "MOVE_UV_ISLANDS_TO_TILE",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "tile_u": 1,
            "tile_v": 0,
        },
        {
            "operation_id": "udim_layout",
            "type": "CREATE_UDIM_TILE_LAYOUT",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UDIM_UV",
            "tile_count_u": 2,
            "tile_count_v": 2,
            "margin": 0.02,
            "preserve_existing_tiles": True,
        },
        {
            "operation_id": "validate_udim",
            "type": "VALIDATE_UDIM_LAYOUT",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UDIM_UV",
            "allowed_tile_min": [0, 0],
            "allowed_tile_max": [9, 9],
            "check_overlaps": True,
            "check_bounds": True,
        },
    ],
)
def test_track_e_texel_density_packing_and_udim_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    if operation["type"] == "MOVE_UV_ISLANDS_TO_TILE":
        assert_future_plan_valid(island_selection_operation(), operation)
    else:
        assert_future_plan_valid(operation)


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "relax_islands",
            "type": "RELAX_UV_ISLANDS",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "iterations": 8,
            "strength": 0.5,
            "preserve_pinned": True,
        },
        {
            "operation_id": "minimize_stretch",
            "type": "MINIMIZE_UV_STRETCH",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "iterations": 12,
            "strength": 0.45,
            "preserve_boundary": True,
        },
        {
            "operation_id": "repair_bounds",
            "type": "REPAIR_UV_BOUNDS",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "target_tile": [0, 0],
            "scale_to_fit": True,
            "preserve_aspect": True,
        },
        {
            "operation_id": "merge_duplicate_uvs",
            "type": "MERGE_DUPLICATE_UV_MAPS",
            "target_ids": ["obj_0001"],
            "source_uv_map_names": ["UVMap_Copy", "UVMap_Backup"],
            "destination_uv_map_name": "UVMap",
            "update_texture_nodes": True,
            "remove_sources": False,
            "assistant_owned_only": True,
        },
        {
            "operation_id": "remove_unused_assistant_uvs",
            "type": "REMOVE_UNUSED_ASSISTANT_UV_MAPS",
            "target_ids": ["obj_0001"],
            "assistant_owned_only": True,
            "dry_run": False,
        },
        {
            "operation_id": "validate_uv",
            "type": "VALIDATE_UV_MAP",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "checks": {
                "missing_uvs": True,
                "out_of_bounds": True,
                "overlaps": True,
                "zero_area_islands": True,
                "stretch": True,
            },
        },
    ],
)
def test_track_f_uv_cleanup_and_repair_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    if operation["type"] == "RELAX_UV_ISLANDS":
        assert_future_plan_valid(island_selection_operation(), operation)
    else:
        assert_future_plan_valid(operation)


def generated_image_operation() -> dict[str, Any]:
    return {
        "operation_id": "generate_atlas_image",
        "type": "GENERATE_IMAGE_ASSET",
        "prompt": "clean uv atlas debug image",
        "image_name": "AI Atlas Image",
        "width": 512,
        "height": 512,
        "color_space": "sRGB",
        "pack": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "fit_to_image_region",
            "type": "FIT_UV_ISLANDS_TO_IMAGE_REGION",
            "target_id": "obj_0001",
            "uv_map_name": "UVMap",
            "island_set_id": "result:select_islands",
            "image_id": "result:generate_atlas_image",
            "region_min_uv": [0.0, 0.0],
            "region_max_uv": [0.5, 0.5],
            "preserve_aspect": True,
        },
        {
            "operation_id": "atlas_layout",
            "type": "CREATE_TEXTURE_ATLAS_LAYOUT",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "atlas_name": "AI Texture Atlas",
            "image_id": "result:generate_atlas_image",
            "atlas_resolution": [2048, 2048],
            "margin": 0.02,
            "allow_rotation": True,
        },
        {
            "operation_id": "assign_atlas_regions",
            "type": "ASSIGN_ATLAS_TEXTURE_REGIONS",
            "target_id": "obj_0001",
            "material_id": "mat_0001",
            "atlas_id": "result:atlas_layout",
            "assignments": [
                {
                    "material_id": "mat_0001",
                    "region_name": "MainMaterial",
                    "bounds_min": [0.0, 0.0],
                    "bounds_max": [0.5, 0.5],
                }
            ],
        },
        {
            "operation_id": "uv_guide_image",
            "type": "BAKE_UV_LAYOUT_GUIDE_IMAGE",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "image_name": "AI UV Guide",
            "width": 512,
            "height": 512,
            "line_color": [1.0, 1.0, 1.0, 1.0],
            "background_color": [0.0, 0.0, 0.0, 1.0],
            "pack": True,
        },
        {
            "operation_id": "grid_material",
            "type": "CREATE_UV_GRID_TEST_MATERIAL",
            "name": "AI UV Grid Material",
            "grid_scale": 8.0,
            "color_a": [1.0, 1.0, 1.0, 1.0],
            "color_b": [0.1, 0.1, 0.1, 1.0],
        },
    ],
)
def test_track_g_texture_aware_uv_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    prefix: tuple[Mapping[str, Any], ...]
    if operation["type"] == "FIT_UV_ISLANDS_TO_IMAGE_REGION":
        prefix = (generated_image_operation(), island_selection_operation())
    elif operation["type"] == "ASSIGN_ATLAS_TEXTURE_REGIONS":
        atlas = {
            "operation_id": "atlas_layout",
            "type": "CREATE_TEXTURE_ATLAS_LAYOUT",
            "target_ids": ["obj_0001"],
            "uv_map_name": "UVMap",
            "atlas_name": "AI Texture Atlas",
            "image_id": "result:generate_atlas_image",
            "atlas_resolution": [2048, 2048],
            "margin": 0.02,
            "allow_rotation": True,
        }
        prefix = (generated_image_operation(), atlas)
    elif "image_id" in operation:
        prefix = (generated_image_operation(),)
    else:
        prefix = ()

    assert_future_plan_valid(*prefix, operation)


def uv_variant_operation() -> dict[str, Any]:
    return {
        "operation_id": "create_uv_variant",
        "type": "CREATE_UV_MAP_VARIANT",
        "target_id": "obj_0001",
        "source_uv_map_name": "UVMap",
        "variant_uv_map_name": "AI_UV_Variant",
        "variant_label": "Less stretched unwrap",
        "copy_pins": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "tag_uv_variant",
            "type": "TAG_UV_VARIANT",
            "target_id": "obj_0001",
            "variant_id": "result:create_uv_variant",
            "label": "Review Candidate",
            "prompt_summary": "Packed with more even texel density.",
        },
        {
            "operation_id": "uv_variant_preview",
            "type": "CREATE_UV_COMPARISON_PREVIEW",
            "target_id": "obj_0001",
            "source_uv_map_name": "UVMap",
            "variant_id": "result:create_uv_variant",
            "preview_name": "AI UV Variant Preview",
            "width": 512,
            "height": 512,
            "pack": True,
        },
        {
            "operation_id": "accept_uv_variant",
            "type": "ACCEPT_UV_VARIANT",
            "target_id": "obj_0001",
            "variant_id": "result:create_uv_variant",
            "replace_uv_map_name": "UVMap",
            "make_active": True,
            "make_render_active": True,
        },
        {
            "operation_id": "reject_uv_variant",
            "type": "REJECT_UV_VARIANT",
            "target_id": "obj_0001",
            "variant_id": "result:create_uv_variant",
            "remove_variant": True,
        },
    ],
)
def test_track_h_uv_variant_review_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(uv_variant_operation(), operation)


def test_provider_instructions_describe_future_uv_tracks() -> None:
    expected_terms = (
        "INSPECT_UV_MAP",
        "MARK_UV_SEAMS_BY_ANGLE",
        "SMART_PROJECT_UV_MAP",
        "TRANSFORM_UV_ISLANDS",
        "SET_UV_TEXEL_DENSITY",
        "VALIDATE_UV_MAP",
        "CREATE_TEXTURE_ATLAS_LAYOUT",
        "CREATE_UV_MAP_VARIANT",
    )

    for term in expected_terms:
        assert term in SYSTEM_INSTRUCTIONS
