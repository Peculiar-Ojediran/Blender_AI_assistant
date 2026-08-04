import os
import sys
from pathlib import Path
from typing import Any, cast

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["OPENAI_IMAGE_GENERATION_ENABLED"] = "false"

from extension.context import (  # noqa: E402
    ContextOptions,
    ContextScope,
    TargetKind,
    read_scene_context,
)
from extension.operations import (  # noqa: E402
    ExecutionPreflightError,
    OperationLimits,
    PlanExecutionError,
    execute_plan,
    validate_operation_plan,
)


def target_id(snapshot: Any, name: str, kind: TargetKind) -> str:
    for reference_id, reference in snapshot.target_index.items():
        if reference.datablock_name == name and reference.kind is kind:
            return str(reference_id)
    raise AssertionError(f"Missing {kind.value} target for {name}.")


def ready_plan(snapshot_id: str, operations: list[dict[str, Any]]) -> Any:
    return validate_operation_plan(
        {
            "snapshot_id": snapshot_id,
            "status": "ready",
            "intent_summary": "Exercise every controlled operation.",
            "assumptions": [],
            "questions": [],
        "operations": operations,
        },
        expected_snapshot_id=snapshot_id,
        limits=OperationLimits(max_operations_per_plan=80),
    )


def vertex_group_weight(group: Any, vertex_index: int) -> float:
    try:
        return float(group.weight(vertex_index))
    except RuntimeError:
        return 0.0


scene = cast(Any, bpy.context.scene)
data: Any = cast(Any, bpy.data)
asset_dir = PROJECT_ROOT / "build" / "execution_assets"
asset_dir.mkdir(parents=True, exist_ok=True)
obj_asset_path = asset_dir / "exec_import.obj"
obj_asset_path.write_text(
    "\n".join(
        (
            "o ExecObjAsset",
            "v 0 0 0",
            "v 1 0 0",
            "v 0 1 0",
            "f 1 2 3",
            "",
        )
    ),
    encoding="utf-8",
)
png_asset_path = asset_dir / "exec_texture.png"
generated_saved_path = asset_dir / "exec_generated_saved.png"
generated_saved_path.unlink(missing_ok=True)
seed_image = data.images.new("ExecTextureSeed", width=1, height=1)
seed_image.pixels[:] = (1.0, 0.0, 0.0, 1.0)
seed_image.filepath_raw = str(png_asset_path)
seed_image.file_format = "PNG"
seed_image.save()
data.images.remove(seed_image)

source = data.objects["Cube"]
source.name = "ExecSource"

old_material = data.materials.new("ExecOldMaterial")
source.data.materials.append(old_material)
shared = source.copy()
shared.data = source.data
shared.name = "ExecShared"
scene.collection.objects.link(shared)

destination = data.collections.new("ExecDestination")
scene.collection.children.link(destination)
delete_parent = data.objects.new("ExecDeleteParent", None)
scene.collection.objects.link(delete_parent)
delete_parent.location = (2.0, 3.0, 0.0)

child_mesh = source.data.copy()
delete_child = data.objects.new("ExecDeleteChild", child_mesh)
destination.objects.link(delete_child)
delete_child.parent = delete_parent
delete_child.location = (1.0, 0.0, 0.0)
child_world_before = delete_child.matrix_world.copy()

boolean_target_mesh = source.data.copy()
boolean_target = data.objects.new("ExecBooleanTarget", boolean_target_mesh)
scene.collection.objects.link(boolean_target)
boolean_cutter_mesh = source.data.copy()
boolean_cutter = data.objects.new("ExecBooleanCutter", boolean_cutter_mesh)
scene.collection.objects.link(boolean_cutter)
boolean_cutter.location.x = 0.5

join_a = data.objects.new("ExecJoinA", source.data.copy())
scene.collection.objects.link(join_a)
join_b = data.objects.new("ExecJoinB", source.data.copy())
scene.collection.objects.link(join_b)
join_b.location.x = 3.0

separate_mesh = source.data.copy()
separate_target = data.objects.new("ExecSeparateSource", separate_mesh)
scene.collection.objects.link(separate_target)
separate_a = data.materials.new("ExecSeparateA")
separate_b = data.materials.new("ExecSeparateB")
separate_mesh.materials.append(separate_a)
separate_mesh.materials.append(separate_b)
for index, polygon in enumerate(separate_mesh.polygons):
    polygon.material_index = index % 2

texture_mesh = source.data.copy()
texture_target = data.objects.new("ExecTextureSource", texture_mesh)
scene.collection.objects.link(texture_target)
texture_material = data.materials.new("ExecTextureExistingMaterial")
texture_material.use_nodes = True
texture_mesh.materials.append(texture_material)
texture_positions_before = tuple(vertex.co.copy() for vertex in texture_mesh.vertices)

blend_asset = data.objects.new("ExecBlendAsset", source.data.copy())
scene.collection.objects.link(blend_asset)
blend_asset_path = asset_dir / "exec_library.blend"
cast(Any, bpy.ops.wm).save_as_mainfile(filepath=str(blend_asset_path))
data.objects.remove(blend_asset, do_unlink=True)
working_scene_path = asset_dir / "exec_working.blend"
cast(Any, bpy.ops.wm).save_as_mainfile(filepath=str(working_scene_path))
delete_child = data.objects["ExecDeleteChild"]
child_world_before = delete_child.matrix_world.copy()

snapshot = read_scene_context(
    bpy.context,
    ContextOptions(
        scope=ContextScope.SCENE,
        detailed_object_budget=40,
        summary_object_budget=40,
        material_budget=40,
        collection_budget=40,
    ),
)
source_id = target_id(snapshot, "ExecSource", TargetKind.OBJECT)
delete_parent_id = target_id(snapshot, "ExecDeleteParent", TargetKind.OBJECT)
destination_id = target_id(snapshot, "ExecDestination", TargetKind.COLLECTION)
boolean_target_id = target_id(snapshot, "ExecBooleanTarget", TargetKind.OBJECT)
boolean_cutter_id = target_id(snapshot, "ExecBooleanCutter", TargetKind.OBJECT)
join_a_id = target_id(snapshot, "ExecJoinA", TargetKind.OBJECT)
join_b_id = target_id(snapshot, "ExecJoinB", TargetKind.OBJECT)
separate_target_id = target_id(snapshot, "ExecSeparateSource", TargetKind.OBJECT)
texture_target_id = target_id(snapshot, "ExecTextureSource", TargetKind.OBJECT)
texture_material_id = target_id(snapshot, "ExecTextureExistingMaterial", TargetKind.MATERIAL)

plan = ready_plan(
    snapshot.snapshot_id,
    [
        {
            "operation_id": "create_collection",
            "type": "CREATE_COLLECTION",
            "name": "ExecGeneratedCollection",
            "parent_collection_id": destination_id,
        },
        {
            "operation_id": "create_mesh",
            "type": "CREATE_PRIMITIVE",
            "primitive": "cube",
            "name": "ExecCreated",
            "collection_id": "result:create_collection",
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
        {
            "operation_id": "create_material",
            "type": "CREATE_MATERIAL",
            "name": "ExecMaterial",
            "base_color": [0.2, 0.4, 0.8],
            "metallic": 0.7,
            "roughness": 0.25,
            "alpha": 0.9,
        },
        {
            "operation_id": "assign_material",
            "type": "ASSIGN_MATERIAL",
            "target_ids": ["result:create_mesh", source_id],
            "material_id": "result:create_material",
        },
        {
            "operation_id": "tune_material",
            "type": "SET_MATERIAL_PROPERTIES",
            "material_id": "result:create_material",
            "base_color": [0.9, 0.1, 0.2],
            "metallic": 0.2,
            "roughness": 0.8,
            "alpha": 1.0,
        },
        {
            "operation_id": "create_material_preset",
            "type": "CREATE_MATERIAL_PRESET",
            "name": "ExecRoughPlastic",
            "material_family": "matte_plastic",
            "base_color": [0.02, 0.02, 0.025],
            "secondary_color": [0.08, 0.08, 0.09],
            "metallic": 0.0,
            "roughness": 0.9,
            "alpha": 1.0,
            "transmission": 0.0,
            "emission_strength": 0.0,
            "texture_scale": 14.0,
            "detail_strength": 0.35,
            "bump_strength": 0.08,
        },
        {
            "operation_id": "create_procedural_wood",
            "type": "CREATE_PROCEDURAL_MATERIAL",
            "name": "ExecProceduralWood",
            "material_family": "wood",
            "pattern": "wood_grain",
            "base_color": [0.32, 0.16, 0.07],
            "secondary_color": [0.78, 0.48, 0.22],
            "metallic": 0.0,
            "roughness": 0.58,
            "alpha": 1.0,
            "texture_scale": 12.0,
            "detail_strength": 0.7,
            "bump_strength": 0.18,
        },
        {
            "operation_id": "assign_material_preset",
            "type": "ASSIGN_MATERIAL",
            "target_ids": [texture_target_id],
            "material_id": "result:create_material_preset",
        },
        {
            "operation_id": "load_image_texture",
            "type": "LOAD_IMAGE_TEXTURE",
            "source": str(png_asset_path),
            "image_name": "ExecTextureImage",
            "color_space": "sRGB",
            "max_size_mb": 1,
        },
        {
            "operation_id": "create_texture_noise_node",
            "type": "CREATE_SHADER_NODE",
            "material_id": texture_material_id,
            "node_type": "ShaderNodeTexNoise",
            "node_label": "Exec Texture Noise",
        },
        {
            "operation_id": "set_texture_noise_scale",
            "type": "SET_SHADER_NODE_VALUE",
            "material_id": texture_material_id,
            "node_ref": "result:create_texture_noise_node",
            "input_name": "Scale",
            "value": 22.0,
        },
        {
            "operation_id": "connect_texture_noise",
            "type": "CONNECT_SHADER_NODES",
            "material_id": texture_material_id,
            "from_node": "result:create_texture_noise_node",
            "from_socket": "Fac",
            "to_node": "principled_bsdf",
            "to_socket": "Roughness",
        },
        {
            "operation_id": "create_image_texture_node",
            "type": "CREATE_IMAGE_TEXTURE_NODE",
            "material_id": texture_material_id,
            "image_id": "result:load_image_texture",
            "node_label": "Exec Image Texture",
            "connect_to": "Base Color",
            "projection": "FLAT",
            "extension": "REPEAT",
        },
        {
            "operation_id": "set_texture_mapping",
            "type": "SET_TEXTURE_MAPPING",
            "material_id": texture_material_id,
            "texture_node_ref": "result:create_image_texture_node",
            "translation": [0.1, 0.2, 0.0],
            "rotation": [0.0, 0.0, 0.25],
            "scale": [2.0, 2.0, 1.0],
            "projection": "FLAT",
            "extension": "EXTEND",
        },
        {
            "operation_id": "create_uv_map",
            "type": "CREATE_UV_MAP",
            "target_ids": [texture_target_id],
            "uv_map_name": "ExecAIUV",
            "set_active": True,
            "set_render": True,
        },
        {
            "operation_id": "unwrap_uv_map",
            "type": "UNWRAP_UV_MAP",
            "target_ids": [texture_target_id],
            "uv_map_name": "ExecAIUV",
            "method": "smart_project",
            "create_if_missing": True,
            "overwrite_existing": True,
            "margin": 0.02,
        },
        {
            "operation_id": "pack_uv_islands",
            "type": "PACK_UV_ISLANDS",
            "target_ids": [texture_target_id],
            "uv_map_name": "ExecAIUV",
            "margin": 0.02,
            "rotate": True,
        },
        {
            "operation_id": "assign_uv_map",
            "type": "ASSIGN_UV_MAP",
            "target_id": texture_target_id,
            "material_id": texture_material_id,
            "texture_node_ref": "result:create_image_texture_node",
            "uv_map_name": "ExecAIUV",
        },
        {
            "operation_id": "import_pbr_set",
            "type": "IMPORT_PBR_TEXTURE_SET",
            "name_prefix": "ExecPBR",
            "textures": [
                {
                    "role": "base_color",
                    "source": str(png_asset_path),
                    "color_space": "sRGB",
                    "max_size_mb": 1,
                },
                {
                    "role": "roughness",
                    "source": str(png_asset_path),
                    "color_space": "Non-Color",
                    "max_size_mb": 1,
                },
            ],
        },
        {
            "operation_id": "load_normal_texture",
            "type": "LOAD_IMAGE_TEXTURE",
            "source": str(png_asset_path),
            "image_name": "ExecNormalTexture",
            "color_space": "Non-Color",
            "max_size_mb": 1,
        },
        {
            "operation_id": "set_pbr_normal_role",
            "type": "SET_PBR_TEXTURE_ROLE",
            "texture_set_id": "result:import_pbr_set",
            "image_id": "result:load_normal_texture",
            "role": "normal",
            "color_space": "Non-Color",
        },
        {
            "operation_id": "create_pbr_material",
            "type": "CREATE_PBR_MATERIAL",
            "name": "ExecPBRMaterial",
            "texture_set_id": "result:import_pbr_set",
            "base_color_image_id": None,
            "roughness_image_id": None,
            "metallic_image_id": None,
            "normal_image_id": "result:load_normal_texture",
            "ambient_occlusion_image_id": None,
            "displacement_image_id": None,
            "alpha_image_id": None,
            "emission_image_id": None,
            "base_color": [0.8, 0.8, 0.8],
            "metallic": 0.0,
            "roughness": 0.5,
            "alpha": 1.0,
        },
        {
            "operation_id": "generate_texture_image",
            "type": "GENERATE_TEXTURE_IMAGE",
            "prompt": "execution test generated ceramic texture",
            "image_name": "ExecGeneratedTexture",
            "width": 8,
            "height": 8,
            "pattern": "checker",
            "base_color": [0.1, 0.2, 0.8, 1.0],
            "secondary_color": [0.9, 0.9, 1.0, 1.0],
            "color_space": "sRGB",
            "pack": True,
        },
        {
            "operation_id": "generate_image_asset",
            "type": "GENERATE_IMAGE_ASSET",
            "prompt": "execution test standalone image asset",
            "image_name": "ExecGeneratedImageAsset",
            "width": 8,
            "height": 8,
            "color_space": "sRGB",
            "pack": True,
        },
        {
            "operation_id": "save_generated_texture",
            "type": "SAVE_GENERATED_TEXTURE",
            "image_id": "result:generate_texture_image",
            "filepath": str(generated_saved_path),
            "file_format": "PNG",
            "pack_after_save": True,
        },
        {
            "operation_id": "attach_generated_texture",
            "type": "ATTACH_GENERATED_TEXTURE",
            "material_id": texture_material_id,
            "image_id": "result:generate_texture_image",
            "node_label": "Exec Generated Texture",
            "connect_to": "Emission Color",
            "uv_map_name": "ExecAIUV",
        },
        {
            "operation_id": "apply_image_to_material",
            "type": "APPLY_IMAGE_TO_MATERIAL",
            "material_id": texture_material_id,
            "image_id": "result:generate_image_asset",
            "node_label": "Exec Applied Image",
            "connect_to": "Base Color",
            "projection": "FLAT",
            "extension": "EXTEND",
            "uv_map_name": None,
        },
        {
            "operation_id": "create_paint_image",
            "type": "CREATE_PAINT_IMAGE",
            "image_name": "ExecPaintImage",
            "width": 8,
            "height": 8,
            "fill_color": [0.0, 0.0, 0.0, 1.0],
            "color_space": "sRGB",
            "pack": True,
        },
        {
            "operation_id": "assign_paint_slot",
            "type": "ASSIGN_PAINT_SLOT",
            "target_id": texture_target_id,
            "material_id": texture_material_id,
            "image_id": "result:create_paint_image",
            "uv_map_name": "ExecAIUV",
            "node_label": "Exec Paint Slot",
            "connect_to": "Base Color",
        },
        {
            "operation_id": "paint_texture_strokes",
            "type": "APPLY_TEXTURE_PAINT_STROKES",
            "image_id": "result:create_paint_image",
            "blend_mode": "replace",
            "strokes": [
                {
                    "uv": [0.5, 0.5],
                    "color": [1.0, 0.0, 0.0, 1.0],
                    "radius": 0.25,
                    "strength": 1.0,
                }
            ],
        },
        {
            "operation_id": "fill_texture_region",
            "type": "FILL_TEXTURE_REGION",
            "image_id": "result:create_paint_image",
            "region": {"kind": "rect", "min_uv": [0.0, 0.0], "max_uv": [0.25, 0.25]},
            "color": [0.0, 1.0, 0.0, 1.0],
            "strength": 1.0,
            "blend_mode": "replace",
        },
        {
            "operation_id": "create_bake_target",
            "type": "CREATE_BAKE_TARGET_IMAGE",
            "image_name": "ExecBakeTarget",
            "width": 8,
            "height": 8,
            "fill_color": [0.0, 0.0, 0.0, 1.0],
            "color_space": "sRGB",
            "pack": True,
        },
        {
            "operation_id": "bake_texture_pass",
            "type": "BAKE_TEXTURE_PASS",
            "target_id": texture_target_id,
            "image_id": "result:create_bake_target",
            "uv_map_name": "ExecAIUV",
            "pass_type": "base_color",
            "samples": 4,
            "margin": 0.02,
        },
        {
            "operation_id": "assign_baked_texture",
            "type": "ASSIGN_BAKED_TEXTURE",
            "material_id": texture_material_id,
            "image_id": "result:create_bake_target",
            "node_label": "Exec Baked Texture",
            "connect_to": "Base Color",
            "uv_map_name": "ExecAIUV",
        },
        {
            "operation_id": "add_texture_displace",
            "type": "ADD_DISPLACE_MODIFIER",
            "target_ids": [texture_target_id],
            "name": "Exec Organic Surface",
            "texture_pattern": "noise",
            "strength": 0.05,
            "midlevel": 0.5,
            "texture_scale": 18.0,
            "coordinates": "local",
            "apply": False,
        },
        {
            "operation_id": "add_texture_smooth",
            "type": "ADD_SMOOTH_MODIFIER",
            "target_ids": [texture_target_id],
            "name": "Exec Surface Smooth",
            "factor": 0.35,
            "iterations": 3,
            "apply": False,
        },
        {
            "operation_id": "add_texture_remesh",
            "type": "ADD_REMESH_MODIFIER",
            "target_ids": [texture_target_id],
            "name": "Exec Remesh Preview",
            "mode": "voxel",
            "voxel_size": 0.25,
            "adaptivity": 0.0,
            "preserve_volume": True,
            "apply": False,
        },
        {
            "operation_id": "smooth_texture_region",
            "type": "SCULPT_SMOOTH_REGION",
            "target_id": texture_target_id,
            "region": {"kind": "all", "material_id": None, "vertex_group": None},
            "strength": 0.25,
            "radius": 0.5,
            "iterations": 2,
        },
        {
            "operation_id": "apply_texture_brush",
            "type": "APPLY_SCULPT_BRUSH_STROKES",
            "target_id": texture_target_id,
            "brush_type": "draw",
            "radius": 0.1,
            "strength": 0.25,
            "falloff": "smooth",
            "strokes": [
                {
                    "location": [100.0, 100.0, 100.0],
                    "normal": [0.0, 0.0, 1.0],
                    "pressure": 0.5,
                }
            ],
        },
        {
            "operation_id": "move_created",
            "type": "SET_TRANSFORM",
            "target_ids": ["result:create_mesh"],
            "mode": "relative",
            "location": [1.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.5],
            "scale": [2.0, 1.0, 1.0],
        },
        {
            "operation_id": "duplicate_source",
            "type": "DUPLICATE_OBJECTS",
            "target_ids": [source_id],
            "count": 2,
            "offset": [0.0, 1.0, 0.0],
            "name_prefix": "AI",
        },
        {
            "operation_id": "add_light",
            "type": "ADD_LIGHT",
            "light_type": "area",
            "name": "ExecLight",
            "collection_id": destination_id,
            "location": [4.0, -4.0, 6.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "color": [1.0, 0.8, 0.6],
            "energy": 800.0,
            "size": 3.0,
        },
        {
            "operation_id": "tune_light",
            "type": "SET_LIGHT_PROPERTIES",
            "target_ids": ["result:add_light"],
            "color": [0.5, 0.6, 1.0],
            "energy": 400.0,
            "size": 2.0,
        },
        {
            "operation_id": "add_camera",
            "type": "ADD_CAMERA",
            "name": "ExecCamera",
            "collection_id": destination_id,
            "location": [6.0, -6.0, 4.0],
            "rotation_euler": [1.0, 0.0, 0.8],
            "focal_length": 55.0,
            "make_active": True,
        },
        {
            "operation_id": "tune_camera",
            "type": "SET_CAMERA_PROPERTIES",
            "target_ids": ["result:add_camera"],
            "focal_length": 35.0,
            "make_active": True,
        },
        {
            "operation_id": "add_bevel",
            "type": "ADD_MODIFIER",
            "target_ids": ["result:create_mesh"],
            "modifier_type": "bevel",
            "name": "Exec Bevel",
            "width": 0.15,
            "segments": 2,
            "thickness": None,
            "count": None,
            "relative_offset": None,
            "levels": None,
            "axis": None,
        },
        {
            "operation_id": "tune_bevel",
            "type": "SET_MODIFIER_PROPERTIES",
            "target_ids": ["result:create_mesh"],
            "modifier_name": "Exec Bevel",
            "width": 0.25,
            "segments": 3,
            "thickness": None,
            "count": None,
            "relative_offset": None,
            "levels": None,
            "axis": None,
        },
        {
            "operation_id": "create_text",
            "type": "CREATE_TEXT_OBJECT",
            "name": "ExecLabel",
            "collection_id": "result:create_collection",
            "body": "AI Label",
            "location": [0.0, 0.0, 2.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "align_x": "CENTER",
            "align_y": "CENTER",
            "size": 1.25,
            "extrude": 0.05,
        },
        {
            "operation_id": "hide_created",
            "type": "SET_OBJECT_VISIBILITY",
            "target_ids": ["result:create_mesh"],
            "viewport_visible": False,
            "render_visible": True,
        },
        {
            "operation_id": "import_asset",
            "type": "IMPORT_ASSET",
            "filepath": str(obj_asset_path),
            "format": "obj",
            "collection_id": destination_id,
            "name_prefix": "ExecImport",
            "location": [0.0, 3.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "asset_metadata": None,
        },
        {
            "operation_id": "append_blend_asset",
            "type": "LINK_OR_APPEND_BLEND_DATA",
            "filepath": str(blend_asset_path),
            "mode": "append",
            "datablock_type": "object",
            "datablock_names": ["ExecBlendAsset"],
            "collection_id": destination_id,
            "name_prefix": "ExecAppend",
        },
        {
            "operation_id": "boolean_target",
            "type": "BOOLEAN_OPERATION",
            "target_id": boolean_target_id,
            "cutter_id": boolean_cutter_id,
            "boolean_operation": "difference",
            "solver": "exact",
            "apply": False,
            "modifier_name": "Exec Boolean",
            "hide_cutter": True,
        },
        {
            "operation_id": "join_meshes",
            "type": "JOIN_OBJECTS",
            "target_ids": [join_a_id, join_b_id],
            "new_name": "ExecJoined",
            "collection_id": destination_id,
        },
        {
            "operation_id": "separate_mesh",
            "type": "SEPARATE_OBJECTS",
            "target_ids": [separate_target_id],
            "mode": "by_material",
            "name_prefix": "ExecPart",
            "collection_id": destination_id,
        },
        {
            "operation_id": "rename_source",
            "type": "RENAME_OBJECTS",
            "renames": [{"target_id": source_id, "new_name": "ExecRenamed"}],
        },
        {
            "operation_id": "move_source",
            "type": "MOVE_TO_COLLECTION",
            "target_ids": [source_id],
            "collection_id": destination_id,
        },
        {
            "operation_id": "delete_parent",
            "type": "DELETE_OBJECTS",
            "target_ids": [delete_parent_id],
            "reason": "Exercise controlled deletion.",
        },
    ],
)

result = execute_plan(bpy.context, plan, snapshot)
assert result.completed_operations == 57
assert not result.partial
assert not result.rolled_back
assert result.changed_count >= 8

created = data.objects["ExecCreated"]
material = data.materials["ExecMaterial"]
renamed = data.objects["ExecRenamed"]
generated_collection = data.collections["ExecGeneratedCollection"]
assert tuple(round(float(value), 4) for value in created.location) == (1.0, 0.0, 0.0)
assert tuple(round(float(value), 4) for value in created.scale) == (2.0, 1.0, 1.0)
assert created.data.materials[0] == material
assert generated_collection.objects.get(created.name) == created
assert round(float(created.modifiers["Exec Bevel"].width), 4) == 0.25
assert int(created.modifiers["Exec Bevel"].segments) == 3
assert bool(created.hide_viewport)
assert not bool(created.hide_render)
text = data.objects["ExecLabel"]
assert text.type == "FONT"
assert text.data.body == "AI Label"
assert round(float(text.data.size), 4) == 1.25
assert round(float(text.data.extrude), 4) == 0.05
assert generated_collection.objects.get(text.name) == text
imported = [item for item in scene.objects if item.name.startswith("ExecImport_")]
assert imported
assert tuple(round(float(value), 4) for value in imported[0].location) == (0.0, 3.0, 0.0)
assert destination.objects.get(imported[0].name) == imported[0]
appended = data.objects["ExecAppend_ExecBlendAsset"]
assert destination.objects.get(appended.name) == appended
assert data.objects["ExecBooleanTarget"].modifiers["Exec Boolean"].operation == "DIFFERENCE"
assert bool(data.objects["ExecBooleanCutter"].hide_viewport)
assert data.objects.get("ExecJoinA") is None
assert data.objects.get("ExecJoinB") is None
joined = data.objects["ExecJoined"]
assert destination.objects.get(joined.name) == joined
assert len(joined.data.polygons) >= 12
assert data.objects.get("ExecSeparateSource") is None
parts = [item for item in scene.objects if item.name.startswith("ExecPart_ExecSeparateSource_")]
assert len(parts) == 2
assert all(destination.objects.get(item.name) == item for item in parts)
assert renamed.data != shared.data
assert renamed.data.materials[0] == material
assert old_material in shared.data.materials[:]
assert material not in shared.data.materials[:]
assert tuple(round(float(value), 4) for value in material.diffuse_color) == (
    0.9,
    0.1,
    0.2,
    1.0,
)
texture_preset = data.materials["ExecRoughPlastic"]
procedural_wood = data.materials["ExecProceduralWood"]
texture_image = data.images["ExecTextureImage"]
normal_image = data.images["ExecNormalTexture"]
generated_texture = data.images["ExecGeneratedTexture"]
generated_image_asset = data.images["ExecGeneratedImageAsset"]
paint_image = data.images["ExecPaintImage"]
bake_target = data.images["ExecBakeTarget"]
texture_node = texture_material.node_tree.nodes["Exec Texture Noise"]
image_texture_node = texture_material.node_tree.nodes["Exec Image Texture"]
texture_target = data.objects["ExecTextureSource"]
assert bool(texture_preset.use_nodes)
assert bool(procedural_wood.use_nodes)
assert texture_image.size[0] == 1
assert normal_image.colorspace_settings.name == "Non-Color"
assert generated_texture.size[:] == (8, 8)
assert generated_image_asset.size[:] == (8, 8)
assert generated_saved_path.exists()
assert paint_image.size[:] == (8, 8)
assert bake_target["ai_bake_pass"] == "base_color"
assert bake_target["ai_bake_source"] == "ExecTextureSource"
assert texture_target.active_material == texture_preset
assert texture_target.data.uv_layers.get("ExecAIUV") is not None
assert round(float(texture_node.inputs["Scale"].default_value), 4) == 22.0
assert image_texture_node.image == texture_image
assert image_texture_node.projection == "FLAT"
assert image_texture_node.extension == "EXTEND"
mapping_node = texture_material.node_tree.nodes["AI Mapping Exec Image Texture"]
assert tuple(round(float(value), 4) for value in mapping_node.inputs["Scale"].default_value) == (
    2.0,
    2.0,
    1.0,
)
uv_node = texture_material.node_tree.nodes["AI UV Exec Image Texture"]
assert uv_node.uv_map == "ExecAIUV"
assert data.materials["ExecPBRMaterial"].node_tree.nodes["AI PBR base_color"].image.name == (
    "ExecPBR_base_color"
)
assert texture_material.node_tree.nodes["Exec Generated Texture"].image == generated_texture
assert texture_material.node_tree.nodes["Exec Applied Image"].image == generated_image_asset
assert texture_material.node_tree.nodes["Exec Applied Image"].extension == "EXTEND"
assert texture_material.node_tree.nodes["Exec Paint Slot"].image == paint_image
assert texture_material.node_tree.nodes["Exec Baked Texture"].image == bake_target
paint_pixels = tuple(round(float(value), 4) for value in paint_image.pixels[:16])
assert paint_pixels[:4] == (0.0, 1.0, 0.0, 1.0)
assert texture_material.node_tree.links[:]
assert texture_target.modifiers["Exec Organic Surface"].type == "DISPLACE"
assert texture_target.modifiers["Exec Surface Smooth"].type == "SMOOTH"
assert texture_target.modifiers["Exec Remesh Preview"].type == "REMESH"
assert any(
    (vertex.co - before).length > 1e-6
    for vertex, before in zip(texture_target.data.vertices, texture_positions_before, strict=True)
)
assert tuple(collection.name for collection in renamed.users_collection) == (
    "ExecDestination",
)

first_duplicate = data.objects["AI_ExecSource_001"]
second_duplicate = data.objects["AI_ExecSource_002"]
assert first_duplicate.data != renamed.data
assert first_duplicate.data != second_duplicate.data
assert round(float(first_duplicate.location.y), 4) == 1.0
assert round(float(second_duplicate.location.y), 4) == 2.0

light = data.objects["ExecLight"]
camera = data.objects["ExecCamera"]
assert light.data.type == "AREA"
assert round(float(light.data.energy), 4) == 400.0
assert tuple(round(float(value), 4) for value in light.data.color) == (0.5, 0.6, 1.0)
assert round(float(light.data.size), 4) == 2.0
assert scene.camera == camera
assert round(float(camera.data.lens), 4) == 35.0
assert data.objects.get("ExecDeleteParent") is None
assert delete_child.parent is None
for row in range(4):
    for column in range(4):
        assert round(float(delete_child.matrix_world[row][column]), 4) == round(
            float(child_world_before[row][column]),
            4,
        )

variant_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(scope=ContextScope.SCENE, detailed_object_budget=20, summary_object_budget=20),
)
variant_operations: list[dict[str, Any]] = []
for primitive in ("plane", "cylinder", "cone", "torus"):
    variant_operations.append(
        {
            "operation_id": f"create_{primitive}",
            "type": "CREATE_PRIMITIVE",
            "primitive": primitive,
            "name": f"Exec{primitive.title()}",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        }
    )
for light_type, size in (("point", 0.25), ("spot", 0.5), ("sun", 0.1)):
    variant_operations.append(
        {
            "operation_id": f"create_{light_type}",
            "type": "ADD_LIGHT",
            "light_type": light_type,
            "name": f"Exec{light_type.title()}",
            "collection_id": None,
            "location": [0.0, 0.0, 2.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "color": [1.0, 1.0, 1.0],
            "energy": 100.0,
            "size": size,
        }
    )
variant_result = execute_plan(
    bpy.context,
    ready_plan(variant_snapshot.snapshot_id, variant_operations),
    variant_snapshot,
)
assert variant_result.completed_operations == 7
for primitive in ("plane", "cylinder", "cone", "torus"):
    assert len(data.objects[f"Exec{primitive.title()}"].data.vertices) > 0
assert data.objects["ExecPoint"].data.type == "POINT"
assert data.objects["ExecSpot"].data.type == "SPOT"
assert data.objects["ExecSun"].data.type == "SUN"

replace_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(scope=ContextScope.SCENE, detailed_object_budget=30, summary_object_budget=30),
)
replace_target_id = target_id(replace_snapshot, "AI_ExecSource_001", TargetKind.OBJECT)
replaced_uid = int(data.objects["AI_ExecSource_001"].session_uid)
replace_plan = ready_plan(
    replace_snapshot.snapshot_id,
    [
        {
            "operation_id": "delete_for_replacement",
            "type": "DELETE_OBJECTS",
            "target_ids": [replace_target_id],
            "reason": "Replace this exact object.",
        },
        {
            "operation_id": "create_replacement",
            "type": "CREATE_PRIMITIVE",
            "primitive": "cube",
            "name": "AI_ExecSource_001",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
    ],
)
replace_result = execute_plan(bpy.context, replace_plan, replace_snapshot)
assert replace_result.completed_operations == 2
assert int(data.objects["AI_ExecSource_001"].session_uid) != replaced_uid

collision_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(scope=ContextScope.SCENE, detailed_object_budget=20, summary_object_budget=20),
)
collision_plan = ready_plan(
    collision_snapshot.snapshot_id,
    [
        {
            "operation_id": "first_collision",
            "type": "CREATE_PRIMITIVE",
            "primitive": "cube",
            "name": "ExecCollision",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
        {
            "operation_id": "second_collision",
            "type": "ADD_CAMERA",
            "name": "ExecCollision",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "focal_length": 50.0,
            "make_active": False,
        },
    ],
)
object_count_before_collision = len(scene.objects)
try:
    execute_plan(bpy.context, collision_plan, collision_snapshot)
except ExecutionPreflightError as error:
    assert "already exists" in str(error)
else:
    raise AssertionError("Cross-operation name collision passed preflight.")
assert len(scene.objects) == object_count_before_collision
assert data.objects.get("ExecCollision") is None

rollback_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(scope=ContextScope.SCENE, detailed_object_budget=20, summary_object_budget=20),
)
rollback_plan = ready_plan(
    rollback_snapshot.snapshot_id,
    [
        {
            "operation_id": "rollback_create",
            "type": "CREATE_PRIMITIVE",
            "primitive": "sphere",
            "name": "ExecRollback",
            "collection_id": None,
            "location": [0.0, 0.0, 0.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
        {
            "operation_id": "rollback_light",
            "type": "ADD_LIGHT",
            "light_type": "point",
            "name": "ExecRollbackLight",
            "collection_id": None,
            "location": [0.0, 0.0, 2.0],
            "rotation_euler": [0.0, 0.0, 0.0],
            "color": [1.0, 1.0, 1.0],
            "energy": 100.0,
            "size": 0.5,
        },
    ],
)


def fail_after_first(current: int, total: int) -> None:
    assert total == 2
    if current == 1:
        raise RuntimeError("Injected execution failure")


try:
    execute_plan(
        bpy.context,
        rollback_plan,
        rollback_snapshot,
        progress_callback=fail_after_first,
    )
except PlanExecutionError as error:
    assert error.result.rolled_back
    assert not error.result.partial
    assert error.result.changed_count == 0
else:
    raise AssertionError("Injected execution failure did not stop the plan.")
assert data.objects.get("ExecRollback") is None
assert data.objects.get("ExecRollbackLight") is None

stale_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(scope=ContextScope.SCENE, detailed_object_budget=20, summary_object_budget=20),
)
renamed_id = target_id(stale_snapshot, "ExecRenamed", TargetKind.OBJECT)
stale_plan = ready_plan(
    stale_snapshot.snapshot_id,
    [
        {
            "operation_id": "stale_move",
            "type": "SET_TRANSFORM",
            "target_ids": [renamed_id],
            "mode": "relative",
            "location": [1.0, 0.0, 0.0],
            "rotation_euler": None,
            "scale": None,
        }
    ],
)
renamed.location.x += 1.0
try:
    execute_plan(bpy.context, stale_plan, stale_snapshot)
except ExecutionPreflightError as error:
    assert "changed after planning" in str(error)
else:
    raise AssertionError("Stale target passed execution preflight.")


def _reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _run_shader_track_execution() -> None:
    _reset_scene()
    material = data.materials.new("TrackAMaterial")
    material.use_nodes = True
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = cast(Any, bpy.context.object)
    cube.name = "TrackASource"
    cube.data.materials.append(material)
    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(scope=ContextScope.SCENE, include_custom_properties=True),
    )
    material_id = target_id(snapshot, "TrackAMaterial", TargetKind.MATERIAL)

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "create_noise",
                "type": "CREATE_SHADER_NODE",
                "material_id": material_id,
                "node_type": "ShaderNodeTexNoise",
                "node_label": "AI Test Noise",
            },
            {
                "operation_id": "create_ramp",
                "type": "CREATE_SHADER_COLOR_RAMP",
                "material_id": material_id,
                "node_label": "AI Test Ramp",
                "stops": [
                    {"position": 0.0, "color": [0.0, 0.0, 1.0, 1.0]},
                    {"position": 1.0, "color": [1.0, 0.0, 0.0, 1.0]},
                ],
            },
            {
                "operation_id": "connect_noise_ramp",
                "type": "CONNECT_SHADER_NODES",
                "material_id": material_id,
                "from_node": "result:create_noise",
                "from_socket": "Fac",
                "to_node": "result:create_ramp",
                "to_socket": "Fac",
            },
            {
                "operation_id": "connect_ramp_principled",
                "type": "CONNECT_SHADER_NODES",
                "material_id": material_id,
                "from_node": "result:create_ramp",
                "from_socket": "Color",
                "to_node": "principled_bsdf",
                "to_socket": "Base Color",
            },
            {
                "operation_id": "set_ramp",
                "type": "SET_SHADER_COLOR_RAMP",
                "material_id": material_id,
                "node_ref": "result:create_ramp",
                "stops": [
                    {"position": 0.0, "color": [0.0, 1.0, 0.0, 1.0]},
                    {"position": 0.5, "color": [1.0, 1.0, 0.0, 1.0]},
                    {"position": 1.0, "color": [1.0, 0.0, 0.0, 1.0]},
                ],
            },
            {
                "operation_id": "disconnect_ramp_principled",
                "type": "DISCONNECT_SHADER_LINK",
                "material_id": material_id,
                "from_node": "result:create_ramp",
                "from_socket": "Color",
                "to_node": "principled_bsdf",
                "to_socket": "Base Color",
            },
            {
                "operation_id": "mix_chain",
                "type": "CREATE_SHADER_MIX_CHAIN",
                "material_id": material_id,
                "chain_label": "AI TrackA Mix",
                "template": "noise_to_base_color",
                "base_color": [0.0, 0.0, 1.0, 1.0],
                "secondary_color": [1.0, 0.0, 0.0, 1.0],
                "strength": 0.5,
                "scale": 8.0,
            },
            {
                "operation_id": "remove_ramp",
                "type": "REMOVE_SHADER_NODE",
                "material_id": material_id,
                "node_ref": "result:create_ramp",
                "assistant_created_only": True,
            },
            {
                "operation_id": "validate_output",
                "type": "VALIDATE_MATERIAL_OUTPUT",
                "material_id": material_id,
                "repair": True,
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    assert result.completed_operations == len(plan.operations)
    assert nodes.get("AI Test Noise") is not None
    assert nodes.get("AI Test Ramp") is None
    assert nodes.get("AI TrackA Mix Noise") is not None
    assert nodes.get("AI TrackA Mix Ramp") is not None
    output = nodes.get("Material Output")
    assert output is not None
    assert output.inputs["Surface"].links
    assert any(link.to_socket.name == "Base Color" for link in links)


def _run_future_tracks_execution() -> None:
    _reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    cube = cast(Any, bpy.context.object)
    cube.name = "FutureTracksSource"
    material = data.materials.new("FutureTracksMaterial")
    cube.data.materials.append(material)
    for polygon in cube.data.polygons:
        polygon.material_index = 0
    vertex_indices = tuple(int(vertex.index) for vertex in cube.data.vertices)
    group = cube.vertex_groups.new(name="FutureRegion")
    group.add(vertex_indices[: max(1, len(vertex_indices) // 2)], 1.0, "REPLACE")

    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(scope=ContextScope.SCENE, include_custom_properties=True),
    )
    cube_id = target_id(snapshot, "FutureTracksSource", TargetKind.OBJECT)
    material_id = target_id(snapshot, "FutureTracksMaterial", TargetKind.MATERIAL)

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "geo_nodes",
                "type": "CREATE_GEOMETRY_NODES_PRESET",
                "target_ids": [cube_id],
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
            },
            {
                "operation_id": "set_geo_input",
                "type": "SET_GEOMETRY_NODE_INPUT",
                "target_id": cube_id,
                "modifier_name": "AI Scatter",
                "input_name": "density",
                "value": 20.0,
            },
            {
                "operation_id": "smooth_copy",
                "type": "CREATE_SMOOTHED_COPY",
                "target_id": cube_id,
                "name": "FutureSmoothedCopy",
                "strength": 0.5,
                "iterations": 1,
                "preserve_original": True,
            },
            {
                "operation_id": "displaced_copy",
                "type": "CREATE_DISPLACED_COPY",
                "target_id": cube_id,
                "name": "FutureDisplacedCopy",
                "strength": 0.1,
                "direction": [0.0, 0.0, 1.0],
                "preserve_original": True,
            },
            {
                "operation_id": "remeshed_copy",
                "type": "CREATE_REMESHED_COPY",
                "target_id": cube_id,
                "name": "FutureRemeshedCopy",
                "mode": "triangulate",
                "preserve_original": True,
            },
            {
                "operation_id": "replace_copy",
                "type": "REPLACE_OBJECT_WITH_GENERATED_COPY",
                "target_id": cube_id,
                "generated_object_id": "result:smooth_copy",
                "hide_original": True,
            },
            {
                "operation_id": "sculpt_region_material",
                "type": "CREATE_SCULPT_REGION_FROM_MATERIAL",
                "target_id": cube_id,
                "material_id": material_id,
                "region_name": "Material Region",
            },
            {
                "operation_id": "sculpt_region_group",
                "type": "CREATE_SCULPT_REGION_FROM_VERTEX_GROUP",
                "target_id": cube_id,
                "vertex_group": "FutureRegion",
                "region_name": "Group Region",
            },
            {
                "operation_id": "sculpt_mask",
                "type": "CREATE_SCULPT_MASK",
                "region_id": "result:sculpt_region_group",
                "mask_name": "FutureMask",
                "strength": 0.8,
            },
            {
                "operation_id": "blur_sculpt_mask",
                "type": "BLUR_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 0.5,
            },
            {
                "operation_id": "sharpen_sculpt_mask",
                "type": "SHARPEN_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 0.5,
            },
            {
                "operation_id": "grow_sculpt_mask",
                "type": "GROW_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 0.5,
            },
            {
                "operation_id": "shrink_sculpt_mask",
                "type": "SHRINK_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 0.5,
            },
            {
                "operation_id": "invert_sculpt_mask",
                "type": "INVERT_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 1.0,
            },
            {
                "operation_id": "combine_sculpt_masks",
                "type": "COMBINE_SCULPT_MASKS",
                "target_id": cube_id,
                "source_mask_name": "FutureRegion",
                "target_mask_name": "FutureMask",
                "result_mask_name": "FutureCombinedMask",
                "combine_mode": "add",
            },
            {
                "operation_id": "clear_sculpt_mask",
                "type": "CLEAR_SCULPT_MASK",
                "target_id": cube_id,
                "mask_name": "FutureMask",
                "iterations": 1,
                "strength": 1.0,
            },
            {
                "operation_id": "sculpt_apply",
                "type": "APPLY_SCULPT_REGION_OPERATION",
                "region_id": "result:sculpt_region_group",
                "operation": "smooth",
                "strength": 0.25,
                "iterations": 1,
            },
            {
                "operation_id": "multires",
                "type": "ADD_MULTIRES_MODIFIER",
                "target_ids": [cube_id],
                "name": "AI Multires",
                "levels": 1,
                "render_levels": 1,
                "apply": False,
            },
            {
                "operation_id": "shape_key",
                "type": "CREATE_SHAPE_KEY",
                "target_id": cube_id,
                "name": "Future Shape",
                "value": 0.5,
                "from_generated_object_id": "result:displaced_copy",
            },
            {
                "operation_id": "preview",
                "type": "CREATE_PREVIEW_IMAGE",
                "preview_name": "FuturePreview",
                "preview_kind": "generated_mesh",
                "target_id": "result:smooth_copy",
                "material_id": None,
                "width": 64,
                "height": 64,
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    assert result.completed_operations == len(plan.operations)
    assert cube.modifiers["AI Scatter"]["ai_input_density"] == 20.0
    assert cube.modifiers["AI Multires"].type == "MULTIRES"
    assert data.objects["FutureSmoothedCopy"].hide_viewport is False
    assert data.objects["FutureDisplacedCopy"].data.vertices[0].co.z != (
        cube.data.vertices[0].co.z
    )
    assert len(data.objects["FutureRemeshedCopy"].data.polygons) >= len(cube.data.polygons)
    assert cube.hide_viewport is True
    assert cube.vertex_groups.get("FutureMask") is not None
    assert cube.vertex_groups.get("FutureCombinedMask") is not None
    future_mask = cube.vertex_groups["FutureMask"]
    combined_mask = cube.vertex_groups["FutureCombinedMask"]
    assert all(
        vertex_group_weight(future_mask, int(vertex.index)) == 0.0
        for vertex in cube.data.vertices
    )
    assert any(
        vertex_group_weight(combined_mask, int(vertex.index)) > 0.0
        for vertex in cube.data.vertices
    )
    assert cube.data.shape_keys.key_blocks.get("Future Shape") is not None
    assert data.images["FuturePreview"]["ai_preview_kind"] == "generated_mesh"


def _run_residual_features_execution() -> None:
    _reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    cube = cast(Any, bpy.context.object)
    cube.name = "ResidualSource"
    material = data.materials.new("ResidualMaterial")
    material.use_nodes = True
    cube.data.materials.append(material)
    for polygon in cube.data.polygons:
        polygon.material_index = 0
    group = cube.vertex_groups.new(name="ResidualGroup")
    group.add(tuple(int(vertex.index) for vertex in cube.data.vertices), 1.0, "REPLACE")

    bpy.ops.object.camera_add(location=(0.0, -6.0, 4.0), rotation=(1.1, 0.0, 0.0))
    camera = cast(Any, bpy.context.object)
    camera.name = "ResidualCamera"
    cast(Any, bpy.context.scene).camera = camera

    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(scope=ContextScope.SCENE, include_custom_properties=True),
    )
    cube_id = target_id(snapshot, "ResidualSource", TargetKind.OBJECT)
    material_id = target_id(snapshot, "ResidualMaterial", TargetKind.MATERIAL)
    camera_id = target_id(snapshot, "ResidualCamera", TargetKind.OBJECT)

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "shader_template",
                "type": "CREATE_SHADER_GRAPH_TEMPLATE",
                "material_id": material_id,
                "graph_label": "AI Residual Graph",
                "template": "layered_noise_material",
                "base_color": [0.1, 0.1, 0.8, 1.0],
                "secondary_color": [0.9, 0.2, 0.1, 1.0],
                "strength": 0.4,
                "scale": 12.0,
            },
            {
                "operation_id": "geometry_group",
                "type": "CREATE_GEOMETRY_NODE_GROUP_TEMPLATE",
                "target_ids": [cube_id],
                "name": "AI Residual Group",
                "template": "point_scatter_group",
                "inputs": {
                    "density": 8.0,
                    "scale": 0.2,
                    "strength": None,
                    "count": 5.0,
                    "seed": 1.0,
                },
                "apply": False,
            },
            {
                "operation_id": "face_set_material",
                "type": "CREATE_FACE_SET_FROM_MATERIAL",
                "target_id": cube_id,
                "material_id": material_id,
                "face_set_name": "ResidualMaterialFaces",
            },
            {
                "operation_id": "face_set_group",
                "type": "CREATE_FACE_SET_FROM_VERTEX_GROUP",
                "target_id": cube_id,
                "vertex_group": "ResidualGroup",
                "face_set_name": "ResidualGroupFaces",
            },
            {
                "operation_id": "dyntopo_copy",
                "type": "CREATE_DYNAMIC_TOPOLOGY_COPY",
                "target_id": cube_id,
                "name": "ResidualDynamicCopy",
                "detail_level": 2,
                "preserve_original": True,
            },
            {
                "operation_id": "apply_generated",
                "type": "APPLY_GENERATED_MESH_TO_OBJECT",
                "target_id": cube_id,
                "generated_object_id": "result:dyntopo_copy",
                "preserve_original_data": True,
                "hide_generated": True,
            },
            {
                "operation_id": "rig_safe_key",
                "type": "CREATE_RIG_SAFE_SHAPE_KEY",
                "target_id": cube_id,
                "name": "Residual Rig Safe",
                "value": 0.25,
                "from_generated_object_id": "result:dyntopo_copy",
                "allow_rigged": False,
                "preserve_animation": True,
            },
            {
                "operation_id": "set_shape_key",
                "type": "SET_SHAPE_KEY_VALUE",
                "target_id": cube_id,
                "shape_key_name": "Residual Rig Safe",
                "value": 0.75,
            },
            {
                "operation_id": "render_preview",
                "type": "CREATE_RENDER_PREVIEW_IMAGE",
                "preview_name": "ResidualRenderPreview",
                "mode": "material",
                "target_id": cube_id,
                "camera_id": camera_id,
                "width": 64,
                "height": 64,
                "samples": 8,
                "pack": True,
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    assert result.completed_operations == len(plan.operations)
    assert material.node_tree.nodes.get("AI Residual Graph Noise") is not None
    assert cube.modifiers["AI Residual Group"]["ai_geometry_node_group_template"] == (
        "point_scatter_group"
    )
    assert any(change.datablock_kind == "face_set" for change in result.changes)
    assert data.objects["ResidualDynamicCopy"].hide_viewport is True
    assert len(cube.data.polygons) > 6
    shape_key = cube.data.shape_keys.key_blocks["Residual Rig Safe"]
    assert round(float(shape_key.value), 4) == 0.75
    preview = data.images["ResidualRenderPreview"]
    assert preview.size[:] == (64, 64)
    assert preview["ai_preview_kind"] == "render"


def _run_advanced_shading_execution() -> None:
    _reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    cube = cast(Any, bpy.context.object)
    cube.name = "AdvancedShadingSource"
    material = data.materials.new("AdvancedShadingMaterial")
    material.use_nodes = True
    cube.data.materials.append(material)
    for polygon in cube.data.polygons:
        polygon.material_index = 0

    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(scope=ContextScope.SCENE, include_custom_properties=True),
    )
    cube_id = target_id(snapshot, "AdvancedShadingSource", TargetKind.OBJECT)
    material_id = target_id(snapshot, "AdvancedShadingMaterial", TargetKind.MATERIAL)

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "layered_material",
                "type": "CREATE_LAYERED_SHADER_MATERIAL",
                "name": "AI Advanced Layered",
                "base_family": "metal",
                "base_color": [0.45, 0.24, 0.1],
                "metallic": 0.85,
                "roughness": 0.35,
                "layer_stack_label": "Aged bronze",
            },
            {
                "operation_id": "dust_layer",
                "type": "ADD_SHADER_LAYER",
                "material_id": "result:layered_material",
                "layer_type": "dust",
                "layer_name": "Dust",
                "blend_mode": "mix",
                "opacity": 0.6,
                "color": [0.8, 0.74, 0.62],
                "roughness_delta": 0.15,
                "bump_strength": 0.05,
            },
            {
                "operation_id": "dust_mask",
                "type": "SET_SHADER_LAYER_MASK",
                "material_id": "result:layered_material",
                "layer_id": "result:dust_layer",
                "mask_source": {
                    "kind": "procedural",
                    "image_id": None,
                    "uv_map_name": None,
                    "vertex_group": None,
                    "pattern": "noise",
                },
                "invert": False,
                "strength": 0.8,
            },
            {
                "operation_id": "reorder_layers",
                "type": "REORDER_SHADER_LAYERS",
                "material_id": "result:layered_material",
                "layer_order": ["result:dust_layer"],
            },
            {
                "operation_id": "pattern_set",
                "type": "CREATE_PROCEDURAL_PATTERN_NODE_SET",
                "material_id": "result:layered_material",
                "pattern": "ceramic_crackle",
                "node_set_label": "AI Advanced Pattern",
                "mapping": "object",
                "scale": 18.0,
                "contrast": 0.7,
                "roughness_influence": 0.25,
                "bump_strength": 0.08,
                "seed": 7,
            },
            {
                "operation_id": "edge_wear",
                "type": "CREATE_EDGE_WEAR_SHADER",
                "material_id": "result:layered_material",
                "node_set_label": "AI Edge Wear",
                "mapping": "object",
                "scale": 10.0,
                "contrast": 0.55,
                "roughness_influence": 0.2,
                "bump_strength": 0.05,
                "seed": 3,
            },
            {
                "operation_id": "triplanar",
                "type": "CREATE_TRIPLANAR_MAPPING_SETUP",
                "material_id": "result:layered_material",
                "node_set_label": "AI Triplanar",
                "mapping": "generated",
                "scale": 6.0,
                "contrast": 0.45,
                "roughness_influence": 0.1,
                "bump_strength": 0.04,
                "seed": 4,
            },
            {
                "operation_id": "object_gradient",
                "type": "CREATE_OBJECT_SPACE_GRADIENT_SHADER",
                "material_id": "result:layered_material",
                "node_set_label": "AI Object Gradient",
                "mapping": "object",
                "scale": 4.0,
                "contrast": 0.5,
                "roughness_influence": 0.1,
                "bump_strength": 0.0,
                "seed": 5,
            },
            {
                "operation_id": "curvature_mask",
                "type": "CREATE_CURVATURE_STYLE_MASK",
                "material_id": "result:layered_material",
                "node_set_label": "AI Curvature Mask",
                "mapping": "object",
                "scale": 24.0,
                "contrast": 0.8,
                "roughness_influence": 0.15,
                "bump_strength": 0.02,
                "seed": 6,
            },
            {
                "operation_id": "extract_palette",
                "type": "EXTRACT_MATERIAL_PALETTE_FROM_IMAGE",
                "source": "https://example.com/reference-material.png",
                "palette_name": "AI Reference Palette",
                "max_colors": 4,
                "include_roughness_guess": True,
                "include_metallic_guess": True,
                "include_pattern_hints": True,
            },
            {
                "operation_id": "reference_material",
                "type": "CREATE_MATERIAL_FROM_REFERENCE_IMAGE",
                "source": "https://example.com/reference-material.png",
                "material_name": "AI Reference Material",
                "palette_id": "result:extract_palette",
                "template_family": "matte_plastic",
                "use_generated_texture": True,
            },
            {
                "operation_id": "match_reference",
                "type": "MATCH_MATERIAL_TO_REFERENCE",
                "material_id": "result:reference_material",
                "reference_source": "https://example.com/reference-material.png",
                "match_color": True,
                "match_roughness": True,
                "match_pattern": True,
                "strength": 0.75,
            },
            {
                "operation_id": "lookdev_preview",
                "type": "CREATE_LOOKDEV_PREVIEW",
                "material_id": "result:reference_material",
                "target_id": cube_id,
                "preview_name": "AI Lookdev Preview",
                "width": 64,
                "height": 64,
                "pack": True,
            },
            {
                "operation_id": "glass",
                "type": "CREATE_GLASS_MATERIAL",
                "name": "AI Glass Material",
                "base_color": [0.35, 0.55, 0.8],
                "alpha": 0.55,
                "roughness": 0.1,
                "ior": 1.45,
                "transmission": 0.7,
                "emission_strength": 0.0,
                "density": 0.1,
                "anisotropy": 0.0,
                "template_strength": 0.8,
            },
            {
                "operation_id": "translucent",
                "type": "CREATE_TRANSLUCENT_MATERIAL",
                "name": "AI Translucent Material",
                "base_color": [0.6, 0.4, 0.8],
                "alpha": 0.65,
                "roughness": 0.35,
                "ior": 1.3,
                "transmission": 0.3,
                "emission_strength": 0.0,
                "density": 0.05,
                "anisotropy": 0.0,
                "template_strength": 0.5,
            },
            {
                "operation_id": "emission",
                "type": "CREATE_EMISSION_MATERIAL",
                "name": "AI Emission Material",
                "base_color": [1.0, 0.4, 0.1],
                "alpha": 1.0,
                "roughness": 0.2,
                "ior": 1.0,
                "transmission": 0.0,
                "emission_strength": 2.0,
                "density": 0.0,
                "anisotropy": 0.0,
                "template_strength": 1.0,
            },
            {
                "operation_id": "volume",
                "type": "CREATE_VOLUME_MATERIAL",
                "name": "AI Volume Material",
                "base_color": [0.2, 0.45, 0.7],
                "alpha": 0.4,
                "roughness": 0.6,
                "ior": 1.0,
                "transmission": 0.0,
                "emission_strength": 0.0,
                "density": 0.15,
                "anisotropy": 0.0,
                "template_strength": 0.5,
            },
            {
                "operation_id": "toon",
                "type": "CREATE_TOON_SHADER_MATERIAL",
                "name": "AI Toon Material",
                "base_color": [0.9, 0.75, 0.2],
                "alpha": 1.0,
                "roughness": 0.4,
                "ior": 1.0,
                "transmission": 0.0,
                "emission_strength": 0.0,
                "density": 0.0,
                "anisotropy": 0.0,
                "template_strength": 0.6,
            },
            {
                "operation_id": "anisotropic",
                "type": "CREATE_ANISOTROPIC_MATERIAL",
                "name": "AI Anisotropic Material",
                "base_color": [0.5, 0.5, 0.55],
                "alpha": 1.0,
                "roughness": 0.18,
                "ior": 1.0,
                "transmission": 0.0,
                "emission_strength": 0.0,
                "density": 0.0,
                "anisotropy": 0.7,
                "template_strength": 0.85,
            },
            {
                "operation_id": "cleanup_unused",
                "type": "REMOVE_UNUSED_ASSISTANT_SHADER_NODES",
                "material_id": "result:layered_material",
                "assistant_owned_only": True,
                "repair_mode": "single_safe_fix",
                "layout_style": "compact",
            },
            {
                "operation_id": "normalize_layout",
                "type": "NORMALIZE_SHADER_NODE_LAYOUT",
                "material_id": "result:layered_material",
                "assistant_owned_only": True,
                "repair_mode": "single_safe_fix",
                "layout_style": "compact",
            },
            {
                "operation_id": "validate_compat",
                "type": "VALIDATE_SHADER_COMPATIBILITY",
                "material_id": "result:layered_material",
                "assistant_owned_only": True,
                "repair_mode": "single_safe_fix",
                "layout_style": "compact",
            },
            {
                "operation_id": "repair_links",
                "type": "REPAIR_BROKEN_SHADER_LINKS",
                "material_id": "result:layered_material",
                "assistant_owned_only": True,
                "repair_mode": "single_safe_fix",
                "layout_style": "compact",
            },
            {
                "operation_id": "consolidate_materials",
                "type": "CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS",
                "material_ids": ["result:glass", "result:translucent"],
                "canonical_material_id": "result:glass",
                "target_ids": [cube_id],
                "assistant_owned_only": True,
            },
            {
                "operation_id": "material_variant",
                "type": "CREATE_MATERIAL_VARIANT",
                "source_material_id": material_id,
                "variant_name": "AI Warmer Variant",
                "variant_label": "Warmer test variant",
                "copy_textures": True,
            },
            {
                "operation_id": "tag_variant",
                "type": "TAG_MATERIAL_VARIANT",
                "variant_id": "result:material_variant",
                "label": "Review Candidate",
                "prompt_summary": "Warmer material test.",
            },
            {
                "operation_id": "variant_preview",
                "type": "CREATE_SHADER_COMPARISON_PREVIEW",
                "target_id": cube_id,
                "source_material_id": material_id,
                "variant_id": "result:material_variant",
                "preview_name": "AI Variant Preview",
                "width": 64,
                "height": 64,
                "mode": "material",
                "pack": True,
            },
            {
                "operation_id": "accept_variant",
                "type": "ACCEPT_MATERIAL_VARIANT",
                "variant_id": "result:material_variant",
                "target_ids": [cube_id],
                "replace_material_id": material_id,
            },
            {
                "operation_id": "reject_variant",
                "type": "REJECT_MATERIAL_VARIANT",
                "variant_id": "result:material_variant",
            },
            {
                "operation_id": "remove_layer",
                "type": "REMOVE_SHADER_LAYER",
                "material_id": "result:layered_material",
                "layer_id": "result:dust_layer",
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    assert result.completed_operations == len(plan.operations)
    assert data.materials["AI Advanced Layered"]["ai_layer_stack_label"] == "Aged bronze"
    assert data.materials["AI Reference Material"]["ai_reference_template_family"] == (
        "matte_plastic"
    )
    assert data.materials["AI Glass Material"]["ai_specialized_material"] == (
        "CREATE_GLASS_MATERIAL"
    )
    assert data.materials["AI Warmer Variant"]["ai_variant_rejected"] is True
    assert cube.data.materials[0].name == "AI Warmer Variant"
    assert data.images["AI Lookdev Preview"]["ai_preview_kind"] == "lookdev"
    assert data.images["AI Variant Preview"]["ai_preview_kind"] == "shader_comparison"
    assert data.texts["AI Reference Palette"]["ai_material_palette"] is True


def _run_advanced_uv_execution() -> None:
    mesh = data.meshes.new("ExecUVMesh")
    mesh.from_pydata(
        [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        ],
        [],
        [
            (0, 1, 2, 3),
            (4, 7, 6, 5),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        ],
    )
    mesh.update()
    uv_target = data.objects.new("ExecUVTarget", mesh)
    scene.collection.objects.link(uv_target)
    uv_material = data.materials.new("ExecUVMaterial")
    mesh.materials.append(uv_material)
    for polygon in mesh.polygons:
        polygon.material_index = 0
    for uv_name, offset in (
        ("UVMap", 0.0),
        ("UVMap_Copy", 0.05),
        ("UVMap_Backup", 0.1),
        ("AI_Unused", 0.15),
    ):
        uv_layer = mesh.uv_layers.new(name=uv_name)
        for index, loop in enumerate(uv_layer.data):
            loop.uv = ((index % 4) / 4.0 + offset, ((index // 4) % 4) / 4.0 + offset)
    mesh.uv_layers.active = mesh.uv_layers["UVMap"]
    mesh.uv_layers["UVMap"].active_render = True

    camera_data = data.cameras.new("ExecUVCameraData")
    uv_camera = data.objects.new("ExecUVCamera", camera_data)
    scene.collection.objects.link(uv_camera)

    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(
            scope=ContextScope.SCENE,
            detailed_object_budget=80,
            summary_object_budget=80,
            material_budget=80,
            collection_budget=80,
        ),
    )
    uv_target_id = target_id(snapshot, "ExecUVTarget", TargetKind.OBJECT)
    uv_material_id = target_id(snapshot, "ExecUVMaterial", TargetKind.MATERIAL)
    uv_camera_id = target_id(snapshot, "ExecUVCamera", TargetKind.OBJECT)

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "uv_inspect",
                "type": "INSPECT_UV_MAP",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "include_island_estimate": True,
                "include_material_usage": True,
            },
            {
                "operation_id": "uv_diagnostic",
                "type": "CREATE_UV_DIAGNOSTIC_REPORT",
                "target_id": uv_target_id,
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
                "operation_id": "uv_overlap_preview",
                "type": "CREATE_UV_OVERLAP_PREVIEW",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "preview_name": "AI UV Overlap Preview",
                "width": 64,
                "height": 64,
                "pack": True,
            },
            {
                "operation_id": "uv_stretch_preview",
                "type": "CREATE_UV_STRETCH_PREVIEW",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "preview_name": "AI UV Stretch Preview",
                "width": 64,
                "height": 64,
                "pack": True,
            },
            {
                "operation_id": "angle_seams",
                "type": "MARK_UV_SEAMS_BY_ANGLE",
                "target_ids": [uv_target_id],
                "seam_set_name": "AI Angle Seams",
                "angle_threshold_degrees": 45.0,
                "mark_sharp_edges": True,
                "assistant_owned_only": True,
            },
            {
                "operation_id": "material_seams",
                "type": "MARK_UV_SEAMS_BY_MATERIAL",
                "target_ids": [uv_target_id],
                "material_id": uv_material_id,
                "seam_set_name": "AI Material Seams",
                "assistant_owned_only": True,
            },
            {
                "operation_id": "edge_set_seams",
                "type": "MARK_UV_SEAMS_BY_EDGE_SET",
                "target_id": uv_target_id,
                "edge_set_name": "HardSurfaceEdges",
                "seam_set_name": "AI Edge Set Seams",
                "assistant_owned_only": True,
            },
            {
                "operation_id": "clear_seams",
                "type": "CLEAR_UV_SEAMS",
                "target_ids": [uv_target_id],
                "seam_set_name": "AI Angle Seams",
                "assistant_owned_only": True,
            },
            {
                "operation_id": "create_islands",
                "type": "CREATE_UV_ISLANDS_FROM_SEAMS",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Islands",
                "seam_set_id": "result:angle_seams",
                "create_if_missing": True,
                "overwrite_existing": False,
            },
            {
                "operation_id": "smart_project",
                "type": "SMART_PROJECT_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Projection",
                "create_if_missing": True,
                "overwrite_existing": False,
                "margin": 0.02,
                "scale_to_bounds": True,
                "angle_limit_degrees": 66.0,
                "area_weight": 0.5,
                "correct_aspect": True,
            },
            {
                "operation_id": "cube_project",
                "type": "CUBE_PROJECT_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Projection",
                "create_if_missing": True,
                "overwrite_existing": True,
                "margin": 0.02,
                "scale_to_bounds": True,
                "cube_size": 1.0,
            },
            {
                "operation_id": "cylinder_project",
                "type": "CYLINDER_PROJECT_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Projection",
                "create_if_missing": True,
                "overwrite_existing": True,
                "margin": 0.02,
                "scale_to_bounds": True,
                "axis": "z",
                "radius": 1.0,
                "height": 2.0,
                "seam_position_degrees": 180.0,
            },
            {
                "operation_id": "sphere_project",
                "type": "SPHERE_PROJECT_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Projection",
                "create_if_missing": True,
                "overwrite_existing": True,
                "margin": 0.02,
                "scale_to_bounds": True,
                "axis": "z",
                "pole_axis": "y",
            },
            {
                "operation_id": "camera_project",
                "type": "CAMERA_PROJECT_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Projection",
                "create_if_missing": True,
                "overwrite_existing": True,
                "margin": 0.02,
                "scale_to_bounds": True,
                "camera_id": uv_camera_id,
            },
            {
                "operation_id": "lightmap_unwrap",
                "type": "LIGHTMAP_UNWRAP_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_Lightmap",
                "create_if_missing": True,
                "overwrite_existing": False,
                "margin": 0.02,
                "scale_to_bounds": True,
                "resolution": 1024,
                "pack": True,
                "new_uv_map_by_default": True,
            },
            {
                "operation_id": "select_islands",
                "type": "SELECT_UV_ISLANDS_BY_MATERIAL",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "material_id": uv_material_id,
                "island_set_name": "AI Material Islands",
            },
            {
                "operation_id": "transform_islands",
                "type": "TRANSFORM_UV_ISLANDS",
                "target_id": uv_target_id,
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
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
                "mode": "center",
                "bounds_min": [0.0, 0.0],
                "bounds_max": [1.0, 1.0],
            },
            {
                "operation_id": "distribute_islands",
                "type": "DISTRIBUTE_UV_ISLANDS",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
                "axis": "horizontal",
                "spacing": 0.02,
                "bounds_min": [0.0, 0.0],
                "bounds_max": [1.0, 1.0],
            },
            {
                "operation_id": "scale_islands",
                "type": "SCALE_UV_ISLANDS_TO_BOUNDS",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
                "bounds_min": [0.1, 0.1],
                "bounds_max": [0.9, 0.9],
                "preserve_aspect": True,
            },
            {
                "operation_id": "pin_islands",
                "type": "PIN_UV_ISLANDS",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
            },
            {
                "operation_id": "unpin_islands",
                "type": "UNPIN_UV_ISLANDS",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
            },
            {
                "operation_id": "set_texel_density",
                "type": "SET_UV_TEXEL_DENSITY",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "texture_resolution": [2048, 2048],
                "pixels_per_unit": 256.0,
                "unit_scale": 1.0,
                "island_set_id": None,
            },
            {
                "operation_id": "normalize_texel_density",
                "type": "NORMALIZE_UV_TEXEL_DENSITY",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "texture_resolution": [2048, 2048],
                "target_pixels_per_unit": 256.0,
                "preserve_pinned": True,
            },
            {
                "operation_id": "advanced_pack",
                "type": "PACK_UV_ISLANDS_ADVANCED",
                "target_ids": [uv_target_id],
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
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
                "tile_u": 1,
                "tile_v": 0,
            },
            {
                "operation_id": "udim_layout",
                "type": "CREATE_UDIM_TILE_LAYOUT",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_UDIM",
                "tile_count_u": 2,
                "tile_count_v": 2,
                "margin": 0.02,
                "preserve_existing_tiles": True,
            },
            {
                "operation_id": "validate_udim",
                "type": "VALIDATE_UDIM_LAYOUT",
                "target_ids": [uv_target_id],
                "uv_map_name": "AI_UDIM",
                "allowed_tile_min": [0, 0],
                "allowed_tile_max": [9, 9],
                "check_overlaps": True,
                "check_bounds": True,
            },
            {
                "operation_id": "relax_islands",
                "type": "RELAX_UV_ISLANDS",
                "target_id": uv_target_id,
                "uv_map_name": "UVMap",
                "island_set_id": "result:select_islands",
                "iterations": 3,
                "strength": 0.5,
                "preserve_pinned": True,
            },
            {
                "operation_id": "minimize_stretch",
                "type": "MINIMIZE_UV_STRETCH",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "iterations": 3,
                "strength": 0.45,
                "preserve_boundary": True,
            },
            {
                "operation_id": "repair_bounds",
                "type": "REPAIR_UV_BOUNDS",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "target_tile": [0, 0],
                "scale_to_fit": True,
                "preserve_aspect": True,
            },
            {
                "operation_id": "merge_duplicate_uvs",
                "type": "MERGE_DUPLICATE_UV_MAPS",
                "target_ids": [uv_target_id],
                "source_uv_map_names": ["UVMap_Copy", "UVMap_Backup"],
                "destination_uv_map_name": "UVMap",
                "update_texture_nodes": True,
                "remove_sources": False,
                "assistant_owned_only": True,
            },
            {
                "operation_id": "remove_unused_assistant_uvs",
                "type": "REMOVE_UNUSED_ASSISTANT_UV_MAPS",
                "target_ids": [uv_target_id],
                "assistant_owned_only": True,
                "dry_run": False,
            },
            {
                "operation_id": "validate_uv",
                "type": "VALIDATE_UV_MAP",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "checks": {
                    "missing_uvs": True,
                    "out_of_bounds": True,
                    "overlaps": True,
                    "zero_area_islands": True,
                    "stretch": True,
                },
            },
            {
                "operation_id": "generate_atlas_image",
                "type": "GENERATE_IMAGE_ASSET",
                "prompt": "clean uv atlas debug image",
                "image_name": "AI Atlas Image",
                "width": 64,
                "height": 64,
                "color_space": "sRGB",
                "pack": True,
            },
            {
                "operation_id": "fit_to_image_region",
                "type": "FIT_UV_ISLANDS_TO_IMAGE_REGION",
                "target_id": uv_target_id,
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
                "target_ids": [uv_target_id],
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
                "target_id": uv_target_id,
                "material_id": uv_material_id,
                "atlas_id": "result:atlas_layout",
                "assignments": [
                    {
                        "material_id": uv_material_id,
                        "region_name": "MainMaterial",
                        "bounds_min": [0.0, 0.0],
                        "bounds_max": [0.5, 0.5],
                    }
                ],
            },
            {
                "operation_id": "uv_guide_image",
                "type": "BAKE_UV_LAYOUT_GUIDE_IMAGE",
                "target_ids": [uv_target_id],
                "uv_map_name": "UVMap",
                "image_name": "AI UV Guide",
                "width": 64,
                "height": 64,
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
            {
                "operation_id": "create_uv_variant",
                "type": "CREATE_UV_MAP_VARIANT",
                "target_id": uv_target_id,
                "source_uv_map_name": "UVMap",
                "variant_uv_map_name": "AI_UV_Variant",
                "variant_label": "Less stretched unwrap",
                "copy_pins": True,
            },
            {
                "operation_id": "tag_uv_variant",
                "type": "TAG_UV_VARIANT",
                "target_id": uv_target_id,
                "variant_id": "result:create_uv_variant",
                "label": "Review Candidate",
                "prompt_summary": "Packed with more even texel density.",
            },
            {
                "operation_id": "uv_variant_preview",
                "type": "CREATE_UV_COMPARISON_PREVIEW",
                "target_id": uv_target_id,
                "source_uv_map_name": "UVMap",
                "variant_id": "result:create_uv_variant",
                "preview_name": "AI UV Variant Preview",
                "width": 64,
                "height": 64,
                "pack": True,
            },
            {
                "operation_id": "accept_uv_variant",
                "type": "ACCEPT_UV_VARIANT",
                "target_id": uv_target_id,
                "variant_id": "result:create_uv_variant",
                "replace_uv_map_name": "UVMap",
                "make_active": True,
                "make_render_active": True,
            },
            {
                "operation_id": "reject_uv_variant",
                "type": "REJECT_UV_VARIANT",
                "target_id": uv_target_id,
                "variant_id": "result:create_uv_variant",
                "remove_variant": True,
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    assert result.completed_operations == len(plan.operations)
    assert data.texts["AI UV Diagnostic"] is not None
    assert data.images["AI UV Overlap Preview"]["ai_preview_kind"] == (
        "CREATE_UV_OVERLAP_PREVIEW"
    )
    assert data.images["AI UV Guide"]["ai_preview_kind"] == "uv_layout_guide"
    assert data.materials["AI UV Grid Material"]["ai_uv_grid_scale"] == 8.0
    assert "ai_uv_atlas_region_0" in uv_material
    assert mesh.uv_layers.get("UVMap") is not None
    assert mesh.uv_layers.get("AI_UV_Variant") is None
    assert mesh.uv_layers.get("AI_Unused") is None


def _run_advanced_sculpting_execution() -> None:
    _reset_scene()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    cube = cast(Any, bpy.context.object)
    cube.name = "AdvancedSculptSource"
    group = cube.vertex_groups.new(name="SculptAll")
    group.add(tuple(int(vertex.index) for vertex in cube.data.vertices), 1.0, "REPLACE")
    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(scope=ContextScope.SCENE, include_custom_properties=True),
    )
    cube_id = target_id(snapshot, "AdvancedSculptSource", TargetKind.OBJECT)
    stroke = {
        "location": [1.0, 1.0, 1.0],
        "normal": [0.0, 0.0, 1.0],
        "direction": [0.25, 0.0, 0.0],
        "pressure": 1.0,
    }

    plan = ready_plan(
        snapshot.snapshot_id,
        [
            {
                "operation_id": "advanced_brush",
                "type": "APPLY_ADVANCED_SCULPT_BRUSH_STROKES",
                "target_id": cube_id,
                "brush_type": "clay",
                "radius": 2.0,
                "strength": 0.1,
                "falloff": "linear",
                "strokes": [stroke],
                "region_id": None,
                "mask_id": None,
                "preserve_original": True,
            },
            {
                "operation_id": "symmetric_brush",
                "type": "APPLY_SYMMETRIC_SCULPT_BRUSH_STROKES",
                "target_id": cube_id,
                "brush_type": "grab",
                "mirror_axes": ["x"],
                "symmetry_origin": {"kind": "object_origin", "location": None},
                "radius": 2.0,
                "strength": 0.05,
                "falloff": "smooth",
                "strokes": [stroke],
                "region_id": None,
                "mask_id": None,
            },
            {
                "operation_id": "normal_face_set",
                "type": "CREATE_FACE_SET_FROM_NORMAL_ANGLE",
                "target_id": cube_id,
                "face_set_name": "NormalFaces",
                "seed_face_index": 0,
                "angle_degrees": 45.0,
            },
            {
                "operation_id": "area_face_set",
                "type": "CREATE_FACE_SET_FROM_POLYGON_AREA",
                "target_id": cube_id,
                "face_set_name": "AreaFaces",
                "min_area": 0.0,
                "max_area": 10.0,
            },
            {
                "operation_id": "expand_face_set",
                "type": "EXPAND_FACE_SET",
                "target_id": cube_id,
                "face_set_name": "NormalFaces",
                "iterations": 1,
            },
            {
                "operation_id": "shrink_face_set",
                "type": "SHRINK_FACE_SET",
                "target_id": cube_id,
                "face_set_name": "NormalFaces",
                "iterations": 1,
            },
            {
                "operation_id": "merge_face_sets",
                "type": "MERGE_FACE_SETS",
                "target_id": cube_id,
                "source_face_set_names": ["NormalFaces", "AreaFaces"],
                "merged_face_set_name": "MergedFaces",
            },
            {
                "operation_id": "rename_face_set",
                "type": "RENAME_FACE_SET",
                "target_id": cube_id,
                "face_set_name": "MergedFaces",
                "new_face_set_name": "ReviewFaces",
            },
            {
                "operation_id": "voxel_copy",
                "type": "CREATE_VOXEL_REMESH_COPY",
                "target_id": cube_id,
                "name": "AdvancedVoxelCopy",
                "voxel_size": 0.25,
                "adaptivity": 0.0,
                "preserve_volume": True,
                "max_vertices": 80_000,
                "max_polygons": 80_000,
            },
            {
                "operation_id": "apply_voxel_copy",
                "type": "APPLY_VOXEL_REMESH_TO_GENERATED_COPY",
                "generated_object_id": "result:voxel_copy",
                "voxel_size": 0.3,
                "adaptivity": 0.0,
                "preserve_volume": True,
                "max_vertices": 80_000,
                "max_polygons": 80_000,
            },
            {
                "operation_id": "quad_prep_copy",
                "type": "CREATE_QUAD_REMESH_PREP_COPY",
                "target_id": cube_id,
                "name": "AdvancedQuadPrepCopy",
                "target_face_count": 1000,
                "preserve_sharp_edges": True,
                "preserve_original": True,
            },
            {
                "operation_id": "dyntopo_detail_copy",
                "type": "CREATE_DYNAMIC_TOPOLOGY_DETAIL_COPY",
                "target_id": cube_id,
                "generated_name": "AdvancedDyntopoCopy",
                "detail_level": 16.0,
                "method": "relative_detail",
                "preserve_original": True,
            },
            {
                "operation_id": "add_multires",
                "type": "ADD_MULTIRES_MODIFIER",
                "target_ids": [cube_id],
                "name": "Advanced Multires",
                "levels": 1,
                "render_levels": 1,
                "apply": False,
            },
            {
                "operation_id": "subdivide_multires",
                "type": "SUBDIVIDE_MULTIRES_MODIFIER",
                "target_id": cube_id,
                "modifier_name": "Advanced Multires",
                "levels": 1,
            },
            {
                "operation_id": "set_multires",
                "type": "SET_MULTIRES_LEVELS",
                "target_id": cube_id,
                "modifier_name": "Advanced Multires",
                "viewport_levels": 2,
                "sculpt_levels": 2,
                "render_levels": 2,
            },
            {
                "operation_id": "multires_copy",
                "type": "CREATE_MULTIRES_SCULPT_COPY",
                "target_id": cube_id,
                "generated_name": "AdvancedMultiresCopy",
                "levels": 1,
                "preserve_original": True,
            },
            {
                "operation_id": "multires_preview",
                "type": "BAKE_MULTIRES_DISPLACEMENT_PREVIEW",
                "target_id": cube_id,
                "modifier_name": "Advanced Multires",
                "image_name": "AdvancedMultiresPreview",
                "width": 64,
                "height": 64,
                "color_space": "Non-Color",
                "pack": True,
            },
            {
                "operation_id": "accepted_variant",
                "type": "CREATE_SCULPT_VARIANT_COPY",
                "target_id": cube_id,
                "variant_name": "AdvancedAcceptedVariant",
                "variant_label": "Accepted sculpt variant",
                "preserve_original": True,
            },
            {
                "operation_id": "tag_variant",
                "type": "TAG_SCULPT_VARIANT",
                "variant_id": "result:accepted_variant",
                "label": "Review Candidate",
                "prompt_summary": "Raised planes and cleaner silhouette.",
            },
            {
                "operation_id": "variant_preview",
                "type": "CREATE_SCULPT_COMPARISON_PREVIEW",
                "target_id": cube_id,
                "variant_id": "result:accepted_variant",
                "preview_name": "AdvancedSculptPreview",
                "width": 64,
                "height": 64,
                "mode": "material",
                "pack": True,
            },
            {
                "operation_id": "accept_variant",
                "type": "ACCEPT_SCULPT_VARIANT",
                "original_target_id": cube_id,
                "variant_id": "result:accepted_variant",
                "hide_original": False,
                "preserve_original_data": True,
            },
            {
                "operation_id": "rejected_variant",
                "type": "CREATE_SCULPT_VARIANT_COPY",
                "target_id": cube_id,
                "variant_name": "AdvancedRejectedVariant",
                "variant_label": "Rejected sculpt variant",
                "preserve_original": True,
            },
            {
                "operation_id": "reject_variant",
                "type": "REJECT_SCULPT_VARIANT",
                "variant_id": "result:rejected_variant",
            },
        ],
    )
    result = execute_plan(bpy.context, plan, snapshot)

    assert result.completed_operations == len(plan.operations)
    assert cube.data.attributes.get("NormalFaces") is not None
    assert cube.data.attributes.get("AreaFaces") is not None
    assert cube.data.attributes.get("ReviewFaces") is not None
    assert data.objects["AdvancedVoxelCopy"].modifiers["AI Voxel Remesh"].type == "REMESH"
    assert data.objects["AdvancedQuadPrepCopy"]["ai_target_face_count"] == 1000
    assert data.objects["AdvancedDyntopoCopy"]["ai_generated_variant"] == (
        "dynamic_topology_detail"
    )
    assert cube.modifiers["Advanced Multires"].levels == 2
    assert data.objects["AdvancedMultiresCopy"].modifiers["AI Multires"].type == "MULTIRES"
    assert data.images["AdvancedMultiresPreview"]["ai_preview_kind"] == (
        "multires_displacement"
    )
    assert data.objects["AdvancedAcceptedVariant"]["ai_sculpt_variant_accepted"] is True
    assert data.images["AdvancedSculptPreview"]["ai_preview_kind"] == "sculpt_comparison"
    assert data.objects.get("AdvancedRejectedVariant") is None


_run_shader_track_execution()
_run_future_tracks_execution()
_run_residual_features_execution()
_run_advanced_shading_execution()
_run_advanced_uv_execution()
_run_advanced_sculpting_execution()
print("Blender controlled execution tests: PASS")
