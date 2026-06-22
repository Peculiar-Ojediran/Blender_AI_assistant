"""Filter unsupported or private custom-property values."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import JsonValue

MAX_CUSTOM_PROPERTIES = 32
MAX_SEQUENCE_ITEMS = 16
MAX_STRING_LENGTH = 256
MAX_DEPTH = 2

_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class PrivacyStats:
    custom_properties_omitted: int = 0
    file_paths_omitted: int = 0


def sanitize_custom_properties(
    properties: Mapping[str, Any],
    *,
    include_file_paths: bool,
) -> tuple[dict[str, JsonValue], PrivacyStats]:
    sanitized: dict[str, JsonValue] = {}
    omitted = 0
    paths_omitted = 0

    for key, value in sorted(properties.items(), key=lambda item: str(item[0]).casefold()):
        if len(sanitized) >= MAX_CUSTOM_PROPERTIES:
            omitted += 1
            continue
        key_text = str(key)
        if key_text == "_RNA_UI":
            omitted += 1
            continue
        if not include_file_paths and isinstance(value, str) and _looks_like_path(value):
            paths_omitted += 1
            continue

        converted = _to_json_value(value, depth=0, include_file_paths=include_file_paths)
        if converted is None and value is not None:
            omitted += 1
            continue
        sanitized[key_text[:MAX_STRING_LENGTH]] = converted

    return sanitized, PrivacyStats(omitted, paths_omitted)


def _to_json_value(value: Any, *, depth: int, include_file_paths: bool) -> JsonValue | None:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        if not include_file_paths and _looks_like_path(value):
            return None
        return value[:MAX_STRING_LENGTH]
    if depth >= MAX_DEPTH:
        return None
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, child in list(value.items())[:MAX_SEQUENCE_ITEMS]:
            converted = _to_json_value(
                child,
                depth=depth + 1,
                include_file_paths=include_file_paths,
            )
            if converted is not None or child is None:
                result[str(key)[:MAX_STRING_LENGTH]] = converted
        return result
    if isinstance(value, list | tuple):
        result_list: list[JsonValue] = []
        for child in value[:MAX_SEQUENCE_ITEMS]:
            converted = _to_json_value(
                child,
                depth=depth + 1,
                include_file_paths=include_file_paths,
            )
            if converted is not None or child is None:
                result_list.append(converted)
        return result_list
    return None


def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    return (
        bool(_WINDOWS_PATH.match(stripped))
        or stripped.startswith(("/", "\\\\", "file://"))
    )
