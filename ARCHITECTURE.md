# Project Architecture

## Request Flow

1. `ui` receives a natural-language request.
2. `workflow` starts a planning job and manages state transitions.
3. `context` reads Blender data on the main thread, filters private data, and applies a context budget.
4. `providers` sends the request and strict operation schema to OpenAI.
5. `operations` validates the returned plan structurally and against the current scene.
6. `ui` presents the validated plan for approval, rejection, or rephrasing.
7. `safety` recomputes local authorization and recovery requirements from the retained plan.
8. `operations` executes an approved plan on Blender's main thread.
9. `history` records the request, approval, result, and changed data without secrets.

No provider response may bypass local validation, approval policy, or the main-thread execution boundary.

## Extension Packages

### `extension/providers`

Owns provider-neutral request/response types and OpenAI Responses API communication. It must not import Blender or mutate scenes.
The OpenAI adapter requires a completed structured response, caps output tokens, retries only
explicit transient HTTP responses within a fixed retry budget, and retains provider request IDs for
diagnostics. Provider-neutral token usage includes input, cached-input, output, reasoning-output, and
total counts. User requests and serialized scene values are treated as untrusted prompt data. The
full adapter contract is documented in `PROVIDER_INTEGRATION.md`.

### `extension/workflow`

Coordinates the full request lifecycle. It owns workflow state and the boundary between background network work and Blender's main thread.
Planning work uses generation IDs, one serialized daemon worker, a latest-request queue,
cooperative cancellation, a result queue, and a guarded Blender timer. Superseded or canceled
generations cannot update UI state or issue a repair request. The coordinator retains the original
request and every clarification round, and it treats a mismatched snapshot ID as terminal rather
than asking the provider to repair against stale state. Usage from the original and optional repair
calls is aggregated before the result reaches Blender's main thread. User-selected operation limits
are captured once per planning generation and drive both provider-schema construction and local
validation, including any repair response.

### `extension/context`

Reads and serializes relevant Blender scene state. It owns context budgets, omission reporting, and privacy filtering.
The provider payload, target-ID rules, privacy behavior, and current limits are documented in
`SCENE_CONTEXT.md`.

### `extension/operations`

Owns the controlled-operation catalog, JSON Schema, local validation, target resolution, risk classification, execution, and undo strategy. The exact provider contract is documented in `CONTROLLED_OPERATIONS.md`.
Validated operation payloads are recursively immutable so approval and later execution receive the
same values that passed validation.
The main-thread executor performs complete-plan simulation before mutation, binds backward creation
results, journals reversible changes, and defers permanent deletions until the final commit. Its
transaction and recovery guarantees are documented in `EXECUTION.md`.

### `extension/ui`

Owns Blender panels, operators, preferences, and UI properties. Planning UI calls the workflow layer;
the approved-plan operator is the only UI entry point to the executor. Layout and interaction rules
are defined in `UX_DESIGN.md`.

### `extension/safety`

Owns local approval, secondary-confirmation, prohibited-capability, and destructive-recovery policy.
It is Blender-independent and never trusts provider risk claims or mutable UI presentation state.
The complete policy is documented in `SAFETY.md`.

### `extension/history`

Owns future persistent history models. The current MVP keeps bounded, secret-free execution history
in WindowManager UI state. API keys and unfiltered scene data must never be stored in either place.

### Shared Modules

- `extension/config.py`: shared defaults and supported settings.
- `extension/errors.py`: extension-wide errors and user-safe error translation.

## Threading Boundary

Background work may perform HTTP requests and parse provider responses. It must not access or mutate `bpy` data. Scene reads, target resolution that touches Blender data, execution, undo, and UI updates happen on Blender's main thread.

Cancellation is logical and cooperative. The current `requests` transport cannot interrupt an HTTP
call already in progress, so the timeout remains the hard upper bound for that call. The runtime
serializes workers and discards canceled results to prevent unbounded overlap or stale UI updates.

## Dependency Direction

The intended dependency direction is:

`ui -> workflow/safety -> context/providers/operations/history`

Lower-level packages must not import `ui`. Providers must not import Blender-specific modules. Operation models and schemas should remain testable without Blender.

## Packaging Boundary

The Blender extension archive is self-contained. It bundles pinned pure-Python wheels for `requests`,
`fastjsonschema`, and the HTTP dependency chain declared in `requirements-runtime.txt`. End users do
not run `pip` inside Blender. The MVP calls OpenAI directly and does not require a local bridge.

Development tests and `.blend` fixtures remain outside the archive. Blender's manifest validator and
`tests/verify_release_package.py` independently check the release before an isolated-profile install.

## Implementation Order

1. Operation models, catalog, and strict schema.
2. Structural and semantic plan validation.
3. Scene-context models, reader, serializer, and budgets.
4. Workflow state, asynchronous planning runtime, and snapshot-retaining coordinator.
5. Blender UI, preferences, and immutable plan preview.
6. Main-thread operation execution and undo.
7. History and change reporting.
8. Live OpenAI integration tests and broader Blender scene tests.
