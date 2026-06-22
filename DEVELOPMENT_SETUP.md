# Development Setup

## Supported Local Environment

- Operating system: Windows
- Blender: 5.1.0
- Blender Python: 3.13.9
- Virtual environment: `.venv`

The virtual environment was created from Blender's bundled Python executable so development tools use the same Python major/minor version as Blender.

## Dependency Groups

Runtime dependencies are listed in `requirements-runtime.txt`:

- `requests`: provider-neutral HTTPS client for AI API calls.
- `fastjsonschema`: validates structured AI operation plans before Blender execution.

Development dependencies are listed in `requirements-dev.txt`:

- `pytest` and `pytest-cov`: automated tests and coverage.
- `ruff`: linting and formatting checks.
- `mypy` and `types-requests`: static type checks.
- `fake-bpy-module`: Blender API stubs for editor support and non-Blender type checking.

`requirements-lock.txt` records the complete installed environment for reproducibility.

No provider-specific SDK is installed. The implementation uses direct HTTPS through `requests`, and
a provider SDK should be added later only if it provides a clear benefit.
The adapter boundary, retries, failures, cost controls, and token reporting are documented in
`PROVIDER_INTEGRATION.md`.

## OpenAI Configuration

OpenAI is the initial provider. The extension uses the Responses API with `gpt-5-nano` and low
reasoning effort by default during development. Blender exposes GPT-5 Nano, GPT-5.4 Nano, GPT-5.4
Mini, GPT-5.5, and a validated custom-model field in both the Assistant panel and preferences. Plans
are constrained through Structured Outputs and validated locally.

API-key resolution uses this priority:

1. The operating-system `OPENAI_API_KEY` environment variable.
2. `OPENAI_API_KEY` in the project-root `.env` file for local source development.
3. Blender's masked, session-only key field.

The project-root `.env` file is already created and ignored by Git. Add the key after the equals
sign without committing or sharing the file:

```dotenv
OPENAI_API_KEY=your-api-key-here
```

An `.env` file is plaintext and may be synchronized by OneDrive. The operating-system environment
or a dedicated secret manager is safer for long-lived credentials. Never add API keys to source
files, Blender files, tests, logs, or project documentation. Installed ZIP users should use the
operating-system environment or session-only Blender field; the project `.env` is not packaged.

The provider is tested with mocked HTTP responses by default. A live API request is never included
in routine verification because it is nondeterministic and billable.

An explicit ten-scenario live matrix is available when provider or prompt behavior changes. It sends
at most ten real requests with automatic HTTP retries disabled. The scenarios cover every controlled
operation type, ambiguity handling, and prohibited capabilities, then apply local schema, snapshot,
target-reference, risk, and usage validation:

```powershell
$env:RUN_LIVE_OPENAI_TESTS = "1"
.\.venv\Scripts\pytest.exe -m live_openai tests/live/test_openai_live.py
```

The live matrix deliberately requires `OPENAI_API_KEY` in the operating-system environment in
addition to its cost acknowledgement flag; it does not activate from `.env`. Run it deliberately
because it incurs ten OpenAI API requests.

## Recreate the Environment

From the project root in PowerShell:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\5.1\python\bin\python.exe' -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

## Development Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe extension tests
```

Blender-dependent tests will run through Blender itself:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/run_execution_tests.py
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/run_sample_scene_tests.py
```

`tests/run_installed_extension_tests.py` is intended for a separate Blender process after the
built ZIP has been installed and enabled in an isolated test profile. It imports every packaged
module and verifies UI registration from the installed artifact rather than the source tree.

## Build the Extension

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --command extension validate .\extension
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --command extension build --source-dir .\extension --output-dir .\dist
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --command extension validate .\dist\blender_ai_assistant-0.1.3.zip
.\.venv\Scripts\python.exe tests\verify_release_package.py .\dist\blender_ai_assistant-0.1.3.zip
```

The source manifest references six pinned pure-Python wheels under `extension/wheels`. End users do
not install dependencies into Blender manually. Refresh those wheels only when
`requirements-runtime.txt` changes, then rebuild and rerun the isolated installation check.

## Sample Fixtures

Regenerate deterministic sample scenes after their generator or required Blender version changes:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/fixtures/build_sample_scenes.py
```

The complete non-billable release gate wraps dependency, Python, Blender, fixture, package, and
clean-install checks:

```powershell
.\scripts\run_release_checks.ps1
```

Pass `-RunLiveOpenAI` only for an intentional billable release check with `OPENAI_API_KEY` set in the
operating-system environment.

## Verified Setup

Verified on June 21, 2026:

- `pip check`: no broken requirements.
- `pytest`: 99 configuration, dependency, provider, planning-pipeline, async-runtime, coordinator,
  execution-result, operation-contract, safety-policy, scene-context, and workflow-state tests
  passed; 10 billable live OpenAI tests skipped by default.
- `ruff check .`: passed.
- `mypy extension tests`: passed, including Blender API stub resolution.
- Blender 5.1 background dependency, scope filtering, stale-target identity/fingerprint,
  scene-context, mocked background planning, immutable plan preview, UI operator guards, timer
  recovery, registration, and state tests: passed.
- Blender safety checks for direct high-risk execution bypass, retained approval state, authoritative
  risk, and visible changed-data details: passed.
- OpenAI token-usage parsing, malformed-usage fallback, bounded `Retry-After`, repair-call
  aggregation, and Blender usage-state propagation: passed.
- Blender 5.1 controlled execution tests for all ten operations, every primitive and light variant,
  result references, deterministic naming, copy-on-write materials, deletion child preservation,
  complete preflight, stale rejection, and rollback: passed.
- Deterministic simple, messy, and 1,000-object sample scenes: passed; the large-scene context
  measured 0.034 seconds, 976 omissions, and 29,294 serialized characters on the verified machine.
- Foreground Blender Undo interaction remains a manual check because background mode has no editor
  context; automatic tests verify operator undo registration and undo-availability state.
- Built-ZIP installation, packaged-module import sweep, and fresh-process UI registration: passed
  in an isolated Blender profile.
- Runtime schema compilation and rejection of unknown fields: passed.
- Extension source and built archive validation: passed.
- Extension archive build: passed.
- Bundled-wheel references, archive secret/bytecode exclusions, and independent release-content
  verification: passed; resulting archive size was 539,249 bytes.
- macOS, Linux, other Blender versions, and interactive foreground Undo remain explicit test-matrix
  gaps documented in `TEST_MATRIX.md`.
