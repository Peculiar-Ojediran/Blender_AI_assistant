import sys
from pathlib import Path
from typing import Any, cast

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

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
        limits=OperationLimits(max_operations_per_plan=40),
    )


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
assert result.completed_operations == 23
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

print("Blender controlled execution tests: PASS")
