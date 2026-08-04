# Project Progress

Add new entries in chronological order, with the earliest entry at the top and the newest entry at the bottom.

## Progress Log Initialized

- Established `PROJECT_PROGRESS.md` as the project change log.
- Recorded the existing planning baseline completed before this log was created.
- Created `AI_BLENDER_EXTENSION_PLAN.md` with project scope, architecture options, build phases, risks, testing strategy, and prior-art research.
- Expanded the plan around controlled operations, structured AI-response validation, context budgets, Blender main-thread constraints, operator context, undo reliability, approval UX, early packaging validation, and product differentiation.
- No implementation code has been added; the project remains in the planning phase.

## Development Dependencies Installed and Verified

- Confirmed Blender 5.1.0 is installed with bundled Python 3.13.9.
- Created a workspace-local `.venv` from Blender's Python interpreter.
- Installed and pinned `requests`, `fastjsonschema`, `pytest`, `pytest-cov`, `ruff`, `mypy`, `types-requests`, and Blender API type stubs.
- Added runtime, development, and full lock requirement files.
- Added `pyproject.toml`, `.gitignore`, and `DEVELOPMENT_SETUP.md`.
- Added normal-Python and real-Blender dependency smoke tests.
- Verified `pip check`, 3 pytest tests, Ruff, Mypy, schema validation, and Blender 5.1 background execution.
- Chose a provider-neutral direct HTTPS approach for the initial runtime; no OpenAI or Anthropic SDK has been added.

## OpenAI Provider Foundation Added

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

## Project Package Skeleton Created

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

## Controlled Operation Contract Integrated

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

## MVP UX Design Completed

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

## Blender UX Implemented

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

## Scene Context System Implemented

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

## Pre-Planning Safety Gaps Resolved

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

## Current-Stage Integration Verified

- Audited imports and contracts across context, provider, controlled operations, risk, workflow state, UI, and packaging modules.
- Added a normal-Python integration test covering serialized scene context, mocked OpenAI Structured Outputs, snapshot binding, semantic plan validation, typed operations, and local risk assessment.
- Added a Blender import sweep that loads every extension module before registration.
- Added a snapshot-bound Blender plan test connecting live scene context, operation validation, and stale-safe target resolution.
- Added a reusable installed-extension test that imports every packaged module and verifies UI registration from the installed ZIP.
- Installed and enabled the built archive in an isolated Blender profile and verified startup in a fresh Blender process.
- Confirmed that incomplete workflow coordinator, asynchronous runtime, execution, undo, and history modules remain intentionally disconnected and cannot mutate scenes.
- Verified 52 pytest tests, Ruff, Mypy across 43 source files, Blender 5.1 source integration, source/archive validation, installed-package imports, and fresh-process UI registration.
- Rebuilt `dist/blender_ai_assistant-0.1.0.zip` after integration verification.

## AI Planning Layer Implemented

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

## AI Planning Layer Hardened

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

## Controlled Execution Layer Implemented

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

## Cost-Efficient OpenAI Development Defaults Added

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


## Live OpenAI Smoke Test Passed

- Reran only the opt-in live structured-plan smoke test after API quota became available.
- Confirmed `gpt-5-nano-2025-08-07` returned a completed, schema-constrained plan for one cube named
  `Live Smoke Cube` at the origin with identity rotation and unit scale.
- Confirmed the response passed the same mandatory local operation-plan validator used by Blender.
- Live test result: 1 passed in 3.75 seconds.
- No other tests were run and no source code changes were required.

## Phase 7 Safety Model Implemented

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

## Phase 8 Model Provider Integration Completed

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

## Phases 9 and 10 Testing and Distribution Completed

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

## Ten-Scenario Live OpenAI Matrix Completed With One Failure

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

## Multi-Model Selection Added

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

## Configurable Controlled-Operation Limits Added

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

## Expanded Controlled-Operation Limits

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

## GitHub Publication Prepared

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

## GitHub Publication Completed

- Created a clean Git history with initial release commit `9f916a7` authored by Peculiar Ojediran.
- Published the `main` branch to
  `git@github.com:Peculiar-Ojediran/Blender_AI_assistant.git` and configured local upstream tracking.
- Verified the remote branch resolves to the published commit and the working tree contains no
  uncommitted source changes.

## GitHub Release Published

- Installed and authorized GitHub CLI for release management using the existing GitHub account.
- Created annotated tag `v0.1.3` for verified commit `40eb074` and pushed the tag to GitHub.
- Published `Blender AI Assistant v0.1.3` as the latest stable GitHub Release and attached
  `blender_ai_assistant-0.1.3.zip` as the installable asset.
- Verified GitHub reports the uploaded asset as 539,249 bytes with SHA-256 digest
  `c2ed9fff04d6073fe6c0d7ed43a0a2c17eb7163dccee560aec27c13023d71121`.

## Complex-Plan Timeout Bug Fixed

- Investigated reports that prompts such as `make a rubiks cube` failed before receiving an OpenAI
  response from Blender.
- Confirmed the installed configuration used GPT-5.5, a 100-operation limit, 10,000 output tokens,
  and the previous 60-second request timeout. A controlled reproduction took 55.39 seconds, leaving
  insufficient margin once real Blender scene context was included.
- Raised the default request timeout from 60 to 180 seconds and the selectable maximum from 300 to
  600 seconds. The existing timeout property was unset, so upgrading adopts the new default without
  overwriting a deliberately customized value.
- Added distinct timeout, TLS, connection, and generic transport error categories with actionable UI
  messages. Timeout failures remain non-retried to avoid an ambiguous duplicate billable request.
- Added provider and Blender UI regression coverage for the new default, bounds, error categories,
  and timeout/connection headlines.
- Bumped the extension from 0.1.3 to 0.1.4 and updated installation, provider, troubleshooting,
  development, and release documentation.
- Verified 102 pytest tests with 10 standard live tests skipped, `pip check`, Ruff, Mypy across 57
  source files, all three Blender 5.1 background suites, source/archive validation, bundled-wheel and
  secret checks, and clean-profile installed-package imports plus UI registration.
- Verified the original prompt through Blender with GPT-5.5: a valid 44-operation high-risk plan was
  returned in 40.14 seconds using 5,745 tokens under the new 180-second timeout.
- Built `dist/blender_ai_assistant-0.1.4.zip` as a 539,666-byte self-contained package.

## Timeout Fix Released

- Pushed timeout-fix commit `62e281c` to `main` and created annotated tag `v0.1.4` at that verified
  commit.
- Published `Blender AI Assistant v0.1.4` as the latest stable GitHub Release with the installable
  `blender_ai_assistant-0.1.4.zip` asset.
- Verified the 539,666-byte GitHub asset matches the local SHA-256 digest
  `266a6a20b3cecaafab5af0b8efec10db12cd8418a40acea43a74ddd3641be21a`.

## Operation Contract Expanded

- Added controlled operations for material property updates, collection creation, light property
  updates, camera property updates, safe modifier creation, modifier property updates, text object
  creation, and object visibility changes.
- Preserved the existing safe-planning model by adding strict JSON schemas, local semantic
  validation, target/result-reference checks, preflight simulation, rollback-aware execution, risk
  metadata, and Blender execution coverage for the expanded operation set.
- Followed the requested staged workflow: implemented the first five operations, ran the full
  non-live release gate successfully, then implemented the remaining three operations.
- Verified the final result with 112 pytest tests passing, 10 live OpenAI tests skipped, Ruff, Mypy,
  Blender integration, controlled execution, sample scene checks, manifest/archive validation,
  package verification, isolated archive install, and installed extension integration checks.

## High-Risk Asset And Mesh Operations Added

- Added controlled high-risk operations for local asset import, local blend data link/append,
  non-applied Boolean modifiers, mesh joining, and mesh separation.
- Kept file access narrow: imports accept only local `.obj`, `.fbx`, `.gltf`, or `.glb` paths, blend
  data loading accepts only local `.blend` files with explicit object or collection names, and URL
  paths remain rejected.
- Preserved rollback behavior by keeping Boolean operations non-applied and implementing join and
  separate as generated replacement meshes with original-object deletion deferred until plan commit.
- Added contract tests and Blender execution coverage using a generated OBJ asset and temporary
  blend library file.
- Verified 120 pytest tests with 10 live OpenAI tests skipped, Ruff, Mypy, Blender integration,
  controlled execution, sample scene checks, manifest/archive validation, package verification,
  isolated archive install, and installed extension integration checks.

## HTTPS Asset Import Added

- Extended `IMPORT_ASSET` so asset sources can be either local paths or HTTPS URLs for `.obj`,
  `.fbx`, `.gltf`, and `.glb` files.
- Kept the URL import path controlled: HTTP, FTP, `file://`, and other URL schemes are rejected,
  downloads are capped at 50 MB, temporary download files are removed after import, and
  `LINK_OR_APPEND_BLEND_DATA` remains local `.blend` only.
- Updated provider instructions, controlled-operation documentation, and operation-contract tests
  for the HTTPS import behavior.

## URL Import Schema Compatibility Fixed

- Fixed OpenAI Structured Outputs rejecting URL import plans with `Invalid JSON schema: regex
  lookaround is not supported`.
- Removed lookaround-based URL/local-path regex checks from the provider-facing schema and kept the
  same URL policy in local semantic validation.
- Added regression coverage to ensure the provider schema does not include regex lookarounds.
- Verified 122 pytest tests with 10 live OpenAI tests skipped, Ruff, Mypy, Blender integration,
  controlled execution, sample scene checks, manifest/archive validation, package verification,
  isolated archive install, and installed extension integration checks.

## NVIDIA Provider Added

- Added a selectable NVIDIA NIM provider alongside OpenAI.
- Implemented direct HTTPS chat-completions support through `requests` using the hosted
  `https://integrate.api.nvidia.com/v1` base URL by default, `NVIDIA_API_KEY` resolution, guided JSON
  schema constraints, bounded retries, timeout handling, request-ID retention, and local plan
  validation.
- Added Blender UI preferences and sidebar controls for provider selection, NVIDIA model selection,
  custom NVIDIA model names, and configurable NVIDIA base URL.
- Updated setup, provider integration, privacy, architecture, troubleshooting, and test-matrix
  documentation for the two-provider workflow.
- Verified the full non-live release gate: 134 pytest tests passed with 10 live OpenAI tests skipped,
  Ruff, Mypy across 61 source files, Blender integration, controlled execution, sample scenes, source
  and archive manifest validation, package verification, isolated archive install, and installed
  extension integration checks.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip` as a 555,519-byte package.

## NVIDIA Live Smoke Test Passed

- Confirmed no OpenAI live test process was running after the interrupted OpenAI matrix command.
- Ran a NVIDIA-only live smoke request using `NVIDIA_API_KEY` and the NVIDIA-hosted
  `openai/gpt-oss-20b` model.
- The initial NVIDIA response proved the key and endpoint worked but showed schema-following drift,
  so the NVIDIA provider prompt now includes a plain field-name reminder in addition to guided JSON.
- Verified a valid NVIDIA plan for creating one cube: status `ready`, one `CREATE_PRIMITIVE`
  operation, low risk, 10.47 seconds, 621 input tokens, 322 output tokens, and 943 total tokens.
- Set `openai/gpt-oss-20b` as the default NVIDIA model because it is the first live-verified NVIDIA
  model for this extension.
- Reran the full non-live release gate after the NVIDIA prompt/default update: 134 pytest tests
  passed with 10 live OpenAI tests skipped, Ruff, Mypy, Blender integration, controlled execution,
  sample scenes, manifest/archive validation, package verification, isolated archive install, and
  installed extension checks all passed.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip` as a 555,861-byte package.

## NVIDIA Local-Validation Recovery Added

- Added a one-shot NVIDIA schema repair path for parseable provider answers that fail the exact
  controlled-operation JSON contract.
- The repair request includes the original prompt, scene context, invalid answer, validation error,
  and the same guided JSON schema; the repaired answer must still pass local validation or the
  request fails closed.
- Added mocked provider coverage for successful schema repair and rejection after one failed repair.
- Updated provider integration documentation to describe the extra NVIDIA repair call and token
  aggregation behavior.
- Verified the full non-live release gate: 135 pytest tests passed with 10 live OpenAI tests skipped,
  Ruff, Mypy across 61 source files, Blender integration, controlled execution, sample scenes, source
  and archive manifest validation, package verification, isolated archive install, and installed
  extension integration checks.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip` as a 556,429-byte package.

## Texture And Sculpting Planning Started

- Added `TEXTURE_AND_SCULPTING_PLAN.md` for the next major feature expansion.
- Split the feature into a near-term texture/shader track and a staged sculpt-like workflow track.
- Recommended material presets and procedural material templates before low-level shader node
  editing.
- Recommended non-destructive modifier-based sculpt-like operations before true sculpt mode or
  destructive mesh editing.
- Linked the new plan from `AI_BLENDER_EXTENSION_PLAN.md`.

## Deferred Texture And Sculpting Features Added

- Added a future implementation backlog to `TEXTURE_AND_SCULPTING_PLAN.md`.
- Captured intentionally deferred work for arbitrary shader graphs, Geometry Nodes, texture painting,
  UV editing, PBR material packs, AI-generated textures, texture baking, direct sculpt brush strokes,
  sculpt masks/face sets, dynamic topology, destructive voxel remeshing, shape keys, Multires, and
  preview rendering.
- Documented why each item is deferred and what prerequisites should exist before implementation.

## Future Texture And Sculpting Tests Added

- Added opt-in future pytest coverage for planned texture and sculpting contract behavior.
- Covered material presets, procedural materials, controlled shader nodes, HTTPS image textures,
  sculpt-like modifiers, high-risk remesh/sculpt operations, and sculpt stroke bounds.
- Added a future Blender background execution scaffold for material preset creation, shader node
  value setting, material assignment, and non-applied displacement modifier behavior.
- Updated `TEXTURE_AND_SCULPTING_PLAN.md` and `TEST_MATRIX.md` with the future test commands.
- Verified the default suite with future tests skipped: 135 pytest tests passed, 19 skipped, Ruff
  passed, Mypy passed across 63 source files, and the future Blender scaffold exits cleanly when its
  opt-in flag is not set.

## Texture And Sculpting Operations Implemented

- Added controlled-operation support for material presets, procedural materials, shader node
  creation/value/linking, image texture loading, displace/smooth/remesh modifiers, bounded region
  smoothing, and bounded sculpt-like brush strokes.
- Added local schema, semantic validation, result-reference handling, target resolution, risk
  scoring, provider instructions, preflight simulation, execution, rollback, and change reporting for
  the new operation set.
- Promoted texture/sculpting Python contract tests from opt-in future coverage to normal pytest
  coverage.
- Verified the updated codebase: 144 pytest tests passed with 10 live OpenAI tests skipped, Ruff
  passed, Mypy passed across 63 source files, Blender texture/sculpting execution passed, Blender
  controlled execution passed, Blender integration passed, and sample scene tests passed.
- Merged the standalone texture/sculpting plan into Phase 11A of `AI_BLENDER_EXTENSION_PLAN.md` and
  removed `TEXTURE_AND_SCULPTING_PLAN.md` to keep one source of truth.

## Texture And Sculpting Tests Added To General Execution Suite

- Merged texture/sculpting Blender execution coverage into `tests/run_execution_tests.py`.
- The general controlled-execution test now covers material presets, procedural materials, image
  texture loading, shader node creation/value/linking, non-applied displace/smooth/remesh
  modifiers, bounded region smoothing, and bounded sculpt-like brush strokes.
- Removed the opt-in environment guard from the targeted texture/sculpting Blender scaffold.
- Updated the test matrix and targeted test README to show that the general execution test is now
  the primary Blender coverage path for texture/sculpting behavior.
- Verified the integration: 144 pytest tests passed with 10 live OpenAI tests skipped, Ruff passed,
  Mypy passed across 63 source files, the general Blender controlled-execution test passed, and the
  targeted texture/sculpting Blender scaffold passed.



## Sculpt Region Schema Fixed For OpenAI

- Fixed `SCULPT_SMOOTH_REGION.region` so strict structured-output providers receive every region
  property as required, with unused `material_id` and `vertex_group` values set to null.
- Updated provider instructions, controlled-operation documentation, and the project plan to explain
  the explicit-null sculpt region payload shape.
- Added unit regression coverage for the nested region schema shape and updated the general Blender
  execution test fixture.
- Verified the fix: 64 operation-contract tests passed, Blender controlled execution passed, 136
  pytest tests passed with 10 live OpenAI tests skipped, Ruff passed, and Mypy passed across 61
  source files.
- Rebuilt and validated `dist/blender_ai_assistant-0.1.4.zip`; new archive size: 564,302 bytes.

## Sculpt Brush Miss Rollback Fixed

- Fixed `APPLY_SCULPT_BRUSH_STROKES` so strokes that miss all vertices inside their radius snap to
  the nearest vertex neighborhood instead of failing the operation and rolling back the entire plan.
- The brush executor now accepts stroke locations either as object-local coordinates or scene-space
  coordinates converted through the target object's world matrix.
- Updated the general Blender controlled-execution test to intentionally use an out-of-radius brush
  stroke and verify the plan still succeeds.
- Updated provider instructions and planning/operation documentation for the safer brush behavior.
- Verified the fix: Blender controlled execution passed, 136 pytest tests passed with 10 live OpenAI
  tests skipped, Ruff passed, and Mypy passed across 61 source files.
- Rebuilt and validated `dist/blender_ai_assistant-0.1.4.zip`; new archive size: 565,113 bytes.

## Deferred Future Implementation Planning Started

- Added `FUTURE_IMPLEMENTATION_PLAN.md` as the staged roadmap for deferred feature work.
- Split future work into context/registry foundations, advanced shader graph editing, UV/image
  workflows, PBR import, AI texture generation, texture painting, texture baking, Geometry Nodes,
  generated mesh variants, advanced sculpt regions, long-term topology workflows, and preview UX.
- Defined operation candidates, risk levels, prerequisites, design rules, test gates, and do-not-build
  criteria for each track.
- Linked the new roadmap from `AI_BLENDER_EXTENSION_PLAN.md` so deferred features have one planning
  entry point before they move into the controlled-operation contract.

## Deferred Future Foundation Implemented

- Added shared operation registries for material families, procedural patterns, shader node types,
  socket names, UV operation names, and future mesh-processing limits.
- Updated the scene context system to schema version 2 with compact material node summaries and
  richer mesh summaries for UV maps, vertex groups, shape keys, modifier stack state, material slots,
  and linked data flags.
- Updated serialization, unit tests, Blender context tests, scene-context documentation, and the
  deferred implementation roadmap to cover the new foundation data.
- Verified the implementation: 137 pytest tests passed with 10 live tests skipped, Ruff passed, Mypy
  passed across 62 source files, Blender dependency/context smoke test passed, sample scene tests
  passed, and Blender controlled execution tests passed.
- Rebuilt and validated `dist/blender_ai_assistant-0.1.4.zip`; new archive size: 566,586 bytes.

## Deferred Future Tracks B-F Implemented

- Implemented controlled UV and image texture operations: image texture node creation, texture
  mapping, UV map assignment, UV map creation, deterministic unwrap, and UV packing.
- Implemented explicit PBR texture-set import, PBR material creation, and PBR texture role
  correction with local role/color-space validation.
- Implemented deterministic local generated texture images, explicit generated-texture saves,
  generated texture attachment, paint image creation, paint slot assignment, UV-space paint strokes,
  region fills, bake target images, deterministic bake-pass writes, and baked texture assignment.
- Updated provider instructions, controlled-operation documentation, the future implementation
  roadmap, the main project plan, and the test matrix for the new operation families.
- Added contract tests and expanded the Blender controlled-execution test to cover Tracks B-F.
- Verified the implementation: 143 pytest tests passed with 10 live tests skipped, Ruff passed, Mypy
  passed across 62 source files, Blender dependency/context smoke test passed, sample scene tests
  passed, and Blender controlled execution tests passed.
- Rebuilt and validated `dist/blender_ai_assistant-0.1.4.zip`; new archive size: 577,400 bytes.
## ComfyUI Texture Provider Connected

- Added a local ComfyUI provider client for server health checks, checkpoint discovery, prompt queueing, history polling, and generated image download.
- Connected `GENERATE_TEXTURE_IMAGE` to use ComfyUI when `COMFYUI_ENABLED=true`; the existing deterministic generator remains the default fallback.
- Added ComfyUI provider tests and release-package verification coverage for the new provider file.
- Verified the local ComfyUI server responds at `http://127.0.0.1:8188`; generation is blocked until a checkpoint model is installed in ComfyUI.
- Verification: Pytest, Ruff, Mypy, Blender dependency smoke test, Blender controlled execution test, and live local ComfyUI connectivity check.

## Temporary ComfyUI Check Button Added

- Added a temporary `Check ComfyUI` button to the Blender assistant panel for local testing.
- The button verifies that the local ComfyUI server is reachable and reports whether at least one checkpoint is available.
- Verified the operator in Blender: ComfyUI reported ready with `v1-5-pruned-emaonly-fp16.safetensors`.
- This is a temporary testing feature intended to be removed before pushing the code to Git.

## Deferred Future Tracks G-K Implemented

- Implemented conservative controlled Geometry Nodes preset operations with bounded exposed-input metadata.
- Implemented generated mesh copy variants: generic generated copies, smoothed copies, displaced copies, remeshed copies, and generated-copy replacement by hiding the original.
- Implemented sculpt region creation from materials and vertex groups, vertex-group sculpt masks, and bounded sculpt region operations.
- Implemented safer Track J operations: non-applied Multires modifiers and controlled shape key creation.
- Implemented bounded local preview image datablocks for review UX.
- Added contract tests, a Blender future-track execution smoke test, release-check coverage, provider instructions, and documentation updates.
- Verification: 148 pytest tests passed with 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender dependency smoke test passed, controlled execution tests passed, future-track execution tests passed, and sample scene tests passed.

## Deferred Future Track A Implemented

- Implemented controlled shader graph editing operations for assistant-created node removal, explicit shader-link disconnect, bounded color ramp creation and updates, safe shader mix-chain templates, and material output validation/repair.
- Updated schema validation, semantic validation, risk catalog entries, executor rollback behavior, provider instructions, controlled-operation documentation, the future implementation roadmap, and the test matrix.
- Added Track A contract tests and a Blender shader graph execution smoke test.
- Verification: 150 pytest tests passed with 10 live tests skipped, Ruff passed, Mypy passed across 66 source files, Blender dependency smoke test passed, controlled execution tests passed, Track A shader execution tests passed, future-track execution tests passed, and sample scene tests passed.

## Controlled Residual Deferred Features Implemented

- Planned and implemented controlled alternatives for the remaining deferred items: shader graph templates, Geometry Nodes group templates, low-resolution render previews, mesh face-set attributes, dynamic-topology-style generated copies, explicit generated-mesh application, and rig-safe shape key updates.
- Added schema, semantic validation, risk catalog entries, preflight simulation, executor rollback behavior, provider instructions, and documentation updates for the new residual operation family.
- Added `tests/run_residual_features_tests.py` and included it in the release-check script.
- Fixed residual execution target resolution for render-preview camera IDs and created valid pass-through Geometry Nodes node groups.
- Verification: release checks passed with 152 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 67 source files, all Blender smoke tests passed, archive validation passed, isolated install passed, and `dist/blender_ai_assistant-0.1.4.zip` was rebuilt at 594,244 bytes.

## Provider Duplication Cleanup

- Addressed review findings around provider-layer duplication by moving shared HTTP retry, retry-delay, request-ID extraction, JSON mapping validation, API error formatting, token integer normalization, and schema-plan validation helpers into `extension/providers/_shared.py`.
- Refactored OpenAI and NVIDIA providers to use the shared helpers while preserving provider-specific payloads, response text extraction, token usage mapping, and NVIDIA's one-repair validation flow.
- Consolidated provider label/API-key metadata into the provider registry and removed the unused `PlanningCoordinator.is_running` wrapper plus one thin UI provider-label forwarding helper.
- Updated release-package verification to require the new shared provider helper.
- Verification: release checks passed with 152 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 68 source files, all Blender smoke tests passed, archive validation passed, isolated install passed, and `dist/blender_ai_assistant-0.1.4.zip` was rebuilt at 595,167 bytes.

## Future Plan And Smoke Test Consolidation

- Deleted `FUTURE_IMPLEMENTATION_PLAN.md` now that the future-track implementation planning has been merged back into the main project plan.
- Folded the shader Track A, future Tracks G-K, and residual deferred-feature Blender smoke scenarios into `tests/run_execution_tests.py`.
- Removed the standalone `tests/run_shader_track_tests.py`, `tests/run_future_tracks_tests.py`, and `tests/run_residual_features_tests.py` files.
- Simplified `scripts/run_release_checks.ps1` so the consolidated execution coverage runs once through `tests/run_execution_tests.py`.
- Updated the test matrix and main project plan to remove active references to the deleted planning/test files.
- Verification: release checks passed with 152 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, merged Blender execution tests passed, archive validation passed, isolated install passed, and `dist/blender_ai_assistant-0.1.4.zip` was rebuilt at 595,167 bytes.




## OpenAI Image Generation Integrated

- Removed the active ComfyUI provider path, temporary ComfyUI test button, ComfyUI provider test, and ComfyUI release-package requirement.
- Added an opt-in OpenAI image-generation provider for `GENERATE_TEXTURE_IMAGE` using `POST /v1/images/generations`, `OPENAI_API_KEY`, `gpt-image-2` by default, PNG output, and base64 image decoding.
- Kept deterministic local texture generation as the default path unless `OPENAI_IMAGE_GENERATION_ENABLED=true` is set.
- Updated provider documentation, development setup, controlled-operation docs, planner instructions, tests, and release-package verification for the OpenAI Images path.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,170 bytes.
- Verification: full release checks passed with 155 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## General Generated Image Operations Added

- Added `GENERATE_IMAGE_ASSET` for standalone generated image datablocks using the existing optional OpenAI Images provider or deterministic local fallback.
- Added `APPLY_IMAGE_TO_MATERIAL` for applying any image result to a controlled material texture node with projection, extension, and optional UV map controls.
- Updated schema validation, result-reference typing, preflight simulation, executor routing, risk catalog entries, provider instructions, controlled-operation docs, the main plan, and the test matrix.
- Extended contract tests and Blender controlled execution coverage to generate a standalone image asset and apply it to a material.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,571 bytes.
- Verification: full release checks passed with 155 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## OpenAI Image Generation Default Enabled

- Changed `OPENAI_IMAGE_GENERATION_ENABLED` so generated image operations use OpenAI Images by default when no explicit setting is present.
- Kept the explicit local fallback switch: setting `OPENAI_IMAGE_GENERATION_ENABLED=false` disables billable image calls and uses deterministic local pattern generation.
- Updated the OpenAI image provider test, development setup docs, provider integration docs, controlled-operation docs, provider instructions, and main plan wording for the new default.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,568 bytes.
- Verification: full release checks passed with 155 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## OpenAI Image Session Key Fallback

- Updated generated image execution so OpenAI Images resolves `OPENAI_API_KEY` first, then falls back to Blender's masked session key when OpenAI is the selected provider.
- Added an explicit OpenAI image provider API-key override and focused tests for session-key fallback behavior.
- Updated provider integration, development setup, installation, controlled-operation, and main-plan docs to describe the shared key lookup.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,816 bytes.
- Verification: full release checks passed with 158 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## Large Plan Capacity Increased

- Raised default and hard controlled-operation limits to 1,000 operations per plan, 1,000 targets per operation, and 10,000 duplicate outputs.
- Raised OpenAI and NVIDIA planning output-token defaults to 65,536 tokens and the Blender preference ceiling to 131,072 tokens.
- Updated the UI fallback path, operation contract docs, safety docs, UX docs, troubleshooting docs, provider docs, and operation-contract tests for the new capacity limits.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,841 bytes.
- Verification: full release checks passed with 158 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## Output Token Default Reduced

- Reduced the default OpenAI and NVIDIA planning output-token request from 65,536 to 32,768 tokens to avoid provider-side HTTP 500 failures on ordinary prompts.
- Kept the Blender preference ceiling at 131,072 tokens for intentional large-plan testing.
- Added troubleshooting guidance for OpenAI HTTP 500 responses after oversized structured planning requests.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 594,841 bytes.
- Verification: full release checks passed with 158 pytest tests passed and 10 live tests skipped, Ruff passed, Mypy passed across 65 source files, Blender integration tests passed, controlled execution tests passed, sample scene tests passed, archive validation passed, archive content verification passed, isolated archive install passed, and installed extension integration passed.

## Sculpting Expansion Planning Started

- Added `SCULPTING_FEATURE_PLAN.md` to plan expanded sculpt brush types, symmetry, mask operations, face-set tools, voxel/remesh generated-copy workflows, advanced multires workflows, and sculpt variant preview/review.
- Linked the focused sculpting plan from the deferred implementation section of `AI_BLENDER_EXTENSION_PLAN.md`.
- Kept this as documentation-only planning; no operation code, schemas, executor behavior, tests, or release package were changed.

## Sculpting Expansion Test Scaffolding Added

- Added expected-failure TDD contract tests for sculpting Tracks A-G in `tests/unit/test_sculpting_future_contract.py`.
- Covered planned payloads for expanded brushes, symmetric strokes, mask operations, face-set tools, voxel/remesh generated-copy workflows, multires workflows, sculpt variant review, and future provider instructions.
- Documented the test scaffolding in `SCULPTING_FEATURE_PLAN.md` and added it to `TEST_MATRIX.md`.
- Kept the tests marked `xfail(strict=True)` so the current suite remains green until the main operation code is implemented.
- Verification: focused sculpting future tests reported 34 expected failures; full Python test suite passed with 158 passed, 10 skipped, and 34 expected failures. Ruff and Mypy passed for the new test file.

## Sculpt Mask Operations Implemented

- Implemented Track C sculpt mask operations: `INVERT_SCULPT_MASK`, `CLEAR_SCULPT_MASK`, `BLUR_SCULPT_MASK`, `SHARPEN_SCULPT_MASK`, `GROW_SCULPT_MASK`, `SHRINK_SCULPT_MASK`, and `COMBINE_SCULPT_MASKS`.
- Added schema, catalog, result-kind validation, semantic combine-mask validation, preflight simulation, executor routing, vertex-group weight editing, and rollback helpers.
- Promoted Track C tests from expected-failure to active validation while leaving the remaining future sculpting tracks expected-failure.
- Extended the controlled Blender execution test to mutate, combine, and clear sculpt masks on a temporary scene.
- Updated provider instructions, the controlled-operation contract, test matrix, main extension plan, and sculpting plan for the implemented mask operations.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 597,272 bytes.
- Verification: full release gate passed dependency check, Python tests with 166 passed, 10 skipped, and 27 expected failures, Ruff, Mypy across 66 source files, Blender integration tests, controlled execution tests, sample scene tests, source validation, extension build, archive validation, and archive content verification. The scripted isolated install step failed with a Windows `WinError 5` rename inside the OneDrive-hosted temporary profile, then the same archive passed manual isolated install and installed-extension integration from a temp profile outside OneDrive.

## Sculpting Plan Merged and Shading Planning Started

- Merged the focused sculpting expansion roadmap into `AI_BLENDER_EXTENSION_PLAN.md` as Phase 11B.
- Removed the standalone `SCULPTING_FEATURE_PLAN.md` file so the main extension plan is the active roadmap source.
- Added Phase 11C to `AI_BLENDER_EXTENSION_PLAN.md` for advanced shading feature planning, covering shader compatibility registries, layered materials, procedural pattern expansion, reference-based material matching, specialized material families, cleanup/repair, and material variant review.
- Updated `TEST_MATRIX.md` so the planned sculpting expansion row points to the main plan for roadmap context.
- Kept this as documentation-only planning; no operation code, schemas, executor behavior, tests, or release package were changed.

## Advanced Shading Test Scaffolding Added

- Added expected-failure TDD contract tests for shading Tracks A-G in `tests/unit/test_shading_future_contract.py`.
- Covered planned payloads for shader compatibility registry metadata, layered material workflows, procedural pattern expansion, reference-based material matching, specialized material families, shader cleanup/repair, material variants, and future provider instructions.
- Updated `TEST_MATRIX.md` to list the planned advanced shading expansion test scaffold.
- Kept the tests marked `xfail(strict=True)` so the current suite remains green until the main shading operation code is implemented.
- Verification: focused advanced shading future tests reported 42 expected failures; Ruff passed for the new test file; full Python test suite passed with 166 passed, 10 skipped, and 69 expected failures.

## Advanced Shading Registry Implemented

- Implemented the Phase 11C Track A shader compatibility foundation in `extension/operations/registries.py`.
- Added shader socket families, socket-family compatibility rules, and node metadata for the existing allowlisted shader nodes plus built-in Principled BSDF and Material Output references.
- Added local semantic validation for `CONNECT_SHADER_NODES` and `DISCONNECT_SHADER_LINK` so incompatible socket-family pairings reject before execution.
- Added `BSDF` and `Emission` shader sockets to the controlled socket allowlist for valid shader-to-surface graph connections.
- Promoted the Track A shading future test from expected-failure to active validation while leaving the remaining shading tracks expected-failure.
- Updated `AI_BLENDER_EXTENSION_PLAN.md` and `TEST_MATRIX.md` for the implemented registry and compatibility validation coverage.
- Rebuilt `dist/blender_ai_assistant-0.1.4.zip`; archive verification passed at 598,063 bytes.
- Verification: focused shading and operation-contract tests passed with 82 passed and 41 expected failures; Ruff passed for touched files; Mypy passed across 67 source files; full Python test suite passed with 170 passed, 10 skipped, and 68 expected failures; Blender controlled execution tests passed; source validation, archive validation, and archive content verification passed.

## Advanced Shading Tracks B-G Implemented

- Implemented layered shader materials, shader layers, layer masks, layer reordering, and layer removal.
- Implemented procedural shading node-set templates for expanded patterns, edge wear, triplanar-style mapping, object-space gradients, and curvature-style masks.
- Implemented reference-image material palette metadata, reference material creation, material matching, and lookdev preview images.
- Implemented specialized material families for glass, translucent, emission, volume, toon, and anisotropic looks.
- Implemented assistant-owned shader cleanup, duplicate material consolidation, node layout normalization, shader compatibility validation, and broken-link repair.
- Implemented material variant creation, tagging, comparison preview, explicit acceptance, and rejection metadata.
- Updated operation enums, catalog entries, JSON schemas, semantic validation, result-reference handling, target resolution, provider instructions, executor routing, rollback helpers, `AI_BLENDER_EXTENSION_PLAN.md`, `CONTROLLED_OPERATIONS.md`, and `TEST_MATRIX.md`.
- Promoted `tests/unit/test_shading_future_contract.py` Tracks B-G from expected-failure placeholders to active validation.
- Added an advanced shading scenario to `tests/run_execution_tests.py`; the current shell could not execute it because no Blender executable was available through `BLENDER_EXE`, `PATH`, or common install paths.
- Verification: focused shading and operation-contract tests passed with 124 passed; Ruff passed for touched source and tests; Mypy passed across 45 source files; full Python test suite passed with 212 passed, 10 skipped, and 27 expected failures.

## Advanced UV Editing Planning Started

- Added Phase 11D to `AI_BLENDER_EXTENSION_PLAN.md` for advanced UV editing.
- Planned UV tracks for diagnostics, seam/island definition, unwrap/projection expansion, island transforms, texel density/advanced packing/UDIM layout, cleanup/repair, texture-aware UV workflows, and UV variants/review.
- Captured UV-specific safety rules, provider instruction updates, future scene context additions, implementation order, and acceptance criteria.
- Kept this as documentation-only planning; no operation code, schemas, executor behavior, tests, or release package were changed.

## Advanced UV Editing Test Scaffolding Added

- Added strict expected-failure TDD contract tests for UV Tracks A-H in `tests/unit/test_uv_future_contract.py`.
- Covered planned payloads for UV diagnostics, seam/island definition, projection unwraps, island transforms, texel density and UDIM workflows, cleanup/repair, texture-aware UV workflows, UV variants, and future provider instructions.
- Updated `AI_BLENDER_EXTENSION_PLAN.md` and `TEST_MATRIX.md` to reference the new UV test scaffold.
- Kept the tests marked `xfail(strict=True)` so the current suite remains green until the main UV operation code is implemented.
- Verification: focused advanced UV future tests reported 43 expected failures; Ruff passed for the new test file; full Python test suite passed with 212 passed, 10 skipped, and 70 expected failures.

## Advanced UV Editing Tracks A-H Implemented

- Implemented UV diagnostics, reports, overlap/stretch previews, seam marking, seam clearing, island creation, projection unwraps, island transforms, pinning, texel-density adjustment, advanced packing, UDIM layout, UV cleanup/repair, texture-atlas metadata, UV guide images, grid test material creation, UV variants, and UV comparison/accept/reject workflows.
- Added operation enum values, catalog entries, registry constants, strict JSON schemas, result-kind validation, semantic UV bounds/merge checks, target resolution for nested atlas materials, provider instructions, preflight simulation, executor routing, and rollback helpers.
- Promoted `tests/unit/test_uv_future_contract.py` from strict expected-failure scaffolding to active validation.
- Added advanced UV Tracks A-H coverage to the general Blender execution test in `tests/run_execution_tests.py`.
- Updated `AI_BLENDER_EXTENSION_PLAN.md`, `CONTROLLED_OPERATIONS.md`, and `TEST_MATRIX.md` for the implemented UV operation set.
- Verification: focused UV contract tests passed with 43 passed; operation-contract plus UV tests passed with 124 passed; full Python test suite passed with 255 passed, 10 skipped, and 27 expected failures; Ruff and Mypy passed; Blender controlled execution tests passed on Blender 5.1.0.

## Release ZIP Rebuilt

- Rebuilt `dist/blender_ai_assistant-0.1.4.zip` from the current extension source after the advanced UV implementation.
- Verification: Blender archive validation passed; independent archive content verification passed at 627,873 bytes.

## Version 1.5.0 Release Prepared

- Updated the Blender extension manifest, installation docs, troubleshooting docs, development release commands, release-check script, and archive verifier for version 1.5.0.
- Rebuilt `dist/blender_ai_assistant-1.5.0.zip` from the current extension source.
- Verification: full Python test suite passed with 255 passed, 10 skipped, and 27 expected failures; Ruff passed; Mypy passed across 45 source files; Blender controlled execution tests passed; Blender archive validation passed; independent archive verification passed at 627,869 bytes.

## Controlled Internet Access Planning Started

- Added `INTERNET_ACCESS_PLAN.md` for opt-in web asset discovery, URL inspection, candidate review, import handoff, licensing metadata, and testing strategy.
- Updated `AI_BLENDER_EXTENSION_PLAN.md` to link internet access to the existing controlled-operation workflow instead of adding unrestricted browsing or arbitrary downloads.
- Kept this as documentation-only planning; no operation code, provider code, UI code, tests, or release package were changed.

## Controlled Internet Access Test Scaffolding Added

- Added strict expected-failure TDD contract tests for internet asset discovery Tracks A-G in `tests/unit/test_internet_access_future_contract.py`.
- Covered planned behavior for opt-in settings, discovery intent routing, safe URL policy, direct HTTPS URL inspection, candidate license/attribution metadata, OpenAI web-search discovery payloads, candidate review, import handoff, and non-live test coverage.
- Updated `INTERNET_ACCESS_PLAN.md` and `TEST_MATRIX.md` to reference the new test scaffold.
- Kept the tests marked `xfail(strict=True)` so the current suite remains green until the internet access implementation is added.
- Verification: focused internet access future tests reported 16 expected failures; Ruff passed for the new test file; full Python test suite passed with 255 passed, 10 skipped, and 43 expected failures.

## Controlled Internet Access Backend Implemented

- Implemented `extension.internet` backend modules for opt-in settings, discovery intent classification, URL policy, URL inspection, provider-neutral search, OpenAI web-search discovery, candidate review, verified-candidate import handoff, and non-live test-surface declarations.
- Added a Blender add-on preference gate for internet asset discovery while leaving full candidate-list UI controls as the next implementation step.
- Updated regular `IMPORT_ASSET` validation and executor preflight to reject localhost, loopback, private-network, non-HTTPS, and unsupported-extension URLs through the shared internet policy.
- Added nullable `asset_metadata` to `IMPORT_ASSET` and executor support for writing discovered asset source, license, attribution, size, confidence, and warning data onto imported objects as `ai_asset_*` custom properties.
- Promoted `tests/unit/test_internet_access_future_contract.py` from strict expected-failure scaffolding to active validation.
- Updated `INTERNET_ACCESS_PLAN.md`, `CONTROLLED_OPERATIONS.md`, `SAFETY.md`, `PROVIDER_INTEGRATION.md`, and `TEST_MATRIX.md` for the implemented backend and remaining UI/live-test gaps.
- Verification: internet access plus operation-contract tests passed with 97 passed; full Python test suite passed with 271 passed, 10 skipped, and 27 expected failures; Ruff passed; Mypy passed across 55 source files; Blender controlled execution tests passed; Blender dependency smoke test passed with a post-test unregister warning from the installed user extension.

## Candidate Search And Review Screen Planning Added

- Added `CANDIDATE_SEARCH_REVIEW_SCREEN_PLAN.md` for the Blender asset-search panel placement, user flow, layout, UI state model, operators, async runtime, import handoff, error states, safety requirements, test plan, implementation order, deferred UX, and acceptance criteria.
- Updated `INTERNET_ACCESS_PLAN.md` and `UX_DESIGN.md` to reference the dedicated candidate-search screen plan.
- Kept this as documentation-only planning; no UI code, operators, runtime code, tests, or release package were changed.

## Candidate Search And Review Screen Test Scaffolding Added

- Added strict expected-failure TDD contract tests for the planned candidate search/review screen in `tests/unit/test_candidate_search_review_screen_future_contract.py`.
- Covered planned screen state, clearing behavior, candidate row fields, preference/provider panel gating, request view-model creation, operator IDs, child-panel registration, stale async result handling, search error preservation, inspection updates, listing-only import blocking, verified import-plan handoff, and future screen test-surface registry.
- Updated `CANDIDATE_SEARCH_REVIEW_SCREEN_PLAN.md` and `TEST_MATRIX.md` to reference the new UI test scaffold.
- Kept the tests marked `xfail(strict=True)` so the current suite remains green until the candidate search/review screen is implemented.
- Verification: focused candidate search/review screen tests reported 13 expected failures; Ruff passed for the new test file; full Python test suite passed with 271 passed, 10 skipped, and 40 expected failures.

## Candidate Search And Review Screen Implemented

- Implemented Blender-independent asset search screen state helpers, candidate row conversion, discovery result reducers, inspection result reducers, selection/rejection helpers, search request building, and verified-candidate import-plan creation.
- Added a dedicated asset-search background runtime for OpenAI discovery and URL inspection, including stale-generation filtering and Blender timer polling.
- Added session-only Blender candidate properties, an `Asset Search` child panel, and operators for search, cancel, clear, expand, select, inspect URL, open source, create import plan, and reject candidate.
- Wired verified candidates into the existing validated planning result path so imports still use the normal Plan panel and high-risk approval flow.
- Promoted the candidate search/review screen tests from strict expected failures to active tests and added Blender smoke assertions for the new panel, operators, and session defaults.
- Updated `AI_BLENDER_EXTENSION_PLAN.md`, `INTERNET_ACCESS_PLAN.md`, `CANDIDATE_SEARCH_REVIEW_SCREEN_PLAN.md`, `UX_DESIGN.md`, and `TEST_MATRIX.md` for the implemented screen.
- Verification: full Python test suite passed with 284 passed, 10 skipped, and 27 expected failures; Ruff passed; Mypy passed across 58 source files; Blender dependency smoke test passed; Blender controlled execution tests passed.
- Updated the Blender manifest network permission description and rebuilt `dist/blender_ai_assistant-1.5.0.zip`.
- Release verification: Blender source validation passed; Blender ZIP validation passed; independent archive verification passed at 650,937 bytes.

## Advanced Sculpting Tracks Implemented

- Promoted the planned sculpting Tracks A-G tests from strict expected failures to active tests.
- Added controlled operations for advanced sculpt brushes, mirrored brush replay, face-set creation/editing, voxel/quad/dyntopo generated-copy workflows, Multires level/preview workflows, and sculpt variant review.
- Updated operation schemas, catalog risk metadata, semantic validation, result-reference kind checks, target resolution, risk accounting, provider instructions, and Blender execution handlers for the new operations.
- Added Blender controlled execution coverage for the advanced sculpting workflow.
- Updated `AI_BLENDER_EXTENSION_PLAN.md`, `CONTROLLED_OPERATIONS.md`, and `TEST_MATRIX.md` for the implemented sculpting surface.
- Verification: focused sculpting contract tests passed with 34 passed; operation contract tests passed with 81 passed; full Python suite passed with 311 passed and 10 skipped; Ruff passed; Mypy passed across 83 source and test files; Blender dependency smoke test passed; Blender controlled execution tests passed.
- Rebuilt and validated `dist/blender_ai_assistant-1.5.0.zip`; independent archive verification passed at 660,131 bytes.

## Pending Commit Change Audit

- Reviewed the current uncommitted source and test changes after the documentation revert.
- Pending internet-access work includes the new `extension.internet` package for opt-in asset discovery, URL policy, URL inspection, OpenAI web-search discovery, candidate review, verified import-operation handoff, and non-live test-surface tracking.
- Pending candidate-search UI work includes session-only candidate state, asset-search screen helpers, a background search/inspection runtime, panel registration, search/cancel/clear/select/inspect/open-source/import-plan/reject operators, and a normal Plan-panel handoff for verified `IMPORT_ASSET` candidates.
- Pending import safety work includes shared policy validation for URL asset imports and `IMPORT_ASSET.asset_metadata` support so imported objects can keep source, license, attribution, size, confidence, and warning metadata.
- Pending advanced sculpting work includes controlled operations for advanced and symmetric brush strokes, face-set creation/editing, voxel remesh copies, quad-remesh prep copies, dynamic-topology detail copies, Multires level/preview workflows, sculpt variant review, and accept/reject flows.
- Pending operation contract work updates enums, schemas, catalog risk entries, registries, semantic validation, result-reference kind checks, target resolution, risk accounting, provider instructions, executor simulation, and Blender execution handlers.
- Pending tests include active internet access contracts, active candidate search/review contracts, Blender UI smoke coverage for the asset-search panel/defaults, expanded operation contract assertions, and a Blender execution scenario for the advanced sculpting workflow.
- `INTERNET_ACCESS_PLAN.md` and `CANDIDATE_SEARCH_REVIEW_SCREEN_PLAN.md` remain untracked documentation files that describe the new internet and candidate-review workflows.
- Verification: audit/documentation update only in this pass; no tests were rerun.

## Internet And Candidate Plans Merged

- Merged `INTERNET_ACCESS_PLAN.md` and `CANDIDATE_SEARCH_REVIEW_SCREEN_PLAN.md` into `AI_BLENDER_EXTENSION_PLAN.md`.
- Preserved the internet discovery goal, policy rules, provider options, architecture, user flow, implementation tracks, risks, deferred work, and acceptance criteria.
- Preserved the candidate search/review goal, screen placement, UI state model, operators, async runtime, import-plan handoff, error states, safety requirements, testing plan, implementation order, deferred UX, and acceptance criteria.
- Added OpenAI web-search and tools references to the main plan research source list.
- Removed the standalone internet and candidate-review plan files so the main Blender extension plan is the single planning document for those features.
- Verification: documentation-only merge; no source tests were rerun.
