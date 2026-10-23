# Remote Vibecoding migration

## Accepted outcome

One workspace at Development/personal/apps/remote-vibecoding, containing two
independent private Git repositories: telegram-vibecoding and vibecoding-core.
One Docker Compose project runs exactly two application containers: bot and core.
Use the existing apps category; do not create or rename Products or move Docket.

Preserve the working Telegram UI, native session identities/history, text/images,
steering/Stop, model/reasoning/Plan configuration, separate bot updates, native
self-update and recovery. Keep full native developer access as VPS alex,
including existing sudo. No extra LLM or rewritten prompts. No subagents.
The owner declined Google OAuth changes. Voice and additional hosts stay deferred.

## Execution queue

1. Split frontend and Core source ownership without rewriting existing history.
2. Move both local checkouts under the shared apps workspace and publish the
   corresponding private GitHub repositories.
3. Version common Compose/workspace operations in the Core repository, with
   workspace entrypoints pointing to that owner; do not create a third Git repo.
4. Containerize bot and Core. Launch native Codex on the host through the existing
   SSH daemon so containerization preserves full developer access.
5. Prepare and verify images, secrets/configuration, protocol, backups and rollback
   before the live cutover.
6. Move the VPS source workspace with compatibility paths and preserve existing private state paths, preserve identities and
   queues, then replace the old application units with the two Compose containers.
7. Verify real native execution, images, steering/Stop, UI continuity, bot-only
   update/restart and offsite recovery boundaries. Reconcile pre/post state.
8. Document observed deployment, remove task scratch and leave checkouts pushed.

## Remaining human acceptance

The owner's phone-side usability check remains open after the prior confusing UI.
Docker layout is resolved: one Compose project, two containers.


## Current checkpoint

- Local workspace and two Git roots exist under personal/apps/remote-vibecoding.
- Core repository was renamed on GitHub without rewriting its existing history.
- Telegram repository foundation is published; application import is not committed yet.
- Runtime packages and dependencies are split. Core checks: 21 tests; frontend
  checks: 24 tests plus lint/types/entrypoints (latest run is pending collection).
- Compose/operator/private host provisioning files are implemented locally.
- VPS still runs legacy systemd Core at 5594278 and the previous working bot.
  No Compose containers, host executor key or live data migration have started.
- Preserve the legacy VPS checkout until all images and host probes are ready.
