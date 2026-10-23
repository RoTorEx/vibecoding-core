# Deployment evidence

Observed on 2026-10-23 in Europe/Warsaw. These are bounded acceptance results,
not a claim that every native Codex feature or failure mode is supported.

## Initial installed result

- Private bot: [GardenSandbox_bot](https://t.me/GardenSandbox_bot).
- Private source: [RoTorEx/codex-relay](https://github.com/RoTorEx/codex-relay).
- VPS checkout: `/home/alex/Development/personal/bots/codex-relay`.
- Bot revision: `1cc06e9f58320f5a61bb9f6bf0bdc79c9545428a`.
- Engine revision: `35adb85bbda1d1e825aebde562b7749c431b57bf`.
- Separate enabled system services: `codex-relay-bot`, `codex-relay-engine`.
- Native runtime: official Codex 0.163.0 and matching code-mode host, with
  verified release SHA-256 digests. Personal ChatGPT authentication works.
- The bot token was checked with getMe, copied through SSH stdin into a private
  file and restricted to its configured owner. No webhook or competing poller
  was observed. Credentials are outside the repository.

The bot intentionally remains on its separately verified revision. The later
engine changes affect backup filtering. Documentation commits after these
revisions do not change installed application code.

## Verification

| Boundary | Observed result |
| --- | --- |
| Required checks | `make check`: 26 tests, Ruff, formatting, mypy and CLI help passed on macOS and Debian |
| Backup integration | Existing backup-service suite: 32 tests passed locally and on the VPS; registry read back after installation |
| Native execution | Real Codex wrote a known file through its native execution tool; the operator read it back |
| Concurrent sessions | Two independent threads completed in different directories; follow-up input steered the active first thread |
| Bot restart | Engine PID stayed unchanged and active work completed; persisted output reached Telegram |
| Stop | Native turn became interrupted; a delayed file write after the interruption did not occur |
| Images | Real native vision identified the left red/right blue halves of a generated test PNG |
| Bot self-update | Codex ran `make deploy-bot` from its own project conversation; bot PID changed, engine PID did not, and the same turn delivered its final response |
| Rollback | Previous bot revision restored and then switched back; engine PID stayed unchanged |
| Engine self-update | Codex scheduled `make deploy-engine`; the updater waited for its turn, activated the new engine, and the same native conversation recalled that command in a follow-up turn |
| Telegram routing | Automated tests exercised actual aiogram-dialog callbacks, persisted FSM, owner checks, albums and retries; Telegram accepted real outbound messages |
| Durable queues | Final readback found no pending outbox entries and no failed or uncertain acceptance requests |

The initial standalone CLI could answer text but could not spawn its execution
host. Installing the matching official companion resolved the failure; actual
file execution was repeated successfully. A model catalog alone was not treated
as proof of working execution.

## Offsite recovery

The existing personal backup-service now includes the relay's private consistent
snapshot and checksum. Its existing account, retention and upload workflow were
preserved. The hourly idle snapshot timer is enabled. Busy work defers a new
snapshot and preserves the previous copy.

Final verified offsite run: `20261022T232024Z-b437a5960879`.
Drive file ID: `1DC8an-lMdEO3enLUl8_vITeufSnmtcKI`.
Outer archive SHA-256:
`343a3a1c049551ae7b6b9856abb9ecffe0f3bae711c3d8cb5c149ae7d30316d9`.

The archive was downloaded from Drive through the supported restore command,
not merely read from the upload's local cache. Its nested snapshot checksum was
checked and extraction used Python's safe data filter into a new private staging
directory. All seven restored SQLite databases passed quick_check: relay bot
and engine databases, and native thread history, state, queue, goals and memories.
Eight active-or-archived native rollout files parsed as JSONL. Native auth,
the private bot token, project registration and project sources were present.
No credentials were printed. Live data was never replaced.

Recovery exposed native temporary absolute helper links; they are now excluded
with a regression test. Download/plugin caches and operational logs are also
excluded without deleting live vendor resources. The final snapshot was 769,927
bytes versus the initial 36,948,911-byte copy. Both task-owned restore staging
directories were removed after verification. Activating a replacement VPS and
an unattended whole-host disaster recovery remain untested.

## Remaining owner steps and limits

Phone acceptance remains open: the owner tried the original navigation and could
not understand the path. Automated routing tests do not establish usability.
The replacement path is Main Deck → Location → a numbered directory → a session.

The prepared VPS key is now a verified read/write repository deploy key, ID
167418103, named `codex-relay / personal-vps / alex`. SSH identified the intended
repository; normal alex fetch, safe pull and push dry-run succeeded without root
transport. It grants this repository's Git operations, not account-wide access
or GitHub API authentication. Other private repositories need separate access.

The earlier audit output contained client_id, client_secret and refresh_token
from the existing personal-backups Drive OAuth file. The owner explicitly
declined changes after being informed; no replacement, revocation or Google
reauthorization is pending in this task. Credential values are not repeated.

## Location-first UI source verification

The revised source passes 40 tests, Ruff, formatting, mypy and CLI checks.
Actual aiogram-dialog callbacks exercise primary Settings, numbered Location
pages, directory-scoped session/archive lists, a paired Deck/Back footer,
Config reasoning cycles and native Plan controls, model selection, Details,
rename/cancel and session closure/reopening. Repeated /start and /menu reuse
the current panel. Tests also cover long Unicode replies without lost text,
history beyond 200 events, native questions and retained answers, bot restart,
failed Telegram edit retry, additive database migration and UI-schema rollback
without dropping captured input or delivery state. Installed revision/readback
evidence for this UI is recorded after deployment below.

Prepare independent phone SSH access before departure. The shared VPS has two
vCPUs and 3.7 GiB RAM; the final resource sample had about 1.6 GiB available RAM
and 7.2 GB disk free. Heavy builds compete with existing services. Full alex/sudo
access and shared project directories are intentional; the bot adds no isolation
or conflict resolution between agents editing the same file. Voice and other
hosts remain deferred. See [operations](operations.md) for recovery commands.
