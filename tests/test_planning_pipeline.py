import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from extension.context import (
    ContextScope,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
    serialize_scene_context,
)
from extension.operations import (
    OPERATION_PLAN_SCHEMA,
    OperationType,
    RiskLevel,
    assess_plan_risk,
    validate_operation_plan,
)
from extension.providers.base import PlanRequest
from extension.providers.openai import OpenAIProvider

SNAPSHOT_ID = "a" * 32


@dataclass
class FakeResponse:
    status_code: int
    data: Any

    def json(self) -> Any:
        return self.data


class FakeSession:
    def __init__(self, plan: dict[str, Any]) -> None:
        self.plan = plan

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "id": "resp_pipeline",
                "model": "gpt-5.5",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(self.plan)}
                        ],
                    }
                ],
            },
        )


def test_snapshot_to_provider_to_validated_plan_pipeline() -> None:
    snapshot = _empty_snapshot()
    serialized = serialize_scene_context(snapshot)
    raw_plan = {
        "snapshot_id": SNAPSHOT_ID,
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
    provider = OpenAIProvider("test-key", session=FakeSession(raw_plan))

    provider_response = provider.create_plan(
        PlanRequest(
            prompt="Create a cube",
            scene_context=serialized.payload,
            response_schema=OPERATION_PLAN_SCHEMA,
        )
    )
    plan = validate_operation_plan(
        provider_response.plan,
        expected_snapshot_id=snapshot.snapshot_id,
    )
    risk = assess_plan_risk(plan)

    assert plan.snapshot_id == snapshot.snapshot_id
    assert plan.operations[0].type is OperationType.CREATE_PRIMITIVE
    assert risk.level is RiskLevel.LOW
    assert risk.requires_confirmation is False


def _empty_snapshot() -> SceneContextSnapshot:
    context = SceneContext(
        schema_version=1,
        blender_version="5.1.0",
        scene_name="Scene",
        file_path=None,
        unit_system="NONE",
        unit_scale=1.0,
        scope=ContextScope.SELECTION,
        active_object_id=None,
        active_collection_id=None,
        total_scene_objects=0,
        scoped_object_count=0,
        object_summaries=(),
        detailed_objects=(),
        materials=(),
        collections=(),
        omissions=OmissionReport(),
        warnings=(),
        include_custom_properties=False,
        include_file_paths=False,
        include_viewport_image=False,
        character_budget=100_000,
    )
    return SceneContextSnapshot(SNAPSHOT_ID, context, MappingProxyType({}))
