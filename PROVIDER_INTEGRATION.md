# Model Provider Integration

## Current Scope

The MVP supports two providers: the OpenAI Responses API and NVIDIA NIM chat completions. The
extension sends requests directly over HTTPS with `requests`; it does not depend on a provider SDK or
a local bridge service. The default development configuration is OpenAI `gpt-5-nano` with low
reasoning effort.

The Blender model selector offers `gpt-5-nano`, `gpt-5.4-nano`, `gpt-5.4-mini`, and `gpt-5.5` plus a
validated custom model name. The default remains the model used by the established live-test baseline;
changing the selection affects the next planning request and does not weaken local validation.

The NVIDIA selector offers `openai/gpt-oss-20b`, `meta/llama-3.3-70b-instruct`, and
`nvidia/nemotron-3-ultra-550b-a55b` plus a validated custom NIM model name. The default hosted model
is `openai/gpt-oss-20b`; the default hosted base URL is `https://integrate.api.nvidia.com/v1`, with a
configurable override.

Streaming responses, automatic provider failover, and local models remain deferred.

## Replaceable Boundary

`extension/providers/base.py` defines Blender-independent `PlanRequest`, `PlanResponse`,
`TokenUsage`, and `Provider` types. A future adapter must accept the same serialized scene context
and strict response schema, then return a plan mapping for the same mandatory local validation.

Provider adapters must not:

- Import `bpy` or access Blender data.
- Mutate the scene.
- Relax the controlled-operation schema.
- Supply authoritative risk or approval decisions.
- Place credentials in prompts, scene context, responses, or logs.

## OpenAI Request Contract

Each request uses `POST /v1/responses` with:

- A configurable model and reasoning effort.
- A strict JSON Schema Structured Output.
- `store: false`.
- A configurable maximum output-token limit.
- System instructions that treat the prompt and scene context as untrusted data.
- A compact, privacy-filtered scene context bounded by the configured character limit.

The response must report `completed`, contain non-empty output text, decode to a JSON object, and
pass the supplied schema locally. The workflow then performs semantic, target-reference, snapshot,
risk, and live-scene validation independently of the provider.

## NVIDIA Request Contract

Each request uses `POST /v1/chat/completions` under the configured base URL with:

- A configurable NIM model.
- `stream: false`.
- A configurable maximum output-token limit through `max_tokens`.
- Low-temperature sampling defaults for predictable planning.
- NVIDIA guided JSON through `nvext.guided_json`.
- The same system instructions and compact scene context used by the OpenAI path.

The response must contain a non-empty assistant message, must not be truncated by `finish_reason:
length`, must decode to a JSON object, and must pass the supplied schema locally. The workflow then
performs the same semantic, target-reference, snapshot, risk, and live-scene validation.

NVIDIA hosted models can drift into near-schema field names such as `operation_type` or `target`.
When a NVIDIA response is parseable but fails local plan validation, the adapter performs at most one
schema-repair request using the original prompt, scene context, invalid answer, validation error, and
the same guided JSON schema. The repaired response must pass the same local validation; otherwise the
request still fails closed.

## Timeouts, Retries, and Failures

Every request has a configurable positive timeout, defaulting to 180 seconds with a 600-second hard
maximum. HTTP `429`, `500`, `502`, `503`, and `504`
responses receive at most two retries by default. Retry delays use exponential backoff with jitter,
honor numeric `Retry-After` values, and cap a server-requested delay at 30 seconds.

Transport exceptions are not retried automatically because the client may not know whether the
server accepted the request. The user can retry explicitly after reviewing the error. Authentication,
non-transient HTTP, incomplete, refused, malformed, and schema-invalid responses fail closed.
Provider request IDs are retained when available to support diagnostics without exposing credentials.

## Token and Cost Controls

The OpenAI adapter parses Responses API input, cached-input, output, reasoning-output, and total
token counts into `TokenUsage`. The NVIDIA adapter parses chat-completions prompt, completion, and
total token counts when available, including any one-shot schema repair call. The coordinator
aggregates both calls when one semantic local-validation repair is needed. Blender accumulates those
totals across clarification rounds and shows the model, token breakdown, and provider-call count in
the Assistant panel.

Token counts are reported instead of estimated currency. Model prices can change and billing tiers
can differ, so current monetary cost belongs in provider billing tools rather than hard-coded UI.
Missing or malformed usage metadata is treated as unavailable and never blocks a valid plan.

Current request-side limits are:

- Prompt fields: 4,096 characters per user entry.
- Serialized scene context: configurable, 100,000 characters by default.
- Detailed context objects: configurable, 25 by default.
- Output: configurable, 4,096 tokens by default.
- NVIDIA schema repair: at most one additional provider call.
- Semantic repair: at most one additional provider call.
- Transient HTTP retries: at most two additional transport attempts by default.

The operations-per-plan, targets-per-operation, and duplicate-output values are user-reducible. The
coordinator generates the provider schema from the captured values, includes an explicit limit
summary in the prompt, and repeats validation locally with the same immutable limit set.

Cached-input and reasoning-output tokens are subsets of input and output tokens respectively; they
must not be added again when calculating the displayed total.

## Threading and Cancellation

Provider work runs outside Blender's main thread. Scene reads happen before dispatch, and result
validation that touches live Blender data plus all UI updates happen on the main thread. Cancellation
invalidates the planning generation and suppresses stale results, but `requests` cannot interrupt an
HTTP call already in progress; the timeout is the hard bound for that call.

## Configuration and Credentials

API-key resolution order is the selected provider's operating-system key, the source-development
`.env` file, then Blender's masked session-only preference. OpenAI uses `OPENAI_API_KEY`; NVIDIA uses
`NVIDIA_API_KEY`. `.env` is plaintext, ignored by Git, and excluded from the extension package. It
may still be synchronized by OneDrive, so an operating-system secret or dedicated secret manager is
preferable for long-lived keys.

## Deferred Work

- Streaming output and partial-plan presentation.
- Local-model adapters and capability negotiation.
- Idempotency strategy for retrying ambiguous transport failures.
- Persistent usage history or budget enforcement across Blender sessions.
- Usage recovery from responses that fail before a provider plan can be returned.
- Currency estimates based on a separately maintained pricing source.
