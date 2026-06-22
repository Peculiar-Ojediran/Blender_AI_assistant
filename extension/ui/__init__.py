"""Register Blender-native panels, operators, preferences, and UI state."""

from typing import Any

import bpy
from bpy.props import PointerProperty

from .operators import CLASSES as OPERATOR_CLASSES
from .panels import CLASSES as PANEL_CLASSES
from .planning import register_planning_runtime, unregister_planning_runtime
from .preferences import CLASSES as PREFERENCE_CLASSES
from .properties import CLASSES as PROPERTY_CLASSES
from .properties import AIASSISTANT_PG_State

CLASSES = PROPERTY_CLASSES + PREFERENCE_CLASSES + OPERATOR_CLASSES + PANEL_CLASSES


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    window_manager_type: Any = bpy.types.WindowManager
    window_manager_type.blender_ai_state = PointerProperty(type=AIASSISTANT_PG_State)
    register_planning_runtime()


def unregister() -> None:
    unregister_planning_runtime()
    window_manager_type: Any = bpy.types.WindowManager
    if hasattr(window_manager_type, "blender_ai_state"):
        del window_manager_type.blender_ai_state
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
