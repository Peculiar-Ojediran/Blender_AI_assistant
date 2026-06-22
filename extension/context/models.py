"""Typed scene-context records independent of Blender runtime objects."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ContextScope(StrEnum):
    SELECTION = "selection"
    COLLECTION = "collection"
    SCENE = "scene"


class TargetKind(StrEnum):
    OBJECT = "object"
    MATERIAL = "material"
    COLLECTION = "collection"


@dataclass(frozen=True, slots=True)
class ContextOptions:
    scope: ContextScope = ContextScope.SELECTION
    detailed_object_budget: int = 25
    summary_object_budget: int = 200
    material_budget: int = 100
    collection_budget: int = 100
    include_custom_properties: bool = False
    include_file_paths: bool = False
    include_viewport_image: bool = False
    max_serialized_characters: int = 100_000

    def __post_init__(self) -> None:
        for name in (
            "detailed_object_budget",
            "summary_object_budget",
            "material_budget",
            "collection_budget",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive.")
        if self.detailed_object_budget > self.summary_object_budget:
            raise ValueError("The detailed object budget cannot exceed the summary budget.")
        if self.max_serialized_characters < 1_024:
            raise ValueError("The serialized context budget must be at least 1024 characters.")


@dataclass(frozen=True, slots=True)
class TargetReference:
    target_id: str
    kind: TargetKind
    datablock_name: str
    session_uid: int
    state_fingerprint: str


@dataclass(frozen=True, slots=True)
class ObjectSummary:
    target_id: str
    name: str
    object_type: str
    selected: bool
    active: bool


@dataclass(frozen=True, slots=True)
class ObjectContext:
    target_id: str
    name: str
    object_type: str
    selected: bool
    active: bool
    collection_ids: tuple[str, ...]
    parent_id: str | None
    location: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]
    dimensions: tuple[float, float, float]
    material_ids: tuple[str, ...]
    modifiers: tuple[str, ...]
    custom_properties: Mapping[str, JsonValue]
    data: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class MaterialContext:
    target_id: str
    name: str
    use_nodes: bool
    diffuse_color: tuple[float, float, float, float]
    metallic: float
    roughness: float
    custom_properties: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CollectionContext:
    target_id: str
    name: str
    parent_id: str | None
    object_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OmissionReport:
    object_summaries: int = 0
    object_details: int = 0
    materials: int = 0
    collections: int = 0
    custom_properties: int = 0
    file_paths: int = 0
    viewport_images: int = 0

    @property
    def total(self) -> int:
        return sum(
            (
                self.object_summaries,
                self.object_details,
                self.materials,
                self.collections,
                self.custom_properties,
                self.file_paths,
                self.viewport_images,
            )
        )


@dataclass(frozen=True, slots=True)
class SceneContext:
    schema_version: int
    blender_version: str
    scene_name: str
    file_path: str | None
    unit_system: str
    unit_scale: float
    scope: ContextScope
    active_object_id: str | None
    active_collection_id: str | None
    total_scene_objects: int
    scoped_object_count: int
    object_summaries: tuple[ObjectSummary, ...]
    detailed_objects: tuple[ObjectContext, ...]
    materials: tuple[MaterialContext, ...]
    collections: tuple[CollectionContext, ...]
    omissions: OmissionReport
    warnings: tuple[str, ...]
    include_custom_properties: bool
    include_file_paths: bool
    include_viewport_image: bool
    character_budget: int


@dataclass(frozen=True, slots=True)
class SceneContextSnapshot:
    snapshot_id: str
    context: SceneContext
    target_index: Mapping[str, TargetReference]


@dataclass(frozen=True, slots=True)
class SerializedSceneContext:
    payload: Mapping[str, JsonValue]
    json_text: str
    character_count: int
