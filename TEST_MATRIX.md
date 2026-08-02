# Test Matrix

## Release Target

| Area | Target | Status |
| --- | --- | --- |
| Operating system | Windows x64 | Passed |
| Blender | 5.1.0 | Passed |
| Blender Python | 3.13.9 | Passed |
| macOS | Not yet qualified | Not run |
| Linux | Not yet qualified | Not run |
| Blender below 5.1 | Rejected by manifest | Expected |
| Blender above 5.1.x | Compatibility unknown | Not run |

The package uses cross-platform pure-Python wheels, but that does not replace real OS and Blender
version testing.

## Automated Coverage

| Surface | Coverage | Command |
| --- | --- | --- |
| Pure Python | Dynamic limit schemas, validation, risk, safety, context, async workflow, provider parsing | `python -m pytest` |
| Invalid AI output | Missing fields, invalid JSON/schema, refusal, incomplete/missing status, truncated chat output | `tests/test_openai_provider.py`, `tests/test_nvidia_provider.py` |
| Network behavior | Authentication, 429, 5xx exhaustion, Retry-After cap, timeout without ambiguous retry | `tests/test_openai_provider.py`, `tests/test_nvidia_provider.py` |
| Blender integration | Registration, scene context, planning, approval, UI state, stale targets | `tests/run_blender_tests.py` |
| Controlled operations | Supported operation types, shader Tracks A-G, advanced UV Tracks A-H, texture/PBR/generation/paint/bake/sculpting execution, Geometry Nodes, generated mesh variants, shape keys, render previews, references, preflight, and rollback | `tests/run_execution_tests.py` |
| Advanced shading | Shader socket compatibility, layered materials, procedural node sets, reference material metadata, specialized material families, cleanup/repair, and material variant review | `tests/unit/test_operation_contract.py`, `tests/unit/test_shading_future_contract.py`, `tests/run_execution_tests.py` |
| Sample scenes | Simple selection, messy scene privacy/budgets, 1,000-object performance | `tests/run_sample_scene_tests.py` |
| Packaging | Manifest/source/archive validation and forbidden-file/wheel checks | `tests/verify_release_package.py` |
| Installed artifact | Clean-profile install, packaged imports, UI registration | `tests/run_installed_extension_tests.py` |
| Live OpenAI provider | Ten schema-constrained scenarios with no automatic retries | 9 passed, 1 failed |
| Live NVIDIA provider | Hosted NIM real-request matrix | Not yet added |
| Texture/sculpting contract | Material presets, procedural materials, shader nodes, image textures, sculpt-like modifiers, and sculpt risk | `tests/future/test_texture_and_sculpting_contract.py` |
| Texture/sculpting targeted scaffold | Material preset assignment, shader node value edit, and displace modifier execution | `tests/future/run_texture_sculpting_execution_tests.py` |
| Planned sculpting expansion | Expected-failure contract payloads for sculpting Tracks A-G before implementation, with roadmap in `AI_BLENDER_EXTENSION_PLAN.md` | `tests/unit/test_sculpting_future_contract.py` |
| Advanced shading expansion | Active contract payloads for shading Tracks A-G, with roadmap in `AI_BLENDER_EXTENSION_PLAN.md` | `tests/unit/test_shading_future_contract.py` |
| Advanced UV editing expansion | Active contract payloads and Blender execution coverage for UV Tracks A-H, with roadmap in `AI_BLENDER_EXTENSION_PLAN.md` | `tests/unit/test_uv_future_contract.py`, `tests/run_execution_tests.py` |

## Latest Live Matrix

The June 20, 2026 live run used `gpt-5-nano-2025-08-07`, made exactly ten API requests, and changed no
Blender scene. Eight ready-plan cases covered all ten controlled operation types. The prohibited
Python/file/download request correctly returned clarification with no operations. The vague request
`Make the selected object look better` failed because the model invented a create-and-assign material
plan instead of requesting clarification. This remains an open planning-quality defect.

## Controlled Operation Matrix

| Operation | Automated |
| --- | --- |
| `CREATE_PRIMITIVE` | Passed for cube, UV sphere, cylinder, cone, plane, and torus |
| `SET_TRANSFORM` | Passed for relative and absolute validated transforms |
| `CREATE_MATERIAL` | Passed |
| `ASSIGN_MATERIAL` | Passed, including copy-on-write mesh data |
| `DUPLICATE_OBJECTS` | Passed with bounded count and deterministic naming |
| `ADD_LIGHT` | Passed for point, sun, spot, and area variants |
| `ADD_CAMERA` | Passed, including active-camera assignment |
| `RENAME_OBJECTS` | Passed with collision preflight |
| `MOVE_TO_COLLECTION` | Passed |
| `DELETE_OBJECTS` | Passed with child world-transform preservation and recovery requirements |
| `SET_MATERIAL_PROPERTIES` | Passed for nullable property updates |
| `CREATE_COLLECTION` | Passed for scene and parent collection creation |
| `SET_LIGHT_PROPERTIES` | Passed |
| `SET_CAMERA_PROPERTIES` | Passed |
| `ADD_MODIFIER` | Passed for supported non-applied modifiers |
| `SET_MODIFIER_PROPERTIES` | Passed |
| `CREATE_TEXT_OBJECT` | Passed |
| `SET_OBJECT_VISIBILITY` | Passed |
| `IMPORT_ASSET` | Passed with local and HTTPS source validation |
| `LINK_OR_APPEND_BLEND_DATA` | Passed with explicit local blend datablock loading |
| `BOOLEAN_OPERATION` | Passed with non-applied Boolean modifier behavior |
| `JOIN_OBJECTS` | Passed with generated replacement mesh and deferred source deletion |
| `SEPARATE_OBJECTS` | Passed for material and loose-part separation |
| `CREATE_MATERIAL_PRESET` | Passed contract tests and Blender execution scaffold |
| `CREATE_PROCEDURAL_MATERIAL` | Passed contract tests |
| `CREATE_SHADER_NODE` | Passed contract tests and Blender execution scaffold |
| `SET_SHADER_NODE_VALUE` | Passed Blender execution scaffold |
| `CONNECT_SHADER_NODES` | Passed invalid-socket contract tests |
| `REMOVE_SHADER_NODE` | Passed contract tests and Blender execution smoke test |
| `DISCONNECT_SHADER_LINK` | Passed contract tests and Blender execution smoke test |
| `CREATE_SHADER_COLOR_RAMP` | Passed contract tests and Blender execution smoke test |
| `SET_SHADER_COLOR_RAMP` | Passed contract tests and Blender execution smoke test |
| `CREATE_SHADER_MIX_CHAIN` | Passed contract tests and Blender execution smoke test |
| `CREATE_SHADER_GRAPH_TEMPLATE` | Passed contract tests and Blender residual execution smoke test |
| `VALIDATE_MATERIAL_OUTPUT` | Passed contract tests and Blender execution smoke test |
| `CREATE_LAYERED_SHADER_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `ADD_SHADER_LAYER` | Passed contract tests; Blender execution smoke scenario added |
| `SET_SHADER_LAYER_MASK` | Passed contract tests; Blender execution smoke scenario added |
| `REORDER_SHADER_LAYERS` | Passed contract tests; Blender execution smoke scenario added |
| `REMOVE_SHADER_LAYER` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_PROCEDURAL_PATTERN_NODE_SET` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_EDGE_WEAR_SHADER` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_TRIPLANAR_MAPPING_SETUP` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_OBJECT_SPACE_GRADIENT_SHADER` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_CURVATURE_STYLE_MASK` | Passed contract tests; Blender execution smoke scenario added |
| `EXTRACT_MATERIAL_PALETTE_FROM_IMAGE` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_MATERIAL_FROM_REFERENCE_IMAGE` | Passed contract tests; Blender execution smoke scenario added |
| `MATCH_MATERIAL_TO_REFERENCE` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_LOOKDEV_PREVIEW` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_GLASS_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_TRANSLUCENT_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_EMISSION_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_VOLUME_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_TOON_SHADER_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_ANISOTROPIC_MATERIAL` | Passed contract tests; Blender execution smoke scenario added |
| `REMOVE_UNUSED_ASSISTANT_SHADER_NODES` | Passed contract tests; Blender execution smoke scenario added |
| `CONSOLIDATE_DUPLICATE_ASSISTANT_MATERIALS` | Passed contract tests; Blender execution smoke scenario added |
| `NORMALIZE_SHADER_NODE_LAYOUT` | Passed contract tests; Blender execution smoke scenario added |
| `VALIDATE_SHADER_COMPATIBILITY` | Passed contract tests; Blender execution smoke scenario added |
| `REPAIR_BROKEN_SHADER_LINKS` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_MATERIAL_VARIANT` | Passed contract tests; Blender execution smoke scenario added |
| `TAG_MATERIAL_VARIANT` | Passed contract tests; Blender execution smoke scenario added |
| `CREATE_SHADER_COMPARISON_PREVIEW` | Passed contract tests; Blender execution smoke scenario added |
| `ACCEPT_MATERIAL_VARIANT` | Passed contract tests; Blender execution smoke scenario added |
| `REJECT_MATERIAL_VARIANT` | Passed contract tests; Blender execution smoke scenario added |
| `LOAD_IMAGE_TEXTURE` | Passed HTTPS/local validation and HTTP rejection contract tests |
| `CREATE_IMAGE_TEXTURE_NODE` | Passed contract tests and Blender execution |
| `SET_TEXTURE_MAPPING` | Passed contract tests and Blender execution |
| `ASSIGN_UV_MAP` | Passed contract tests and Blender execution |
| `CREATE_UV_MAP` | Passed contract tests and Blender execution |
| `UNWRAP_UV_MAP` | Passed contract tests and Blender execution |
| `PACK_UV_ISLANDS` | Passed contract tests and Blender execution |
| `INSPECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_DIAGNOSTIC_REPORT` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_OVERLAP_PREVIEW` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_STRETCH_PREVIEW` | Passed contract tests and Blender execution smoke test |
| `MARK_UV_SEAMS_BY_ANGLE` | Passed contract tests and Blender execution smoke test |
| `MARK_UV_SEAMS_BY_MATERIAL` | Passed contract tests and Blender execution smoke test |
| `MARK_UV_SEAMS_BY_EDGE_SET` | Passed contract tests and Blender execution smoke test |
| `CLEAR_UV_SEAMS` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_ISLANDS_FROM_SEAMS` | Passed contract tests and Blender execution smoke test |
| `SMART_PROJECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `CUBE_PROJECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `CYLINDER_PROJECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `SPHERE_PROJECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `CAMERA_PROJECT_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `LIGHTMAP_UNWRAP_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `SELECT_UV_ISLANDS_BY_MATERIAL` | Passed contract tests and Blender execution smoke test |
| `TRANSFORM_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `ALIGN_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `DISTRIBUTE_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `SCALE_UV_ISLANDS_TO_BOUNDS` | Passed contract tests and Blender execution smoke test |
| `PIN_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `UNPIN_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `SET_UV_TEXEL_DENSITY` | Passed contract tests and Blender execution smoke test |
| `NORMALIZE_UV_TEXEL_DENSITY` | Passed contract tests and Blender execution smoke test |
| `PACK_UV_ISLANDS_ADVANCED` | Passed contract tests and Blender execution smoke test |
| `MOVE_UV_ISLANDS_TO_TILE` | Passed contract tests and Blender execution smoke test |
| `CREATE_UDIM_TILE_LAYOUT` | Passed contract tests and Blender execution smoke test |
| `VALIDATE_UDIM_LAYOUT` | Passed contract tests and Blender execution smoke test |
| `RELAX_UV_ISLANDS` | Passed contract tests and Blender execution smoke test |
| `MINIMIZE_UV_STRETCH` | Passed contract tests and Blender execution smoke test |
| `REPAIR_UV_BOUNDS` | Passed contract tests and Blender execution smoke test |
| `MERGE_DUPLICATE_UV_MAPS` | Passed contract tests and Blender execution smoke test |
| `REMOVE_UNUSED_ASSISTANT_UV_MAPS` | Passed contract tests and Blender execution smoke test |
| `VALIDATE_UV_MAP` | Passed contract tests and Blender execution smoke test |
| `FIT_UV_ISLANDS_TO_IMAGE_REGION` | Passed contract tests and Blender execution smoke test |
| `CREATE_TEXTURE_ATLAS_LAYOUT` | Passed contract tests and Blender execution smoke test |
| `ASSIGN_ATLAS_TEXTURE_REGIONS` | Passed contract tests and Blender execution smoke test |
| `BAKE_UV_LAYOUT_GUIDE_IMAGE` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_GRID_TEST_MATERIAL` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_MAP_VARIANT` | Passed contract tests and Blender execution smoke test |
| `TAG_UV_VARIANT` | Passed contract tests and Blender execution smoke test |
| `CREATE_UV_COMPARISON_PREVIEW` | Passed contract tests and Blender execution smoke test |
| `ACCEPT_UV_VARIANT` | Passed contract tests and Blender execution smoke test |
| `REJECT_UV_VARIANT` | Passed contract tests and Blender execution smoke test |
| `IMPORT_PBR_TEXTURE_SET` | Passed role/color-space contract tests and Blender execution |
| `CREATE_PBR_MATERIAL` | Passed contract tests and Blender execution |
| `SET_PBR_TEXTURE_ROLE` | Passed contract tests and Blender execution |
| `GENERATE_IMAGE_ASSET` | Passed contract tests and Blender execution |
| `GENERATE_TEXTURE_IMAGE` | Passed contract tests and Blender execution |
| `SAVE_GENERATED_TEXTURE` | Passed contract tests and Blender execution |
| `APPLY_IMAGE_TO_MATERIAL` | Passed contract tests and Blender execution |
| `ATTACH_GENERATED_TEXTURE` | Passed contract tests and Blender execution |
| `CREATE_PAINT_IMAGE` | Passed contract tests and Blender execution |
| `ASSIGN_PAINT_SLOT` | Passed contract tests and Blender execution |
| `APPLY_TEXTURE_PAINT_STROKES` | Passed contract tests and Blender execution |
| `FILL_TEXTURE_REGION` | Passed contract tests and Blender execution |
| `CREATE_BAKE_TARGET_IMAGE` | Passed contract tests and Blender execution |
| `BAKE_TEXTURE_PASS` | Passed contract tests and Blender execution |
| `ASSIGN_BAKED_TEXTURE` | Passed contract tests and Blender execution |
| `ADD_DISPLACE_MODIFIER` | Passed contract tests and Blender execution scaffold |
| `ADD_SMOOTH_MODIFIER` | Passed contract tests |
| `ADD_REMESH_MODIFIER` | Passed high-risk contract tests |
| `SCULPT_SMOOTH_REGION` | Passed high-risk contract tests |
| `APPLY_SCULPT_BRUSH_STROKES` | Passed stroke-limit contract tests |
| `CREATE_GEOMETRY_NODES_PRESET` | Passed contract tests and Blender execution smoke test |
| `SET_GEOMETRY_NODE_INPUT` | Passed contract tests and Blender execution smoke test |
| `CREATE_GEOMETRY_NODE_GROUP_TEMPLATE` | Passed contract tests and Blender residual execution smoke test |
| `REMOVE_GEOMETRY_NODES_MODIFIER` | Passed contract tests |
| `CREATE_GENERATED_GEOMETRY_COPY` | Passed contract tests and Blender execution smoke test |
| `CREATE_SMOOTHED_COPY` | Passed contract tests and Blender execution smoke test |
| `CREATE_DISPLACED_COPY` | Passed contract tests and Blender execution smoke test |
| `CREATE_REMESHED_COPY` | Passed contract tests and Blender execution smoke test |
| `REPLACE_OBJECT_WITH_GENERATED_COPY` | Passed contract tests and Blender execution smoke test |
| `CREATE_SCULPT_REGION_FROM_MATERIAL` | Passed contract tests and Blender execution smoke test |
| `CREATE_SCULPT_REGION_FROM_VERTEX_GROUP` | Passed contract tests and Blender execution smoke test |
| `CREATE_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `INVERT_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `CLEAR_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `BLUR_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `SHARPEN_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `GROW_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `SHRINK_SCULPT_MASK` | Passed contract tests and Blender execution smoke test |
| `COMBINE_SCULPT_MASKS` | Passed contract tests and Blender execution smoke test |
| `CREATE_FACE_SET_FROM_MATERIAL` | Passed contract tests and Blender residual execution smoke test |
| `CREATE_FACE_SET_FROM_VERTEX_GROUP` | Passed contract tests and Blender residual execution smoke test |
| `APPLY_SCULPT_REGION_OPERATION` | Passed contract tests and Blender execution smoke test |
| `CREATE_DYNAMIC_TOPOLOGY_COPY` | Passed contract tests and Blender residual execution smoke test |
| `APPLY_GENERATED_MESH_TO_OBJECT` | Passed contract tests and Blender residual execution smoke test |
| `ADD_MULTIRES_MODIFIER` | Passed contract tests and Blender execution smoke test |
| `CREATE_SHAPE_KEY` | Passed contract tests and Blender execution smoke test |
| `CREATE_RIG_SAFE_SHAPE_KEY` | Passed contract tests and Blender residual execution smoke test |
| `SET_SHAPE_KEY_VALUE` | Passed contract tests and Blender residual execution smoke test |
| `CREATE_PREVIEW_IMAGE` | Passed contract tests and Blender execution smoke test |
| `CREATE_RENDER_PREVIEW_IMAGE` | Passed contract tests and Blender residual execution smoke test |

## Sample Scene Baseline

Measured on Windows x64, Blender 5.1.0:

| Fixture | Purpose | Baseline |
| --- | --- | --- |
| `simple_scene.blend` | Selected mesh/material context | 3 targets, 1,916 characters |
| `messy_scene.blend` | Privacy and budget reduction | 34 omissions, 10,121 characters |
| `large_scene.blend` | 1,000-object context performance | 0.035 seconds, 976 omissions, 29,294 characters |

The automated performance ceiling is 15 seconds to avoid machine-specific false failures. Baseline
changes should be reviewed when context serialization behavior changes.

## Manual Foreground Checklist

These checks require an interactive Blender window and are not claimed as automated:

1. Install the release ZIP in a clean Blender profile.
2. Open `tests/fixtures/simple_scene.blend` and submit a low-risk transform request.
3. Confirm the plan preview identifies the exact object and values before applying.
4. Apply the plan, press Ctrl-Z once, and confirm the original transform returns.
5. Redo and confirm the complete plan returns as one undoable transaction.
6. Submit a delete request and confirm the high-risk dialog cannot be bypassed.
7. Apply the confirmed delete, then verify Undo restores the object and its child relationships.
8. Disable network access and confirm planning fails without freezing the 3D View.
9. Re-enable network access and verify a fresh request succeeds.
10. Inspect the Context and AI Usage sections for omissions, model, token counts, and no API key.

## Release Gate

Run all non-billable automated checks, build the archive, and test a clean-profile installation:

```powershell
.\scripts\run_release_checks.ps1
```

Use `-RunLiveOpenAI` only with explicit cost acknowledgement and an operating-system API key.

Texture and sculpting Python contract tests run under normal `pytest`. Shader Tracks A-G,
advanced UV Tracks A-H, future-track, residual deferred-feature, and texture/sculpting execution
coverage are all part of `tests/run_execution_tests.py`.
