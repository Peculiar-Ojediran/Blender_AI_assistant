"""Prompt classification for opt-in internet asset discovery."""

from .models import InternetDiscoveryIntent

ASSET_DISCOVERY_VERBS = (
    "find",
    "search",
    "look up",
    "download",
    "get",
)
MODEL_TERMS = (
    "model",
    "mesh",
    "base mesh",
    "asset",
    "character",
    "prop",
    "object",
)
TEXTURE_TERMS = (
    "texture",
    "material",
    "pbr",
    "image",
)
KNOWN_FORMATS = ("obj", "fbx", "gltf", "glb")


def classify_internet_intent(prompt: str) -> InternetDiscoveryIntent:
    normalized = prompt.strip().lower()
    requested_formats = tuple(
        format_name
        for format_name in KNOWN_FORMATS
        if _mentions_format(normalized, format_name)
    )

    asks_to_search = any(verb in normalized for verb in ASSET_DISCOVERY_VERBS)
    mentions_model = any(term in normalized for term in MODEL_TERMS)
    mentions_texture = any(term in normalized for term in TEXTURE_TERMS)
    requires_internet = asks_to_search and (mentions_model or mentions_texture)

    if mentions_texture and not mentions_model:
        asset_kind = "texture"
    elif mentions_model:
        asset_kind = "model"
    else:
        asset_kind = "unknown"

    return InternetDiscoveryIntent(
        requires_internet=requires_internet,
        asset_kind=asset_kind,
        requested_formats=requested_formats,
        scene_mutating=False,
    )


def _mentions_format(prompt: str, format_name: str) -> bool:
    return (
        f".{format_name}" in prompt
        or f" {format_name} " in f" {prompt} "
        or f"{format_name} format" in prompt
    )
