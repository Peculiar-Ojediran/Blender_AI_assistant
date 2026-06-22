# Installation

## Requirements

- Windows x64.
- Blender 5.1.0 or a compatible Blender 5.1.x build.
- Internet access to `api.openai.com` when planning a request.
- An OpenAI API key with available API credit.

Only Windows x64 with Blender 5.1.0 is verified. Other operating systems and Blender versions are
not release-qualified yet, even though the bundled Python wheels are cross-platform.

## Install the Extension

1. Open Blender.
2. Open `Edit > Preferences > Extensions`.
3. Open the Extensions menu and choose `Install from Disk`.
4. Select `blender_ai_assistant-0.1.3.zip` without extracting it.
5. Approve the declared network permission and enable `Blender AI Assistant` if Blender does not
   enable it automatically.
6. Close Preferences, open the 3D View sidebar, and select the `AI Assistant` tab.

The ZIP bundles `requests`, `fastjsonschema`, and their runtime dependencies. Do not install packages
into Blender's Python environment manually.

## Configure the API Key

The safest supported source is the operating-system environment:

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-key", "User")
```

Restart Blender after setting it. The extension checks key sources in this order:

1. Operating-system `OPENAI_API_KEY`.
2. Project `.env`, only when running from this source checkout.
3. The masked session-only field in the extension preferences.

The session field is not saved when Blender closes. The source-development `.env` file is plaintext,
is excluded from the package, and may be synchronized by OneDrive.

## First Request

1. Open or create a Blender scene.
2. Select the objects relevant to the request.
3. Open `3D View > Sidebar > AI Assistant`.
4. Keep context scope on `Selection` for the smallest payload.
5. Choose a model from the Model dropdown.
6. Optionally expand `Plan Limits` and reduce operations, targets, or duplicate outputs.
7. Enter a request and choose `Plan Changes`.
8. Review the validated operation list, affected-object count, risk, context summary, and AI usage.
9. Choose `Apply Plan` only when the preview matches the intended changes.

## Update or Remove

Install a newer ZIP through `Install from Disk` after closing active planning work. To remove the
extension, use its menu in `Preferences > Extensions`. Removing the extension does not delete Blender
files or OpenAI account data.

## Development Install

Source environment creation, Blender CLI validation, fixture generation, and release commands are in
`DEVELOPMENT_SETUP.md`. The local bridge described as a possible future architecture is not required
for version 0.1.3.
