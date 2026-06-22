# Extension Safety Policy

## Trust Boundary

The provider proposes data. It never receives an API key and it cannot call Blender, access files,
run a subprocess, download an asset, or execute Python. Only a locally validated `ready` plan made
from the ten controlled operation types can reach the approval UI. Only the retained immutable plan
shown in that UI can reach execution.

Unknown operation types, unknown fields, unsupported references, generated code, and arbitrary tool
requests fail closed. Provider instructions explicitly require unsupported file, process, external
asset, and script requests to return clarification rather than inventing a workaround.

User-selected plan limits control the number of operations, targets, and duplicate outputs. Defaults
remain 20/100/100, while controlled hard maxima are 100/500/1,000. Captured limits are enforced in
both the provider schema and local validation before a plan can be retained.

## Risk Classification

Risk is calculated locally from the operation catalog and cannot be supplied or lowered by the
model.

| Level | Current examples | Approval |
| --- | --- | --- |
| Low | Create primitive/material/light/camera, assign material, transform a bounded set | Visible plan plus `Apply Plan` |
| Medium | Duplicate, rename, move between collections, or a broad low-risk plan | Visible warning plus `Apply Plan` |
| High | Delete objects or affect more than 25 objects | Visible warning plus a second confirmation dialog |

Blast radius counts unique existing object targets plus every object a plan creates, including all
duplicates. Repeated edits to one existing object count once. Plans affecting more than 10 objects
are at least medium risk; plans affecting more than 25 are high risk. More than 10 low-risk
operations also raises a plan to medium risk.

## Approval Integrity

- Every plan requires explicit approval; there is no automatic low-risk execution.
- High-risk confirmation is derived again from the retained immutable plan immediately before
  execution. Mutable UI labels are not authorization inputs.
- Calling the operator's execute path directly cannot bypass high-risk confirmation.
- Rephrase, reject, stale-target errors, and blocked safety decisions never mutate the scene.
- Structured operation editing and per-operation approval are not available in the MVP.

## High-Risk Recovery

Deletion and any plan affecting more than 25 objects require all of the following:

1. A validated high-risk plan.
2. Blender Global Undo enabled.
3. A second explicit confirmation using `Apply High-Risk Plan`.
4. A successfully created pre-plan recovery point.
5. A final execution preflight against unchanged live targets.

If any condition fails, execution stops before mutation and the plan remains available when it can
be retried safely. Permanent deletion remains deferred until all reversible operations complete.

## Secrets and Private Data

- Authorization is sent only in the HTTPS header and is never included in provider input.
- API keys are excluded from plans, history, errors, Blender files, and package archives.
- File paths and custom properties are excluded from context by default.
- A local `.env` is plaintext, gitignored, and intended only for source development.
- Provider errors shown to users contain bounded messages and request IDs, not request payloads.

## Change Reporting

Successful and partial executions produce immutable change records for every changed object,
material, collection, and active-scene camera setting. The result panel exposes a collapsible
changed-data list, while bounded session history retains a compact secret-free report.

## Non-Goals

The current policy does not make arbitrary generated code safe. Python execution, file access,
imports, external asset downloads, edit-mode mesh operations, modifiers, geometry nodes, rigging,
and animation remain outside the controlled contract.
