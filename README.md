# Blender AI Assistant

Blender AI Assistant is a Blender 5.1 extension that sends a bounded scene snapshot and a natural-
language request to OpenAI, receives a strict controlled-operation plan, validates it locally, shows
it for approval, and applies only supported Blender operations.

## Current Release

- Version: 0.1.4 MVP.
- Verified platform: Windows x64.
- Verified Blender version: 5.1.0.
- Provider: OpenAI Responses API.
- Default development model: `gpt-5-nano` with low reasoning effort.
- Models: GPT-5 Nano, GPT-5.4 Nano, GPT-5.4 Mini, GPT-5.5, or a custom model name.
- Configurable plan limits: operations, targets per operation, and duplicate outputs.
- Local release package after building: `dist/blender_ai_assistant-0.1.4.zip`.

The archive contains all Python runtime dependencies. It does not require `pip`, a provider SDK, or
a local bridge service on the user's machine. The generated `dist/` directory is intentionally not
tracked in Git.

## Install

Follow [INSTALLATION.md](INSTALLATION.md). Configure an API key, install the ZIP through Blender's
Extensions preferences, then open `3D View > Sidebar > AI Assistant`.

## Safety Boundary

The model cannot execute Python or call Blender directly. It can propose only the operation types in
`CONTROLLED_OPERATIONS.md`. Every plan is checked against a retained scene snapshot, risk is derived
locally, scene mutation requires explicit approval, and destructive plans require Blender Global
Undo plus a pre-plan recovery point.

## Documentation

- [Installation](INSTALLATION.md)
- [Privacy](PRIVACY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Test matrix](TEST_MATRIX.md)
- [Development setup](DEVELOPMENT_SETUP.md)
- [Architecture](ARCHITECTURE.md)
- [Provider integration](PROVIDER_INTEGRATION.md)

## Release Verification

Run the complete non-billable release gate from PowerShell:

```powershell
.\scripts\run_release_checks.ps1
```

Live OpenAI verification remains explicit and billable:

```powershell
.\scripts\run_release_checks.ps1 -RunLiveOpenAI
```

## License

Licensed under the [GNU General Public License v3.0 or later](LICENSE).
