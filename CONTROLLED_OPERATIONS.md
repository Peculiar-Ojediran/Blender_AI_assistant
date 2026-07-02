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
| `SET_MATERIAL_PROPERTIES` | material ID, nullable base color/metallic/roughness/alpha | Low |
| `CREATE_COLLECTION` | name, parent collection ID or null | Low |
| `SET_LIGHT_PROPERTIES` | target IDs, nullable color/energy/size | Low |
| `SET_CAMERA_PROPERTIES` | target IDs, nullable focal length/active flag | Low |
| `ADD_MODIFIER` | target IDs, supported modifier type, name, nullable supported settings | Medium |
| `SET_MODIFIER_PROPERTIES` | target IDs, modifier name, nullable supported settings | Medium |
| `CREATE_TEXT_OBJECT` | name, collection ID or null, body, transform, alignment, size, extrude | Low |
| `SET_OBJECT_VISIBILITY` | target IDs, nullable viewport/render visibility flags | Low |
| `IMPORT_ASSET` | local filepath or HTTPS URL, format, collection ID or null, name prefix or null, transform | High |
| `LINK_OR_APPEND_BLEND_DATA` | local blend filepath, mode, datablock type/names, collection ID or null, name prefix or null | High |
| `BOOLEAN_OPERATION` | target ID, cutter ID, operation, solver, non-applied flag, modifier name, hide-cutter flag | High |
| `JOIN_OBJECTS` | target IDs, new object name, collection ID or null | High |
| `SEPARATE_OBJECTS` | target IDs, mode, name prefix, collection ID or null | High |
| `CREATE_MATERIAL_PRESET` | name, material family, colors, metallic, roughness, alpha, transmission/emission, procedural detail controls | Low |
| `CREATE_PROCEDURAL_MATERIAL` | name, material family, procedural pattern, colors, metallic, roughness, alpha, scale/detail/bump controls | Low |
| `CREATE_SHADER_NODE` | material ID, approved node type, node label | Low |
| `SET_SHADER_NODE_VALUE` | material ID, node reference, approved input socket, bounded value | Low |
| `CONNECT_SHADER_NODES` | material ID, from/to node references, approved from/to sockets | Low |
| `REMOVE_SHADER_NODE` | material ID, assistant-created node reference | Medium |
| `DISCONNECT_SHADER_LINK` | material ID, explicit from/to node references and sockets | Medium |
| `CREATE_SHADER_COLOR_RAMP` | material ID, node label, bounded color stops | Medium |
| `SET_SHADER_COLOR_RAMP` | material ID, node reference, bounded color stops | Medium |
| `CREATE_SHADER_MIX_CHAIN` | material ID, chain label, template, colors, scale/detail/bump controls | Medium |
| `CREATE_SHADER_GRAPH_TEMPLATE` | material ID, graph label, approved template, colors, strength, scale | Medium |
| `VALIDATE_MATERIAL_OUTPUT` | material ID, repair flag | Medium |
| `LOAD_IMAGE_TEXTURE` | local or HTTPS image source, image name, color space, max size | High |
| `CREATE_IMAGE_TEXTURE_NODE` | material ID, image result ID, node label, target socket, projection, extension | Medium |
| `SET_TEXTURE_MAPPING` | material ID, texture node reference, translation, rotation, scale, projection, extension | Medium |
| `ASSIGN_UV_MAP` | object ID, material ID, texture node reference, UV map name | Medium |
| `CREATE_UV_MAP` | target IDs, UV map name, active/render flags | Medium |
| `UNWRAP_UV_MAP` | target IDs, UV map name, method, create/overwrite flags, margin | High |
| `PACK_UV_ISLANDS` | target IDs, UV map name, margin, rotate flag | High |
| `IMPORT_PBR_TEXTURE_SET` | name prefix, explicit texture role/source/color-space entries | High |
| `CREATE_PBR_MATERIAL` | name, texture set or nullable image IDs, fallback PBR values | High |
| `SET_PBR_TEXTURE_ROLE` | texture set result ID, image result ID, role, color space | Medium |
| `GENERATE_TEXTURE_IMAGE` | prompt, image name, dimensions, pattern, colors, color space, pack flag | High |
| `SAVE_GENERATED_TEXTURE` | image result ID, explicit local output path, file format, pack-after-save flag | High |
| `ATTACH_GENERATED_TEXTURE` | material ID, image result ID, node label, target socket, nullable UV map | Medium |
| `CREATE_PAINT_IMAGE` | image name, dimensions, fill color, color space, pack flag | High |
| `ASSIGN_PAINT_SLOT` | object ID, material ID, image result ID, UV map name, node label, target socket | Medium |
| `APPLY_TEXTURE_PAINT_STROKES` | image result ID, blend mode, bounded UV-space strokes | High |
| `FILL_TEXTURE_REGION` | image result ID, region, color, strength, blend mode | Medium |
| `CREATE_BAKE_TARGET_IMAGE` | image name, dimensions, fill color, color space, pack flag | High |
| `BAKE_TEXTURE_PASS` | object ID, image result ID, UV map name, pass type, samples, margin | High |
| `ASSIGN_BAKED_TEXTURE` | material ID, image result ID, node label, target socket, nullable UV map | Medium |
| `ADD_DISPLACE_MODIFIER` | target IDs, name, procedural texture pattern, strength, midlevel, scale, coordinates, non-applied flag | Medium |
| `ADD_SMOOTH_MODIFIER` | target IDs, name, factor, iterations, non-applied flag | Medium |
| `ADD_REMESH_MODIFIER` | target IDs, name, mode, voxel size, adaptivity, preserve-volume flag, non-applied flag | High |
| `SCULPT_SMOOTH_REGION` | target ID, region with kind plus nullable material ID and vertex group, strength, radius, iterations | High |
| `APPLY_SCULPT_BRUSH_STROKES` | target ID, brush type, radius, strength, falloff, bounded strokes | High |
| `CREATE_GEOMETRY_NODES_PRESET` | target IDs, preset name, approved exposed inputs, non-applied flag | High |
| `SET_GEOMETRY_NODE_INPUT` | target ID, modifier name, approved input name and value | Medium |
| `CREATE_GEOMETRY_NODE_GROUP_TEMPLATE` | target IDs, name, approved group template, approved exposed inputs, apply flag | High |
| `REMOVE_GEOMETRY_NODES_MODIFIER` | target ID, assistant-created modifier name | Medium |
| `CREATE_GENERATED_GEOMETRY_COPY` | target ID, name, approved variant, strength/detail, preserve-original flag | High |
| `CREATE_SMOOTHED_COPY` | target ID, name, factor, iterations, preserve-original flag | High |
| `CREATE_DISPLACED_COPY` | target ID, name, pattern, strength, scale, preserve-original flag | High |
| `CREATE_REMESHED_COPY` | target ID, name, remesh mode or triangulate mode, preserve-original flag | High |
| `REPLACE_OBJECT_WITH_GENERATED_COPY` | original target ID, generated object result ID, hide-original flag | High |
| `CREATE_SCULPT_REGION_FROM_MATERIAL` | target ID, material ID, region name | High |
| `CREATE_SCULPT_REGION_FROM_VERTEX_GROUP` | target ID, vertex group name, region name | High |
| `CREATE_SCULPT_MASK` | target ID, sculpt region result ID, mask name, strength | High |
| `CREATE_FACE_SET_FROM_MATERIAL` | target ID, material ID, face-set name | High |
| `CREATE_FACE_SET_FROM_VERTEX_GROUP` | target ID, vertex group name, face-set name | High |
| `APPLY_SCULPT_REGION_OPERATION` | sculpt region result ID, mode, strength, iterations | High |
| `CREATE_DYNAMIC_TOPOLOGY_COPY` | target ID, generated name, detail level, preserve-original flag | High |
| `APPLY_GENERATED_MESH_TO_OBJECT` | target ID, generated object result ID, preserve-original-data flag, hide-generated flag | High |
| `ADD_MULTIRES_MODIFIER` | target IDs, name, levels, render levels, non-applied flag | High |
| `CREATE_SHAPE_KEY` | target ID, key name, value, nullable generated-object result ID | High |
| `CREATE_RIG_SAFE_SHAPE_KEY` | target ID, key name, value, nullable generated-object result ID, rig/animation guards | High |
| `SET_SHAPE_KEY_VALUE` | target ID, shape-key name, bounded value | Medium |
| `CREATE_PREVIEW_IMAGE` | preview name, dimensions, source kind, background and overlay colors, pack flag | Medium |
| `CREATE_RENDER_PREVIEW_IMAGE` | preview name, mode, nullable target/camera IDs, dimensions, samples, pack flag | Medium |

Arbitrary Geometry Nodes graphs, arbitrary animation or rig generation, arbitrary directory
browsing, arbitrary file access, and arbitrary Python are not part of the controlled contract.

## Reference Rules

Existing targets use typed IDs from the submitted context snapshot:

- Objects: `obj_0001` and later numeric IDs.
- Materials: `mat_0001` and later numeric IDs.
- Collections: `col_0001` and later numeric IDs.

`CREATE_PRIMITIVE`, `CREATE_MATERIAL`, `CREATE_MATERIAL_PRESET`,
`CREATE_PROCEDURAL_MATERIAL`, `ADD_LIGHT`, `ADD_CAMERA`, `CREATE_COLLECTION`,
`CREATE_TEXT_OBJECT`, `JOIN_OBJECTS`, `CREATE_SHADER_NODE`, `LOAD_IMAGE_TEXTURE`,
`CREATE_SHADER_COLOR_RAMP`, `CREATE_SHADER_MIX_CHAIN`, `CREATE_SHADER_GRAPH_TEMPLATE`,
`CREATE_IMAGE_TEXTURE_NODE`, `IMPORT_PBR_TEXTURE_SET`, `CREATE_PBR_MATERIAL`,
`GENERATE_TEXTURE_IMAGE`, `CREATE_PAINT_IMAGE`, `CREATE_BAKE_TARGET_IMAGE`, `ASSIGN_PAINT_SLOT`,
`ATTACH_GENERATED_TEXTURE`, `ASSIGN_BAKED_TEXTURE`, `CREATE_GENERATED_GEOMETRY_COPY`,
`CREATE_SMOOTHED_COPY`, `CREATE_DISPLACED_COPY`, `CREATE_REMESHED_COPY`,
`CREATE_SCULPT_REGION_FROM_MATERIAL`, `CREATE_SCULPT_REGION_FROM_VERTEX_GROUP`,
`CREATE_SCULPT_MASK`, `CREATE_DYNAMIC_TOPOLOGY_COPY`, `CREATE_FACE_SET_FROM_MATERIAL`,
`CREATE_FACE_SET_FROM_VERTEX_GROUP`, `CREATE_PREVIEW_IMAGE`, and `CREATE_RENDER_PREVIEW_IMAGE`
each produce one addressable result. A later operation in the same plan may reference that result
as `result:<operation_id>`. Forward references and result-kind mismatches are rejected. Duplicate
operations, asset imports, blend data loading, and separate operations can produce multiple objects
and therefore do not expose one object result reference in the MVP.

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
- `SET_MATERIAL_PROPERTIES` updates only provided material fields and leaves null fields unchanged.
- `CREATE_COLLECTION` creates one collection under the referenced parent collection or scene root.
  The requested name must be available.
- `SET_LIGHT_PROPERTIES` updates only provided light fields. `size` keeps the same meaning used by
  `ADD_LIGHT`.
- `SET_CAMERA_PROPERTIES` updates focal length and can make a referenced camera active.
- `ADD_MODIFIER` adds one supported, non-applied modifier: bevel, solidify, mirror, subdivision
  surface, array, or weighted normal.
- `SET_MODIFIER_PROPERTIES` updates supported fields on an existing named modifier.
- `CREATE_TEXT_OBJECT` creates one Blender text object with explicit transform, alignment, size,
  and extrusion values.
- `SET_OBJECT_VISIBILITY` sets viewport and/or render visibility while leaving null fields
  unchanged.
- `IMPORT_ASSET` imports local or HTTPS `.obj`, `.fbx`, `.gltf`, or `.glb` files. HTTP, FTP,
  `file://`, and other URL schemes are rejected. URL downloads are bounded before import.
  Imported objects are moved to the requested collection and receive the requested transform.
- `LINK_OR_APPEND_BLEND_DATA` links or appends explicit object or collection names from a local
  `.blend` file. It cannot browse or import arbitrary datablock types.
- `BOOLEAN_OPERATION` creates a non-applied Boolean modifier between two mesh objects. Applying the
  Boolean is deliberately unsupported so the transaction can remain rollback-safe.
- `JOIN_OBJECTS` creates one generated mesh object from explicit mesh targets and defers deletion
  of the original targets until the rest of the plan succeeds.
- `SEPARATE_OBJECTS` creates generated mesh objects from explicit mesh targets by material or loose
  parts and defers deletion of the original targets until the rest of the plan succeeds.
- `CREATE_MATERIAL_PRESET` creates one controlled Principled BSDF material with allowlisted material
  family controls and deterministic procedural detail nodes.
- `CREATE_PROCEDURAL_MATERIAL` creates one controlled procedural material template with allowlisted
  pattern controls and bounded bump/detail values.
- `CREATE_SHADER_NODE` creates one allowlisted node in a referenced material node tree.
- `SET_SHADER_NODE_VALUE` changes one allowlisted shader input socket and stores the previous value
  for rollback.
- `CONNECT_SHADER_NODES` connects explicit allowlisted sockets inside one material and rolls back by
  removing the created link.
- `LOAD_IMAGE_TEXTURE` loads a local or HTTPS `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, or
  `.exr` image, with a per-operation size cap. HTTP and other schemes are rejected.
- `CREATE_IMAGE_TEXTURE_NODE` creates a controlled image texture node, texture coordinate node, and
  mapping node in a material, then connects the image to an approved shader socket.
- `SET_TEXTURE_MAPPING` updates a controlled mapping node attached to a controlled image texture
  node. Translation, rotation, scale, projection, and extension are explicit and bounded.
- `ASSIGN_UV_MAP` assigns an existing mesh UV map to a controlled image texture node through a UV
  Map node. Missing UV maps reject during preflight.
- `CREATE_UV_MAP` adds a new UV map to explicit mesh targets and can mark it active/render-active.
- `UNWRAP_UV_MAP` writes bounded generated UV coordinates to an explicit UV map. It requires explicit
  create/overwrite flags and stores previous UV coordinates for rollback.
- `PACK_UV_ISLANDS` normalizes existing UV coordinates into the allowed UV space with the requested
  margin and stores previous UV coordinates for rollback.
- `IMPORT_PBR_TEXTURE_SET` loads explicitly listed image sources into role-tagged PBR texture sets.
  It does not scan directories or infer files from folders.
- `CREATE_PBR_MATERIAL` builds one controlled Principled BSDF material from a texture set and/or
  explicit image results. Non-color PBR roles are forced to non-color color space.
- `SET_PBR_TEXTURE_ROLE` updates a texture set role and color space for an explicit image result.
- `GENERATE_TEXTURE_IMAGE` creates a bounded local image from prompt metadata and an approved
  pattern. When `OPENAI_IMAGE_GENERATION_ENABLED=true`, it may call OpenAI image generation using the
  existing `OPENAI_API_KEY`; otherwise it falls back to deterministic local pattern generation.
- `SAVE_GENERATED_TEXTURE` saves an explicit image result to a local path whose parent directory
  already exists. Existing output files are not overwritten.
- `ATTACH_GENERATED_TEXTURE`, `ASSIGN_PAINT_SLOT`, and `ASSIGN_BAKED_TEXTURE` attach explicit image
  results to controlled material texture nodes.
- `CREATE_PAINT_IMAGE` and `CREATE_BAKE_TARGET_IMAGE` create bounded image datablocks with explicit
  dimensions, fill color, color space, and packing behavior.
- `APPLY_TEXTURE_PAINT_STROKES` edits image pixels with bounded UV-space strokes and stores prior
  pixels for rollback.
- `FILL_TEXTURE_REGION` fills a full image or explicit UV rectangle and stores prior pixels for
  rollback.
- `BAKE_TEXTURE_PASS` writes a bounded deterministic bake pass into an explicit image result after
  validating the mesh target and UV map.
- `ADD_DISPLACE_MODIFIER`, `ADD_SMOOTH_MODIFIER`, and `ADD_REMESH_MODIFIER` add non-applied mesh
  modifiers only. Remesh is high risk because it can significantly alter visible geometry if later
  applied by the user.
- `REMOVE_SHADER_NODE` removes only assistant-created shader nodes and refuses protected material
  output nodes.
- `DISCONNECT_SHADER_LINK` removes one explicit existing shader link between allowlisted sockets.
- `CREATE_SHADER_COLOR_RAMP` and `SET_SHADER_COLOR_RAMP` create or update bounded color ramp stops.
- `CREATE_SHADER_MIX_CHAIN` creates a known safe shader subgraph template, not an arbitrary graph.
- `CREATE_SHADER_GRAPH_TEMPLATE` creates one approved larger shader template from an allowlisted
  template name and bounded color/detail controls.
- `VALIDATE_MATERIAL_OUTPUT` checks or repairs the material output surface connection with safe
  defaults.
- `SCULPT_SMOOTH_REGION` edits mesh vertex coordinates for an explicit mesh target and stores the
  affected vertex positions before mutation for rollback.
- `APPLY_SCULPT_BRUSH_STROKES` replays bounded sculpt-like strokes from structured data and stores
  affected vertex positions before mutation for rollback. If a stroke misses all vertices inside
  its radius, execution snaps that stroke to the nearest vertex neighborhood instead of rolling back
  the whole plan.
- `CREATE_GEOMETRY_NODES_PRESET` adds a template-driven Geometry Nodes modifier marker with
  approved preset names and bounded exposed inputs. It does not generate arbitrary node graphs.
- `SET_GEOMETRY_NODE_INPUT` updates one approved exposed Geometry Nodes input on an assistant-created
  preset modifier.
- `CREATE_GEOMETRY_NODE_GROUP_TEMPLATE` creates an approved pass-through Geometry Nodes node group
  template and attaches it through a non-applied modifier.
- `REMOVE_GEOMETRY_NODES_MODIFIER` removes only assistant-created Geometry Nodes preset modifiers.
- `CREATE_GENERATED_GEOMETRY_COPY`, `CREATE_SMOOTHED_COPY`, `CREATE_DISPLACED_COPY`, and
  `CREATE_REMESHED_COPY` create new mesh objects while preserving the original target.
- `REPLACE_OBJECT_WITH_GENERATED_COPY` can hide the original and reveal a generated copy after
  explicit approval; it does not delete the original.
- `CREATE_SCULPT_REGION_FROM_MATERIAL` and `CREATE_SCULPT_REGION_FROM_VERTEX_GROUP` create named
  runtime sculpt regions from explicit mesh selections.
- `CREATE_SCULPT_MASK` creates a vertex-group mask from a sculpt region.
- `CREATE_FACE_SET_FROM_MATERIAL` and `CREATE_FACE_SET_FROM_VERTEX_GROUP` create mesh face
  attributes from explicit material or vertex-group selections.
- `APPLY_SCULPT_REGION_OPERATION` applies bounded smooth, inflate, or flatten behavior to an
  explicit sculpt region with rollback.
- `CREATE_DYNAMIC_TOPOLOGY_COPY` creates a generated dynamic-topology-style mesh copy and preserves
  the original target.
- `APPLY_GENERATED_MESH_TO_OBJECT` explicitly replaces one object's mesh data with a generated
  object mesh copy while keeping rollback data.
- `ADD_MULTIRES_MODIFIER` adds a non-applied Multires modifier only.
- `CREATE_SHAPE_KEY` creates a bounded shape key, optionally copying coordinates from a generated
  object with the same vertex count.
- `CREATE_RIG_SAFE_SHAPE_KEY` adds rig and animation guards around shape-key creation.
- `SET_SHAPE_KEY_VALUE` updates one existing shape key value with rollback.
- `CREATE_PREVIEW_IMAGE` creates a bounded local review image datablock. It is not a full render.
- `CREATE_RENDER_PREVIEW_IMAGE` creates a bounded low-resolution render preview image with temporary
  render settings restored after execution.

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
- Property update operations must change at least one supported field.
- File operations require an allowed file extension. URL asset imports must use HTTPS, while blend
  link/append remains local-file only.
- Image texture operations require an allowed image extension. URL image sources must use HTTPS.
- PBR texture sets require unique roles, explicit files, and correct color space for color vs
  non-color roles.
- Generated texture saves require explicit local output paths and cannot overwrite existing files.
- UV operations require explicit UV map names; unwrap requires explicit create/overwrite choices.
- Texture paint and fill operations use bounded image dimensions, strokes, UV coordinates, strength,
  and blend modes.
- Bake operations require an explicit target image, mesh target, UV map name, pass type, sample
  count, and margin.
- Boolean operations require distinct mesh target and cutter objects and cannot be applied.
- Join and separate operations require mesh targets.
- Material families, procedural patterns, shader node types, shader sockets, texture patterns,
  sculpt brushes, falloffs, remesh modes, and sculpt regions are allowlisted.
- Shader graph editing is limited to assistant-created nodes, explicit links, bounded color ramps,
  safe mix-chain templates, and output repair.
- Sculpt regions always include `kind`, `material_id`, and `vertex_group`; unused region fields are
  null.
- Sculpt brush stroke lists are capped at 500 strokes.
- Geometry Nodes are template-driven only; arbitrary node graph generation is rejected.
- Generated mesh copy operations enforce mesh size limits and preserve originals by default.
- Sculpt region results must come from earlier region creation operations before mask or region
  operations can reference them.
- Full sculpt-mode dynamic topology and provider-authored destructive remesh are rejected. The
  supported path is generated dynamic-topology-style copies followed by explicit generated-mesh
  application when approved.
- Preview and render-preview images are bounded local datablocks and may contain scene-derived
  metadata.
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
