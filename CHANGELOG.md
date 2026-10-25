# Changelog

## [Unreleased]

- Preserve asynchronous agentMessage questions as durable waiting state, with native-item deduplication and verbatim session steering for answers instead of fabricated RPC responses.

## [0.1.9] - 2026-10-24

- Expire local interface history and image originals seven days after saving, while preserving active work, native identities and replay protection. Add an immediate maintenance cleanup API and periodic in-process cleanup.

## [0.1.8] - 2026-10-24

- Make session creation idempotent by captured request identity and directory.
- Register explicitly selected image originals in private request-scoped attachment history for durable Telegram download.

- Expose read-only native Codex account usage limits and reset times, with short caching and explicit unavailable states.

## [0.1.7] - 2026-10-24

- Keep question-waiting status until all native questions resolve, including server resolution notifications without a thread ID.
- Expose latest interaction timestamps, pending input and pending question counts; sort active and archived sessions consistently by latest interaction.

## [0.1.6] - 2026-10-24

- Expose stable terminal-outcome cursors for the frontend unread-results journal.

## [0.1.5] - 2026-10-24

- Support the independent workspace routing repository without overwriting its entrypoints; keep root source snapshots restorable alongside both components.

## [0.1.4] - 2026-10-23

- Recognize voice locally with bounded offline CPU workers, durable transcripts, Stop/restart safety and per-recording load metrics.

## [0.1.3] - 2026-10-23

- Expose the last completed response timestamp in session lists, independently
  of configuration changes and progress updates.

## [0.1.2] - 2026-10-23

- Request native public reasoning summaries, stream their sections and retain
  completed summaries in conversation history without collecting raw reasoning.
- Publish connecting feedback and a stable elapsed-time origin before native
  execution starts, and clear failed initialization feedback.

## [0.1.1] - 2026-10-23

- Use one stable host operations script, remove retired worker copies, rebuild rollbacks from Git and prune obsolete images after activation. Defer a duplicate snapshot without failing the timer.

- Add independent Kernel-compliant interactive release and atomic tag publishing,
  with one canonical package version and matching CLI/build metadata.
- Isolate deployment tests from installed host image-cleanup helpers.

- Split Remote Vibecoding into independent Core and Telegram repositories in one
  workspace and one Compose project with two containers. Preserve native host
  execution through a dedicated forced-command SSH identity, session state and
  independent frontend updates. Add private provisioning and host snapshot jobs.

- Name the two components Telegram Vibecoding and Vibecoding Core. Update bot
  display names, bootstrap labels, native client title and service descriptions;
  add operator service aliases while retaining existing state and identifiers.
- Replace overlapping Projects/Sessions/Actions navigation with a location-first
  Main Deck, numbered pages, scoped sessions and a consistent Deck/Back footer.
- Show requests, streaming responses, questions and paginated history in one
  editable panel. Add inline reasoning/Plan controls, curated model selection,
  session Details and independent UI upgrade/rollback recovery.
- Configure the VPS repository deploy key and refresh Telegram command labels.
- Await background dialog cleanup before propagating failed panel edits to the
  durable retry loop, avoiding unhandled SDK task exceptions.
- Reuse the published panel when rebuilding incompatible navigation, and isolate
  deployment checks from host configuration and live menu state.
- Exclude rebuildable native/plugin caches and operational logs from private
  snapshots while retaining WAL-backed conversation state and source changes.
- Omit native runtime helper links so recovery archives can be safely extracted
  with the standard data filter into an independent directory.
- Verify new bot readiness against its connected process before accepting updates.
- Retain follow-up input when an active turn completes just before native steering.
- Keep partial image downloads out of retry reuse.

- Add direct native Codex sessions with persistent identity, steering, Stop,
  archive/reopen, live model settings and question handling.
- Add private Telegram button navigation, text/image/album input, durable
  routing, restart recovery and background response delivery.
- Add independently deployable bot and host engine, native runtime installer,
  deferred engine updates, bot rollback and consistent private snapshots.
