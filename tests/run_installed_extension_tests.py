import importlib
import pkgutil
from typing import Any, cast

import bpy

preferences = cast(Any, bpy.context.preferences)
addon_modules = [
    addon.module
    for addon in preferences.addons
    if addon.module.endswith(".blender_ai_assistant")
]
assert len(addon_modules) == 1, addon_modules

installed_extension = importlib.import_module(addon_modules[0])
for module_info in pkgutil.walk_packages(
    installed_extension.__path__,
    prefix=f"{addon_modules[0]}.",
):
    importlib.import_module(module_info.name)

assert hasattr(bpy.types, "AIASSISTANT_PT_assistant")
assert hasattr(bpy.types.WindowManager, "blender_ai_state")

print("Installed extension integration test: PASS")
