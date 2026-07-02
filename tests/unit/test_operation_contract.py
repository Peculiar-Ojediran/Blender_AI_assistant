import json
from copy import deepcopy
from typing import Any

import pytest

from extension.operations import (
    DEFAULT_MAX_DUPLICATE_OBJECTS,
    DEFAULT_MAX_OPERATIONS_PER_PLAN,
    DEFAULT_MAX_TARGETS_PER_OPERATION,
    DEFAULT_OPERATION_LIMITS,
    HARD_MAX_DUPLICATE_OBJECTS,
    HARD_MAX_OPERATIONS_PER_PLAN,
    HARD_MAX_TARGETS_PER_OPERATION,
    OPERATION_CATALOG,
    OPERATION_PLAN_SCHEMA,
    OPERATION_SCHEMAS,
    OperationContractError,
    OperationLimits,
    OperationType,
    PlanStatus,
    RiskLevel,
    assess_plan_risk,
    build_operation_plan_schema,
    validate_operation_plan,
)
from extension.operations.registries import (
    GENERATED_TEXTURE_PATTERNS,
    MATERIAL_FAMILIES,
    PBR_TEXTURE_ROLES,
    PROCEDURAL_PATTERNS,
    SHADER_NODE_TYPES,
    TEXTURE_BAKE_PASS_TYPES,
)

SNAPSHOT_ID = "a" * 32


def create_primitive_operation(operation_id: str = "create_cube") -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "type": "CREATE_PRIMITIVE",
        "primitive": "cube",
        "name": "Cube",
        "collection_id": None,
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def ready_plan(*operations: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "status": "ready",
        "intent_summary": "Apply the requested scene changes.",
        "assumptions": [],
        "questions": [],
        "operations": list(operations),
    }


VALID_OPERATIONS = [
    create_primitive_operation(),
    {
        "operation_id": "delete_cube",
        "type": "DELETE_OBJECTS",
        "target_ids": ["obj_0001"],
        "reason": "The user explicitly requested deletion.",
    },
    {
        "operation_id": "duplicate_cube",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001"],
        "count": 2,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": "Copy",
    },
    {
        "operation_id": "move_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001"],
        "mode": "relative",
        "location": [1.0, 0.0, 0.0],
        "rotation_euler": None,
        "scale": None,
    },
    {
        "operation_id": "create_red_material",
        "type": "CREATE_MATERIAL",
        "name": "Red Material",
        "base_color": [1.0, 0.0, 0.0],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
    },
    {
        "operation_id": "assign_red_material",
        "type": "ASSIGN_MATERIAL",
        "target_ids": ["obj_0001"],
        "material_id": "mat_0001",
    },
    {
        "operation_id": "add_key_light",
        "type": "ADD_LIGHT",
        "light_type": "area",
        "name": "Key Light",
        "collection_id": None,
        "location": [4.0, -4.0, 6.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "color": [1.0, 0.9, 0.8],
        "energy": 1000.0,
        "size": 5.0,
    },
    {
        "operation_id": "add_camera",
        "type": "ADD_CAMERA",
        "name": "Hero Camera",
        "collection_id": None,
        "location": [6.0, -6.0, 4.0],
        "rotation_euler": [1.0, 0.0, 0.8],
        "focal_length": 50.0,
        "make_active": True,
    },
    {
        "operation_id": "rename_cube",
        "type": "RENAME_OBJECTS",
        "renames": [{"target_id": "obj_0001", "new_name": "HeroCube"}],
    },
    {
        "operation_id": "move_collection",
        "type": "MOVE_TO_COLLECTION",
        "target_ids": ["obj_0001"],
        "collection_id": "col_0001",
    },
    {
        "operation_id": "set_material_properties",
        "type": "SET_MATERIAL_PROPERTIES",
        "material_id": "mat_0001",
        "base_color": [0.1, 0.2, 0.3],
        "metallic": 0.2,
        "roughness": 0.8,
        "alpha": 0.75,
    },
    {
        "operation_id": "create_collection",
        "type": "CREATE_COLLECTION",
        "name": "Generated Collection",
        "parent_collection_id": "col_0001",
    },
    {
        "operation_id": "set_light_properties",
        "type": "SET_LIGHT_PROPERTIES",
        "target_ids": ["obj_0001"],
        "color": [1.0, 0.95, 0.8],
        "energy": 500.0,
        "size": 2.0,
    },
    {
        "operation_id": "set_camera_properties",
        "type": "SET_CAMERA_PROPERTIES",
        "target_ids": ["obj_0001"],
        "focal_length": 35.0,
        "make_active": True,
    },
    {
        "operation_id": "add_bevel",
        "type": "ADD_MODIFIER",
        "target_ids": ["obj_0001"],
        "modifier_type": "bevel",
        "name": "AI Bevel",
        "width": 0.1,
        "segments": 3,
        "thickness": None,
        "count": None,
        "relative_offset": None,
        "levels": None,
        "axis": None,
    },
    {
        "operation_id": "set_bevel",
        "type": "SET_MODIFIER_PROPERTIES",
        "target_ids": ["obj_0001"],
        "modifier_name": "AI Bevel",
        "width": 0.2,
        "segments": 4,
        "thickness": None,
        "count": None,
        "relative_offset": None,
        "levels": None,
        "axis": None,
    },
    {
        "operation_id": "create_text",
        "type": "CREATE_TEXT_OBJECT",
        "name": "AI Label",
        "collection_id": "col_0001",
        "body": "Hello",
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
        "align_x": "CENTER",
        "align_y": "CENTER",
        "size": 1.0,
        "extrude": 0.0,
    },
    {
        "operation_id": "hide_object",
        "type": "SET_OBJECT_VISIBILITY",
        "target_ids": ["obj_0001"],
        "viewport_visible": False,
        "render_visible": True,
    },
    {
        "operation_id": "import_asset",
        "type": "IMPORT_ASSET",
        "filepath": "C:\\assets\\test.obj",
        "format": "obj",
        "collection_id": None,
        "name_prefix": "Imported",
        "location": [0.0, 0.0, 0.0],
        "rotation_euler": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    },
    {
        "operation_id": "append_blend_object",
        "type": "LINK_OR_APPEND_BLEND_DATA",
        "filepath": "C:\\assets\\library.blend",
        "mode": "append",
        "datablock_type": "object",
        "datablock_names": ["AssetCube"],
        "collection_id": None,
        "name_prefix": "Appended",
    },
    {
        "operation_id": "boolean_difference",
        "type": "BOOLEAN_OPERATION",
        "target_id": "obj_0001",
        "cutter_id": "obj_0002",
        "boolean_operation": "difference",
        "solver": "exact",
        "apply": False,
        "modifier_name": "AI Boolean",
        "hide_cutter": True,
    },
    {
        "operation_id": "join_meshes",
        "type": "JOIN_OBJECTS",
        "target_ids": ["obj_0001", "obj_0002"],
        "new_name": "Joined Mesh",
        "collection_id": None,
    },
    {
        "operation_id": "separate_mesh",
        "type": "SEPARATE_OBJECTS",
        "target_ids": ["obj_0001"],
        "mode": "by_material",
        "name_prefix": "Part",
        "collection_id": None,
    },
]


def test_catalog_and_schema_cover_the_same_operations() -> None:
    assert set(OPERATION_CATALOG) == set(OperationType)
    assert set(OPERATION_SCHEMAS) == set(OperationType)


def test_provider_schema_is_json_serializable() -> None:
    assert json.loads(json.dumps(OPERATION_PLAN_SCHEMA)) == OPERATION_PLAN_SCHEMA


def test_default_limits_match_the_controlled_contract() -> None:
    assert OperationLimits(
        max_operations_per_plan=DEFAULT_MAX_OPERATIONS_PER_PLAN,
        max_targets_per_operation=DEFAULT_MAX_TARGETS_PER_OPERATION,
        max_duplicate_objects=DEFAULT_MAX_DUPLICATE_OBJECTS,
    ) == DEFAULT_OPERATION_LIMITS


def test_hard_limits_allow_values_above_the_safe_defaults() -> None:
    limits = OperationLimits(
        max_operations_per_plan=HARD_MAX_OPERATIONS_PER_PLAN,
        max_targets_per_operation=HARD_MAX_TARGETS_PER_OPERATION,
        max_duplicate_objects=HARD_MAX_DUPLICATE_OBJECTS,
    )

    assert limits.max_operations_per_plan > DEFAULT_MAX_OPERATIONS_PER_PLAN
    assert limits.max_targets_per_operation > DEFAULT_MAX_TARGETS_PER_OPERATION
    assert limits.max_duplicate_objects > DEFAULT_MAX_DUPLICATE_OBJECTS


@pytest.mark.parametrize(
    ("field", "value", "maximum"),
    [
        ("max_operations_per_plan", 0, HARD_MAX_OPERATIONS_PER_PLAN),
        (
            "max_targets_per_operation",
            HARD_MAX_TARGETS_PER_OPERATION + 1,
            HARD_MAX_TARGETS_PER_OPERATION,
        ),
        (
            "max_duplicate_objects",
            HARD_MAX_DUPLICATE_OBJECTS + 1,
            HARD_MAX_DUPLICATE_OBJECTS,
        ),
    ],
)
def test_limits_reject_values_outside_hard_contract(
    field: str,
    value: int,
    maximum: int,
) -> None:
    values = {
        "max_operations_per_plan": 1,
        "max_targets_per_operation": 1,
        "max_duplicate_objects": 1,
    }
    values[field] = value

    with pytest.raises(ValueError, match=rf"between 1 and {maximum}"):
        OperationLimits(**values)


def test_configured_limits_are_embedded_in_provider_schema() -> None:
    limits = OperationLimits(3, 4, 5)
    schema = build_operation_plan_schema(limits)
    variants = schema["properties"]["operations"]["items"]["anyOf"]
    operations = {
        variant["properties"]["type"]["enum"][0]: variant for variant in variants
    }

    assert schema["properties"]["operations"]["maxItems"] == 3
    assert operations["SET_TRANSFORM"]["properties"]["target_ids"]["maxItems"] == 4
    assert operations["RENAME_OBJECTS"]["properties"]["renames"]["maxItems"] == 4
    assert operations["DUPLICATE_OBJECTS"]["properties"]["count"]["maximum"] == 5


def test_configured_operation_limit_is_enforced_locally() -> None:
    limits = OperationLimits(max_operations_per_plan=1)

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(
            ready_plan(
                create_primitive_operation("first_cube"),
                create_primitive_operation("second_cube"),
            ),
            limits=limits,
        )


def test_operation_schema_uses_shared_operation_registries() -> None:
    material_schema = OPERATION_SCHEMAS[OperationType.CREATE_MATERIAL_PRESET]
    procedural_schema = OPERATION_SCHEMAS[OperationType.CREATE_PROCEDURAL_MATERIAL]
    node_schema = OPERATION_SCHEMAS[OperationType.CREATE_SHADER_NODE]
    pbr_schema = OPERATION_SCHEMAS[OperationType.IMPORT_PBR_TEXTURE_SET]
    generated_schema = OPERATION_SCHEMAS[OperationType.GENERATE_TEXTURE_IMAGE]
    bake_schema = OPERATION_SCHEMAS[OperationType.BAKE_TEXTURE_PASS]

    assert tuple(material_schema["properties"]["material_family"]["enum"]) == MATERIAL_FAMILIES
    assert tuple(procedural_schema["properties"]["pattern"]["enum"]) == PROCEDURAL_PATTERNS
    assert tuple(node_schema["properties"]["node_type"]["enum"]) == SHADER_NODE_TYPES
    assert (
        tuple(pbr_schema["properties"]["textures"]["items"]["properties"]["role"]["enum"])
        == PBR_TEXTURE_ROLES
    )
    assert tuple(generated_schema["properties"]["pattern"]["enum"]) == GENERATED_TEXTURE_PATTERNS
    assert tuple(bake_schema["properties"]["pass_type"]["enum"]) == TEXTURE_BAKE_PASS_TYPES


def test_configured_target_limit_is_enforced_locally() -> None:
    operation = deepcopy(VALID_OPERATIONS[3])
    operation["target_ids"] = ["obj_0001", "obj_0002", "obj_0003"]

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(
            ready_plan(operation),
            limits=OperationLimits(max_targets_per_operation=2),
        )


def test_configured_duplicate_output_limit_uses_targets_times_count() -> None:
    operation = deepcopy(VALID_OPERATIONS[2])
    operation["target_ids"] = ["obj_0001", "obj_0002"]
    operation["count"] = 3

    with pytest.raises(OperationContractError, match="more than 5"):
        validate_operation_plan(
            ready_plan(operation),
            limits=OperationLimits(
                max_targets_per_operation=2,
                max_duplicate_objects=5,
            ),
        )


@pytest.mark.parametrize(
    "operation",
    VALID_OPERATIONS,
    ids=[operation["type"].lower() for operation in VALID_OPERATIONS],
)
def test_each_supported_operation_validates(operation: dict[str, Any]) -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(operation)))

    assert plan.operations[0].type.value == operation["type"]


def test_valid_ready_plan_becomes_typed_model() -> None:
    plan = validate_operation_plan(ready_plan(create_primitive_operation()))

    assert plan.status is PlanStatus.READY
    assert plan.operations[0].type is OperationType.CREATE_PRIMITIVE
    assert plan.operations[0].operation_id == "create_cube"
    assert plan.operations[0].payload["primitive"] == "cube"


def test_validated_operation_payload_is_deeply_immutable() -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(VALID_OPERATIONS[8])))
    renames = plan.operations[0].payload["renames"]

    assert isinstance(renames, tuple)
    with pytest.raises(TypeError):
        renames[0]["new_name"] = "ChangedAfterApproval"


def test_valid_clarification_has_no_operations() -> None:
    plan = validate_operation_plan(
        {
            "snapshot_id": SNAPSHOT_ID,
            "status": "needs_clarification",
            "intent_summary": "The target objects are unclear.",
            "assumptions": [],
            "questions": ["Which objects should be changed?"],
            "operations": [],
        }
    )

    assert plan.status is PlanStatus.NEEDS_CLARIFICATION
    assert not plan.operations


def test_unknown_fields_are_rejected() -> None:
    operation = create_primitive_operation()
    operation["python_code"] = "import bpy"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_unknown_operation_type_is_rejected() -> None:
    operation = create_primitive_operation()
    operation["type"] = "RUN_PYTHON"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_ready_plan_requires_an_operation() -> None:
    with pytest.raises(OperationContractError, match="at least one operation"):
        validate_operation_plan(ready_plan())


def test_clarification_cannot_include_operations() -> None:
    data = {
        "snapshot_id": SNAPSHOT_ID,
        "status": "needs_clarification",
        "intent_summary": "More information is needed.",
        "assumptions": [],
        "questions": ["Continue?"],
        "operations": [create_primitive_operation()],
    }

    with pytest.raises(OperationContractError, match="cannot contain operations"):
        validate_operation_plan(data)


def test_duplicate_operation_ids_are_rejected() -> None:
    with pytest.raises(OperationContractError, match="Operation IDs must be unique"):
        validate_operation_plan(
            ready_plan(create_primitive_operation(), create_primitive_operation())
        )


def test_duplicate_target_ids_are_rejected_locally() -> None:
    operation = {
        "operation_id": "move_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001", "obj_0001"],
        "mode": "relative",
        "location": [1.0, 0.0, 0.0],
        "rotation_euler": None,
        "scale": None,
    }

    with pytest.raises(OperationContractError, match="target IDs must be unique"):
        validate_operation_plan(ready_plan(operation))


def test_plan_must_match_the_expected_scene_snapshot() -> None:
    with pytest.raises(OperationContractError, match="different scene snapshot"):
        validate_operation_plan(
            ready_plan(create_primitive_operation()),
            expected_snapshot_id="b" * 32,
        )


def test_transform_must_change_at_least_one_component() -> None:
    operation = {
        "operation_id": "transform_cube",
        "type": "SET_TRANSFORM",
        "target_ids": ["obj_0001"],
        "mode": "absolute",
        "location": None,
        "rotation_euler": None,
        "scale": None,
    }

    with pytest.raises(OperationContractError, match="must change"):
        validate_operation_plan(ready_plan(operation))


def test_property_update_operations_must_change_at_least_one_component() -> None:
    operations: list[dict[str, Any]] = [
        {
            "operation_id": "set_material_properties",
            "type": "SET_MATERIAL_PROPERTIES",
            "material_id": "mat_0001",
            "base_color": None,
            "metallic": None,
            "roughness": None,
            "alpha": None,
        },
        {
            "operation_id": "set_light_properties",
            "type": "SET_LIGHT_PROPERTIES",
            "target_ids": ["obj_0001"],
            "color": None,
            "energy": None,
            "size": None,
        },
        {
            "operation_id": "set_camera_properties",
            "type": "SET_CAMERA_PROPERTIES",
            "target_ids": ["obj_0001"],
            "focal_length": None,
            "make_active": None,
        },
        {
            "operation_id": "set_modifier_properties",
            "type": "SET_MODIFIER_PROPERTIES",
            "target_ids": ["obj_0001"],
            "modifier_name": "AI Bevel",
            "width": None,
            "segments": None,
            "thickness": None,
            "count": None,
            "relative_offset": None,
            "levels": None,
            "axis": None,
        },
        {
            "operation_id": "set_visibility",
            "type": "SET_OBJECT_VISIBILITY",
            "target_ids": ["obj_0001"],
            "viewport_visible": None,
            "render_visible": None,
        },
    ]

    for operation in operations:
        with pytest.raises(OperationContractError, match="must change"):
            validate_operation_plan(ready_plan(operation))


def test_zero_scale_is_rejected() -> None:
    operation = create_primitive_operation()
    operation["scale"] = [1.0, 0.0, 1.0]

    with pytest.raises(OperationContractError, match="cannot be zero"):
        validate_operation_plan(ready_plan(operation))


def test_material_color_outside_normalized_range_is_rejected() -> None:
    operation = deepcopy(VALID_OPERATIONS[4])
    operation["base_color"] = [1.5, 0.0, 0.0]

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(operation))


def test_non_finite_numbers_are_rejected() -> None:
    operation = create_primitive_operation()
    operation["location"] = [float("nan"), 0.0, 0.0]

    with pytest.raises(OperationContractError, match="non-finite"):
        validate_operation_plan(ready_plan(operation))


def test_duplicate_blast_radius_is_bounded() -> None:
    operation = {
        "operation_id": "duplicate_cubes",
        "type": "DUPLICATE_OBJECTS",
        "target_ids": ["obj_0001", "obj_0002"],
        "count": 51,
        "offset": [1.0, 0.0, 0.0],
        "name_prefix": None,
    }

    with pytest.raises(OperationContractError, match="more than 100"):
        validate_operation_plan(ready_plan(operation))


def test_import_asset_accepts_https_urls() -> None:
    operation = deepcopy(VALID_OPERATIONS[18])
    operation["filepath"] = "https://example.com/assets/model.obj"

    plan = validate_operation_plan(ready_plan(operation))

    assert plan.operations[0].payload["filepath"] == "https://example.com/assets/model.obj"


def test_import_asset_rejects_non_https_url_and_extension_mismatches() -> None:
    url_operation = deepcopy(VALID_OPERATIONS[18])
    url_operation["filepath"] = "http://example.com/model.obj"
    with pytest.raises(OperationContractError, match="must use HTTPS"):
        validate_operation_plan(ready_plan(url_operation))

    mismatch_operation = deepcopy(VALID_OPERATIONS[18])
    mismatch_operation["filepath"] = "C:\\assets\\test.fbx"
    with pytest.raises(OperationContractError, match="must end with"):
        validate_operation_plan(ready_plan(mismatch_operation))


def test_blend_data_names_must_be_unique() -> None:
    operation = deepcopy(VALID_OPERATIONS[19])
    operation["datablock_names"] = ["AssetCube", "AssetCube"]

    with pytest.raises(OperationContractError, match="must be unique"):
        validate_operation_plan(ready_plan(operation))


def test_boolean_operation_rejects_self_target_and_apply_true() -> None:
    self_target = deepcopy(VALID_OPERATIONS[20])
    self_target["cutter_id"] = "obj_0001"
    with pytest.raises(OperationContractError, match="must be different"):
        validate_operation_plan(ready_plan(self_target))

    apply_true = deepcopy(VALID_OPERATIONS[20])
    apply_true["apply"] = True
    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(apply_true))


def test_later_operation_can_reference_an_earlier_creation_result() -> None:
    create_material = deepcopy(VALID_OPERATIONS[4])
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_red_material"

    plan = validate_operation_plan(ready_plan(create_material, assign_material))

    assert plan.operations[1].payload["material_id"] == "result:create_red_material"


def test_later_operation_can_reference_an_earlier_collection_result() -> None:
    create_collection = deepcopy(VALID_OPERATIONS[11])
    create_cube = create_primitive_operation()
    create_cube["collection_id"] = "result:create_collection"

    plan = validate_operation_plan(ready_plan(create_collection, create_cube))

    assert plan.operations[1].payload["collection_id"] == "result:create_collection"


def test_track_b_texture_and_uv_operations_validate_as_a_chain() -> None:
    load_image = {
        "operation_id": "load_texture",
        "type": "LOAD_IMAGE_TEXTURE",
        "source": "C:\\assets\\base_color.png",
        "image_name": "Base Color",
        "color_space": "sRGB",
        "max_size_mb": 5,
    }
    create_node = {
        "operation_id": "create_texture_node",
        "type": "CREATE_IMAGE_TEXTURE_NODE",
        "material_id": "mat_0001",
        "image_id": "result:load_texture",
        "node_label": "AI Base Color",
        "connect_to": "Base Color",
        "projection": "FLAT",
        "extension": "REPEAT",
    }
    set_mapping = {
        "operation_id": "set_texture_mapping",
        "type": "SET_TEXTURE_MAPPING",
        "material_id": "mat_0001",
        "texture_node_ref": "result:create_texture_node",
        "translation": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
        "projection": "FLAT",
        "extension": "REPEAT",
    }
    assign_uv = {
        "operation_id": "assign_uv",
        "type": "ASSIGN_UV_MAP",
        "target_id": "obj_0001",
        "material_id": "mat_0001",
        "texture_node_ref": "result:create_texture_node",
        "uv_map_name": "UVMap",
    }
    create_uv = {
        "operation_id": "create_uv",
        "type": "CREATE_UV_MAP",
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_UV",
        "set_active": True,
        "set_render": True,
    }
    unwrap = {
        "operation_id": "unwrap_uv",
        "type": "UNWRAP_UV_MAP",
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_UV",
        "method": "smart_project",
        "create_if_missing": True,
        "overwrite_existing": True,
        "margin": 0.02,
    }
    pack = {
        "operation_id": "pack_uv",
        "type": "PACK_UV_ISLANDS",
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_UV",
        "margin": 0.02,
        "rotate": True,
    }

    plan = validate_operation_plan(
        ready_plan(load_image, create_node, set_mapping, assign_uv, create_uv, unwrap, pack)
    )

    assert plan.operations[1].payload["image_id"] == "result:load_texture"
    assert plan.operations[2].payload["texture_node_ref"] == "result:create_texture_node"


def test_track_c_pbr_operations_validate_as_a_chain() -> None:
    pbr_set = {
        "operation_id": "import_pbr",
        "type": "IMPORT_PBR_TEXTURE_SET",
        "name_prefix": "HeroPBR",
        "textures": [
            {
                "role": "base_color",
                "source": "C:\\assets\\hero_base_color.png",
                "color_space": "sRGB",
                "max_size_mb": 5,
            },
            {
                "role": "roughness",
                "source": "C:\\assets\\hero_roughness.png",
                "color_space": "Non-Color",
                "max_size_mb": 5,
            },
        ],
    }
    load_normal = {
        "operation_id": "load_normal",
        "type": "LOAD_IMAGE_TEXTURE",
        "source": "C:\\assets\\hero_normal.png",
        "image_name": "Hero Normal",
        "color_space": "Non-Color",
        "max_size_mb": 5,
    }
    role_fix = {
        "operation_id": "set_normal_role",
        "type": "SET_PBR_TEXTURE_ROLE",
        "texture_set_id": "result:import_pbr",
        "image_id": "result:load_normal",
        "role": "normal",
        "color_space": "Non-Color",
    }
    material = {
        "operation_id": "create_pbr_material",
        "type": "CREATE_PBR_MATERIAL",
        "name": "Hero PBR",
        "texture_set_id": "result:import_pbr",
        "base_color_image_id": None,
        "roughness_image_id": None,
        "metallic_image_id": None,
        "normal_image_id": "result:load_normal",
        "ambient_occlusion_image_id": None,
        "displacement_image_id": None,
        "alpha_image_id": None,
        "emission_image_id": None,
        "base_color": [0.8, 0.8, 0.8],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
    }

    plan = validate_operation_plan(ready_plan(pbr_set, load_normal, role_fix, material))

    assert plan.operations[-1].type is OperationType.CREATE_PBR_MATERIAL


def test_tracks_d_to_f_image_generation_paint_and_bake_validate_as_a_chain() -> None:
    create_material = deepcopy(VALID_OPERATIONS[4])
    create_uv = {
        "operation_id": "create_uv",
        "type": "CREATE_UV_MAP",
        "target_ids": ["obj_0001"],
        "uv_map_name": "AI_UV",
        "set_active": True,
        "set_render": True,
    }
    generate = {
        "operation_id": "generate_texture",
        "type": "GENERATE_TEXTURE_IMAGE",
        "prompt": "blue brushed ceramic texture",
        "image_name": "Generated Texture",
        "width": 64,
        "height": 64,
        "pattern": "checker",
        "base_color": [0.1, 0.2, 0.8, 1.0],
        "secondary_color": [0.8, 0.9, 1.0, 1.0],
        "color_space": "sRGB",
        "pack": True,
    }
    save = {
        "operation_id": "save_generated",
        "type": "SAVE_GENERATED_TEXTURE",
        "image_id": "result:generate_texture",
        "filepath": "C:\\assets\\generated_texture.png",
        "file_format": "PNG",
        "pack_after_save": True,
    }
    attach = {
        "operation_id": "attach_generated",
        "type": "ATTACH_GENERATED_TEXTURE",
        "material_id": "result:create_red_material",
        "image_id": "result:generate_texture",
        "node_label": "AI Generated",
        "connect_to": "Base Color",
        "uv_map_name": None,
    }
    paint_image = {
        "operation_id": "create_paint_image",
        "type": "CREATE_PAINT_IMAGE",
        "image_name": "Paint Image",
        "width": 32,
        "height": 32,
        "fill_color": [0.0, 0.0, 0.0, 1.0],
        "color_space": "sRGB",
        "pack": True,
    }
    paint_slot = {
        "operation_id": "assign_paint_slot",
        "type": "ASSIGN_PAINT_SLOT",
        "target_id": "obj_0001",
        "material_id": "result:create_red_material",
        "image_id": "result:create_paint_image",
        "uv_map_name": "AI_UV",
        "node_label": "AI Paint",
        "connect_to": "Base Color",
    }
    paint = {
        "operation_id": "paint_strokes",
        "type": "APPLY_TEXTURE_PAINT_STROKES",
        "image_id": "result:create_paint_image",
        "blend_mode": "mix",
        "strokes": [
            {
                "uv": [0.5, 0.5],
                "color": [1.0, 0.0, 0.0, 1.0],
                "radius": 0.1,
                "strength": 0.75,
            }
        ],
    }
    fill = {
        "operation_id": "fill_region",
        "type": "FILL_TEXTURE_REGION",
        "image_id": "result:create_paint_image",
        "region": {"kind": "rect", "min_uv": [0.1, 0.1], "max_uv": [0.4, 0.4]},
        "color": [0.0, 1.0, 0.0, 1.0],
        "strength": 0.5,
        "blend_mode": "replace",
    }
    bake_target = {
        "operation_id": "create_bake_target",
        "type": "CREATE_BAKE_TARGET_IMAGE",
        "image_name": "Bake Target",
        "width": 32,
        "height": 32,
        "fill_color": [0.0, 0.0, 0.0, 1.0],
        "color_space": "sRGB",
        "pack": True,
    }
    bake = {
        "operation_id": "bake_pass",
        "type": "BAKE_TEXTURE_PASS",
        "target_id": "obj_0001",
        "image_id": "result:create_bake_target",
        "uv_map_name": "AI_UV",
        "pass_type": "base_color",
        "samples": 8,
        "margin": 0.02,
    }
    assign_baked = {
        "operation_id": "assign_baked",
        "type": "ASSIGN_BAKED_TEXTURE",
        "material_id": "result:create_red_material",
        "image_id": "result:create_bake_target",
        "node_label": "AI Baked",
        "connect_to": "Base Color",
        "uv_map_name": "AI_UV",
    }

    plan = validate_operation_plan(
        ready_plan(
            create_material,
            create_uv,
            generate,
            save,
            attach,
            paint_image,
            paint_slot,
            paint,
            fill,
            bake_target,
            bake,
            assign_baked,
        )
    )

    assert plan.operations[-1].payload["image_id"] == "result:create_bake_target"


def test_tracks_g_to_k_geometry_mesh_sculpt_topology_and_preview_validate() -> None:
    geometry_nodes = {
        "operation_id": "geo_nodes",
        "type": "CREATE_GEOMETRY_NODES_PRESET",
        "target_ids": ["obj_0001"],
        "name": "AI Scatter",
        "preset": "scatter_points",
        "inputs": {
            "density": 12.0,
            "scale": 0.25,
            "strength": None,
            "count": 8.0,
            "seed": 3.0,
        },
        "apply": False,
    }
    set_geo_input = {
        "operation_id": "set_geo_input",
        "type": "SET_GEOMETRY_NODE_INPUT",
        "target_id": "obj_0001",
        "modifier_name": "AI Scatter",
        "input_name": "density",
        "value": 20.0,
    }
    smoothed_copy = {
        "operation_id": "smooth_copy",
        "type": "CREATE_SMOOTHED_COPY",
        "target_id": "obj_0001",
        "name": "Smoothed Copy",
        "strength": 0.5,
        "iterations": 2,
        "preserve_original": True,
    }
    displaced_copy = {
        "operation_id": "displaced_copy",
        "type": "CREATE_DISPLACED_COPY",
        "target_id": "obj_0001",
        "name": "Displaced Copy",
        "strength": 0.1,
        "direction": [0.0, 0.0, 1.0],
        "preserve_original": True,
    }
    replace = {
        "operation_id": "replace_copy",
        "type": "REPLACE_OBJECT_WITH_GENERATED_COPY",
        "target_id": "obj_0001",
        "generated_object_id": "result:smooth_copy",
        "hide_original": True,
    }
    sculpt_region = {
        "operation_id": "sculpt_region",
        "type": "CREATE_SCULPT_REGION_FROM_VERTEX_GROUP",
        "target_id": "obj_0001",
        "vertex_group": "Head",
        "region_name": "Head Region",
    }
    sculpt_mask = {
        "operation_id": "sculpt_mask",
        "type": "CREATE_SCULPT_MASK",
        "region_id": "result:sculpt_region",
        "mask_name": "Head Mask",
        "strength": 0.8,
    }
    sculpt_apply = {
        "operation_id": "sculpt_apply",
        "type": "APPLY_SCULPT_REGION_OPERATION",
        "region_id": "result:sculpt_region",
        "operation": "smooth",
        "strength": 0.4,
        "iterations": 1,
    }
    multires = {
        "operation_id": "multires",
        "type": "ADD_MULTIRES_MODIFIER",
        "target_ids": ["obj_0001"],
        "name": "AI Multires",
        "levels": 1,
        "render_levels": 1,
        "apply": False,
    }
    shape_key = {
        "operation_id": "shape_key",
        "type": "CREATE_SHAPE_KEY",
        "target_id": "obj_0001",
        "name": "AI Shape",
        "value": 0.5,
        "from_generated_object_id": "result:displaced_copy",
    }
    preview = {
        "operation_id": "preview",
        "type": "CREATE_PREVIEW_IMAGE",
        "preview_name": "AI Preview",
        "preview_kind": "generated_mesh",
        "target_id": "result:smooth_copy",
        "material_id": None,
        "width": 64,
        "height": 64,
    }

    plan = validate_operation_plan(
        ready_plan(
            geometry_nodes,
            set_geo_input,
            smoothed_copy,
            displaced_copy,
            replace,
            sculpt_region,
            sculpt_mask,
            sculpt_apply,
            multires,
            shape_key,
            preview,
        )
    )

    assert plan.operations[-1].type is OperationType.CREATE_PREVIEW_IMAGE


def test_track_a_shader_graph_editing_validates_as_a_chain() -> None:
    create_material = deepcopy(VALID_OPERATIONS[4])
    ramp = {
        "operation_id": "create_ramp",
        "type": "CREATE_SHADER_COLOR_RAMP",
        "material_id": "result:create_red_material",
        "node_label": "AI Ramp",
        "stops": [
            {"position": 0.0, "color": [0.0, 0.0, 1.0, 1.0]},
            {"position": 1.0, "color": [1.0, 0.0, 0.0, 1.0]},
        ],
    }
    set_ramp = {
        "operation_id": "set_ramp",
        "type": "SET_SHADER_COLOR_RAMP",
        "material_id": "result:create_red_material",
        "node_ref": "result:create_ramp",
        "stops": [
            {"position": 0.0, "color": [0.0, 1.0, 0.0, 1.0]},
            {"position": 1.0, "color": [1.0, 1.0, 0.0, 1.0]},
        ],
    }
    mix_chain = {
        "operation_id": "mix_chain",
        "type": "CREATE_SHADER_MIX_CHAIN",
        "material_id": "result:create_red_material",
        "chain_label": "AI Mix",
        "template": "noise_to_base_color",
        "base_color": [0.0, 0.0, 1.0, 1.0],
        "secondary_color": [1.0, 0.0, 0.0, 1.0],
        "strength": 0.5,
        "scale": 12.0,
    }
    disconnect = {
        "operation_id": "disconnect_mix",
        "type": "DISCONNECT_SHADER_LINK",
        "material_id": "result:create_red_material",
        "from_node": "result:mix_chain",
        "from_socket": "Fac",
        "to_node": "principled_bsdf",
        "to_socket": "Base Color",
    }
    remove = {
        "operation_id": "remove_ramp",
        "type": "REMOVE_SHADER_NODE",
        "material_id": "result:create_red_material",
        "node_ref": "result:create_ramp",
        "assistant_created_only": True,
    }
    validate_output = {
        "operation_id": "validate_output",
        "type": "VALIDATE_MATERIAL_OUTPUT",
        "material_id": "result:create_red_material",
        "repair": True,
    }

    plan = validate_operation_plan(
        ready_plan(
            create_material,
            ramp,
            set_ramp,
            mix_chain,
            disconnect,
            remove,
            validate_output,
        )
    )

    assert plan.operations[-1].type is OperationType.VALIDATE_MATERIAL_OUTPUT


def test_color_ramp_positions_must_be_sorted() -> None:
    operation = {
        "operation_id": "bad_ramp",
        "type": "CREATE_SHADER_COLOR_RAMP",
        "material_id": "mat_0001",
        "node_label": "Bad Ramp",
        "stops": [
            {"position": 1.0, "color": [1.0, 0.0, 0.0, 1.0]},
            {"position": 0.0, "color": [0.0, 0.0, 1.0, 1.0]},
        ],
    }

    with pytest.raises(OperationContractError, match="positions must be sorted"):
        validate_operation_plan(ready_plan(operation))


def test_controlled_residual_features_validate_as_a_chain() -> None:
    create_material = deepcopy(VALID_OPERATIONS[4])
    create_camera = deepcopy(VALID_OPERATIONS[7])
    shader_template = {
        "operation_id": "shader_template",
        "type": "CREATE_SHADER_GRAPH_TEMPLATE",
        "material_id": "result:create_red_material",
        "graph_label": "AI Graph",
        "template": "layered_noise_material",
        "base_color": [0.1, 0.1, 0.8, 1.0],
        "secondary_color": [0.9, 0.2, 0.1, 1.0],
        "strength": 0.4,
        "scale": 16.0,
    }
    geometry_group = {
        "operation_id": "geometry_group",
        "type": "CREATE_GEOMETRY_NODE_GROUP_TEMPLATE",
        "target_ids": ["obj_0001"],
        "name": "AI Group",
        "template": "point_scatter_group",
        "inputs": {
            "density": 8.0,
            "scale": 0.2,
            "strength": None,
            "count": 5.0,
            "seed": 1.0,
        },
        "apply": False,
    }
    dyntopo_copy = {
        "operation_id": "dyntopo_copy",
        "type": "CREATE_DYNAMIC_TOPOLOGY_COPY",
        "target_id": "obj_0001",
        "name": "Dynamic Copy",
        "detail_level": 2,
        "preserve_original": True,
    }
    apply_generated = {
        "operation_id": "apply_generated",
        "type": "APPLY_GENERATED_MESH_TO_OBJECT",
        "target_id": "obj_0001",
        "generated_object_id": "result:dyntopo_copy",
        "preserve_original_data": True,
        "hide_generated": True,
    }
    face_set_material = {
        "operation_id": "face_set_material",
        "type": "CREATE_FACE_SET_FROM_MATERIAL",
        "target_id": "obj_0001",
        "material_id": "result:create_red_material",
        "face_set_name": "Material Faces",
    }
    face_set_group = {
        "operation_id": "face_set_group",
        "type": "CREATE_FACE_SET_FROM_VERTEX_GROUP",
        "target_id": "obj_0001",
        "vertex_group": "Head",
        "face_set_name": "Group Faces",
    }
    rig_safe_key = {
        "operation_id": "rig_safe_key",
        "type": "CREATE_RIG_SAFE_SHAPE_KEY",
        "target_id": "obj_0001",
        "name": "Rig Safe",
        "value": 0.25,
        "from_generated_object_id": "result:dyntopo_copy",
        "allow_rigged": False,
        "preserve_animation": True,
    }
    set_key = {
        "operation_id": "set_key",
        "type": "SET_SHAPE_KEY_VALUE",
        "target_id": "obj_0001",
        "shape_key_name": "Rig Safe",
        "value": 0.75,
    }
    render_preview = {
        "operation_id": "render_preview",
        "type": "CREATE_RENDER_PREVIEW_IMAGE",
        "preview_name": "Render Preview",
        "mode": "material",
        "target_id": "obj_0001",
        "camera_id": "result:add_camera",
        "width": 64,
        "height": 64,
        "samples": 8,
        "pack": True,
    }

    plan = validate_operation_plan(
        ready_plan(
            create_material,
            create_camera,
            shader_template,
            geometry_group,
            dyntopo_copy,
            apply_generated,
            face_set_material,
            face_set_group,
            rig_safe_key,
            set_key,
            render_preview,
        )
    )

    assert plan.operations[-1].type is OperationType.CREATE_RENDER_PREVIEW_IMAGE


def test_apply_generated_mesh_rejects_same_target() -> None:
    operation = {
        "operation_id": "bad_apply",
        "type": "APPLY_GENERATED_MESH_TO_OBJECT",
        "target_id": "obj_0001",
        "generated_object_id": "obj_0001",
        "preserve_original_data": True,
        "hide_generated": True,
    }

    with pytest.raises(OperationContractError, match="target and generated copy must differ"):
        validate_operation_plan(ready_plan(operation))


def test_displaced_copy_rejects_zero_direction() -> None:
    operation = {
        "operation_id": "bad_displaced_copy",
        "type": "CREATE_DISPLACED_COPY",
        "target_id": "obj_0001",
        "name": "Bad Copy",
        "strength": 0.1,
        "direction": [0.0, 0.0, 0.0],
        "preserve_original": True,
    }

    with pytest.raises(OperationContractError, match="direction cannot be zero"):
        validate_operation_plan(ready_plan(operation))


def test_forward_result_reference_is_rejected() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_red_material"

    with pytest.raises(OperationContractError, match="earlier creation operation"):
        validate_operation_plan(
            ready_plan(assign_material, deepcopy(VALID_OPERATIONS[4]))
        )


def test_result_reference_must_have_the_expected_kind() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "result:create_cube"

    with pytest.raises(OperationContractError, match="produces object, not material"):
        validate_operation_plan(ready_plan(create_primitive_operation(), assign_material))


def test_snapshot_reference_prefix_must_match_the_field_kind() -> None:
    assign_material = deepcopy(VALID_OPERATIONS[5])
    assign_material["material_id"] = "obj_0001"

    with pytest.raises(OperationContractError, match="schema validation"):
        validate_operation_plan(ready_plan(assign_material))


def test_pbr_texture_roles_are_unique_and_use_correct_color_space() -> None:
    duplicate_roles = {
        "operation_id": "import_pbr",
        "type": "IMPORT_PBR_TEXTURE_SET",
        "name_prefix": "HeroPBR",
        "textures": [
            {
                "role": "roughness",
                "source": "C:\\assets\\roughness.png",
                "color_space": "Non-Color",
                "max_size_mb": 5,
            },
            {
                "role": "roughness",
                "source": "C:\\assets\\roughness_2.png",
                "color_space": "Non-Color",
                "max_size_mb": 5,
            },
        ],
    }
    with pytest.raises(OperationContractError, match="roles must be unique"):
        validate_operation_plan(ready_plan(duplicate_roles))

    wrong_color_space = deepcopy(duplicate_roles)
    wrong_color_space["textures"] = [
        {
            "role": "roughness",
            "source": "C:\\assets\\roughness.png",
            "color_space": "sRGB",
            "max_size_mb": 5,
        }
    ]
    with pytest.raises(OperationContractError, match="must use non-color data"):
        validate_operation_plan(ready_plan(wrong_color_space))


def test_pbr_material_requires_a_texture_input() -> None:
    operation = {
        "operation_id": "create_pbr_material",
        "type": "CREATE_PBR_MATERIAL",
        "name": "Empty PBR",
        "texture_set_id": None,
        "base_color_image_id": None,
        "roughness_image_id": None,
        "metallic_image_id": None,
        "normal_image_id": None,
        "ambient_occlusion_image_id": None,
        "displacement_image_id": None,
        "alpha_image_id": None,
        "emission_image_id": None,
        "base_color": [0.8, 0.8, 0.8],
        "metallic": 0.0,
        "roughness": 0.5,
        "alpha": 1.0,
    }

    with pytest.raises(OperationContractError, match="needs texture_set_id"):
        validate_operation_plan(ready_plan(operation))


def test_texture_fill_region_requires_consistent_bounds() -> None:
    create_image = {
        "operation_id": "create_paint_image",
        "type": "CREATE_PAINT_IMAGE",
        "image_name": "Paint Image",
        "width": 32,
        "height": 32,
        "fill_color": [0.0, 0.0, 0.0, 1.0],
        "color_space": "sRGB",
        "pack": True,
    }
    fill = {
        "operation_id": "fill_region",
        "type": "FILL_TEXTURE_REGION",
        "image_id": "result:create_paint_image",
        "region": {"kind": "full", "min_uv": [0.0, 0.0], "max_uv": None},
        "color": [0.0, 1.0, 0.0, 1.0],
        "strength": 0.5,
        "blend_mode": "replace",
    }

    with pytest.raises(OperationContractError, match="full regions must use null"):
        validate_operation_plan(ready_plan(create_image, fill))


def test_sun_angular_size_is_bounded_in_radians() -> None:
    sun = deepcopy(VALID_OPERATIONS[6])
    sun["light_type"] = "sun"
    sun["size"] = 4.0

    with pytest.raises(OperationContractError, match="pi radians"):
        validate_operation_plan(ready_plan(sun))


def test_sculpt_region_schema_uses_required_nullable_fields() -> None:
    variants = OPERATION_PLAN_SCHEMA["properties"]["operations"]["items"]["anyOf"]
    sculpt_schema = next(
        variant
        for variant in variants
        if variant["properties"]["type"]["enum"] == ["SCULPT_SMOOTH_REGION"]
    )
    region_schema = sculpt_schema["properties"]["region"]

    assert set(region_schema["required"]) == set(region_schema["properties"])

    plan = validate_operation_plan(
        ready_plan(
            {
                "operation_id": "smooth_region",
                "type": "SCULPT_SMOOTH_REGION",
                "target_id": "obj_0001",
                "region": {
                    "kind": "all",
                    "material_id": None,
                    "vertex_group": None,
                },
                "strength": 0.25,
                "radius": 0.5,
                "iterations": 2,
            }
        )
    )

    assert plan.operations[0].payload["region"]["material_id"] is None


def test_low_risk_plan_does_not_require_confirmation() -> None:
    plan = validate_operation_plan(ready_plan(create_primitive_operation()))

    assessment = assess_plan_risk(plan)

    assert assessment.level is RiskLevel.LOW
    assert assessment.requires_confirmation is False


@pytest.mark.parametrize(
    ("operation", "expected_level"),
    [
        (
            {
                "operation_id": "rename_cube",
                "type": "RENAME_OBJECTS",
                "renames": [{"target_id": "obj_0001", "new_name": "HeroCube"}],
            },
            RiskLevel.MEDIUM,
        ),
        (
            {
                "operation_id": "delete_cube",
                "type": "DELETE_OBJECTS",
                "target_ids": ["obj_0001"],
                "reason": "The user explicitly requested deletion.",
            },
            RiskLevel.HIGH,
        ),
    ],
)
def test_risky_operations_require_confirmation(
    operation: dict[str, Any],
    expected_level: RiskLevel,
) -> None:
    plan = validate_operation_plan(ready_plan(deepcopy(operation)))

    assessment = assess_plan_risk(plan)

    assert assessment.level is expected_level
    assert assessment.requires_confirmation is True
