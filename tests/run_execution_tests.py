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
    )


scene = cast(Any, bpy.context.scene)
data: Any = cast(Any, bpy.data)
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

snapshot = read_scene_context(
    bpy.context,
    ContextOptions(
        scope=ContextScope.SCENE,
        detailed_object_budget=20,
        summary_object_budget=20,
        material_budget=20,
        collection_budget=20,
    ),
)
source_id = target_id(snapshot, "ExecSource", TargetKind.OBJECT)
delete_parent_id = target_id(snapshot, "ExecDeleteParent", TargetKind.OBJECT)
destination_id = target_id(snapshot, "ExecDestination", TargetKind.COLLECTION)

plan = ready_plan(
    snapshot.snapshot_id,
    [
        {
            "operation_id": "create_mesh",
            "type": "CREATE_PRIMITIVE",
            "primitive": "cube",
            "name": "ExecCreated",
            "collection_id": destination_id,
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
assert result.completed_operations == 10
assert not result.partial
assert not result.rolled_back
assert result.changed_count >= 8

created = data.objects["ExecCreated"]
material = data.materials["ExecMaterial"]
renamed = data.objects["ExecRenamed"]
assert tuple(round(float(value), 4) for value in created.location) == (1.0, 0.0, 0.0)
assert tuple(round(float(value), 4) for value in created.scale) == (2.0, 1.0, 1.0)
assert created.data.materials[0] == material
assert renamed.data != shared.data
assert renamed.data.materials[0] == material
assert old_material in shared.data.materials[:]
assert material not in shared.data.materials[:]
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
assert round(float(light.data.energy), 4) == 800.0
assert scene.camera == camera
assert round(float(camera.data.lens), 4) == 55.0
assert data.objects.get("ExecDeleteParent") is None
assert delete_child.parent is None
assert delete_child.matrix_world == child_world_before

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
