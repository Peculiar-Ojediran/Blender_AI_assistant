# Blender Tests

`run_blender_tests.py` covers registration, scene reading, planning, approval, execution entry, UI
state, history, and undo registration. `run_execution_tests.py` covers complete preflight,
transaction rollback, and every controlled operation against Blender data.

`run_sample_scene_tests.py` reopens the generated simple, messy, and 1,000-object fixtures to verify
privacy filtering, context omission reporting, serialized size limits, and collection performance.

Blender background mode has no editor context, so interactive Undo must also be checked manually in
a foreground Blender session.
