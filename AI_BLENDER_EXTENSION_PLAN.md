# AI Blender Extension Project Plan

Last researched: June 18, 2026

## Project Goal

Build a Blender extension that lets a user describe changes in natural language and have an AI model make controlled changes directly to the open Blender file.

The core product is not just "AI writes Blender Python." The safer and more useful version is an assistant that can inspect the current scene, propose a plan, ask for approval when needed, execute changes through controlled Blender operations, and keep enough history that the user can understand and undo what happened.

## Initial Development Baseline

- Initial Blender target: Blender 5.1.x.
- Initial platform: Windows.
- Python compatibility target: Python 3.13, matching Blender 5.1.
- Runtime dependencies: `requests` 2.32.3 and `fastjsonschema` 2.21.1.
- Initial provider: OpenAI Responses API.
- Initial development model: GPT-5 Nano with low reasoning effort.
- Provider integration: direct HTTPS through `requests`; no provider SDK is required.
- Output contract: OpenAI Structured Outputs plus mandatory local schema validation.
- Development environment: workspace-local `.venv` created from Blender's bundled Python.

## Has This Been Done Before?

Yes. Similar projects already exist, so this project should assume there is prior art and focus on safety, workflow quality, and a clear differentiator.

Notable examples found:

- BlenderGPT: a GitHub add-on that integrates OpenAI GPT-4/GPT-3.5 into Blender's UI. The user enters English commands, the model generates Blender Python, and the add-on executes it. It has thousands of GitHub stars and is an important reference for the simplest direct approach.
- BlenderMCP: a popular open-source MCP-based project connecting Blender to Claude through a Blender add-on plus an external MCP server. It supports scene inspection, object creation/modification/deletion, material control, screenshots, assets, and arbitrary Python execution.
- Official Claude/Blender connector: Anthropic announced in 2026 that Blender developers created an MCP connector for Claude. The announcement describes a natural-language interface to Blender's Python API, scene analysis/debugging, batch changes, and adding tools directly to Blender's interface.
- Commercial/community tools: Blender Copilot, 3D-Agent, Blender AI Assistant, and similar tools market natural-language scene editing, text-to-3D, material generation, and workflow automation.

Conclusion: the idea is validated, but a basic version that only sends prompts to a model and runs generated Python will not be enough to stand out. The best opportunity is a safer, more predictable, model-agnostic assistant with good approval flows and strong Blender-native UX.

Deliberate product bet: this extension should be an approval-first Blender assistant built around controlled operations. The main differentiator should be trust: users can see what will happen, approve risky changes, undo changes, and inspect exactly what the AI changed. Model flexibility and MCP compatibility can matter later, but safety and predictability should be the first public-facing identity.

## Recommended Product Direction

Start with a focused assistant for scene editing and automation, not a fully general "do anything" agent.

Good MVP scope:

- Create, delete, move, rotate, scale, duplicate, rename, group, and organize objects.
- Apply and edit basic materials.
- Add common lights and cameras.
- Add simple modifiers.
- Summarize the scene and selected objects.
- Perform batch operations on selected objects.
- Explain what it is about to do before making destructive changes.
- Record every AI action in a visible history panel.
- Use Blender's undo system wherever possible.

Avoid in the first version:

- Fully arbitrary generated scripts without review.
- Complex geometry nodes generation.
- Rigging and animation automation beyond simple transforms/keyframes.
- Third-party asset downloads.
- Multi-model orchestration.
- Rendering farm or cloud asset processing.

## High-Level Architecture

There are three realistic architecture options.

### Option 1: Direct Blender Add-on Calls AI API

The Blender extension contains the UI, gathers scene context, sends requests directly to an AI API, receives instructions, and applies changes.

Pros:

- Simplest install story.
- Fewer moving pieces.
- Easier MVP.

Cons:

- Harder dependency management inside Blender's Python environment.
- API key storage happens inside Blender.
- Network calls can freeze the UI if not handled carefully.
- Harder to support multiple AI providers cleanly.
- Harder to add external tools later.

Best use: early prototype.

### Option 2: Blender Add-on Plus Local Bridge Service

The Blender extension handles UI and scene execution. A local companion process handles AI requests, model-provider SDKs, auth, streaming, logs, and optional MCP support.

Pros:

- Cleaner separation between Blender operations and AI/provider logic.
- Easier dependency management.
- Easier to support OpenAI, Claude, local models, or future providers.
- Better security boundary.
- Better long-term architecture.

Cons:

- More complex install and troubleshooting.
- Requires process startup/connection handling.
- Users may struggle with firewall, port, Python, or PATH issues.

Best use: serious product after MVP.

### Option 3: MCP-First Architecture

The extension exposes Blender as tools through MCP, and an AI client calls those tools.

Pros:

- Aligns with current direction of AI tool integrations.
- Model-agnostic in principle.
- Lets external AI clients interact with Blender using a known protocol.
- Easier to compare with BlenderMCP and official connector patterns.

Cons:

- More moving pieces.
- Less control over the full user experience if the main chat UI lives outside Blender.
- Still needs safety design; MCP does not solve trust by itself.

Best use: interoperability-focused version or advanced mode.

Recommended path: start with Option 1 for a prototype, but design the boundaries so the project can move toward Option 2 with optional MCP compatibility. Do not build the first version around arbitrary Python execution as the main workflow.

Important architecture constraint: almost all Blender scene edits must happen on Blender's main thread. Network calls, model calls, and long-running planning work should not directly call the `bpy` API from background threads. The extension should treat AI communication and Blender scene execution as separate systems, even in the first prototype.

## Controlled Operation Contract

The controlled operation list is the heart of the project. It must exist before serious model integration, because validation, safety, testing, approval UX, and undo behavior all depend on it.

The model should not be asked to produce arbitrary Blender Python by default. It should produce a structured plan containing only approved operation types. Each operation needs:

- Operation name.
- Required fields.
- Optional fields.
- Type constraints.
- Numeric bounds.
- Target rules.
- Risk level.
- Confirmation requirement.
- Undo expectation.
- Failure behavior.

Recommended MVP operation catalog:

| Operation | Purpose | Important Fields | Risk |
| --- | --- | --- | --- |
| `CREATE_PRIMITIVE` | Add a mesh primitive such as cube, sphere, plane, cylinder, or cone. | primitive type, name, location, rotation, scale, collection | Low |
| `DELETE_OBJECTS` | Delete specific objects. | target object ids, reason | High |
| `DUPLICATE_OBJECTS` | Duplicate selected or named objects. | target object ids, count, offset, naming rule | Medium |
| `SET_TRANSFORM` | Move, rotate, or scale objects. | target object ids, location, rotation, scale, absolute/relative mode | Low/Medium |
| `ASSIGN_MATERIAL` | Assign an existing or new material to objects. | target object ids, material id/spec | Low |
| `CREATE_MATERIAL` | Create a simple material. | name, base color, roughness, metallic, alpha | Low |
| `ADD_LIGHT` | Add a light to the scene. | type, name, location, power, color | Low |
| `ADD_CAMERA` | Add or position a camera. | name, collection ID, location, rotation, focal length, active flag | Low |
| `RENAME_OBJECTS` | Rename objects. | explicit target ID and new-name pairs | Medium |
| `MOVE_TO_COLLECTION` | Move objects into an existing collection. | target object IDs, collection ID | Medium |

The first version should avoid modifiers, operations that require edit mode, geometry nodes, rigging, destructive mesh edits, file access, or arbitrary script execution. Those can be added only after the basic operation contract proves reliable.

The integrated contract uses two response states: `ready` and `needs_clarification`. Risk and confirmation are derived locally rather than accepted from the model. The exact contract and current limits are documented in `CONTROLLED_OPERATIONS.md`.

## AI Response Contract and Validation

The AI response format needs to be enforceable, not just described in prose.

Recommended top-level response fields:

- Plan status: ready or needs clarification.
- Intent summary.
- Assumptions.
- Questions for the user when the request is too ambiguous.
- Ordered list of controlled operations.

Risk level, confirmation requirements, and affected-target counts are calculated locally. They are not accepted from the model as safety decisions.

Validation should happen in several passes before any scene edit:

1. Parse the response as structured data.
2. Validate the response against the operation schema.
3. Reject unknown operation names and unknown fields.
4. Validate field types and numeric bounds.
5. Resolve object references against the current scene.
6. Reject references to objects that do not exist or are outside the allowed target scope.
7. Estimate the blast radius, such as number of objects affected.
8. Confirm the risk level and approval requirement.
9. Reject operations that require unsupported Blender modes or contexts.
10. Produce a user-readable preview from the validated operations.

Implementation options to evaluate later:

- JSON Schema for model-facing response validation.
- Python typed models for internal validation.
- A small custom validator if dependency packaging becomes a problem.

If validation fails, no scene changes should happen. The extension can either show the error to the user or send one repair request back to the model with the validation errors. It should not silently guess how to fix invalid operations.

## Context Window Economics

Large Blender scenes can easily produce too much context. The context system needs an explicit budget strategy from the start.

Recommended context tiers:

- Tier 0: Blender version, scene units, active collection, active object, selection count.
- Tier 1: Full details for selected objects.
- Tier 2: Summary of objects in the same collections as the selection.
- Tier 3: Compact full-scene summary by object type, collection, material, camera, and light counts.
- Tier 4: Optional viewport screenshot or rendered preview.

Default behavior should prioritize selected objects and user intent. Full-scene details should not be sent unless the task requires them.

The extension should track:

- Maximum number of objects serialized in detail.
- Maximum number of materials/modifiers included in detail.
- Estimated token or character count.
- Data omitted from context.
- Whether file paths, custom properties, or screenshots are included.

The user should be able to see a context preview for privacy and debugging. If context was omitted, the assistant should say what was omitted instead of pretending it had full scene knowledge.

## Blender Execution Constraints

The execution layer must account for Blender-specific behavior that can make otherwise valid plans fail.

### Main Thread and Async Work

Blender's UI should not freeze during model calls. The likely pattern is:

1. UI operator collects user request and scene context.
2. Network/model work runs outside the UI path.
3. The result is queued back to Blender.
4. A modal operator, timer, or equivalent main-thread mechanism applies validated scene operations.

Background work should not directly mutate `bpy.data` or call Blender operators.

### Operator Context

Some Blender operators require an active object, a selected object, a specific mode, or an area/region context. Operations can fail if the context is wrong.

The extension should:

- Prefer direct data API changes when they are safer and deterministic.
- Use Blender operators only when necessary.
- Track required mode and context for each controlled operation.
- Use context override mechanisms such as `bpy.context.temp_override(...)` where appropriate.
- Restore selection, active object, and mode when possible.

### Undo Strategy

Undo is not guaranteed to work cleanly for every multi-step operation. Some operations may become multiple undo entries, and some background or data-block changes may not register how the user expects.

The MVP needs an explicit undo strategy:

- Each approved plan should aim to behave like one user-visible action.
- Operations should be grouped where Blender supports it.
- The action history should record affected objects and properties.
- Destructive operations should require confirmation.
- For high-risk operations, consider a pre-operation recovery point or affected-object snapshot.
- If an operation cannot be reliably undone, the preview should say so before approval.

Undo behavior must be tested as a first-class feature, not treated as a minor polish item.

## Approval UX Decisions

"Edit the plan" needs a precise meaning.

Recommended MVP approval flow:

1. User enters natural language request.
2. AI returns a validated plan.
3. Extension shows a readable summary and affected objects.
4. User can approve, reject, or rephrase.
5. Structured operations are visible for transparency but not directly editable in the MVP.

Later versions can add:

- Natural-language plan refinement, such as "same plan, but only for selected cubes."
- Advanced structured operation editing.
- Per-operation approve/skip controls.
- Saved approval presets for trusted low-risk operations.

For the first version, direct editing of structured operations is likely more complexity than value. Rephrase-and-replan is easier to understand and safer.

## Core Interaction Flow

1. User opens the AI assistant panel in Blender.
2. User types a request, such as "make the selected objects look like brushed metal and arrange them in a semicircle."
3. Extension collects context:
   - Blender version.
   - Selected objects.
   - Object names, types, transforms, materials, modifiers.
   - Scene units, active camera, active collection.
   - Optional viewport screenshot.
4. AI returns a structured plan, not immediate raw code.
5. Extension shows the plan to the user if the action is destructive, broad, expensive, or ambiguous.
6. User approves, rejects, or rephrases the plan.
7. Extension executes the plan using controlled Blender operations.
8. Extension reports what changed.
9. User can undo through Blender and can inspect the assistant history.

## Step-By-Step Build Plan

### Phase 1: Research and Scope

1. Decide the target Blender version range.
2. Decide whether this is a personal tool, open-source extension, or commercial add-on.
3. Define the first 20 commands the assistant should handle reliably.
4. Choose the initial AI provider.
5. Decide whether the first prototype can require an API key.
6. Study Blender extension packaging, add-on guidelines, and the current Blender Python API.
7. Review BlenderGPT, BlenderMCP, and the official Claude/Blender connector to understand what users already expect.
8. Run a small packaging spike before building the full system.
9. Verify whether the dependency strategy works in the target Blender version.

Deliverable: written MVP specification and architecture decision.

### Phase 2: Controlled Operation Contract

1. Define the MVP operation catalog.
2. Define required and optional fields for each operation.
3. Define type constraints, numeric bounds, and target rules.
4. Define confirmation requirements per operation.
5. Define undo expectations per operation.
6. Define what operation failures should look like.
7. Choose a validation mechanism.
8. Build mocked examples of valid and invalid operation plans.

Deliverable: operation schema catalog and validation specification.

### Phase 3: UX Design

1. Design a Blender sidebar panel for prompt input.
2. Add clear states: idle, thinking, awaiting approval, running, complete, failed.
3. Design a plan preview view.
4. Design an action history view.
5. Design settings for model provider, API key, safety level, and context detail.
6. Decide which actions require confirmation.
7. Decide that MVP plan editing means approve, reject, or rephrase.

Deliverable: UI mockup and interaction rules.

UX decisions are specified in `UX_DESIGN.md`. The MVP uses a compact 3D View sidebar, explicit preview before every execution, an additional confirmation dialog for high-risk plans, rephrase instead of direct operation editing, and mandatory local safety validation.

The UI shell, workflow states, preferences, panels, scene context, live planning orchestration, and
approved controlled execution are implemented.

### Phase 4: Scene Context System

1. Build a scene summarizer concept.
2. Limit context to relevant selected objects first.
3. Add broader scene context only when needed.
4. Decide how to represent materials, modifiers, cameras, lights, collections, and constraints.
5. Add safeguards against sending huge scenes or private metadata unnecessarily.
6. Define context tiers and context budgets.
7. Define how omitted context is reported to the user.
8. Consider optional screenshot/viewport context later.

Deliverable: context format specification.

The typed context records, selection/collection/scene readers, deterministic object budgets,
privacy filtering, omission reporting, opaque target IDs, provider-safe serialization, and UI
context preview are implemented. Scope-relevant material/collection filtering, a hard serialized
character ceiling, snapshot IDs, Blender runtime identity checks, and state-fingerprint validation
are also implemented. The contract is documented in `SCENE_CONTEXT.md`. Viewport image capture
remains deferred.

### Phase 5: AI Planning Layer

1. Define what the model is allowed to return.
2. Prefer structured tool instructions over free-form Python.
3. Make the model return:
   - Exact context snapshot ID.
   - Intent summary.
   - Assumptions.
   - Clarification questions when required.
   - Ordered controlled operations.
4. Add validation before execution.
5. Reject operations that are unsupported, dangerous, or too broad.
6. Add one repair loop for invalid structured responses if needed.
7. Assign every planning job a generation ID and ignore responses from canceled, superseded, or
   unregistered jobs.
8. Retain the exact scene snapshot through provider response validation and approval.
9. Run network work outside Blender's main thread, but queue all `bpy` reads and UI updates back to
   the main thread.
10. Make cancellation cooperative, bound every request by timeout, and remove timers/workers during
    extension unregistration.

Deliverable: AI response contract and validation rules.

Phase 5 is implemented. Planning uses one serialized daemon worker with a latest-request queue,
cooperative cancellation, superseded-response rejection, timeout-bounded OpenAI requests, and
queue-only handoff to a guarded Blender main-thread timer. An in-flight HTTP request cannot be
forcibly interrupted by `requests`, but cancellation prevents repair calls, UI updates, and further
queued work for that generation.

The coordinator retains the exact snapshot and complete multi-round clarification transcript. It
validates strict completed Structured Outputs, treats snapshot mismatches as terminal, checks target
references, calculates risk locally, and makes at most one cancellation-aware repair request for
other locally invalid plans. Validated operation payloads are recursively immutable. The provider
uses bounded retries only for explicit transient HTTP responses, honors `Retry-After`, captures
OpenAI request IDs for diagnostics, limits output tokens, and treats scene and request values as
untrusted prompt data. Blender revalidates live target identities and fingerprints before showing
clarification or an immutable plan preview. UI operators enforce legal workflow states, and timer
failures cannot silently unregister polling. Add-on unregistration invalidates active work without
waiting for network completion. Planning itself never mutates the scene; only explicit approval can
enter the Phase 6 executor.

### Phase 6: Execution Layer

1. Create a controlled list of Blender operations.
2. Map each operation to a safe Blender action.
3. Group actions into undoable transactions where possible.
4. Add dry-run/preview where possible.
5. Log every object/material/collection changed.
6. Add graceful failure behavior if only part of a plan succeeds.
7. Define main-thread execution flow for all Blender scene changes.
8. Define operator context requirements and context override rules.
9. Preflight the complete plan before mutation and revalidate snapshot ID, target runtime identity,
   fingerprints, names, kinds, and result-reference ordering immediately before execution.
10. Prefer atomic per-plan execution. If Blender prevents complete rollback, stop at the first safe
    operation boundary and report an explicit partial result with recovery instructions.

Deliverable: command execution design.

Phase 6 is implemented for all ten MVP operations. The executor repeats snapshot and live-target
validation, requires Object Mode, simulates the complete ordered plan, rejects lifecycle and naming
conflicts, and resolves backward creation-result references before mutation. It uses direct Blender
data APIs and `bmesh`, deterministic duplicate naming, copy-on-write material assignment, deferred
object deletion, reverse-order rollback, structured change records, and explicit partial-failure
recovery instructions. `Apply Plan` is registered as one Blender undoable action and records a
bounded session-history result. The detailed transaction contract and current cancellation/undo
limits are documented in `EXECUTION.md`.

### Phase 7: Safety Model

1. Classify requests by risk:
   - Low risk: create object, change color, move selected item.
   - Medium risk: batch edit many objects, apply modifiers, rename collections.
   - High risk: delete, overwrite, run generated script, import external assets.
2. Require approval for medium/high-risk operations.
3. Block or warn on arbitrary file access.
4. Never expose API keys to the model.
5. Avoid executing generated Python by default.
6. Add a visible "what changed" report after each run.

Deliverable: safety policy for the extension.

Phase 7 is implemented. Risk is derived locally from immutable operations and an accurate affected-
object count that includes generated objects without double-counting repeated targets. Every plan
requires preview and explicit application; high-risk plans require a second non-bypassable
confirmation derived from the retained plan. Destructive execution is blocked unless Blender Global
Undo is enabled and a pre-plan recovery point is successfully created. File access, subprocesses,
external downloads, and generated Python are absent from the controlled contract and explicitly
rejected by provider instructions. API keys remain outside model payloads. Successful and partial
results expose a readable changed-data report. The enforceable policy is documented in `SAFETY.md`.

### Phase 8: Model Provider Integration

1. Start with one provider.
2. Keep the provider layer replaceable.
3. Support streaming responses only after the core flow works.
4. Handle timeouts, rate limits, network failure, and invalid responses.
5. Add cost controls, such as max context size and max output size.
6. Consider local-model support only after the cloud provider flow is stable.

Deliverable: provider integration plan.

Phase 8 is implemented for the single-provider MVP. OpenAI communication remains behind a
Blender-independent provider protocol and uses direct HTTPS, strict Structured Outputs, local
validation, configurable timeouts and output limits, bounded retries for explicit transient HTTP
responses, capped `Retry-After` delays, and provider request IDs for diagnostics. Provider-neutral
token usage is parsed and aggregated across the one repair call and all clarification rounds, then
shown in Blender without hard-coding changing model prices. Context and prompt size limits provide
request-side cost controls. Streaming, local models, multi-provider selection, persistent budgets,
and automatic retries after ambiguous transport failures remain deferred. The implemented contract
and limits are documented in `PROVIDER_INTEGRATION.md`.

OpenAI model selection is implemented independently of provider selection. The Assistant panel and
preferences offer GPT-5 Nano, GPT-5.4 Nano, GPT-5.4 Mini, GPT-5.5, and a validated custom model name.
GPT-5 Nano remains the default so existing cost behavior and live-test baselines do not change.

Per-plan safety limits are also configurable. The defaults are 20 operations, 100 targets per
operation, and 100 duplicate outputs; Blender controls allow increases up to hard maxima of
100/500/1,000. The coordinator captures those values, constrains the provider schema and prompt, and
locally validates the response with the same immutable values. Plans affecting more than 25 objects
remain high risk and require Global Undo, recovery-point creation, and a second confirmation.

### Phase 9: Testing

1. Create repeatable sample Blender files.
2. Test each supported command against simple and messy scenes.
3. Test undo behavior.
4. Test invalid model responses.
5. Test network failures.
6. Test different Blender versions and operating systems.
7. Test with large scenes to measure context and performance limits.

Deliverable: test matrix and sample scenes.

Phase 9 is implemented for the supported Windows x64 and Blender 5.1.0 target. Deterministic simple,
messy, and 1,000-object `.blend` fixtures now cover selection context, privacy filtering, omission
reporting, character budgets, and performance. Pure-Python tests cover malformed responses and
network failures; Blender suites cover every controlled operation, preflight, rollback, stale
targets, UI workflow, and package registration. `scripts/run_release_checks.ps1` provides one
repeatable non-billable release gate. Foreground Undo, macOS, Linux, and additional Blender versions
remain explicit manual/unrun rows rather than implied support. See `TEST_MATRIX.md`.

### Phase 10: Packaging and Distribution

1. Package as a Blender extension using current Blender extension conventions.
2. Decide how dependencies are bundled or installed.
3. Decide whether the local bridge service is optional or required.
4. Add install instructions.
5. Add privacy notes for what scene data is sent to AI providers.
6. Add troubleshooting docs for API keys, network errors, and Blender version issues.

Deliverable: installable extension package and documentation.

Phase 10 is implemented for the MVP. The Blender extension manifest declares network access and six
pinned cross-platform runtime wheels, so users install one self-contained ZIP without `pip`, an SDK,
or a local bridge. The release gate validates source and archive metadata, rejects secrets and
bytecode, checks every referenced wheel, installs into an isolated Blender profile, imports every
packaged module, and verifies UI registration. `README.md`, `INSTALLATION.md`, `PRIVACY.md`, and
`TROUBLESHOOTING.md` document the supported platform, key setup, data sent to OpenAI, cost/privacy
controls, failures, updates, and removal.

### Phase 11: Advanced Features

Add these only after the MVP is reliable:

- Viewport screenshot understanding.
- Geometry nodes generation.
- Procedural material generation.
- Animation/keyframe assistance.
- Asset search/import.
- Local model support.
- MCP server/client compatibility.
- Multi-step autonomous tasks.
- Per-project memory.
- Voice input.

## Testing Strategy After Code Changes

Testing should happen in layers, starting with fast checks that do not require Blender and ending with manual/live Blender testing only when needed.

### 1. Static and Python-Level Checks

Run these before opening Blender:

- Syntax checks for all Python files.
- Formatting/linting if the project uses those tools.
- Unit tests for logic that does not need Blender.

Good candidates for normal Python unit tests:

- Operation schema validation.
- Scene context formatting.
- Prompt construction.
- AI response parsing.
- Safety/risk classification.
- Provider error handling.
- Settings serialization.
- Context budget and omission reporting.

These tests should be fast and should not require a running Blender process.

### 2. Mocked AI Response Tests

Most tests should not call a live AI model. Instead, feed the extension known structured responses and confirm the extension handles them correctly.

This avoids:

- API cost.
- Network failures.
- Rate limits.
- Non-deterministic model output.
- Slow test runs.

Example mocked scenarios:

- Valid material change operation.
- Valid transform operation.
- Delete operation requiring approval.
- Invalid operation name.
- Unknown field name.
- Missing required fields.
- Out-of-range numeric values.
- Operation targeting objects that do not exist.
- Operation targeting too many objects.
- Model response that contains unsupported or unsafe instructions.

The goal is to test whether the extension can safely execute validated operations, not whether the model happens to answer correctly on one run.

### 3. Blender Background Tests

Code that depends on Blender's Python API should be tested through Blender in background mode.

Typical command shape:

```powershell
blender --background --factory-startup --python tests/run_blender_tests.py
```

These tests should verify:

- Add-on registration and unregistration.
- Operators can run without UI interaction.
- Objects, materials, lights, and cameras are created correctly.
- Selection-based operations affect only the intended objects.
- Destructive actions require confirmation.
- Invalid operations fail without modifying the scene.
- Undo behavior works where possible.
- Mode and context requirements are handled correctly.
- Unsupported context requirements fail with clear errors.

Background tests are important because normal Python tests cannot fully simulate Blender's context, data blocks, dependency graph, undo stack, or mode behavior.

### 4. Sample Scene Tests

Keep a folder of small `.blend` files that represent common real-world conditions.

Recommended sample scenes:

- Empty scene.
- Default cube scene.
- Multiple selected objects.
- Scene with existing materials.
- Scene with lights and camera.
- Scene with nested collections.
- Scene with many objects.
- Scene with object names that are duplicated or confusing.
- Messy imported scene.

After execution, tests should check expected scene state:

- Object count.
- Object names.
- Object transforms.
- Material assignments.
- Camera/lights existence.
- Selection state.
- Whether unrelated objects were left unchanged.
- Whether context omissions were reported.

### 5. Async and UI Responsiveness Tests

Any code path that calls a model provider or waits on IO should be tested for UI impact.

Test for:

- Blender UI stays responsive while the request is running.
- Cancellation works.
- A timed-out request does not leave the assistant stuck in a running state.
- Background work does not directly mutate Blender data.
- Validated operations are applied back on the main thread.

### 6. Manual Blender Testing

Manual testing is required for visible workflow changes.

Use manual testing for:

- Sidebar panel layout.
- Prompt input.
- Loading/thinking/running/error states.
- Plan preview.
- Approval/rejection/rephrase flows.
- Action history.
- Undo from Blender's UI.
- Responsiveness during long requests.
- Error message clarity.

Manual testing should happen before considering any user-facing UI change complete.

### 7. Live AI Provider Testing

Live AI tests should be limited and deliberate. They are useful, but they should not be the foundation of the test suite.

The opt-in matrix at `tests/live/test_openai_live.py` contains ten real, billable scenarios with
automatic HTTP retries disabled. It is skipped unless both `RUN_LIVE_OPENAI_TESTS=1` and
`OPENAI_API_KEY` are present. Never enable it in the default test command or an unmetered CI job.

The June 20, 2026 matrix passed nine of ten scenarios. Every controlled operation type, local risk
assessment, and the prohibited-capability boundary passed. The model failed the vague aesthetic
request `Make the selected object look better` by inventing material choices instead of returning
clarification. Ambiguity handling must be hardened and rerun before that row can pass.

Run live tests for:

- Provider authentication.
- Real model response format.
- Timeout behavior.
- Rate limit behavior.
- Invalid API key behavior.
- Vague user prompts.
- Impossible user prompts.
- Destructive user prompts.
- Large scene context.

Every live response should still pass through the same validator used for mocked responses before any Blender operation runs.

### Recommended Test Order After Each Change

1. Run static/Python-level checks.
2. Run operation schema and mocked AI response tests.
3. Run Blender background tests.
4. Run sample scene tests if execution behavior changed.
5. Run async/UI responsiveness checks if provider or threading behavior changed.
6. Manually test in Blender if UI or workflow changed.
7. Run live AI tests only if provider, prompt, or response handling changed.

The key testing principle is to separate two questions:

- Did the AI understand the user's request?
- Can the extension safely execute a validated operation?

Most automated testing should focus on the second question, because that is what protects the Blender file.

## Major Challenges

### Safety and Trust

The biggest challenge is preventing the AI from making destructive or unexpected edits. Users will lose trust quickly if the assistant deletes objects, changes the wrong selection, or silently runs unsafe code.

Mitigation:

- Use structured operations.
- Require approval for risky actions.
- Keep action history.
- Use Blender undo.
- Avoid arbitrary Python execution as the default path.

### Blender Python Complexity

Blender's Python API is powerful but full of edge cases. Object mode vs edit mode, dependency graph updates, material node trees, modifiers, context overrides, and undo behavior can all cause subtle failures.

Mitigation:

- Start with simple object-mode operations.
- Build a small reliable tool set before expanding.
- Test on multiple Blender versions.

### Model Hallucination

AI models may invent Blender APIs, misunderstand scene context, or produce instructions that are impossible to execute.

Mitigation:

- Validate every operation.
- Keep supported tools explicit.
- Return useful errors to the model for correction.
- Prefer retries with feedback over blind execution.

### Dependency Management

Blender ships its own Python environment. Installing external packages inside it can be fragile across Windows, macOS, Linux, and Blender versions.

Mitigation:

- Keep the in-Blender extension lightweight.
- Move provider SDKs and heavy dependencies into a local bridge service if needed.
- Avoid unnecessary packages.
- Run a packaging spike in Phase 1 before depending on any package-heavy approach.

### Context Window and Cost Control

Large scenes can create expensive or oversized AI requests. If the assistant omits important scene data without saying so, the model may make bad decisions while sounding confident.

Mitigation:

- Use context tiers.
- Prioritize selected objects.
- Track context size.
- Report omitted context.
- Let users preview what scene data will be sent.

### Undo Reliability

Users will expect AI edits to undo cleanly, but Blender undo behavior can be inconsistent across direct data changes, operators, multi-step workflows, and background-driven actions.

Mitigation:

- Treat undo as part of each operation's design.
- Test undo behavior per operation.
- Group changes where possible.
- Require confirmation when undo confidence is low.
- Keep an action history with affected objects and changed properties.

### UI Freezing and Performance

Network calls or large scene analysis can block Blender's UI if handled poorly.

Mitigation:

- Run model/provider calls outside the UI path.
- Apply Blender scene changes back on the main thread.
- Use modal/timer-style execution patterns where appropriate.
- Keep scene context compact.
- Show progress states.
- Add cancellation.

### Privacy

Scene names, object names, custom properties, file paths, and screenshots can leak sensitive project information to external AI providers.

Mitigation:

- Tell users what is sent.
- Provide a context preview.
- Add privacy modes.
- Support local or self-hosted models later.

### API Key and Billing Risk

If the extension stores keys poorly or allows unlimited prompts, users may face security or cost problems.

Mitigation:

- Store keys using Blender preferences carefully.
- Never send keys to the model.
- Add request limits and visible cost-related settings.

### Packaging and Version Compatibility

Blender's extension platform and API behavior can change across versions. Packaging dependencies for Blender extensions can also become difficult.

Mitigation:

- Pick a narrow supported Blender version range at first.
- Track Blender extension guidelines.
- Test packaging early, not at the end.

### Competitive Differentiation

Since BlenderGPT, BlenderMCP, Claude's connector, and commercial AI Blender tools already exist, a new extension needs a reason to exist.

Primary differentiator:

- Safer approval-first workflow built on controlled operations instead of raw generated Python.

Secondary differentiators:

- Strong history and undo reporting.
- Better in-Blender plan preview UX.
- More reliable constrained tools.
- Model-agnostic provider support after the MVP.
- Privacy-first local model mode after the MVP.
- Focused workflows such as environment layout, product visualization, or batch cleanup.

## Suggested MVP Feature List

Must have:

- Blender sidebar chat/prompt panel.
- API provider settings.
- Scene/selection context summary.
- Context budget and omitted-context reporting.
- Controlled operation schema.
- AI response validator.
- Structured AI plan response.
- Plan preview for risky changes.
- Controlled execution for object transforms, object creation, deletion with confirmation, renaming, material assignment, lighting, and camera setup.
- Main-thread Blender execution path.
- Action history.
- Error messages that explain what failed.

Should have:

- Undo grouping.
- Retry/correction loop.
- Context size limits.
- Privacy/context preview.
- Basic test scenes.
- Early packaging spike.
- Async request handling with cancellation.

Not MVP:

- Marketplace-quality polish.
- Arbitrary script execution.
- Geometry nodes creation.
- Third-party asset integrations.
- Multi-agent architecture.
- Local LLM support.

## Key Design Decisions To Make Early

1. Is this a personal extension or a public product?
2. Which Blender versions will be supported first?
3. Will it use direct API calls from Blender, a local bridge, or MCP?
4. Which AI provider will be supported first?
5. Are generated Python scripts allowed at all?
6. What actions require user approval?
7. What scene data can be sent to the model?
8. Which validation mechanism will enforce the AI response contract?
9. What are the first supported controlled operations?
10. What context budget should the assistant use by default?
11. What does "edit the plan" mean in the MVP?
12. What undo guarantees can the extension honestly make?
13. What makes this extension meaningfully different from BlenderMCP and Claude's official connector?

## Recommended First Milestone

Build a non-public prototype that can reliably do this:

1. Prove the extension can be packaged and loaded in the target Blender version.
2. Define a small controlled operation schema.
3. Validate mocked AI responses against that schema.
4. Read the selected objects.
5. Send a compact scene summary and user request to one AI model.
6. Receive a structured plan.
7. Show the plan in Blender.
8. Let the user approve, reject, or rephrase the plan.
9. Execute only approved, predefined operations on Blender's main thread.
10. Log what changed.
11. Let Blender undo the operation, or clearly report if a specific action has limited undo reliability.

Example target prompts:

- "Make the selected object red plastic."
- "Arrange these selected cubes in a circle."
- "Add a three-point lighting setup around the selected object."
- "Rename selected objects based on their shape and location."
- "Create a camera looking at the selected object."

If those simple tasks are dependable, the project is on solid ground. If they are flaky, adding broader AI autonomy will make the system worse, not better.

## Research Sources

- BlenderGPT GitHub: https://github.com/gd3kr/BlenderGPT
- BlenderMCP GitHub: https://github.com/ahujasid/blender-mcp
- Anthropic announcement for Claude creative connectors and Blender connector: https://www.anthropic.com/news/claude-for-creative-work
- Blender Extensions add-ons directory: https://extensions.blender.org/add-ons/
- Blender extension creation docs: https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html
- Blender add-on guidelines: https://developer.blender.org/docs/handbook/extensions/addon_guidelines/
- Blender Python API docs: https://docs.blender.org/api/current/index.html
- Blender Copilot listing: https://superhivemarket.com/products/blender-copilot-blendergpt
- Blender AI Assistant community post: https://blenderartists.org/t/the-blender-ai-assistant/1601597
- 3D-Agent Blender AI page: https://3d-agent.com/blender-ai
- OpenAI current model guidance: https://developers.openai.com/api/docs/guides/latest-model.md
- OpenAI Structured Outputs guide: https://developers.openai.com/api/docs/guides/structured-outputs
