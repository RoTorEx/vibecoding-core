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
