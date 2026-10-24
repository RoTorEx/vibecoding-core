# Vibecoding Core

## Purpose and ownership

The host service of Remote Vibecoding owns agent sessions, native execution,
history, project/location registration and a versioned Unix-socket JSON API.
Telegram interaction is owned by the sibling telegram-vibecoding repository.

The accepted deployment is one Compose project with exactly two containers.
Core launches native Codex on the execution host through the existing SSH
daemon, as alex with the owner's existing sudo rights. The SSH executor is a
short-lived entrypoint, not another permanent service. Each future execution
host owns its state; live cross-host session migration is deferred.

## Native execution contract

Text/images pass directly to Codex, with no extra LLM, rewriting, translation
or custom execution approval layer. Native delegation is disabled. User
questions remain distinct from command execution approvals. Supported native
model/effort settings and Default/Plan collaboration modes apply to the next
turn. Steering appends input to the active turn. Stop interrupts; Close stops
and archives without deleting files. Multiple sessions share project files.

The host account, home directory and source paths retain their host semantics
inside the containerized control plane. Host GitHub access uses the normal alex
account SSH key and authenticated gh CLI, without a Core repository allowlist.
Native commands execute on the host,
not in the Core container. No Docker socket, privileged container or host PID
namespace is needed for that access.

## State and recovery

Core owns engine.db and native host threads. The frontend owns bot.db.
Stable request IDs deduplicate accepted input. Unknown RPC outcomes are never
blindly replayed. Bot restart must preserve active native execution. Core restart
can interrupt work and must preserve thread identity, history and source files.

Backups use online SQLite snapshots, preserve private configuration, native
history/auth and registered Git source changes, and exclude rebuildable caches.
An explicitly registered Remote Vibecoding workspace includes its root router
Git repository and both independent component repositories. The root owns routing
and has no product release version. Core retains shared Compose/Make ownership. Home is never recursively backed up as a generic project.
Existing offsite backup credentials/retention remain unchanged; the owner
explicitly declined Google OAuth credential changes after the earlier exposure.

## Boundaries and verification

The native protocol baseline is Codex 0.163.0 plus its matching code-mode host.
Source and host path validation, request/lifecycle ordering, migration, backup
integrity, container-to-host execution, Stop and independent bot updates require
meaningful checks. No subagents. Additional hosts remain deferred.

## Independent versioning

This component owns its semantic version, changelog, release commit and annotated
vMAJOR.MINOR.PATCH tag. The sibling version and deployment revision do not change
when this repository is released. API protocol compatibility is separate from
product versions. Follow the local Kernel release contract through make release
and make release-push. Source package version, built metadata, CLI and runtime
version reports must agree.

## Installed copies

Keep one installed image per component and one host operations script in the
reviewed source checkout. Never cache operations code by commit directory.
Verified activation retires obsolete images; recorded revision strings are
source identities, not retained executable copies. Rollback rebuilds the chosen
Git revision. A staged Core candidate is protected until the idle activation
finishes; automatic host image cleanup must not remove that pending candidate.

## Public progress

Request native reasoning summaries with summary=auto. Only public summary
notifications and the completed reasoning item's summary field enter the Core
progress API and durable conversation history. Never consume raw reasoning text
or the reasoning item's content field. Retain summary section order and preserve
completed summaries across restarts. Publish a started timestamp while connecting
and executing so the UI can show elapsed time without inventing an ETA.

## Session activity timestamps

Session lists include last_response, the timestamp of the last completed agent
answer or plan. Commentary, public summaries, renames and settings changes do
not make an old answer appear new. No schema or identity migration is needed.

## Local voice

Accept text, supported images and voice recordings; video is explicitly out of
scope. Core recognizes voice locally with pinned multilingual Whisper base,
CPU INT8, one thread and one worker at a time. Recognition uses no paid API or
additional LLM. The exact transcript then becomes native Codex user text and is
visible in the conversation; provider processing of that text follows normal
agent behavior. Original typed input and recordings remain unchanged.

Recordings are limited to 20 MB (Telegram cloud download ceiling) and five minutes
(to bound decoded memory and keep mobile interactions practical on the two-core
VPS). A worker times out after ten minutes, giving slow recognition headroom
without retaining a stuck process indefinitely. The decoder enforces duration
independently of Telegram metadata. Stop cancels and reaps preprocessing and
queued input; shutdown retains locally replayable queued work. Each successful
transcript is durably cached by request identity before any native dispatch.
Unknown native outcomes retain the existing no-replay rule. Decode/recognition
failure never invokes the agent. Model memory is released when its process exits.

Raw recordings stay in private uploads and normal state snapshots; rebuildable
model weights stay in the private host cache and are excluded from snapshots.
Use scripts/install_speech_model.py to install the pinned model. Runtime model
loading is offline. Transcription events record recording duration, elapsed time,
CPU seconds and process peak RSS for load assessment. Tests cover captured input,
cache/retry, parallel text work, failure, cancellation and restart boundaries.

## Completed-result visibility

Session lists expose last_completed_event, the latest terminal event ID, for the
frontend's unread-results journal. This includes failed/interrupted turns so the
owner can inspect their outcome. Native session metadata edits never advance it.
Core does not infer Telegram read receipts; the frontend owns explicit viewing
cursors. Closed sessions stay retained and leave the active-results journal.

## Session overview contract

All active and archived session lists sort by latest interaction, newest first,
with stable ID tie-breaking. last_interaction includes metadata changes, captured
input (including steering and question answers), final answers/plans, questions
and terminal outcomes; tool output and public progress do not reorder the list.
The additive pending_requests and pending_questions counts expose queued input
and unresolved user-input/MCP requests without inferring them from turn IDs.
No session identity or schema migration is required.

A session remains waiting while any native user-input or MCP elicitation request
is pending. Server resolution notifications identify questions by RPC request ID
without requiring threadId. Resolving one of several questions does not return
the session to Working prematurely.
