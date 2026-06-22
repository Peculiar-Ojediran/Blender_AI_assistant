# Controlled Execution Layer

## Authority and Entry Point

Only the retained, locally validated plan shown in the approval UI can reach
`extension/operations/executor.py`. Execution starts from `Apply Plan`; provider responses never
call Blender operations directly.

Before preflight, `extension/safety` recomputes authorization from the retained plan. High-risk
execution cannot use mutable UI risk fields as authority. Destructive plans require both Global Undo
and a successfully created pre-plan recovery point.

All preflight and mutation work runs synchronously on Blender's main thread. The executor rejects
non-ready plans, mismatched snapshots, changed scenes, non-Object modes, stale targets, linked
objects, invalid destination collections, unsupported material targets, lifecycle errors, and name
collisions before mutation.

## Transaction Flow

1. Revalidate the plan and retained snapshot.
2. Resolve every existing target by kind, Blender `session_uid`, and state fingerprint.
3. Simulate all operations in order, including created-result bindings, deletions, renames, and
   deterministic generated names.
4. Create a Blender recovery point when global undo is available.
5. Execute operations with reverse-order rollback actions registered before mutable work.
6. Defer permanent object deletion until every non-destructive operation succeeds.
7. Return immutable change records or a structured rolled-back/partial failure.

Runtime failures before destructive commit trigger reverse-order rollback. A failure after deletion
commit begins is reported as partial because removed Blender object datablocks cannot be reconstructed
reliably by the local journal. The pre-plan Blender recovery point is the recovery path for that case.

## Supported Execution

- Mesh primitives: cube, UV sphere, cylinder, cone, plane, and torus.
- Explicit object deletion with non-target children unparented and world transforms preserved.
- Independent object and object-data duplication with shared materials.
- Absolute and relative location, XYZ Euler rotation, and scale changes.
- Principled BSDF material creation and copy-on-write material assignment.
- Point, sun, spot, and area lights.
- Perspective cameras with optional active-camera assignment.
- Exact object renaming, including safe multi-object name swaps.
- Exclusive movement to an existing scene collection.
- Backward `result:<operation_id>` references for single-result creation operations.

Duplicate names are deterministic. With a prefix, copies use
`<prefix>_<source_name>_<number>`; without one they use
`<source_name>_copy_<number>`. Numbers are three digits and start at `001`. Any collision rejects the
whole plan during preflight.

## Undo and Reporting

`Apply Plan` is a Blender operator registered with `REGISTER` and `UNDO`, so a successful plan is
one user-visible Blender action. The executor also requests a pre-plan recovery point when global
undo is enabled. The result panel reports whether Blender Undo is available, and the session history
stores a bounded, secret-free summary of every changed object or material.

The extension does not expose a custom Undo button because it cannot prove that the AI transaction
is still the top undo step after unrelated user work. Users should use Blender's standard Undo
immediately when needed.

## Current Limits

- Execution is synchronous and bounded to 20 validated operations. Once `Apply Plan` starts, it
  cannot be canceled from the UI; planning requests remain cancelable.
- All plans require Object Mode. Edit-mode operations are outside the MVP contract.
- Orphaned datablocks from deleted existing objects are not purged automatically.
- Background Blender tests cannot invoke editor undo because no editor context exists. They verify
  operator undo registration and recovery metadata; foreground Ctrl-Z remains a manual test.
