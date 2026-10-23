# Core API contract v1

Transport: private HTTP/JSON over the configured Unix socket. The frontend and
Core share this contract, not implementation imports or a third package.

- GET /health: readiness, revision, host_id, accepting, busy, pending_requests.
- GET/POST /projects: registered host directories with stable id/name/path.
- GET/POST /sessions: scoped native session metadata; cwd is a host directory.
- POST /messages: stable request_id, session_id, original text and local image
  host paths. Reuse requires identical target/payload. HTTP 503 means input is
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
