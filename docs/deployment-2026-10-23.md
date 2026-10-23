# Remote Vibecoding deployment verification

Verified personally on 2026-10-23. Workspace paths:

- Mac: /Users/alex/Documents/WorkSpace/Development/personal/apps/remote-vibecoding
- VPS: /home/alex/Development/personal/apps/remote-vibecoding

Each contains independent telegram-vibecoding and vibecoding-core Git roots.
Common entrypoints link to Core-owned files; there is no third Git repository.
Private GitHub repositories are RoTorEx/telegram-vibecoding and
RoTorEx/vibecoding-core. Core retains the original history. VPS repository-scoped
SSH credentials work; no broad GitHub account token was copied to the VPS.

## Running deployment

One Compose project, remote-vibecoding, runs exactly two healthy containers.
Core image revision: d834493b6ac6ef44ef670481e76e321490deee96.
Telegram image revision: 92a8d4c30e1d3a6bd2e4831069e048de67c8c0b6.
Later documentation commits do not change these running image revisions.
Legacy application units and snapshot timer are inactive/disabled. The new
remote-vibecoding-snapshot.timer is active/enabled; this maintenance job is not
a third application service. No public application ports are published.

Telegram getMe confirms ID 8579559552, @GardenSandbox_bot and display name
Telegram Vibecoding. getMyCommands confirms Start/Menu open Main Deck and Stop
stops the selected task. Existing panel message 169 and UI version 2 survived.
Phone-side usability acceptance remains outstanding.

## Reconciliation and runtime evidence

Before cutover: 2 locations, 7 sessions, 10 requests, 39 events, 0 questions.
Every original row was compared after activation, including native thread IDs,
request payloads/results and events. Only the old source location's name/path
and matching session cwd fields changed. Other identities, timestamps, archives
and queues were preserved. Both SQLite databases passed integrity_check.

State remains at ~/.local/state/codex-relay to preserve attachment paths and the
existing offsite backup selection. The old source path links to the workspace.
These private compatibility paths are not product/menu names.

- Mac and VPS checks passed: 21 Core tests, 24 frontend tests, Ruff, types and CLI
  entrypoints. Production imports and runtime dependencies are independent.
- The Core image inspected a host directory and initialized host Codex 0.163.0
  through dedicated forced-command SSH with strict host verification.
  account/read returned a ChatGPT account; model/list returned seven models.
  requiresOpenaiAuth=true describes provider authentication requirements; it
  does not by itself mean the account is logged out.
- A native shell verified id -un is alex, ran sudo -n true successfully and wrote
  a host proof file owned by UID 1002.
- Replacing only bot during a native shell wait changed bot identity, preserved
  Core identity and retained the native turn/thread. Readiness required the new
  container's per-boot nonce. Native turn/steer accepted follow-up input.
- A scheduled immutable Core updater drained intake without stopping work.
  Stop interrupted the native turn; the updater replaced Core, released drain
  and preserved the native thread. The same thread resumed after replacement.
- A new solid orange PNG was identified as Orange. A prior green/magenta split
  PNG returned both correct colors with left/right reversed. This native visual
  interpretation error is retained as a limitation; attachment transport tests
  do not establish universal visual accuracy.
- The existing QA session was archived again. Four acceptance requests and ten
  events were added, leaving 7 sessions, 14 requests and 49 events. No user
  session was created, deleted or repurposed.

One idle sample measured approximately 30 MiB Core and 162 MiB bot memory.
The VPS retained about 5.6 GiB disk free after builds. These are samples, not
performance guarantees. Unrelated services/images/caches were not pruned.

## Recovery and retained fallback

Pre-cutover and new snapshots passed checksum, safe extraction and SQLite
integrity checks. The new approximately 1 MiB archive contains both complete Git
repositories, native auth/history, uploads, component configuration and executor
credentials. Restored Git objects passed git fsck. No live data was overwritten.

The offsite registration still selects snapshots/latest.tar.gz and its checksum
under the existing codex-relay backup identity. Automatic approval review
rejected manual upload of the new private payload pending explicit owner
permission for Google Drive backups/vps/codex-relay. Local recovery is verified;
new offsite upload/recovery is not. Existing schedules and stored archives were
not changed. The owner declined Google OAuth credential rotation.

Retain ~/.local/share/remote-vibecoding/migration-legacy/ as a private rollback
bundle until phone acceptance and a verified independent replacement recovery
copy: old source checkout, archive/checksum, stopped-writer DB copies, units and
reconciliation evidence. This migration owns the bundle; remove it only after
those conditions and an explicit retention decision. Legacy installed releases
and config remain available. Temporary extracted restore trees and the host
proof scratch file were removed after verification.

Application rollback: make stop in the new workspace, then enable/start
codex-relay-engine.service and codex-relay-bot.service. Disable the replacement
snapshot timer before enabling the old one. Never run both generations against
the same databases. This fallback retains migrated paths and new history; do not
replace live databases with old copies. Point-in-time data restore is a separate
explicit recovery decision.

For staged reconstruction, restore the two repositories under the manifest
location ID and run the restored Core's scripts/link_workspace.py on their parent.
It recreates common entrypoints from versioned files. Reconcile private paths,
host identity, UID/GID, executor authorization and known_hosts before activation
on a different host.
