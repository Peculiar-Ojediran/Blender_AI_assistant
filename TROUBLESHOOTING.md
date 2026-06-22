# Troubleshooting

## Extension Will Not Install

Confirm that the selected file is the unextracted `blender_ai_assistant-0.1.4.zip` and that Blender is
5.1.x. Older Blender versions are rejected by the manifest. If Blender reports invalid metadata,
download or rebuild the archive rather than editing its contents.

## OpenAI Setup Required

The extension could not resolve an API key. Set `OPENAI_API_KEY` in the operating-system environment
and restart Blender, or enter a key in the masked session field under the extension preferences. A
project `.env` is only intended for running this source checkout.

## Authentication Error

Check that the key is an OpenAI API key, has not been revoked, and belongs to an account or project
with API access. ChatGPT subscriptions and API billing are separate. Replace exposed keys immediately.

## Selected Model Is Unavailable

Choose GPT-5 Nano, which remains the verified default, or confirm that the API project can access the
selected model. A Custom selection requires an exact non-empty Responses API model name. Model
availability can differ by account, project, and processing region.

## Rate Limit or Server Error

HTTP 429 and transient 5xx responses receive a bounded retry. If the final attempt fails, wait and
retry manually. The UI can include an OpenAI request ID in technical details; retain that ID when
investigating provider issues, but never share the API key.

## Timeout or Network Error

The UI now distinguishes request timeout, TLS, and connection failures. The default timeout is 180
seconds because complex structured plans can take longer than 60 seconds, especially with GPT-5.5
and high operation/output limits. If a request still times out, increase `Request Timeout` up to 600
seconds or use a faster Nano model. For connection errors, verify internet access, proxy/firewall and
DNS rules, Blender's network permission for the extension, and access to `api.openai.com`. Transport
failures with no HTTP response are not retried automatically because the server may already have
accepted a billable request.

## Invalid or Incomplete Plan

Shorten the request, reduce context scope, or raise the output-token limit within a reasonable budget.
The extension rejects malformed, incomplete, stale, unknown-target, and schema-invalid plans rather
than applying partial guesses. One semantic repair call may occur automatically.

## Request Exceeds Plan Limits

Expand `Plan Limits` in the AI Assistant or open the extension preferences. Increase the selected
value only as far as needed. Defaults are 20 operations per plan, 100 existing targets per operation,
and 100 total duplicate outputs. The selectable hard maxima are 100 operations, 500 targets, and
1,000 duplicate outputs. Duplicate output equals the number of targets multiplied by the requested
copy count. Plans affecting more than 25 objects require Global Undo, a recovery point, and a second
confirmation.

## Plan Became Stale

The scene changed after planning. Reject the plan and submit it again so the extension captures a new
snapshot. Renaming, replacing, deleting, or modifying a target can invalidate approval.

## Apply Is Blocked

Return Blender to Object Mode. Destructive plans also require `Edit > Preferences > System > Global
Undo` and a successful pre-plan recovery point. High-risk plans require the separate
`Apply High-Risk Plan` confirmation.

## Undo Did Not Restore the Expected State

Stop editing and save a copy of the current file. Use Blender's Undo History to locate the
`Before AI Assistant Plan` recovery point. Foreground Ctrl-Z behavior depends on Blender editor
context and is part of the manual release checklist in `TEST_MATRIX.md`.

## Developer Verification Fails

Recreate `.venv` from Blender 5.1's bundled Python, install `requirements-lock.txt`, regenerate the
fixtures, then run `scripts/run_release_checks.ps1`. Do not reuse a virtual environment or build tree
created for a different Blender/Python installation.
