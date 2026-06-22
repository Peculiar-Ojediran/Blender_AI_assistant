"""Create deterministic fingerprints for Blender context targets."""

import hashlib
import json
from typing import Any

from .models import TargetKind


def target_state_fingerprint(datablock: Any, kind: TargetKind) -> str:
    """Hash the target state that must remain stable while a plan is pending."""

    if kind is TargetKind.OBJECT:
        payload = _object_identity(datablock)
    elif kind is TargetKind.MATERIAL:
        payload = _material_identity(datablock)
    else:
        payload = _collection_identity(datablock)

    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _object_identity(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "type": item.type,
        "data_uid": _session_uid(item.data),
        "parent_uid": _session_uid(item.parent),
        "location": _float_values(item.location),
        "rotation_euler": _float_values(item.rotation_euler),
        "scale": _float_values(item.scale),
        "dimensions": _float_values(item.dimensions),
        "data_state": _object_data_identity(item),
        "collections": sorted(_session_uid(value) for value in item.users_collection),
        "materials": [
            _session_uid(slot.material) if slot.material is not None else None
            for slot in item.material_slots
        ],
        "modifiers": [(modifier.name, modifier.type) for modifier in item.modifiers],
        "hide_viewport": bool(item.hide_viewport),
        "hide_render": bool(item.hide_render),
    }


def _object_data_identity(item: Any) -> dict[str, Any]:
    data = item.data
    if item.type == "MESH":
        return {
            "vertex_count": len(data.vertices),
            "edge_count": len(data.edges),
            "polygon_count": len(data.polygons),
        }
    if item.type == "LIGHT":
        return {
            "light_type": data.type,
            "energy": float(data.energy),
            "color": _float_values(data.color),
        }
    if item.type == "CAMERA":
        return {
            "focal_length": float(data.lens),
            "sensor_width": float(data.sensor_width),
        }
    return {}


def _material_identity(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "use_nodes": bool(item.use_nodes),
        "diffuse_color": _float_values(item.diffuse_color),
        "metallic": float(getattr(item, "metallic", 0.0)),
        "roughness": float(getattr(item, "roughness", 0.5)),
        "node_tree_uid": _session_uid(getattr(item, "node_tree", None)),
    }


def _collection_identity(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "objects": sorted(_session_uid(value) for value in item.objects),
        "children": sorted(_session_uid(value) for value in item.children),
        "hide_viewport": bool(item.hide_viewport),
        "hide_render": bool(item.hide_render),
    }


def _session_uid(item: Any | None) -> int | None:
    return int(item.session_uid) if item is not None else None


def _float_values(values: Any) -> list[float]:
    return [float(value) for value in values]
