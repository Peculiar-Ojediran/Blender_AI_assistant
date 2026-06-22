"""Generate deterministic Blender files used by the Phase 9 test matrix."""

from pathlib import Path
from typing import Any, cast

import bpy

FIXTURE_DIRECTORY = Path(__file__).resolve().parent
FIXTURE_VERSION = 1


def _reset_scene(kind: str) -> Any:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = cast(Any, bpy.context.scene)
    scene.name = f"{kind.title()} Fixture"
    scene["fixture_kind"] = kind
    scene["fixture_version"] = FIXTURE_VERSION
    return scene


def _save(filename: str) -> None:
    result = cast(
        set[str],
        bpy.ops.wm.save_as_mainfile(filepath=str(FIXTURE_DIRECTORY / filename)),
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"Could not save fixture {filename}: {result}")


def _build_simple_scene() -> None:
    scene = _reset_scene("simple")
    bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
    cube = cast(Any, bpy.context.active_object)
    cube.name = "FixtureCube"

    material = cast(Any, bpy.data.materials).new("FixtureMaterial")
    material.diffuse_color = (0.18, 0.42, 0.8, 1.0)
    cube.data.materials.append(material)

    light_data = cast(Any, bpy.data.lights).new("FixtureLightData", "AREA")
    light = cast(Any, bpy.data.objects).new("FixtureLight", light_data)
    scene.collection.objects.link(light)
    light.location = (4.0, -4.0, 6.0)

    camera_data = cast(Any, bpy.data.cameras).new("FixtureCameraData")
    camera = cast(Any, bpy.data.objects).new("FixtureCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (6.0, -6.0, 4.0)
    scene.camera = camera

    for item in scene.objects:
        item.select_set(False)
    cube.select_set(True)
    cast(Any, bpy.context.view_layer).objects.active = cube
    _save("simple_scene.blend")


def _build_messy_scene() -> None:
    scene = _reset_scene("messy")
    assets = cast(Any, bpy.data.collections).new("Messy Assets")
    archive = cast(Any, bpy.data.collections).new("Messy Archive")
    nested = cast(Any, bpy.data.collections).new("Messy Nested")
    scene.collection.children.link(assets)
    scene.collection.children.link(archive)
    assets.children.link(nested)

    bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0))
    base = cast(Any, bpy.context.active_object)
    base.name = "MessyBase"
    scene.collection.objects.unlink(base)
    assets.objects.link(base)
    base["private_path"] = "C:\\private\\client\\asset.blend"
    base["project_code"] = "fixture-only"

    material = cast(Any, bpy.data.materials).new("MessySharedMaterial")
    material.diffuse_color = (0.65, 0.2, 0.12, 1.0)
    material["private_path"] = "C:\\private\\client\\texture.png"
    base.data.materials.append(material)

    for index in range(30):
        item = base.copy()
        if index % 4 == 0:
            item.data = base.data.copy()
        item.name = f"MessyObject_{index:03d}"
        target_collection = nested if index % 3 else archive
        target_collection.objects.link(item)
        item.location = (float(index % 6), float(index // 6), float(index % 3))
        item.hide_render = index % 5 == 0
        if index % 7 == 0:
            item.scale = (1.0, 1.0, 0.0)

    parent = cast(Any, bpy.data.objects).new("MessyParent", None)
    assets.objects.link(parent)
    cast(Any, bpy.data.objects)["MessyObject_001"].parent = parent

    for item in scene.objects:
        item.select_set(False)
    base.select_set(True)
    cast(Any, bpy.data.objects)["MessyObject_002"].select_set(True)
    cast(Any, bpy.context.view_layer).objects.active = base
    _save("messy_scene.blend")


def _build_large_scene() -> None:
    scene = _reset_scene("large")
    first_object: Any | None = None
    for index in range(1_000):
        item = cast(Any, bpy.data.objects).new(f"LargeObject_{index:04d}", None)
        scene.collection.objects.link(item)
        item.location = (
            float(index % 25),
            float((index // 25) % 20),
            float(index // 500),
        )
        if index < 5:
            item.select_set(True)
        if first_object is None:
            first_object = item

    cast(Any, bpy.context.view_layer).objects.active = first_object
    _save("large_scene.blend")


def main() -> None:
    FIXTURE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    _build_simple_scene()
    _build_messy_scene()
    _build_large_scene()
    print("Generated simple, messy, and large Blender fixtures.")


if __name__ == "__main__":
    main()
