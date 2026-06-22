"""Blender undo helpers for approved plan execution."""

from typing import Any


def global_undo_enabled(context: Any) -> bool:
    return bool(context.preferences.edit.use_global_undo)


def create_recovery_point(context: Any, message: str) -> bool:
    """Capture the pre-plan scene for recovery from a destructive partial failure."""

    if not global_undo_enabled(context):
        return False

    import bpy

    try:
        result: Any = bpy.ops.ed.undo_push(message=message)
        return "FINISHED" in result
    except RuntimeError:
        return False
