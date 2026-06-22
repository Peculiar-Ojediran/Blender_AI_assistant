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
| Invalid AI output | Missing fields, invalid JSON/schema, refusal, incomplete/missing status | `tests/test_openai_provider.py` |
| Network behavior | Authentication, 429, 5xx exhaustion, Retry-After cap, timeout without ambiguous retry | `tests/test_openai_provider.py` |
| Blender integration | Registration, scene context, planning, approval, UI state, stale targets | `tests/run_blender_tests.py` |
| Controlled operations | All ten operation types, variants, references, preflight, rollback | `tests/run_execution_tests.py` |
| Sample scenes | Simple selection, messy scene privacy/budgets, 1,000-object performance | `tests/run_sample_scene_tests.py` |
| Packaging | Manifest/source/archive validation and forbidden-file/wheel checks | `tests/verify_release_package.py` |
| Installed artifact | Clean-profile install, packaged imports, UI registration | `tests/run_installed_extension_tests.py` |
| Live provider | Ten schema-constrained scenarios with no automatic retries | 9 passed, 1 failed |

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

## Sample Scene Baseline

Measured on Windows x64, Blender 5.1.0:

| Fixture | Purpose | Baseline |
| --- | --- | --- |
| `simple_scene.blend` | Selected mesh/material context | 3 targets, 1,431 characters |
| `messy_scene.blend` | Privacy and budget reduction | 34 omissions, 7,341 characters |
| `large_scene.blend` | 1,000-object context performance | 0.046 seconds, 976 omissions, 29,294 characters |

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
