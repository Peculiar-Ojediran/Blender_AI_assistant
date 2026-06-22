# Scene Context Contract

## Purpose

The scene context system creates a bounded, privacy-filtered snapshot of the current Blender
scene for AI planning. Collection runs on Blender's main thread. The resulting typed records and
provider serialization are read-only and do not modify Blender data.

## Supported Scopes

| Scope | Objects considered |
| --- | --- |
| `selection` | Currently selected objects. This is the default. |
| `collection` | Objects in the active collection and its child collections. |
| `scene` | All objects in the current scene, subject to configured budgets. |

Objects are ordered deterministically. The active object is prioritized first, followed by other
selected objects and then remaining objects by name.

## Context Records

The provider-safe payload contains:

- Blender version, scene name, unit system, and unit scale.
- Scope, active object ID, active collection ID, and scene/scoped object counts.
- Budgeted object summaries with name, type, selection state, and active state.
- Detailed object transforms, dimensions, collection/material references, modifiers, and compact
  type-specific data.
- Mesh vertex, edge, and polygon counts.
- Light type, energy, and color.
- Camera focal length and sensor width.
- Budgeted material and collection records.
- Omission counts, privacy flags, and collection warnings.

The serializer produces deterministic compact JSON and reports its exact character count.

## Target IDs

Objects, materials, and collections receive opaque snapshot IDs such as `obj_0001`, `mat_0001`,
and `col_0001`. Provider operations must refer to these IDs instead of Blender datablock names.

The snapshot keeps a local target index that maps IDs to target kind, datablock name, Blender
`session_uid`, and a deterministic state fingerprint. This index is never included in the provider
payload. Every serialized reference is limited to a target included in the same snapshot,
preventing dangling provider-visible IDs.

Target IDs are valid only for the snapshot that created them. The provider payload includes a
random snapshot ID that must be echoed by the plan. Live target resolution rejects missing,
replaced, renamed, reparented, transformed, or otherwise fingerprint-changed targets.

## Budgets and Omissions

Default budgets are:

- 25 objects with full details.
- 200 object summaries.
- 100 materials.
- 100 collections.
- 100,000 serialized characters across the complete payload.

The detailed object budget cannot exceed the summary budget. Selection and collection scopes send
only materials used by detailed objects and collections connected to scoped objects or their
ancestors. Full-scene scope may include broader budgeted collection data. Omission reporting distinguishes
summary objects, object details, materials, collections, custom properties, file paths, and
viewport images. Context collection never silently expands beyond these limits.

If the complete payload exceeds its character ceiling, reduction removes custom properties first,
then lower-priority collections, materials, detailed objects, and summaries. The target index and
all cross-references are reduced with the payload. Collection fails if minimal scene metadata still
cannot fit.

## Privacy Rules

- Custom properties are excluded by default.
- File paths are excluded by default, including the current `.blend` path and path-like custom
  property strings.
- Custom properties are sorted, bounded, depth-limited, and converted only to JSON-safe values.
- Non-finite numbers and unsupported custom-property values are omitted.
- Viewport images are not implemented. Enabling the preference records a warning and omission
  instead of capturing an image.
- The internal target index and Blender runtime objects are never serialized.

## UI Integration

Opening `Preview Context` collects a fresh snapshot and displays included targets, omitted data,
and serialized character count. Starting `Plan Changes` collects and retains a fresh snapshot,
then submits its provider-safe payload to the planning coordinator. Both operations fail without
changing the scene if context collection or planning raises an error.

## Module Boundaries

- `extension/context/models.py`: Blender-independent immutable records and options.
- `extension/context/budget.py`: deterministic object priority and limits.
- `extension/context/privacy.py`: custom-property filtering and JSON conversion.
- `extension/context/serializer.py`: provider-safe deterministic payload creation.
- `extension/context/scene_reader.py`: Blender-only main-thread scene access.
- `extension/context/errors.py`: context-specific errors available without importing `bpy`.

Blender-independent context modules remain importable and testable in normal Python. The live
scene reader is loaded lazily only when a Blender context is collected.

## Current Boundaries

- The planning coordinator retains snapshots through provider validation and plan approval.
- Snapshot and live target validation run when planning results return. The executor repeats full
  live validation and complete-plan preflight immediately before mutation.
- Constraints, geometry nodes, animation, rigging, and detailed node graphs are not serialized.
- Viewport screenshots and rendered previews are deferred.
