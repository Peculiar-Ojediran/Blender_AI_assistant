import importlib
import pkgutil
import sys
import time
from pathlib import Path
from typing import Any, cast

import bpy
import fastjsonschema
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import extension  # noqa: E402
from extension.context import (  # noqa: E402
    ContextOptions,
    ContextScope,
    TargetKind,
    read_scene_context,
    serialize_scene_context,
)
from extension.operations import (  # noqa: E402
    DEFAULT_OPERATION_LIMITS,
    HARD_MAX_DUPLICATE_OBJECTS,
    HARD_MAX_OPERATIONS_PER_PLAN,
    HARD_MAX_TARGETS_PER_OPERATION,
    OPERATION_PLAN_SCHEMA,
    OperationType,
    validate_operation_plan,
)
from extension.operations.targets import (  # noqa: E402
    TargetResolutionError,
    resolve_snapshot_targets,
)
from extension.providers.base import PlanRequest, PlanResponse, TokenUsage  # noqa: E402
from extension.providers.openai import (  # noqa: E402
    CUSTOM_MODEL_OPTION,
    OPENAI_MODEL_OPTIONS,
)
from extension.ui import planning as planning_module  # noqa: E402
from extension.ui.operators import (  # noqa: E402
    AIASSISTANT_OT_apply_plan,
    AIASSISTANT_OT_plan_changes,
)
from extension.ui.planning import (  # noqa: E402
    pending_planning_result,
    process_planning_events,
    start_planning_job,
)
from extension.ui.preferences import AIASSISTANT_AP_preferences  # noqa: E402

for module_info in pkgutil.walk_packages(extension.__path__, prefix="extension."):
    importlib.import_module(module_info.name)


class FakePlanningProvider:
    def __init__(self, snapshot_id: str) -> None:
        self.snapshot_id = snapshot_id

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        assert request.response_schema == OPERATION_PLAN_SCHEMA
        assert request.scene_context["snapshot_id"] == self.snapshot_id
        return PlanResponse(
            "resp_blender_test",
            "model_test",
            {
                "snapshot_id": self.snapshot_id,
                "status": "ready",
                "intent_summary": "Create a generated cube.",
                "assumptions": ["Use the active collection."],
                "questions": [],
                "operations": [
                    {
                        "operation_id": "create_generated_cube",
                        "type": "CREATE_PRIMITIVE",
                        "primitive": "cube",
                        "name": "Generated Cube",
                        "collection_id": None,
                        "location": [2.0, 0.0, 0.0],
                        "rotation_euler": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    }
                ],
            },
            usage=TokenUsage(
                input_tokens=120,
                cached_input_tokens=20,
                output_tokens=30,
                reasoning_tokens=10,
                total_tokens=150,
            ),
        )


class FakeDeleteProvider:
    def __init__(self, snapshot_id: str, target_id: str) -> None:
        self.snapshot_id = snapshot_id
        self.target_id = target_id

    def create_plan(self, request: PlanRequest) -> PlanResponse:
        return PlanResponse(
            "resp_delete_test",
            "model_test",
            {
                "snapshot_id": self.snapshot_id,
                "status": "ready",
                "intent_summary": "Delete the generated cube.",
                "assumptions": [],
                "questions": [],
                "operations": [
                    {
                        "operation_id": "delete_generated_cube",
                        "type": "DELETE_OBJECTS",
                        "target_ids": [self.target_id],
                        "reason": "Exercise high-risk confirmation.",
                    }
                ],
            },
        )

assert bpy.app.version >= (5, 1, 0)
assert requests.__version__ == "2.32.3"
assert fastjsonschema.VERSION == "2.21.1"

validator = fastjsonschema.compile(
    {
        "type": "object",
        "properties": {"operation": {"type": "string"}},
        "required": ["operation"],
        "additionalProperties": False,
    }
)
validator({"operation": "CREATE_PRIMITIVE"})

operation_plan = validate_operation_plan(
    {
        "snapshot_id": "a" * 32,
        "status": "ready",
        "intent_summary": "Create a cube.",
        "assumptions": [],
        "questions": [],
        "operations": [
            {
                "operation_id": "create_cube",
                "type": "CREATE_PRIMITIVE",
                "primitive": "cube",
                "name": "Cube",
                "collection_id": None,
                "location": [0.0, 0.0, 0.0],
                "rotation_euler": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
        ],
    }
)
assert operation_plan.operations[0].type is OperationType.CREATE_PRIMITIVE

objects = cast(Any, bpy.data.objects)
cube = cast(Any, objects["Cube"])
material = bpy.data.materials.new("ContextMaterial")
cube.data.materials.clear()
cube.data.materials.append(material)
cube["private_path"] = "C:\\private\\source.blend"
unused_material = bpy.data.materials.new("UnrelatedMaterial")
unused_collection = bpy.data.collections.new("UnrelatedCollection")
scene = cast(Any, bpy.context.scene)
scene.collection.children.link(unused_collection)

snapshot = read_scene_context(
    bpy.context,
    ContextOptions(
        scope=ContextScope.SELECTION,
        detailed_object_budget=1,
        summary_object_budget=1,
        include_custom_properties=True,
    ),
)
scene_context = snapshot.context
assert scene_context.scoped_object_count == 1
assert len(scene_context.detailed_objects) == 1
assert scene_context.detailed_objects[0].name == "Cube"
assert scene_context.detailed_objects[0].data["vertex_count"] == 8
assert scene_context.detailed_objects[0].custom_properties == {}
assert scene_context.omissions.file_paths == 1
material_names = [item.name for item in scene_context.materials]
collection_names = [item.name for item in scene_context.collections]
assert material_names == ["ContextMaterial"], material_names
assert "UnrelatedMaterial" not in material_names
assert "UnrelatedCollection" not in collection_names
assert scene_context.active_object_id is not None
assert snapshot.target_index[scene_context.active_object_id].datablock_name == "Cube"
assert len(snapshot.snapshot_id) == 32

snapshot_plan = validate_operation_plan(
    {
        "snapshot_id": snapshot.snapshot_id,
        "status": "ready",
        "intent_summary": "Move the selected cube.",
        "assumptions": [],
        "questions": [],
        "operations": [
            {
                "operation_id": "move_cube",
                "type": "SET_TRANSFORM",
                "target_ids": [scene_context.active_object_id],
                "mode": "relative",
                "location": [1.0, 0.0, 0.0],
                "rotation_euler": None,
                "scale": None,
            }
        ],
    },
    expected_snapshot_id=snapshot.snapshot_id,
)
assert snapshot_plan.operations[0].target_ids == (scene_context.active_object_id,)

resolved = resolve_snapshot_targets(
    snapshot,
    [scene_context.active_object_id],
    expected_kind=TargetKind.OBJECT,
)
assert resolved[scene_context.active_object_id] == cube

root_collection_id = next(
    item.target_id for item in scene_context.collections if item.parent_id is None
)
resolved_root = resolve_snapshot_targets(
    snapshot,
    [root_collection_id],
    expected_kind=TargetKind.COLLECTION,
)
assert resolved_root[root_collection_id] == scene.collection

cube.location.x = 1.0
try:
    resolve_snapshot_targets(
        snapshot,
        [scene_context.active_object_id],
        expected_kind=TargetKind.OBJECT,
    )
except TargetResolutionError as error:
    assert "changed after planning" in str(error)
else:
    raise AssertionError("A changed Blender target was not rejected as stale.")
finally:
    cube.location.x = 0.0

serialized_context = serialize_scene_context(snapshot)
assert "target_index" not in serialized_context.payload
assert "private_path" not in serialized_context.json_text
assert serialized_context.character_count == len(serialized_context.json_text)
assert serialized_context.character_count <= scene_context.character_budget

material_target_id = scene_context.materials[0].target_id
bpy.data.materials.remove(material)
bpy.data.materials.new("ContextMaterial")
try:
    resolve_snapshot_targets(
        snapshot,
        [material_target_id],
        expected_kind=TargetKind.MATERIAL,
    )
except TargetResolutionError as error:
    assert "replaced after planning" in str(error)
else:
    raise AssertionError("A replaced Blender target was not rejected as stale.")

extension.register()

assert hasattr(bpy.types.WindowManager, "blender_ai_state")
assert hasattr(bpy.types, "AIASSISTANT_PT_assistant")
assert hasattr(bpy.types, "BLENDER_AI_OT_plan_changes")
model_property: Any = AIASSISTANT_AP_preferences.bl_rna.properties["model_choice"]
model_identifiers = {item.identifier for item in model_property.enum_items}
assert model_identifiers == {
    *(identifier for identifier, _label, _description in OPENAI_MODEL_OPTIONS),
    CUSTOM_MODEL_OPTION,
}
for property_name, expected_default, expected_maximum in (
    (
        "max_plan_operations",
        DEFAULT_OPERATION_LIMITS.max_operations_per_plan,
        HARD_MAX_OPERATIONS_PER_PLAN,
    ),
    (
        "max_operation_targets",
        DEFAULT_OPERATION_LIMITS.max_targets_per_operation,
        HARD_MAX_TARGETS_PER_OPERATION,
    ),
    (
        "max_duplicate_objects",
        DEFAULT_OPERATION_LIMITS.max_duplicate_objects,
        HARD_MAX_DUPLICATE_OBJECTS,
    ),
):
    limit_property: Any = AIASSISTANT_AP_preferences.bl_rna.properties[property_name]
    assert limit_property.default == expected_default
    assert limit_property.hard_min == 1
    assert limit_property.hard_max == expected_maximum
assert hasattr(bpy.types, "AIASSISTANT_PT_limits")

window_manager = cast(Any, bpy.context.window_manager)
ui_state = window_manager.blender_ai_state
blender_ai_ops: Any = cast(Any, bpy.ops).blender_ai
assert ui_state.workflow_status == "idle"
assert ui_state.context_scope == "SELECTION"
assert not bool(ui_state.has_plan)
assert AIASSISTANT_OT_plan_changes.poll(bpy.context)
ui_state.workflow_status = "planning"
assert not AIASSISTANT_OT_plan_changes.poll(bpy.context)
ui_state.workflow_status = "idle"

ui_state.draft_prompt = "Create a cube"
assert blender_ai_ops.clear_prompt() == {"FINISHED"}
assert ui_state.draft_prompt == ""

assert not bool(ui_state.show_context_details)
assert blender_ai_ops.toggle_context_details() == {"FINISHED"}
assert bool(ui_state.show_context_details)
assert ui_state.context_included_count >= 3
assert ui_state.context_serialized_size > 0

object_count_before_planning = len(cast(Any, scene.objects))
ui_state.workflow_status = "planning"
start_planning_job(
    prompt="Create a generated cube",
    snapshot=snapshot,
    api_key="",
    provider=FakePlanningProvider(snapshot.snapshot_id),
)
deadline = time.monotonic() + 2.0
while time.monotonic() < deadline and ui_state.workflow_status == "planning":
    process_planning_events(bpy.context)
    time.sleep(0.01)

assert ui_state.workflow_status == "awaiting_approval"
assert bool(ui_state.has_plan)
assert ui_state.plan_summary == "Create a generated cube."
assert ui_state.operation_count == 1
assert ui_state.operation_previews[0].operation_id == "create_generated_cube"
assert ui_state.provider_model == "model_test"
assert ui_state.provider_call_count == 1
assert ui_state.input_tokens == 120
assert ui_state.cached_input_tokens == 20
assert ui_state.output_tokens == 30
assert ui_state.reasoning_tokens == 10
assert ui_state.total_tokens == 150
assert pending_planning_result() is not None
assert len(cast(Any, scene.objects)) == object_count_before_planning
assert AIASSISTANT_OT_apply_plan.poll(bpy.context)
assert blender_ai_ops.apply_plan() == {"FINISHED"}
assert ui_state.workflow_status == "complete"
assert not bool(ui_state.has_plan)
assert ui_state.changed_count == 2
assert len(ui_state.result_details) == 2
assert not bool(ui_state.show_result_details)
assert bool(ui_state.undo_available)
assert pending_planning_result() is None
assert cast(Any, bpy.data.objects).get("Generated Cube") is not None
assert ui_state.history[-1].status == "completed"
assert "UNDO" in AIASSISTANT_OT_apply_plan.bl_options

generated_cube = cast(Any, bpy.data.objects)["Generated Cube"]
cast(Any, bpy.ops.object).select_all(action="DESELECT")
generated_cube.select_set(True)
cast(Any, bpy.context.view_layer).objects.active = generated_cube
delete_snapshot = read_scene_context(
    bpy.context,
    ContextOptions(
        scope=ContextScope.SELECTION,
        detailed_object_budget=1,
        summary_object_budget=1,
    ),
)
delete_target_id = delete_snapshot.context.active_object_id
assert delete_target_id is not None
ui_state.workflow_status = "planning"
start_planning_job(
    prompt="Delete the generated cube",
    snapshot=delete_snapshot,
    api_key="",
    provider=FakeDeleteProvider(delete_snapshot.snapshot_id, delete_target_id),
)
deadline = time.monotonic() + 2.0
while time.monotonic() < deadline and ui_state.workflow_status == "planning":
    process_planning_events(bpy.context)
    time.sleep(0.01)

assert ui_state.workflow_status == "awaiting_approval"
assert ui_state.risk_level == "high"
assert blender_ai_ops.apply_plan() == {"CANCELLED"}
assert cast(Any, bpy.data.objects).get("Generated Cube") is not None
assert ui_state.workflow_status == "awaiting_approval"
assert blender_ai_ops.reject_plan() == {"FINISHED"}

planning_module_any = cast(Any, planning_module)
original_process_events = planning_module_any.process_planning_events
original_print_exc = planning_module_any.traceback.print_exc
try:
    planning_module_any.process_planning_events = lambda context: (_ for _ in ()).throw(
        RuntimeError("timer test")
    )
    planning_module_any.traceback.print_exc = lambda: None
    assert planning_module_any._poll_timer() == planning_module.POLL_INTERVAL_SECONDS
    assert bpy.app.timers.is_registered(planning_module_any._poll_timer)
finally:
    planning_module_any.process_planning_events = original_process_events
    planning_module_any.traceback.print_exc = original_print_exc

extension.unregister()
assert not hasattr(bpy.types.WindowManager, "blender_ai_state")

print("Blender dependency smoke test: PASS")
