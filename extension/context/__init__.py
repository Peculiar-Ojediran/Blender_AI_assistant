"""Blender scene context collection and serialization."""

from typing import Any

from .budget import ObjectBudgetResult, apply_object_budget
from .errors import ContextBudgetError, ContextThreadError
from .models import (
    CollectionContext,
    ContextOptions,
    ContextScope,
    MaterialContext,
    ObjectContext,
    ObjectSummary,
    OmissionReport,
    SceneContext,
    SceneContextSnapshot,
    SerializedSceneContext,
    TargetKind,
    TargetReference,
)
from .privacy import PrivacyStats, sanitize_custom_properties
from .serializer import fit_scene_context_to_budget, serialize_scene_context


def read_scene_context(context: Any, options: ContextOptions) -> SceneContextSnapshot:
    """Load the Blender-only reader only when live scene data is requested."""

    from .scene_reader import read_scene_context as read_context

    return read_context(context, options)

__all__ = [
    "CollectionContext",
    "ContextBudgetError",
    "ContextOptions",
    "ContextScope",
    "ContextThreadError",
    "MaterialContext",
    "ObjectBudgetResult",
    "ObjectContext",
    "ObjectSummary",
    "OmissionReport",
    "PrivacyStats",
    "SceneContext",
    "SceneContextSnapshot",
    "SerializedSceneContext",
    "TargetKind",
    "TargetReference",
    "apply_object_budget",
    "fit_scene_context_to_budget",
    "read_scene_context",
    "sanitize_custom_properties",
    "serialize_scene_context",
]
