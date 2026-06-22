# Blender AI Assistant UX Design

## Implementation Status

Implemented in the Blender extension:

- 3D View `AI Assistant` sidebar panels.
- Session workflow state and legal transition model.
- Request, context, clarification, plan, result, error, and history views.
- Risk-aware plan preview and high-risk confirmation dialog.
- Preferences with environment-key priority and a masked non-persistent session key.
- Clear, cancel, reject, rephrase, apply, dismiss, new-request, and context-preview operators.
- Clean registration/unregistration of panels, operators, preferences, and WindowManager state.
- Scene-context collection and serialization.
- Background OpenAI planning orchestration and clarification history.
- Per-request model and token-usage reporting across repair and clarification calls.
- Configurable per-plan operation, per-operation target, and duplicate-output limits.
- Live immutable plan previews and bounded session history.
- Controlled Blender operation execution, rollback, recovery points, and Blender Undo integration.

## UX Goal

Create a compact Blender-native assistant that helps users prepare, inspect, approve, and review AI-planned scene changes without obscuring what will happen.

The UX should feel like an operational Blender tool, not a general chat application. The primary workflow is request, validated plan, approval, execution, and result.

## Product Principles

1. Show planned effects before scene changes.
2. Never use color alone to communicate risk or status.
3. Keep the main workflow in the 3D View sidebar.
4. Keep advanced configuration out of the main panel.
5. Do not expose raw provider payloads or API keys.
6. Preserve the user's prompt when planning fails or requires clarification.
7. Disable actions that are invalid for the current workflow state.
8. Use Blender terminology for objects, materials, collections, cameras, and lights.

## Location and Navigation

- Editor: 3D View.
- Region: Sidebar.
- Tab label: `AI Assistant`.
- Main panel: `Assistant`.
- Collapsible subpanels: `Plan`, `Context`, and `History`.
- Provider, model, privacy, and network configuration live in Blender Add-on Preferences.

The main panel remains narrow and vertically scannable. It does not use decorative cards or marketing content.

## Main Panel Layout

```text
AI Assistant
[status icon] Ready

Request
[ prompt input........................ ]
[ Plan Changes ]                [ X ]

Context
[ Selection | Collection | Scene ]
3 selected objects
[ Preview Context ]

Plan
Arrange selected cubes in a semicircle
[warning icon] Medium risk - 6 objects
3 operations
  1. Set transform - 6 objects
  2. Create material - Brushed Metal
  3. Assign material - 6 objects
[ Apply Plan ] [ Rephrase ] [ Reject ]

Recent Activity
12:41  Completed  Arrange selected cubes
12:35  Rejected   Delete unused lights
```

Only sections relevant to the current state are expanded. `Plan` appears after a valid plan exists. `History` defaults to collapsed once entries exist.

## Prompt Composer

The MVP uses Blender's native string input in the sidebar. It supports long prompts through horizontal text scrolling, while the submitted request is displayed as wrapped read-only text in the plan/result view.

Prompt behavior:

- The prompt remains editable while idle, complete, failed, or awaiting clarification.
- `Plan Changes` starts context collection and planning.
- The clear icon empties only the draft prompt.
- The last submitted prompt remains available after errors and rejection.
- Submitting an empty or whitespace-only prompt is blocked locally.
- Starting a new request while an unexecuted plan exists requires discarding that plan first.

A dedicated multiline composer is deferred until it can be implemented without replacing Blender-native editing behavior with a fragile custom widget.

## Context Scope

The context mode uses an expanded enum control:

- `Selection`: selected objects plus minimal scene metadata. This is the default.
- `Collection`: active collection plus minimal scene metadata.
- `Scene`: budgeted scene summary with detailed active/selected objects.

The panel shows a compact context summary before submission, such as `3 selected objects` or `42 scene objects, 10 detailed`.

`Preview Context` opens a read-only view containing:

- Included object/material/collection counts.
- Omitted counts and reasons.
- Whether custom properties, paths, or viewport images are included.
- Estimated serialized size.

The context preview does not show the API key or provider authorization data.

## Workflow States

| State | Main Status | Available Actions |
| --- | --- | --- |
| `configuration_required` | OpenAI setup required | Open Settings |
| `idle` | Ready | Edit prompt, select context, Plan Changes |
| `collecting_context` | Reading scene | Cancel |
| `planning` | Planning changes | Cancel request |
| `validating` | Validating plan | Cancel request |
| `needs_clarification` | More information needed | Answer, Continue Planning, Reject |
| `awaiting_approval` | Review plan | Apply Plan, Rephrase, Reject |
| `executing` | Applying changes | Cancel remaining operations when safe |
| `complete` | Changes applied | Undo, New Request, View Details |
| `error` | Request failed | Retry when safe, Edit Request, View Details |
| `canceled` | Request canceled | Edit Request, New Request |

Transient states use Blender's progress/status indicators where available. A network task must never freeze the 3D View.

## Clarification Flow

When the provider returns `needs_clarification`:

1. Show the model's validated questions.
2. Preserve the original request and context summary.
3. Provide a response field below the questions.
4. `Continue Planning` sends the original request, questions, and user response through the workflow.
5. `Reject` closes the clarification state without changing the scene.

No operations are displayed or executable while clarification is required.

Completed provider calls remain visible as an `AI Usage` summary during clarification so the user
can see the cost already incurred before deciding whether to continue.

## Plan Preview

The preview is generated from the locally validated operation model, not provider prose.

Always show:

- Intent summary.
- Locally calculated risk level.
- Number of operations.
- Number of referenced object targets.
- Assumptions, when present.
- Omitted context warning, when relevant.
- Undo limitation warning, when relevant.

Each operation row shows:

- Sequence number.
- User-readable operation label.
- Target count or created item name.
- Expand control for validated fields.

Structured operations are read-only in the MVP.

## Approval and Risk

Every valid plan receives a preview and requires an explicit `Apply Plan` command. The local `requires_confirmation` result controls whether an additional confirmation step is required.

| Risk | Preview | Apply Behavior |
| --- | --- | --- |
| Low | Standard information icon | Apply after the user presses `Apply Plan` |
| Medium | Warning icon and reason | Apply after the user presses `Apply Plan` |
| High | Error/warning icon, reason, affected count | Open a confirmation dialog before execution |

High-risk confirmation uses the retained immutable plan, names the risk and affected count, and uses
the explicit `Apply High-Risk Plan` command. Direct operator execution cannot bypass it.

Approval actions:

- `Apply Plan`: execute the current immutable validated plan.
- `Rephrase`: retain the original request and open a refinement draft; the current plan becomes non-executable.
- `Reject`: retain the request in history and close the plan without scene changes.

Direct structured-operation editing, per-operation skipping, and automatic low-risk execution are deferred.

## Execution and Cancellation

While executing:

- Prompt and plan controls are disabled.
- Operation progress counters are updated at each safe operation boundary.
- Execution is synchronous on Blender's main thread and cannot be canceled after `Apply Plan` starts.
- Partial completion reports how many operations completed and what scene data remains changed.
- The workflow never reports success unless all required operations completed.

## Result View

A successful result shows:

- `Changes applied` status.
- Completed operation count.
- Changed object/material/collection count.
- Warnings and undo limitations.
- Blender Undo availability for the completed transaction.
- Collapsible changed-data details naming each affected datablock and change.
- `New Request` to return to idle.

The Assistant panel also shows the model, total/input/output tokens, cached input when present,
reasoning output when present, and provider-call count when more than one call was required. Usage
is cumulative for one logical request and resets when a new request begins. It is token reporting,
not a currency estimate.

The extension does not add a custom Undo command because it cannot safely prove that the AI plan is
still Blender's latest undo step after unrelated user work.

## History

History is session-scoped for the MVP and stores at most 20 entries.

Each row contains:

- Local timestamp.
- Final state: completed, rejected, failed, canceled, or partially completed.
- Short request summary.
- Risk icon for executed plans.

Expanded history details contain the validated plan summary, approvals, operation results, warnings, and changed data references. They do not contain API keys, authorization headers, or raw unfiltered scene context.

## Preferences

### Provider

- Provider: OpenAI, read-only for the MVP.
- Model: a dropdown in the Assistant panel and preferences with GPT-5 Nano as the default,
  GPT-5.4 Nano, GPT-5.4 Mini, GPT-5.5, and a validated Custom option.
- Reasoning effort: low development default with medium and high evaluation options.
- API key status: environment, local `.env`, session, or missing. The key value is never displayed.
- Session API key: masked field marked `SKIP_SAVE`, used only when no environment or local key exists.
- Clear Session Key command.
- Request timeout.

The operating-system `OPENAI_API_KEY` remains the preferred source. A gitignored project `.env` is
available for source development, but remains plaintext and is not packaged. A session key is held
only in memory so `Open Settings` can resolve missing configuration without writing a secret to
Blender preferences.

### Context and Privacy

- Default context scope.
- Include custom properties: off by default.
- Include file paths: off by default.
- Include viewport image: off and unavailable until implemented.
- Context detail/object budget.

### Safety

- Medium and high-risk confirmation behavior is mandatory.
- Destructive plans require Global Undo and a successful pre-plan recovery point.
- Local schema and scene validation cannot be disabled.
- Arbitrary Python execution is unavailable.
- The collapsible `Plan Limits` panel and preferences expose numeric limits for operations per plan,
  targets per operation, and total duplicate outputs. Values default to 20/100/100 and have hard
  maxima of 100/500/1,000.
- Any future convenience setting must preserve these minimum guarantees.

## Error Design

Errors use a short headline, actionable next step, and optional technical details.

| Error Class | User Action |
| --- | --- |
| Missing API key | Open Settings |
| Authentication failure | Open Settings, Retry |
| Timeout/network failure | Retry, Edit Request |
| Invalid provider response | Retry Planning, Edit Request |
| Missing/stale target | Refresh Context, Replan |
| Blender context/mode failure | Return to required mode, Retry |
| Partial execution | View Details, Undo when available |

Technical details must redact secrets and avoid dumping raw scene context into the UI.

## Accessibility and Density

- Status always includes text and an icon.
- Primary commands use icon and text.
- Familiar secondary commands may use icons with tooltips.
- Risk is communicated through icon, label, and reason rather than color alone.
- Long object names and summaries wrap or truncate without resizing controls.
- Buttons keep stable dimensions while status text changes.
- Keyboard focus remains predictable after planning, rejection, errors, and completion.

## Deferred UX

- Direct editing of structured operations.
- Per-operation approval or skipping.
- Automatic execution of low-risk plans.
- Persistent cross-session history.
- Multiline custom prompt widget.
- Viewport image capture controls.
- Voice input.
- Multiple provider selection.
- MCP client controls.

## Module Mapping

- `extension/ui/properties.py`: UI and workflow-facing Blender properties.
- `extension/ui/operators.py`: plan, cancel, apply, reject, rephrase, retry, and history commands.
- `extension/ui/panels.py`: main panel and conditional subpanels.
- `extension/ui/planning.py`: background-result polling, live target validation, clarification, and
  immutable plan-preview state.
- `extension/operations/executor.py`: complete-plan preflight, controlled mutation, rollback, and
  change records.
- `extension/ui/preferences.py`: provider, context, privacy, and timeout preferences.
- `extension/context`: scene collection, context budgets, privacy filtering, and provider-safe
  serialization as specified in `SCENE_CONTEXT.md`.
- `extension/workflow/state.py`: state enum and legal transitions.
- `extension/history`: history rows and details.

## MVP Acceptance Criteria

1. The sidebar never allows an unvalidated plan to execute.
2. Every executable plan is visible before application.
3. High-risk operations require a second explicit confirmation.
4. Rephrase and reject never change the scene.
5. The UI remains responsive during network requests.
6. Missing configuration, provider errors, invalid plans, and stale targets have distinct states.
7. The user can see what context was included or omitted.
8. Execution results distinguish complete, partial, failed, and canceled outcomes.
9. History excludes secrets and raw unfiltered scene context.
10. UI registration and state visibility are testable in Blender background mode.
