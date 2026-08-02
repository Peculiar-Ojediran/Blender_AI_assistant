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
        "intent_summary": "Apply planned advanced shading changes.",
        "assumptions": [],
        "questions": [],
        "operations": list(operations),
    }


def assert_future_plan_valid(*operations: Mapping[str, Any]) -> None:
    plan = validate_operation_plan(ready_plan(*operations))

    assert tuple(operation.type.value for operation in plan.operations) == tuple(
        str(operation["type"]) for operation in operations
    )


def test_track_a_shader_compatibility_registry_exposes_socket_metadata() -> None:
    from extension.operations import registries

    assert hasattr(registries, "SHADER_NODE_COMPATIBILITY")
    assert hasattr(registries, "SHADER_SOCKET_COMPATIBILITY")
    assert hasattr(registries, "SHADER_SOCKET_FAMILIES")


def layered_material_operation() -> dict[str, Any]:
    return {
        "operation_id": "create_layered_material",
        "type": "CREATE_LAYERED_SHADER_MATERIAL",
        "name": "AI Layered Bronze",
        "base_family": "metal",
        "base_color": [0.45, 0.24, 0.1],
        "metallic": 0.9,
        "roughness": 0.35,
        "layer_stack_label": "Aged bronze layers",
    }


def shader_layer_operation(layer_type: str) -> dict[str, Any]:
    return {
        "operation_id": f"add_{layer_type}_layer",
        "type": "ADD_SHADER_LAYER",
        "material_id": "result:create_layered_material",
        "layer_type": layer_type,
        "layer_name": f"{layer_type.title()} Layer",
        "blend_mode": "mix",
        "opacity": 0.65,
        "color": [0.8, 0.74, 0.62],
        "roughness_delta": 0.15,
        "bump_strength": 0.08,
    }


@pytest.mark.parametrize(
    "layer_type",
    [
        "base",
        "paint",
        "dust",
        "edge_wear",
        "scratches",
        "clearcoat",
        "emission_detail",
        "decal",
    ],
)
def test_track_b_layered_material_layer_types_validate(layer_type: str) -> None:
    assert_future_plan_valid(layered_material_operation(), shader_layer_operation(layer_type))


def test_track_b_layer_mask_reorder_and_remove_validate_as_a_chain() -> None:
    add_layer = shader_layer_operation("dust")
    set_mask = {
        "operation_id": "set_dust_mask",
        "type": "SET_SHADER_LAYER_MASK",
        "material_id": "result:create_layered_material",
        "layer_id": "result:add_dust_layer",
        "mask_source": {
            "kind": "procedural",
            "image_id": None,
            "uv_map_name": None,
            "vertex_group": None,
            "pattern": "noise",
        },
        "invert": False,
        "strength": 0.8,
    }
    reorder = {
        "operation_id": "reorder_layers",
        "type": "REORDER_SHADER_LAYERS",
        "material_id": "result:create_layered_material",
        "layer_order": ["result:add_dust_layer"],
    }
    remove = {
        "operation_id": "remove_dust_layer",
        "type": "REMOVE_SHADER_LAYER",
        "material_id": "result:create_layered_material",
        "layer_id": "result:add_dust_layer",
    }

    assert_future_plan_valid(layered_material_operation(), add_layer, set_mask, reorder, remove)


def procedural_pattern_operation(operation_type: str) -> dict[str, Any]:
    if operation_type == "CREATE_PROCEDURAL_PATTERN_NODE_SET":
        return {
            "operation_id": "create_pattern_set",
            "type": operation_type,
            "material_id": "mat_0001",
            "pattern": "ceramic_crackle",
            "node_set_label": "AI Ceramic Crackle",
            "mapping": "object",
            "scale": 18.0,
            "contrast": 0.7,
            "roughness_influence": 0.3,
            "bump_strength": 0.12,
            "seed": 7,
        }
    return {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "material_id": "mat_0001",
        "node_set_label": operation_type.title(),
        "mapping": "object",
        "scale": 10.0,
        "contrast": 0.55,
        "roughness_influence": 0.25,
        "bump_strength": 0.08,
        "seed": 3,
    }


@pytest.mark.parametrize(
    "operation_type",
    [
        "CREATE_PROCEDURAL_PATTERN_NODE_SET",
        "CREATE_EDGE_WEAR_SHADER",
        "CREATE_TRIPLANAR_MAPPING_SETUP",
        "CREATE_OBJECT_SPACE_GRADIENT_SHADER",
        "CREATE_CURVATURE_STYLE_MASK",
    ],
)
def test_track_c_procedural_pattern_operations_validate(operation_type: str) -> None:
    assert_future_plan_valid(procedural_pattern_operation(operation_type))


@pytest.mark.parametrize(
    "pattern",
    [
        "marble",
        "granite",
        "brushed_metal",
        "oxidation",
        "peeling_paint",
        "ceramic_crackle",
        "carbon_fiber",
        "fabric_weave",
        "skin_pores",
        "water_ripples",
    ],
)
def test_track_c_procedural_pattern_names_validate(pattern: str) -> None:
    operation = procedural_pattern_operation("CREATE_PROCEDURAL_PATTERN_NODE_SET")
    operation["operation_id"] = f"create_{pattern}"
    operation["pattern"] = pattern

    assert_future_plan_valid(operation)


def palette_extraction_operation() -> dict[str, Any]:
    return {
        "operation_id": "extract_palette",
        "type": "EXTRACT_MATERIAL_PALETTE_FROM_IMAGE",
        "source": "https://example.com/reference-material.png",
        "palette_name": "Reference Palette",
        "max_colors": 6,
        "include_roughness_guess": True,
        "include_metallic_guess": True,
        "include_pattern_hints": True,
    }


def test_track_d_reference_material_matching_validates_as_a_chain() -> None:
    create_material = {
        "operation_id": "create_reference_material",
        "type": "CREATE_MATERIAL_FROM_REFERENCE_IMAGE",
        "source": "https://example.com/reference-material.png",
        "material_name": "AI Reference Material",
        "palette_id": "result:extract_palette",
        "template_family": "matte_plastic",
        "use_generated_texture": False,
    }
    match_material = {
        "operation_id": "match_reference",
        "type": "MATCH_MATERIAL_TO_REFERENCE",
        "material_id": "result:create_reference_material",
        "reference_source": "https://example.com/reference-material.png",
        "match_color": True,
        "match_roughness": True,
        "match_pattern": True,
        "strength": 0.75,
    }
    preview = {
        "operation_id": "create_lookdev_preview",
        "type": "CREATE_LOOKDEV_PREVIEW",
        "material_id": "result:create_reference_material",
        "target_id": "obj_0001",
        "preview_name": "Reference Lookdev Preview",
        "width": 512,
        "height": 512,
        "pack": True,
    }

    assert_future_plan_valid(
        palette_extraction_operation(),
        create_material,
        match_material,
        preview,
    )


def test_track_d_generated_image_result_can_be_used_as_reference_source() -> None:
    generated_image = {
        "operation_id": "generate_reference",
        "type": "GENERATE_IMAGE_ASSET",
        "prompt": "reference ceramic surface",
        "image_name": "Generated Reference",
        "width": 64,
        "height": 64,
        "color_space": "sRGB",
        "pack": True,
    }
    extract_palette = palette_extraction_operation()
    extract_palette["source"] = "result:generate_reference"
    create_material = {
        "operation_id": "create_from_generated_reference",
        "type": "CREATE_MATERIAL_FROM_REFERENCE_IMAGE",
        "source": "result:generate_reference",
        "material_name": "AI Generated Reference Material",
        "palette_id": "result:extract_palette",
        "template_family": "ceramic",
        "use_generated_texture": False,
    }
    match_material = {
        "operation_id": "match_generated_reference",
        "type": "MATCH_MATERIAL_TO_REFERENCE",
        "material_id": "result:create_from_generated_reference",
        "reference_source": "result:generate_reference",
        "match_color": True,
        "match_roughness": False,
        "match_pattern": False,
        "strength": 0.5,
    }

    assert_future_plan_valid(
        generated_image,
        extract_palette,
        create_material,
        match_material,
    )


def specialized_material_operation(operation_type: str) -> dict[str, Any]:
    return {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "name": operation_type.removeprefix("CREATE_").removesuffix("_MATERIAL").title(),
        "base_color": [0.35, 0.55, 0.8],
        "alpha": 0.65,
        "roughness": 0.2,
        "ior": 1.45,
        "transmission": 0.6,
        "emission_strength": 0.0,
        "density": 0.15,
        "anisotropy": 0.4,
        "template_strength": 0.75,
    }


@pytest.mark.parametrize(
    "operation_type",
    [
        "CREATE_GLASS_MATERIAL",
        "CREATE_TRANSLUCENT_MATERIAL",
        "CREATE_EMISSION_MATERIAL",
        "CREATE_VOLUME_MATERIAL",
        "CREATE_TOON_SHADER_MATERIAL",
        "CREATE_ANISOTROPIC_MATERIAL",
    ],
)
def test_track_e_specialized_material_families_validate(operation_type: str) -> None:
    assert_future_plan_valid(specialized_material_operation(operation_type))


def shader_cleanup_operation(operation_type: str) -> dict[str, Any]:
    if operation_type == "CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS":
        return {
            "operation_id": "consolidate_duplicate_materials",
            "type": operation_type,
            "material_ids": ["mat_0001", "mat_0002"],
            "canonical_material_id": "mat_0001",
            "target_ids": ["obj_0001", "obj_0002"],
            "assistant_owned_only": True,
        }
    return {
        "operation_id": operation_type.lower(),
        "type": operation_type,
        "material_id": "mat_0001",
        "assistant_owned_only": True,
        "repair_mode": "single_safe_fix",
        "layout_style": "compact",
    }


@pytest.mark.parametrize(
    "operation_type",
    [
        "REMOVE_UNUSED_ASSISTANT_SHADER_NODES",
        "CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS",
        "NORMALIZE_SHADER_NODE_LAYOUT",
        "VALIDATE_SHADER_COMPATIBILITY",
        "REPAIR_BROKEN_SHADER_LINKS",
    ],
)
def test_track_f_shader_cleanup_repair_operations_validate(operation_type: str) -> None:
    assert_future_plan_valid(shader_cleanup_operation(operation_type))


def material_variant_operation() -> dict[str, Any]:
    return {
        "operation_id": "create_material_variant",
        "type": "CREATE_MATERIAL_VARIANT",
        "source_material_id": "mat_0001",
        "variant_name": "AI Warmer Metal Variant",
        "variant_label": "Warmer worn metal",
        "copy_textures": True,
    }


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation_id": "tag_material_variant",
            "type": "TAG_MATERIAL_VARIANT",
            "variant_id": "result:create_material_variant",
            "label": "Review Candidate",
            "prompt_summary": "Warmer worn metal with subtle scratches.",
        },
        {
            "operation_id": "preview_material_variant",
            "type": "CREATE_SHADER_COMPARISON_PREVIEW",
            "target_id": "obj_0001",
            "source_material_id": "mat_0001",
            "variant_id": "result:create_material_variant",
            "preview_name": "Material Variant Comparison",
            "width": 512,
            "height": 512,
            "mode": "material",
            "pack": True,
        },
        {
            "operation_id": "accept_material_variant",
            "type": "ACCEPT_MATERIAL_VARIANT",
            "variant_id": "result:create_material_variant",
            "target_ids": ["obj_0001"],
            "replace_material_id": "mat_0001",
        },
        {
            "operation_id": "reject_material_variant",
            "type": "REJECT_MATERIAL_VARIANT",
            "variant_id": "result:create_material_variant",
        },
    ],
)
def test_track_g_material_variant_review_operations_validate(
    operation: Mapping[str, Any],
) -> None:
    assert_future_plan_valid(material_variant_operation(), operation)


def test_provider_instructions_describe_future_shading_tracks() -> None:
    expected_terms = (
        "CREATE_LAYERED_SHADER_MATERIAL",
        "ADD_SHADER_LAYER",
        "CREATE_PROCEDURAL_PATTERN_NODE_SET",
        "CREATE_MATERIAL_FROM_REFERENCE_IMAGE",
        "CREATE_GLASS_MATERIAL",
        "VALIDATE_SHADER_COMPATIBILITY",
        "CREATE_MATERIAL_VARIANT",
    )

    for term in expected_terms:
        assert term in SYSTEM_INSTRUCTIONS
