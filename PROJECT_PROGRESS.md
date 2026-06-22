# Project Progress

All timestamps use the `America/Toronto` timezone. Add new entries in chronological order, with the earliest entry at the top and the newest entry at the bottom.

## 2026-06-19 10:29:01 -04:00

### Progress Log Initialized

- Established `PROJECT_PROGRESS.md` as the project change log.
- Recorded the existing planning baseline completed before this log was created.
- Created `AI_BLENDER_EXTENSION_PLAN.md` with project scope, architecture options, build phases, risks, testing strategy, and prior-art research.
- Expanded the plan around controlled operations, structured AI-response validation, context budgets, Blender main-thread constraints, operator context, undo reliability, approval UX, early packaging validation, and product differentiation.
- No implementation code has been added; the project remains in the planning phase.

## 2026-06-19 10:39:49 -04:00

### Development Dependencies Installed and Verified

- Confirmed Blender 5.1.0 is installed with bundled Python 3.13.9.
- Created a workspace-local `.venv` from Blender's Python interpreter.
- Installed and pinned `requests`, `fastjsonschema`, `pytest`, `pytest-cov`, `ruff`, `mypy`, `types-requests`, and Blender API type stubs.
- Added runtime, development, and full lock requirement files.
- Added `pyproject.toml`, `.gitignore`, and `DEVELOPMENT_SETUP.md`.
- Added normal-Python and real-Blender dependency smoke tests.
- Verified `pip check`, 3 pytest tests, Ruff, Mypy, schema validation, and Blender 5.1 background execution.
- Chose a provider-neutral direct HTTPS approach for the initial runtime; no OpenAI or Anthropic SDK has been added.

## 2026-06-19 10:56:43 -04:00

### OpenAI Provider Foundation Added

- Selected OpenAI as the initial AI provider and GPT-5.5 as the initial model.
- Kept the provider boundary replaceable and used direct HTTPS instead of adding an SDK.
- Added the minimal Blender 5.1 extension manifest and registration module.
- Added a provider protocol and OpenAI Responses API implementation.
- Added Structured Outputs request construction and mandatory local schema validation.
- Added API, authentication, refusal, malformed-response, and validation error handling.
- Added mocked OpenAI provider tests; no live API request or API key was used.
- Added Blender registration testing with reliable nonzero failure exit codes.
- Built and validated `dist/blender_ai_assistant-0.1.0.zip`.
- Verified 8 pytest tests, Ruff, Mypy, Blender background execution, source manifest validation, archive validation, and package contents.

## 2026-06-19 11:08:18 -04:00

### Project Package Skeleton Created

- Added `ARCHITECTURE.md` with the request flow, dependency direction, threading boundary, and implementation order.
- Added workflow modules for coordination, asynchronous runtime handling, and state.
- Added scene-context modules for models, reading, serialization, budgets, and privacy filtering.
- Added controlled-operation modules for models, catalog, schema, validation, target resolution, risk, execution, and undo.
- Added UI modules for panels, operators, preferences, and properties.
- Added history modules plus shared configuration and error modules.
- Added unit, Blender, and fixture test-directory documentation.
- Kept all new modules intentionally minimal so each subsystem can be implemented and tested separately.
- Verified 32 extension module imports, 8 pytest tests, Ruff, Mypy across 36 source files, Blender registration, source validation, archive build, and archive validation.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the complete package skeleton.

## 2026-06-19 16:29:14 -04:00

### Controlled Operation Contract Integrated

- Added typed plan status, operation type, risk, operation, plan, and risk-assessment models.
- Added a local catalog for ten MVP operation types and their safety metadata.
- Added the strict JSON Schema sent to OpenAI through Structured Outputs.
- Added structural and semantic validation for plan states, unique operation IDs, numeric values, transforms, scales, renames, and duplicate limits.
- Added locally derived risk and confirmation rules; the model cannot decide whether its plan is safe.
- Added `CONTROLLED_OPERATIONS.md` as the human-readable contract reference.
- Updated OpenAI instructions to return clarification questions instead of guessing missing information.
- Deferred modifiers, edit-mode mesh operations, geometry nodes, rigging, animation, file access, and arbitrary Python.
- Added coverage for all ten operation variants and major rejection paths.
- Verified 35 pytest tests, Ruff, Mypy, Blender 5.1 contract validation, source validation, archive build, and archive validation.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the integrated contract.

## 2026-06-19 16:46:57 -04:00

### MVP UX Design Completed

- Added `UX_DESIGN.md` as the implementation specification for the Blender-native interface.
- Chose a compact `AI Assistant` tab in the 3D View sidebar with Assistant, Plan, Context, and History sections.
- Defined configuration, idle, context collection, planning, validation, clarification, approval, execution, completion, error, and cancellation states.
- Defined explicit plan preview before every execution and an additional confirmation dialog for high-risk plans.
- Confirmed that MVP plan editing means rephrase or reject; structured operations remain read-only.
- Defined selection, collection, and budgeted scene context modes plus a privacy/context preview.
- Defined result, partial execution, cancellation, undo, history, error, and secret-redaction behavior.
- Defined OpenAI preferences with environment-key priority and a masked session-only key that is never persisted.
- Added accessibility, layout-density, module-mapping, deferred-feature, and acceptance-criteria requirements.
- Corrected the Core Interaction Flow heading in the main project plan and linked the UX specification from architecture and planning documents.
- No runtime UI code was added during this design milestone.

## 2026-06-19 18:52:24 -04:00

### Blender UX Implemented

- Registered an `AI Assistant` tab in the 3D View sidebar.
- Added Assistant, Context, Plan, and History panels with state-dependent visibility and controls.
- Added Blender WindowManager properties for prompt drafts, context scope, workflow status, clarification, plan previews, risk, progress, results, errors, and bounded session history.
- Added OpenAI preferences for model, timeout, context/privacy settings, environment-key detection, and a masked session key marked `SKIP_SAVE`.
- Added safe operators for settings, prompt clearing, planning entry, clarification, cancellation, rejection, rephrasing, application confirmation, error dismissal, new requests, and context details.
- Added explicit high-risk confirmation UI and kept all structured operations read-only.
- Added workflow-state definitions and legal-transition tests.
- Kept live planning and execution disconnected; unavailable actions fail without changing the Blender scene.
- Expanded Blender background tests to verify UI registration, state defaults, command execution, and clean unregistration.
- Verified 39 pytest tests, Ruff, Mypy across 38 source files, Blender 5.1 UI smoke tests, source validation, archive build, and archive validation.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the implemented UX.

## 2026-06-19 20:28:03 -04:00

### Scene Context System Implemented

- Added Blender-independent immutable scene-context records and validated context options.
- Added deterministic active/selected-first object budgeting with separate detail and summary limits.
- Added selection, active-collection, and budgeted full-scene collection on Blender's main thread.
- Added opaque object, material, and collection target IDs plus a local target index that is excluded from provider payloads.
- Added object transforms, mesh counts, light data, camera data, materials, collections, modifiers, and scene metadata.
- Added privacy filtering for custom properties and file paths, bounded JSON conversion, omission counts, and collection warnings.
- Added deterministic provider-safe JSON serialization with exact character-count reporting.
- Connected `Preview Context` and `Plan Changes` to live context collection and UI summary fields without enabling scene mutation.
- Added `SCENE_CONTEXT.md` and updated the architecture, implementation plan, UX mapping, and development verification notes.
- Added unit coverage for budgets, privacy, serialization, and target-index exclusion.
- Expanded Blender background coverage to verify real scene reading, path redaction, material capture, target resolution, serialization, and UI preview updates.
- Verified 44 pytest tests, Ruff, Mypy across 40 source files, Blender 5.1 background tests, source validation, archive build, and archive validation.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the scene context system.

## 2026-06-20 01:00:24 -04:00

### Pre-Planning Safety Gaps Resolved

- Added random context snapshot IDs that provider plans must echo exactly.
- Added Blender `session_uid` and deterministic state fingerprints to local target references.
- Added main-thread target resolution that rejects unknown, wrong-kind, missing, replaced, renamed, transformed, reparented, or otherwise changed targets.
- Added typed `obj_`, `mat_`, and `col_` reference formats plus backward-only `result:<operation_id>` references for single-result creation operations.
- Defined binding execution semantics for units, radians, relative transforms, duplication, deletion, material assignment, collection movement, naming collisions, and creation-result references.
- Changed material creation to use RGB base color plus one separate alpha value.
- Restricted selection/collection context to materials and collections relevant to the scoped objects and collection ancestry.
- Added a configurable 100,000-character default context ceiling with deterministic snapshot reduction and synchronized target-index pruning.
- Added UI preferences for the serialized context character budget.
- Added unit tests for snapshot binding, typed references, result ordering/kinds, sun-light radians, and global context reduction.
- Expanded Blender tests for irrelevant-resource exclusion, valid target resolution, changed-state rejection, replaced-datablock rejection, and payload ceilings.
- Recorded mandatory phase-5 requirements for job generation IDs, stale-response rejection, cancellation, timeout handling, main-thread handoff, unregister cleanup, complete preflight, and atomic rollback behavior.
- Verified 51 pytest tests, Ruff, Mypy across 41 source files, Blender 5.1 background tests, source validation, archive build, and archive validation.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the pre-planning safety changes.

## 2026-06-20 01:45:49 -04:00

### Current-Stage Integration Verified

- Audited imports and contracts across context, provider, controlled operations, risk, workflow state, UI, and packaging modules.
- Added a normal-Python integration test covering serialized scene context, mocked OpenAI Structured Outputs, snapshot binding, semantic plan validation, typed operations, and local risk assessment.
- Added a Blender import sweep that loads every extension module before registration.
- Added a snapshot-bound Blender plan test connecting live scene context, operation validation, and stale-safe target resolution.
- Added a reusable installed-extension test that imports every packaged module and verifies UI registration from the installed ZIP.
- Installed and enabled the built archive in an isolated Blender profile and verified startup in a fresh Blender process.
- Confirmed that incomplete workflow coordinator, asynchronous runtime, execution, undo, and history modules remain intentionally disconnected and cannot mutate scenes.
- Verified 52 pytest tests, Ruff, Mypy across 43 source files, Blender 5.1 source integration, source/archive validation, installed-package imports, and fresh-process UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` after integration verification.

## 2026-06-20 01:59:16 -04:00

### AI Planning Layer Implemented

- Connected Blender prompt submission to the OpenAI Responses API provider through a provider-neutral coordinator.
- Added generation-scoped daemon workers, queue-only result handoff, logical cancellation, superseded-response rejection, and non-blocking shutdown.
- Added a persistent Blender main-thread timer for accepted planning results and UI updates.
- Retained the exact scene snapshot through provider response validation and plan approval.
- Added worker-safe snapshot reference validation and repeated live Blender identity/fingerprint validation on the main thread.
- Added strict snapshot binding, semantic operation validation, local risk assessment, and one bounded repair request for locally invalid plans.
- Added complete, incomplete, failed, canceled, refusal, malformed-response, API, authentication, and network error handling at the provider boundary.
- Connected clarification questions and fresh-snapshot clarification responses to the planning workflow.
- Populated immutable plan summaries, assumptions, operation previews, target counts, and risk information in the Blender UI.
- Removed the obsolete mutable backend-availability flag; capability now follows registered coordinator and executor boundaries.
- Kept controlled execution disabled, so planning and approval cannot mutate the Blender scene.
- Added deterministic tests for runtime completion, cancellation, supersession, shutdown, coordinator success/failure, snapshot mismatch, unknown targets, and one-shot repair.
- Expanded Blender integration tests to verify mocked background planning reaches approval state without scene mutation.
- Verified 60 pytest tests, Ruff, Mypy across 46 source files, Blender 5.1 background planning, source/archive validation, clean-profile installation, packaged imports, and fresh-process UI registration.
- No live OpenAI request or API key was used; provider behavior remains covered with mocked responses.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the AI planning layer.

## 2026-06-20 02:43:16 -04:00

### AI Planning Layer Hardened

- Made validated operation payloads recursively immutable, including nested mappings and lists.
- Made context snapshot mismatches terminal so they cannot trigger a provider repair request.
- Serialized background planning to one worker with one latest pending generation, cooperative
  cancellation, and cancellation checks around initial and repair provider calls.
- Retained the original request and every clarification round across multi-round planning.
- Added bounded retries for explicit transient OpenAI HTTP responses, `Retry-After` support,
  response output limits, provider request-ID diagnostics, and structured API error metadata.
- Required an explicit completed Responses API status and hardened provider instructions against
  instructions embedded in scene names, paths, custom properties, or other context values.
- Added legal-state guards to planning UI operators, kept execution controls disabled until Phase 6,
  preserved retained plans when dismissing errors, and made timer polling recover from exceptions.
- Added regression coverage for immutability, terminal snapshot mismatch, cancellation-aware repair,
  clarification history, response status, retries, diagnostics, UI guards, and timer recovery.
- Added one opt-in live OpenAI smoke test that is skipped unless explicitly enabled with an API key;
  no live or billable API request was made during verification.
- Verified 66 pytest tests with 1 live test skipped, Ruff, Mypy across 47 source files, and Blender
  5.1 background integration tests.
- Rebuilt and validated `dist/blender_ai_assistant-0.1.0.zip` with the hardened planning layer.
- Installed the rebuilt archive into an isolated extension repository and verified packaged-module
  imports plus UI registration in a fresh Blender process.

## 2026-06-20 13:55:57 -04:00

### Controlled Execution Layer Implemented

- Implemented complete scene-aware preflight for ready plans, including retained-snapshot checks,
  active-scene and Object Mode requirements, live target identity/fingerprint validation, linked
  data restrictions, collection membership, lifecycle ordering, result bindings, and name conflicts.
- Implemented all ten MVP operations using Blender's direct data API and `bmesh`: six primitive
  variants, deletion, independent duplication, absolute/relative transforms, Principled material
  creation, copy-on-write material assignment, four light types, cameras, renaming, and collection
  movement.
- Added deterministic duplicate naming and exact requested-name enforcement so Blender cannot
  silently suffix a provider-requested object, material, light, or camera name.
- Added backward creation-result resolution for objects and materials during execution.
- Added a per-plan transaction journal with reverse-order rollback for runtime failures and deferred
  permanent deletion after all reversible operations succeed.
- Preserved non-target child world transforms during deletion and left existing orphaned datablocks
  untouched rather than purging unrelated data.
- Added immutable execution results and explicit change records for every changed object, material,
  collection, and active scene-camera setting.
- Connected `Apply Plan` to the retained approved plan, high-risk confirmation, operation progress,
  complete/failed/partial UI states, bounded secret-free session history, and Blender undo metadata.
- Registered approved execution as a Blender `REGISTER`/`UNDO` operator and added a pre-plan recovery
  point when global undo is available. Foreground Ctrl-Z remains a manual test because background
  Blender has no editor context.
- Added `EXECUTION.md` and updated the operation contract, architecture, scene-context, UX,
  development setup, and main project plan to reflect the implemented behavior and current limits.
- Added normal-Python execution-result tests and a dedicated Blender suite covering all operations,
  every primitive and light type, deterministic names, result references, copy-on-write materials,
  child-preserving deletion, delete-then-recreate ordering, preflight rejection, stale plans, and
  injected-failure rollback.
- Verified 68 pytest tests with 1 billable live test skipped, `pip check`, Ruff, Mypy across 49 source
  files, both Blender 5.1 background suites, source/archive validation, and clean-profile packaged
  imports plus UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the controlled execution layer. No live OpenAI
  request or API key was used.

## 2026-06-20 16:15:54 -04:00

### Cost-Efficient OpenAI Development Defaults Added

- Changed the default planning model from `gpt-5.5` to `gpt-5-nano`.
- Changed the default reasoning effort from medium to low and made reasoning effort configurable in
  Blender preferences with low, medium, and high options.
- Propagated the selected reasoning effort through UI planning, the OpenAI provider, and Responses
  API payload construction.
- Created a project-root `.env` file with an empty `OPENAI_API_KEY` placeholder and added `.env` to
  `.gitignore` so local credentials cannot be committed accidentally.
- Added dependency-free `.env` parsing with operating-system environment priority and Blender's
  masked session key as the final fallback.
- Kept the billable live test explicitly gated by the operating-system environment so placing a key
  in `.env` cannot accidentally enable live API usage.
- Documented that `.env` is plaintext, may be synchronized by OneDrive, is intended only for source
  development, and is excluded from the extension ZIP.
- Added configuration and provider tests for environment priority, local-file loading, quoted values,
  reasoning payloads, defaults, and invalid reasoning settings.
- Verified 73 pytest tests with 1 live test skipped, Ruff, Mypy across 50 source files, both Blender
  5.1 background suites, source/archive validation, archive secret exclusion, and clean-profile
  installed-package imports plus UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip`; no live OpenAI request was made.


## 2026-06-20 19:34:23 -04:00

### Live OpenAI Smoke Test Passed

- Reran only the opt-in live structured-plan smoke test after API quota became available.
- Confirmed `gpt-5-nano-2025-08-07` returned a completed, schema-constrained plan for one cube named
  `Live Smoke Cube` at the origin with identity rotation and unit scale.
- Confirmed the response passed the same mandatory local operation-plan validator used by Blender.
- Live test result: 1 passed in 3.75 seconds.
- No other tests were run and no source code changes were required.

## 2026-06-20 19:46:37 -04:00

### Phase 7 Safety Model Implemented

- Added a Blender-independent safety policy that recomputes authorization from the retained
  immutable plan rather than trusting provider claims or mutable UI presentation fields.
- Made every plan require visible preview and explicit application, while high-risk plans require a
  second confirmation with the explicit `Apply High-Risk Plan` command.
- Prevented direct `EXEC_DEFAULT` operator calls from bypassing high-risk confirmation and retained
  the approved plan when confirmation is missing.
- Blocked destructive execution unless Blender Global Undo is enabled and a pre-plan recovery point
  is successfully created before mutation.
- Improved blast-radius assessment to count unique existing objects plus every generated object,
  including bounded duplicates, without double-counting repeated edits to one target.
- Declared Python execution, file reads/writes, subprocesses, external asset downloads, and provider
  workarounds prohibited by the controlled contract and reinforced those limits in model instructions.
- Added provider-payload coverage proving API keys are excluded from model input.
- Added collapsible result details that identify every changed object, material, collection, and
  active-scene camera setting after successful or partial execution.
- Added `SAFETY.md` and updated the project plan, architecture, controlled-operation contract,
  execution notes, UX specification, and development verification documentation.
- Added safety tests for low/medium/high authorization, destructive recovery requirements,
  high-risk bypass prevention, prohibited capabilities, accurate affected-object counts, key
  isolation, retained scene state, and changed-data UI properties.
- Verified 79 pytest tests with 1 billable live test skipped, `pip check`, Ruff, Mypy across 53 source
  files, both Blender 5.1 background suites, source/archive validation, and clean-profile installed
  package imports plus UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with the Phase 7 safety model. No live OpenAI request
  was made during this phase.

## 2026-06-20 19:58:56 -04:00

### Phase 8 Model Provider Integration Completed

- Kept OpenAI as the single MVP provider behind Blender-independent request, response, usage, and
  provider protocol types so a future adapter cannot bypass local planning validation.
- Added immutable token accounting for input, cached input, output, reasoning output, and total
  tokens from completed Responses API calls.
- Aggregated usage across the one permitted semantic-repair call and across clarification rounds,
  with a provider-call count that exposes when more than one billed request was needed.
- Added an `AI Usage` summary to the Blender Assistant panel showing model and token details while
  treating missing provider usage as unavailable instead of blocking the plan.
- Preserved existing configurable request timeouts, output limits, context character/object budgets,
  transient HTTP retry budget, 30-second `Retry-After` cap, request-ID diagnostics, and fail-closed
  response validation.
- Added `PROVIDER_INTEGRATION.md` and updated the project plan, architecture, UX specification, and
  development setup with the implemented provider boundary and deferred streaming/local-model work.
- Added provider, coordinator, Blender, and opt-in live-test assertions for usage parsing, malformed
  metadata, retry-delay bounds, repair aggregation, and UI-state propagation.
- Verified 81 pytest tests with 1 billable live test skipped, `pip check`, Ruff, Mypy across 53 source
  files, both Blender 5.1 background suites, source/archive validation, archive secret exclusion,
  and clean-profile installed-package imports plus UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` with Phase 8. No live OpenAI request was made during
  this phase.

## 2026-06-20 22:55:32 -04:00

### Phases 9 and 10 Testing and Distribution Completed

- Added deterministic simple, messy, and 1,000-object Blender fixtures plus a reproducible Blender
  generator so sample scenes contain no production data or credentials.
- Added a sample-scene suite covering selection context, nested/shared scene data, path privacy,
  omission accounting, character limits, and large-scene collection performance.
- Measured the release baseline at 3 targets/1,431 characters for the simple fixture, 34 omissions/
  7,341 characters for the messy fixture, and 0.046 seconds/976 omissions/29,294 characters for the
  1,000-object fixture.
- Added explicit provider tests for timeout handling without ambiguous automatic retry and transient
  5xx exhaustion at the configured retry budget.
- Added `scripts/run_release_checks.ps1` to run dependencies, Python checks, all Blender suites,
  optional live testing, source/archive validation, independent package inspection, and isolated
  installed-extension verification through one command.
- Added `TEST_MATRIX.md` with operation coverage, fixture baselines, a foreground Undo checklist,
  and honest unrun rows for macOS, Linux, and Blender versions other than 5.1.0.
- Bundled six pinned pure-Python wheels for `requests`, `fastjsonschema`, and the HTTP dependency
  chain in the extension manifest; users no longer depend on packages present in one Blender install.
- Confirmed the MVP uses direct HTTPS and does not require a provider SDK, user-run `pip`, or a local
  bridge service.
- Added `README.md`, `INSTALLATION.md`, `PRIVACY.md`, and `TROUBLESHOOTING.md`, and updated the main
  plan, architecture, fixture notes, and development setup for release use.
- Verified 83 pytest tests with 1 billable live test skipped, `pip check`, Ruff, Mypy across 56 source
  files, all three Blender 5.1 background suites, source/archive validation, bundled-wheel and secret
  checks, and clean-profile installed-package imports plus UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` as a self-contained 536,869-byte package. No live
  OpenAI request was made during these phases.

## 2026-06-20 23:02:49 -04:00

### Ten-Scenario Live OpenAI Matrix Completed With One Failure

- Replaced the single live smoke case with exactly ten parameterized live scenarios and disabled
  automatic transient retries, enforcing a maximum of ten tests and ten API requests per run.
- Used a fixed synthetic scene snapshot and sent no production Blender data, file contents, or API
  key in model payloads; no Blender scene mutation was attempted.
- Confirmed `gpt-5-nano-2025-08-07` produced locally valid plans covering all ten controlled
  operation types across eight ready-plan scenarios.
- Confirmed local risk assessment classified duplication and rename/move plans as medium and the
  delete plan as high risk.
- Confirmed the prohibited Python, local-file-read, and external-download request returned
  `needs_clarification` with no operations.
- Found one planning-quality failure: `Make the selected object look better` returned a ready
  create-material/assign-material plan instead of requesting clarification about the desired look.
- Live result: 9 passed, 1 failed in 41.68 seconds. Nine reported responses consumed 20,317 tokens;
  the failed case's token count was not emitted before its assertion.
- Preserved the failing clarification expectation as a regression target and moved diagnostics ahead
  of assertions for future runs. No additional live requests were made after reaching the ten-test cap.

## 2026-06-20 23:59:47 -04:00

### Multi-Model Selection Added

- Added a Blender-native model dropdown to both the Assistant panel and extension preferences.
- Added GPT-5 Nano, GPT-5.4 Nano, GPT-5.4 Mini, and GPT-5.5 catalog choices based on the current
  Responses API model support list, plus a Custom option for exact account-specific model names.
- Kept GPT-5 Nano as the default so existing cost behavior and live-test baselines remain unchanged.
- Added strict model resolution that trims custom names and blocks empty, unknown, or corrupted
  selections before an API request is created.
- Disabled model changes while planning, executing, or retaining an approved plan, while allowing a
  model switch between requests and clarification rounds.
- Added provider tests for catalog, custom, blank, and unknown selections plus real Blender RNA
  registration coverage for every dropdown item.
- Bumped the extension from 0.1.0 to 0.1.1 and updated installation, troubleshooting, UX, provider,
  architecture-plan, and development documentation.
- Verified 87 pytest tests with 10 billable live tests skipped, `pip check`, Ruff, Mypy across 56
  source files, all three Blender 5.1 background suites, source/archive validation, bundled-wheel and
  secret checks, and clean-profile installed-package imports plus UI registration.
- Built `dist/blender_ai_assistant-0.1.1.zip` as a 537,527-byte self-contained package. No API key or
  live OpenAI request was used during this feature verification.

## 2026-06-21 19:22:20 -04:00

### Configurable Controlled-Operation Limits Added

- Added persistent Blender numeric controls for maximum operations per plan, existing targets per
  operation, and total objects created by one duplicate operation.
- Added a collapsible `Plan Limits` panel in the AI Assistant plus matching extension-preference
  controls, disabled while planning, executing, or retaining an approved plan.
- Preserved 20 operations, 100 targets, and 100 duplicate outputs as both defaults and non-overridable
  hard safety ceilings; users can select any lower positive value.
- Added immutable `OperationLimits` records and generated each provider JSON Schema from the values
  captured at planning start.
- Added an explicit provider-prompt limit summary, including the rule that duplicate output equals
  target count multiplied by duplicate count.
- Reused the same captured limits for initial response validation, the optional repair response, and
  local semantic validation before approval.
- Added tests for defaults, hard-ceiling rejection, dynamic schema values, reduced operation/target
  limits, duplicate-product enforcement, coordinator propagation and repair, and Blender RNA bounds.
- Bumped the extension from 0.1.1 to 0.1.2 and updated controlled-operation, safety, provider,
  architecture, UX, installation, troubleshooting, plan, and development documentation.
- Verified 97 pytest tests with 10 billable live tests skipped, `pip check`, Ruff, Mypy across 57
  source files, all three Blender 5.1 background suites, source/archive validation, bundled-wheel and
  secret checks, and clean-profile installed-package imports plus UI registration.
- Built `dist/blender_ai_assistant-0.1.2.zip` as a 539,175-byte self-contained package. No API key or
  live OpenAI request was used during this feature verification.

## 2026-06-21 19:30:47 -04:00

### Expanded Controlled-Operation Limits

- Kept the conservative defaults at 20 operations, 100 existing targets, and 100 duplicate outputs,
  while raising the selectable hard maxima to 100 operations, 500 targets, and 1,000 outputs.
- Separated default constants from hard contract maxima so existing installations retain their
  current behavior until a user deliberately increases a limit.
- Expanded scene-summary budgeting with the selected target limit so the model can receive IDs for
  the larger permitted target set, subject to the configured context character budget.
- Required Blender Global Undo and successful recovery-point creation for every high-risk plan,
  including non-destructive plans affecting more than 25 objects; second confirmation remains
  mandatory.
- Added regression coverage for values above the former ceilings and broad non-destructive recovery
  enforcement.
- Bumped the extension from 0.1.2 to 0.1.3 and updated controlled-operation, safety, UX,
  installation, troubleshooting, plan, and development documentation.
- Verified 99 pytest tests with 10 billable live tests skipped, `pip check`, Ruff, Mypy across 57
  source files, all three Blender 5.1 background suites, source/archive validation, bundled-wheel and
  secret checks, and clean-profile installed-package imports plus UI registration.
- Built `dist/blender_ai_assistant-0.1.3.zip` as a 539,252-byte self-contained package. No API key or
  live OpenAI request was used during this feature verification.

## 2026-06-21 22:23:21 -04:00

### GitHub Publication Prepared

- Added public-repository ignore rules for local `.env`, virtual environments, generated release
  archives, test caches, local agent metadata, operating-system metadata, and Blender backup files.
- Added the GPL-3.0-or-later license notice declared by the extension manifest and linked it from the
  README.
- Clarified that release ZIP archives under `dist/` are generated locally and are not tracked in
  source control.
- Prepared publication to `git@github.com:Peculiar-Ojediran/Blender_AI_assistant.git` using a clean
  `main` branch and repository-local author identity.
- Re-ran the complete non-billable release gate before publication: 99 tests passed, 10 live tests
  were skipped, and all Blender, package, secret, and clean-install checks passed.
