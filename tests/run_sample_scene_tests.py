"""Validate deterministic sample scenes and large-scene context behavior in Blender."""

import sys
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import bpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = PROJECT_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(PROJECT_ROOT))

from extension.context import (  # noqa: E402
    ContextOptions,
    ContextScope,
    read_scene_context,
    serialize_scene_context,
)

PERFORMANCE_LIMIT_SECONDS = 15.0


def _open_fixture(filename: str, expected_kind: str) -> Any:
    filepath = FIXTURE_DIRECTORY / filename
    if not filepath.is_file():
        raise AssertionError(
            f"Missing {filepath}. Run tests/fixtures/build_sample_scenes.py in Blender."
        )
    result = cast(set[str], bpy.ops.wm.open_mainfile(filepath=str(filepath)))
    if result != {"FINISHED"}:
        raise AssertionError(f"Could not open {filepath}: {result}")
    scene = cast(Any, bpy.context.scene)
    assert scene["fixture_kind"] == expected_kind
    assert scene["fixture_version"] == 1
    return scene


def _test_simple_scene() -> tuple[int, int]:
    scene = _open_fixture("simple_scene.blend", "simple")
    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(
            scope=ContextScope.SELECTION,
            detailed_object_budget=10,
            summary_object_budget=10,
        ),
    )
    serialized = serialize_scene_context(snapshot)

    assert len(scene.objects) == 3
    assert snapshot.context.scoped_object_count == 1
    assert snapshot.context.detailed_objects[0].name == "FixtureCube"
    assert snapshot.context.materials[0].name == "FixtureMaterial"
    assert snapshot.context.omissions.file_paths == 1
    assert snapshot.context.omissions.total == 1
    return len(snapshot.target_index), serialized.character_count


def _test_messy_scene() -> tuple[int, int]:
    scene = _open_fixture("messy_scene.blend", "messy")
    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(
            scope=ContextScope.SCENE,
            detailed_object_budget=10,
            summary_object_budget=20,
            material_budget=10,
            collection_budget=10,
            include_custom_properties=True,
            include_file_paths=False,
            max_serialized_characters=12_000,
        ),
    )
    serialized = serialize_scene_context(snapshot)

    assert len(scene.objects) == 32
    assert snapshot.context.scoped_object_count == 32
    assert len(snapshot.context.object_summaries) <= 20
    assert len(snapshot.context.detailed_objects) <= 10
    assert snapshot.context.omissions.object_summaries >= 12
    assert snapshot.context.omissions.object_details >= 10
    assert snapshot.context.omissions.file_paths >= 1
    assert "private_path" not in serialized.json_text
    assert "C:\\\\private" not in serialized.json_text
    assert serialized.character_count <= 12_000
    return snapshot.context.omissions.total, serialized.character_count


def _test_large_scene() -> tuple[float, int, int]:
    scene = _open_fixture("large_scene.blend", "large")
    started = perf_counter()
    snapshot = read_scene_context(
        bpy.context,
        ContextOptions(
            scope=ContextScope.SCENE,
            detailed_object_budget=25,
            summary_object_budget=200,
            material_budget=25,
            collection_budget=25,
            max_serialized_characters=50_000,
        ),
    )
    serialized = serialize_scene_context(snapshot)
    elapsed = perf_counter() - started

    assert len(scene.objects) == 1_000
    assert snapshot.context.scoped_object_count == 1_000
    assert len(snapshot.context.object_summaries) <= 200
    assert len(snapshot.context.detailed_objects) <= 25
    assert snapshot.context.omissions.object_summaries >= 800
    assert snapshot.context.omissions.object_details >= 175
    assert serialized.character_count <= 50_000
    assert elapsed < PERFORMANCE_LIMIT_SECONDS
    return elapsed, snapshot.context.omissions.total, serialized.character_count


def main() -> None:
    simple_targets, simple_chars = _test_simple_scene()
    messy_omissions, messy_chars = _test_messy_scene()
    large_seconds, large_omissions, large_chars = _test_large_scene()
    print(
        "Sample scene tests: PASS "
        f"(simple={simple_targets} targets/{simple_chars} chars, "
        f"messy={messy_omissions} omissions/{messy_chars} chars, "
        f"large={large_seconds:.3f}s/{large_omissions} omissions/{large_chars} chars)"
    )


if __name__ == "__main__":
    main()
