# Remaining acceptance

The two-repository, two-container Remote Vibecoding migration is deployed and
verified. See docs/deployment-2026-10-23.md for evidence and rollback boundaries.

- Obtain explicit owner permission for the new private snapshot manual upload to
  the existing Google Drive destination, then verify staged offsite recovery.
  Automatic approval review rejected upload; do not bypass this boundary.
  Local recovery is already verified.
- Obtain phone-side acceptance of the location-first UI. Preserve the private
  legacy rollback bundle until acceptance and replacement recovery verification;
  then agree its retention/removal.

## Active Telegram improvements and local voice

Accepted scope: default Settings styling; no Other location or archive browser;
Config only inside an open session; Back-left/Deck-right footers; ten sessions
per page with paired arrows, completed-response ages (s/m/h/d) and working icons.
These source changes pass focused and full checks and are being released first.

Next, implement local voice transcription inside Core using an offline Whisper
worker with bounded concurrency. Keep text and images; video was explicitly
cancelled. Preserve raw voice input, captured session targets and durable retries.
Verify Russian transcription, a Telegram voice request reaching native Codex,
photo recognition, and measured VPS time/CPU/peak memory. Do not add a third
container or a paid speech API. Additional hosts remain deferred.
