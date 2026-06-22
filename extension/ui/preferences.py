"""Provider, model, privacy, and safety preferences."""

from typing import TYPE_CHECKING, Any

from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences

from ..config import environment_value_source, resolve_environment_value
from ..operations import (
    DEFAULT_OPERATION_LIMITS,
    HARD_MAX_DUPLICATE_OBJECTS,
    HARD_MAX_OPERATIONS_PER_PLAN,
    HARD_MAX_TARGETS_PER_OPERATION,
    OperationLimits,
)
from ..providers.openai import (
    CUSTOM_MODEL_OPTION,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    OPENAI_MODEL_OPTIONS,
    resolve_model_name,
)
from .properties import CONTEXT_SCOPE_ITEMS

ADDON_ID = (__package__ or "").rsplit(".ui", 1)[0]


class AIASSISTANT_AP_preferences(AddonPreferences):
    bl_idname = ADDON_ID

    if TYPE_CHECKING:
        model_choice: str
        custom_model: str
        reasoning_effort: str
        session_api_key: str
        request_timeout: float
        max_output_tokens: int
        default_context_scope: str
        include_custom_properties: bool
        include_file_paths: bool
        include_viewport_image: bool
        context_object_budget: int
        context_character_budget: int
        max_plan_operations: int
        max_operation_targets: int
        max_duplicate_objects: int
    else:
        model_choice: EnumProperty(
            name="Model",
            items=(
                *OPENAI_MODEL_OPTIONS,
                (
                    CUSTOM_MODEL_OPTION,
                    "Custom",
                    "Use another Responses API compatible model name",
                ),
            ),
            default=DEFAULT_MODEL,
        )
        custom_model: StringProperty(name="Custom Model", maxlen=128)
        reasoning_effort: EnumProperty(
            name="Reasoning Effort",
            items=(
                ("low", "Low", "Lower-cost reasoning for development and routine plans"),
                ("medium", "Medium", "Balanced reasoning for more difficult plans"),
                ("high", "High", "Higher-cost reasoning for evaluation only"),
            ),
            default=DEFAULT_REASONING_EFFORT,
        )
        session_api_key: StringProperty(
            name="Session API Key",
            subtype="PASSWORD",
            options={"SKIP_SAVE"},
        )
        request_timeout: FloatProperty(
            name="Request Timeout",
            description="Maximum time to wait for an OpenAI response",
            default=60.0,
            min=5.0,
            max=300.0,
            unit="TIME",
        )
        max_output_tokens: IntProperty(
            name="Maximum Output Tokens",
            default=4_096,
            min=512,
            max=32_768,
        )
        default_context_scope: EnumProperty(
            name="Default Context",
            items=CONTEXT_SCOPE_ITEMS,
            default="SELECTION",
        )
        include_custom_properties: BoolProperty(
            name="Include Custom Properties",
            default=False,
        )
        include_file_paths: BoolProperty(name="Include File Paths", default=False)
        include_viewport_image: BoolProperty(name="Include Viewport Image", default=False)
        context_object_budget: IntProperty(
            name="Detailed Object Budget",
            default=25,
            min=1,
            max=500,
        )
        context_character_budget: IntProperty(
            name="Context Character Budget",
            default=100_000,
            min=10_000,
            max=1_000_000,
        )
        max_plan_operations: IntProperty(
            name="Operations per Plan",
            description="Maximum number of controlled operations in one plan",
            default=DEFAULT_OPERATION_LIMITS.max_operations_per_plan,
            min=1,
            max=HARD_MAX_OPERATIONS_PER_PLAN,
        )
        max_operation_targets: IntProperty(
            name="Targets per Operation",
            description="Maximum existing objects referenced by one operation",
            default=DEFAULT_OPERATION_LIMITS.max_targets_per_operation,
            min=1,
            max=HARD_MAX_TARGETS_PER_OPERATION,
        )
        max_duplicate_objects: IntProperty(
            name="Duplicate Outputs",
            description="Maximum total objects created by one duplicate operation",
            default=DEFAULT_OPERATION_LIMITS.max_duplicate_objects,
            min=1,
            max=HARD_MAX_DUPLICATE_OBJECTS,
        )

    def draw(self, context: Any) -> None:
        layout = self.layout
        assert layout is not None

        provider = layout.column(align=True)
        provider.label(text="Provider", icon="NETWORK_DRIVE")
        provider.label(text="OpenAI")
        provider.prop(self, "model_choice")
        if self.model_choice == CUSTOM_MODEL_OPTION:
            provider.prop(self, "custom_model")
        provider.prop(self, "reasoning_effort")
        provider.prop(self, "request_timeout")
        provider.prop(self, "max_output_tokens")

        key_column = layout.column(align=True)
        key_column.label(text="API Key", icon="KEYINGSET")
        source = api_key_source(self)
        key_column.label(text=f"Source: {source}")
        session_row = key_column.row(align=True)
        session_row.enabled = source not in {"Environment", "Local .env"}
        session_row.prop(self, "session_api_key", text="Session Key")
        session_row.operator("blender_ai.clear_session_key", text="", icon="X")

        context_column = layout.column(align=True)
        context_column.label(text="Context and Privacy", icon="LOCKED")
        context_column.prop(self, "default_context_scope")
        context_column.prop(self, "context_object_budget")
        context_column.prop(self, "context_character_budget")
        context_column.prop(self, "include_custom_properties")
        context_column.prop(self, "include_file_paths")
        image_row = context_column.row()
        image_row.enabled = False
        image_row.prop(self, "include_viewport_image")

        safety = layout.column(align=True)
        safety.label(text="Safety", icon="LOCKED")
        safety.prop(self, "max_plan_operations")
        safety.prop(self, "max_operation_targets")
        safety.prop(self, "max_duplicate_objects")
        safety.label(text="Schema validation: Required")
        safety.label(text="Scene validation: Required")
        safety.label(text="Arbitrary Python: Disabled")


def get_preferences(context: Any) -> AIASSISTANT_AP_preferences | None:
    addon = context.preferences.addons.get(ADDON_ID)
    if addon is None:
        return None
    return addon.preferences


def resolve_api_key(context: Any) -> str:
    environment_key = resolve_environment_value("OPENAI_API_KEY")
    if environment_key:
        return environment_key

    preferences = get_preferences(context)
    if preferences is None:
        return ""
    return preferences.session_api_key.strip()


def resolve_selected_model(preferences: AIASSISTANT_AP_preferences | None) -> str:
    if preferences is None:
        return DEFAULT_MODEL
    return resolve_model_name(preferences.model_choice, preferences.custom_model)


def resolve_operation_limits(
    preferences: AIASSISTANT_AP_preferences | None,
) -> OperationLimits:
    if preferences is None:
        return DEFAULT_OPERATION_LIMITS
    return OperationLimits(
        max_operations_per_plan=preferences.max_plan_operations,
        max_targets_per_operation=preferences.max_operation_targets,
        max_duplicate_objects=preferences.max_duplicate_objects,
    )


def api_key_source(preferences: AIASSISTANT_AP_preferences | None) -> str:
    source = environment_value_source("OPENAI_API_KEY")
    if source != "Missing":
        return source
    if preferences is not None and preferences.session_api_key.strip():
        return "Session"
    return "Missing"


CLASSES = (AIASSISTANT_AP_preferences,)
