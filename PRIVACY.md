# Privacy

## Data Sent to OpenAI

When the user chooses `Plan Changes` or continues a clarification, the extension sends:

- The submitted request and clarification transcript.
- The selected context scope: selection, active collection, or budgeted scene.
- Scene and Blender version metadata, unit settings, and a generated snapshot ID.
- Included object names, types, transforms, dimensions, material references, modifier names, and
  type-specific summaries such as mesh vertex counts.
- Included material and collection names plus bounded material settings and collection membership.
- Omission counts and warnings so the model knows when context is incomplete.
- A strict JSON Schema defining the only operations the model may propose.

Object, material, and collection names can contain confidential project information. Use neutral
names or a smaller scope when that matters.

## Data Not Sent by Default

- The API key or authorization header.
- The `.blend` file itself.
- Arbitrary binary mesh, image, texture, audio, or video data.
- File paths.
- Custom properties.
- Viewport screenshots.
- Internal Blender runtime references used to revalidate targets.
- Generated Python, because generated Python is unsupported.

Custom properties and file paths can be enabled separately in preferences for source workflows.
Review the Context panel before planning. Viewport capture is currently unavailable.

## Limits and Reduction

The default context contains at most 25 detailed objects and 200 object summaries and is capped at
100,000 serialized characters. When context exceeds a limit, the extension removes lower-priority
data deterministically and reports omissions. The output limit defaults to 4,096 tokens.

## Provider Handling

OpenAI requests set `store` to false. Provider-side processing, abuse monitoring, account controls,
and retention are governed by the provider's current terms and API data policies, not by this
extension. Do not submit data that the applicable account or organization policy forbids.

## Local Storage

- The operating-system API key remains outside Blender files.
- The masked session key stays in memory and is not saved in preferences.
- A source-checkout `.env` is plaintext and may be synchronized by OneDrive.
- Session history stores short request summaries, status, risk, and result details in memory.
- The extension does not persist raw provider payloads or raw scene context.
- Blender Undo and saved `.blend` files may contain the scene changes the user approved.

The release ZIP excludes `.env`, bytecode, test scenes, development caches, and source test data.
