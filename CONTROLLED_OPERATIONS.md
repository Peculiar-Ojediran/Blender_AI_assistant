# Controlled Operation Contract

## Authority

The AI proposes operations. The extension owns validation, risk, confirmation, target resolution, execution, and undo. Model-provided data is never treated as trusted Blender code.

The contract source of truth is:

- `extension/operations/models.py`
- `extension/operations/catalog.py`
- `extension/operations/schema.py`
- `extension/operations/validator.py`
- `extension/operations/risk.py`

## Plan Shape

Every provider response must contain exactly these fields:

| Field | Purpose |
| --- | --- |
| `snapshot_id` | Exact context snapshot the plan was created from |
| `status` | `ready` or `needs_clarification` |
| `intent_summary` | Short description of the requested result |
| `assumptions` | Explicit assumptions made by the model |
| `questions` | Clarifying questions when the plan cannot be safely prepared |
| `operations` | Ordered list of controlled operations |

A `ready` plan requires at least one operation and cannot include questions. A `needs_clarification` response requires at least one question and cannot include operations.

Risk and confirmation are deliberately absent from the provider response. They are calculated locally from the validated operations and affected-target count.

## Supported Operations

Every operation requires a unique `operation_id` and an exact `type`. Unknown fields and operation types are rejected.

| Operation | Required Payload | Base Risk |
| --- | --- | --- |
| `CREATE_PRIMITIVE` | primitive, name, collection ID or null, location, Euler rotation, scale | Low |
| `DELETE_OBJECTS` | target IDs, reason | High |
| `DUPLICATE_OBJECTS` | target IDs, count, offset, name prefix or null | Medium |
| `SET_TRANSFORM` | target IDs, absolute/relative mode, nullable location/rotation/scale | Low |
| `CREATE_MATERIAL` | name, RGB base color, metallic, roughness, alpha | Low |
| `ASSIGN_MATERIAL` | target IDs, material ID | Low |
| `ADD_LIGHT` | light type, name, collection ID or null, transform, color, energy, size | Low |
| `ADD_CAMERA` | name, collection ID or null, transform, focal length, active flag | Low |
| `RENAME_OBJECTS` | explicit target ID and new-name pairs | Medium |
| `MOVE_TO_COLLECTION` | target IDs, collection ID | Medium |

Modifiers, edit-mode mesh changes, geometry nodes, animation, rigging, file access, imports, and arbitrary Python are not part of the MVP contract.

## Reference Rules

Existing targets use typed IDs from the submitted context snapshot:

- Objects: `obj_0001` and later numeric IDs.
- Materials: `mat_0001` and later numeric IDs.
- Collections: `col_0001` and later numeric IDs.

`CREATE_PRIMITIVE`, `CREATE_MATERIAL`, `ADD_LIGHT`, and `ADD_CAMERA` each produce one addressable
result. A later operation in the same plan may reference that result as
`result:<operation_id>`. Forward references and result-kind mismatches are rejected. Duplicate
operations produce multiple objects and therefore do not expose one result reference in the MVP.

The plan must echo the submitted context `snapshot_id`. The coordinator must validate that value
against its retained snapshot. Existing targets must then pass kind, Blender `session_uid`, and
state-fingerprint checks immediately before execution.

## Execution Semantics

These rules are implemented by the main-thread executor:

- Locations and distances use Blender scene units. Rotations use XYZ Euler radians. Scale is
  dimensionless.
- Every plan receives complete scene-aware preflight before any mutation. Name collisions,
  missing targets, stale targets, unsupported modes, and invalid collection membership reject the
  whole plan.
- `CREATE_PRIMITIVE` creates one object with independent mesh data. A null collection uses the
  active collection, falling back to the scene root. The requested name must be available.
- `DELETE_OBJECTS` deletes only explicit targets. Non-target children are unparented while their
  world transforms are preserved. Orphaned datablocks are not automatically purged.
- `DUPLICATE_OBJECTS` creates `count` independent object and object-data copies per target;
  materials remain shared. Copy number `n` receives `n * offset` from the source transform. Names
  use `<prefix>_<source>_<n>` when a prefix is supplied and `<source>_copy_<n>` otherwise, with a
  three-digit number starting at `001`.
- `SET_TRANSFORM` absolute mode replaces each provided channel. Relative mode adds location and
  rotation and multiplies scale component by component. Null channels remain unchanged.
- `CREATE_MATERIAL` creates a Principled BSDF material from RGB base color plus the separate alpha,
  metallic, and roughness values. The requested name must be available.
- `ASSIGN_MATERIAL` uses copy-on-write for shared object data, replaces all material slots with the
  referenced material, and resets mesh polygon material indices to zero.
- `ADD_LIGHT` creates the requested Blender light. `size` means area size for area lights,
  shadow-soft size for point/spot lights, and angular size in radians for sun lights.
- `ADD_CAMERA` creates one perspective camera and changes the scene's active camera only when
  `make_active` is true.
- `RENAME_OBJECTS` changes object names only, not object-data names. Duplicate requested names or
  collisions with non-target objects reject the plan.
- `MOVE_TO_COLLECTION` links each target to the destination and unlinks it from every other
  collection, leaving exactly one collection membership.

## Contract Limits

- Defaults: 20 operations per plan, 100 existing object targets per operation, and 100 total objects
  created by one duplicate operation.
- Selectable hard maxima: 100 operations per plan, 500 existing targets per operation, and 1,000
  total objects created by one duplicate operation.
- Users may change each limit from the `Plan Limits` panel or extension preferences. Values cannot
  exceed the controlled-contract hard maxima.
- Duplicate output is calculated as target count multiplied by duplicate count. The schema bounds
  each field and local semantic validation enforces the total product.
- Operation IDs must be unique and use a restricted identifier format.
- Plans affecting more than 25 existing and created objects are high risk. They require Global Undo,
  a successfully created recovery point, and a second explicit confirmation before execution.
- Existing target IDs must come from scene context and be unique within target lists.
- Result references must point backward to a compatible single-result creation operation.
- The response snapshot ID must match the retained planning snapshot.
- Numeric fields are bounded and non-finite values are rejected.
- Scale components cannot be zero.
- `SET_TRANSFORM` must change at least one transform component.
- Unknown fields are rejected at every object level.

## Validation Stages

1. OpenAI Structured Outputs constrains the response to a JSON Schema generated from the selected
   limits.
2. `fastjsonschema` repeats the same selected-limit structural validation locally.
3. Semantic validation checks state combinations, unique operation IDs, numeric safety, and operation-specific limits.
4. Scene-aware validation resolves target/material/collection IDs and verifies current Blender context.
5. Local risk assessment determines whether confirmation is required.
6. Local safety policy verifies approval, destructive recovery, and prohibited capabilities.
7. Only an approved, scene-valid, policy-authorized plan can reach the main-thread executor.

Approved plans are preflighted as a complete transaction and then executed on Blender's main
thread. Runtime failures before destructive commit are rolled back in reverse order. Permanent
deletions are deferred until other operations succeed; a failure after deletion begins is reported
as partial with Blender Undo recovery instructions. Detailed behavior is documented in
`EXECUTION.md`.
