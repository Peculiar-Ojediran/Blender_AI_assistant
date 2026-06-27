bl_info = {
    "name": "Blender AI Assistant",
    "author": "Blender AI Assistant Contributors",
    "version": (0, 1, 4),
    "blender": (5, 1, 0),
    "location": "3D View > Sidebar",
    "description": "Plan controlled Blender changes with selectable AI providers",
    "category": "3D View",
}


def register() -> None:
    """Register the extension with Blender."""

    from .ui import register as register_ui

    register_ui()


def unregister() -> None:
    """Unregister the extension from Blender."""

    from .ui import unregister as unregister_ui

    unregister_ui()
