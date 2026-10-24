# Core API contract v1

Transport: private HTTP/JSON over the configured Unix socket. The frontend and
Core share this contract, not implementation imports or a third package.

- GET /health: readiness, revision, host_id, accepting, busy, pending_requests.
- GET/POST /projects: registered host directories with stable id/name/path.
- GET/POST /sessions: scoped native session metadata; cwd is a host directory.
- POST /messages: stable request_id, session_id, original text and local image
  host paths, plus optional audio (one local recording path). Reuse requires identical target/payload. HTTP 503 means input is
  retained for retry; unknown execution outcomes must not be blindly replayed.
- GET /sessions/{id}, /conversation, /details, /history and /questions: metadata,
  complete exchange cursors, timestamps/storage, recent export and pending native
  user questions. Directory resolution/storage refer to the host, not image paths.
- POST /sessions/{id}/stop, /archive, /reopen, /rename, /settings: native lifecycle
  and next-turn model/effort/default-plan configuration. Archive preserves files.
- POST /questions/{id}: original user answers to the native request.
- GET /events?after=cursor and /live: durable events and replaceable live previews.
- POST /drain: maintenance intake boundary; does not interrupt current work.

Session/thread/request identities, payload fields, event kinds, cursor ordering,
native modes and recovery semantics are preserved from the prior working MVP.
Changes affecting both components require coordinated compatible commits and
integration checks before deployment.

Progress fields are additive within protocol v1. Live entries include started
(epoch seconds) and summaries (item ID to section index/text map). Completed
public summaries are reasoning_summary events with item_id, text and parts;
conversation/history include them in chronological order. Raw reasoning is not
an application event. Agent text deltas and tool events remain separate from
public summaries; clients must not display them as reasoning. Native protocol
reference: https://learn.chatgpt.com/docs/app-server#item-deltas.

GET /sessions also returns nullable last_response for compact response ages.
It is derived from completed message events, excluding commentary.

Voice support is additive in v1: audio defaults to an empty list. Original user
events retain audio paths. A transcription event carries request_id, audio_index,
text, language and measured duration_seconds/wall_seconds/cpu_seconds/peak_rss_mib.
Conversation replies include transcriptions matched to the original request even
if later inputs arrived before recognition finished. Clients display transcripts
as user input. Session status transcribing and live activity Transcribing indicate
local preprocessing; the native agent has not received that voice input yet.

GET /sessions additionally returns nullable last_completed_event, the newest
completed event ID for that session. It is a monotonic terminal-outcome cursor,
including failed/interrupted outcomes, distinct from last_response timestamps.
Clients persist their own viewed cursor and acknowledge only the presented ID.

GET /sessions includes last_interaction (epoch seconds), pending_questions and
pending_requests. Lists, including archived lists, sort by last_interaction
descending with stable ID tie-breaking. Interaction time includes session
metadata changes, captured input, final answers/plans, questions and terminal
outcomes. Public progress and tool output do not advance it. Pending requests
count queued/dispatching inputs; pending questions include native user-input and
MCP elicitation requests. Clients combine these with status, turn_id and /live
activity, and retain unfamiliar statuses instead of claiming they are idle.

GET /limits reads native account/rateLimits/read without running an inference
turn. It preserves rateLimits and rateLimitsByLimitId, adds available and
checked_at (epoch seconds), and caches the result for 60 seconds to avoid
provider reads on every menu animation. Native account/rateLimits/updated
refreshes the cache between reads. Unknown/unsupported/unavailable limits are
available=false, never an inferred unused quota. The endpoint cannot consume
reset credits, buy credits, or change account settings. Schema reference:
https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt.

POST /sessions accepts optional request_id for idempotent creation. Reusing it
returns the original session without changing its name/settings; changing the
captured directory is rejected. Telegram uses this for New callbacks and input
sent from a location's session list before downloads/native execution.

GET/POST /sessions/{id}/attachments lists/registers image originals. POST supplies
an absolute host path, optional name and optional anchor (a user event in this
session; defaults to the latest user event). Only explicit PNG/JPEG/WebP sources
up to 20 MB are accepted. The producer must retain its anchor on retries. Core
copies bytes into private shared uploads and deduplicates by session, anchor and
content. Responses include id, session_id, user_event_id, name, path, mime_type,
size and created; attachment events include attachment_id/name/anchor. The
conversation/history APIs retain these references. GET may filter by ?anchor=ID.
This exports only selected files, not arbitrary tools' output or host images.

POST /maintenance/retention applies the fixed seven-day local interface retention
and returns cutoff (epoch seconds), expired event count and removed file count.
It preserves active/pending/question sessions, native identities and request
identity tombstones. Expired request IDs reject replay explicitly. History and
attachment lists contain retained content only; newer attachments can have a null
user_event_id after their original request expires. The Core runs this check
every 15 minutes; the frontend owns cleanup of bot.db and non-attachment uploads.
Lifetime is measured from saved timestamps, never last access. Native Codex
history and Telegram's server-side messages are outside this contract.
