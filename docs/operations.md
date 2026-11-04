# Remote Vibecoding operations

## Workspace

Use personal/projects/vibecoding/remote-vibecoding with sibling telegram-vibecoding and
vibecoding-core Git checkouts. Run scripts/link_workspace.py from Core to create
the common entrypoint links. Source changes/commits belong to their component.

Python 3.13+ and uv support development. make check at the workspace root runs
both repositories; frontend integration tests use the sibling Core checkout
without making it a production package dependency. Frozen Docker builds install
only their component's runtime dependencies.

## Host prerequisites and private configuration

The initial host is Debian with Docker Compose, the existing alex account and
SSH daemon, git, Python and passwordless sudo. Install official Codex 0.163.0 plus
its matching code-mode host with scripts/install_codex.py if absent. Authenticate
native Codex with the owner's ChatGPT account before migration.

scripts/provision_host.py prepares /srv/remote-vibecoding/config/core and
config/notifier from the private deployment. Existing installations must first
migrate their stopped state; provisioning refuses an empty replacement Core.
The bot token stays in mode-0600 config/notifier/notifier-token. Verify its getMe
identity before cutover and pin bot_username in bot.toml. The notifier owns
data/notifier; runtime_dir points to Core's data/core/run directory. Keep existing shared state and the old token for recovery, without
running the old interactive bot. Separate bot.toml/core.toml define settings. compose.env holds
host paths, UID/GID and selected image revisions; the workspace .env links to it.
Installed operations read config/core/compose.env directly. Only explicit source
builds consult REMOTE_VIBECODING_ROOT; lifecycle/status/snapshots use installed files.
Credential values must not enter Git, images, logs or shell command arguments.

The dedicated executor SSH key is scoped by forced command and the actual
Compose subnet plus loopback. known_hosts comes from the host's public SSH host
key; strict checking stays enabled. Core uses host.docker.internal/host-gateway.
Run directory/account/native execution probes from the Core image before
switching traffic. Do not weaken checking to bypass setup.

## Lifecycle

make build checks and builds commit-tagged images. make up starts the project;
make status/logs/stop operate only this Compose project. Never use a global
Docker prune or restart unrelated services.

make deploy-bot checks/builds that repository and replaces only bot with
--no-deps. The operation verifies Core container identity and requires the
image to report notifications-only through --capabilities before activation
or full workspace startup.
Rollback and automatic failure recovery also reject old interactive images;
a first-cutover failure stops Telegram without restoring executable intake.
Later notification-only revisions retain safe rollback. The bot mounts only its
own state, the read-only Core socket directory, config and notifier token.
No confirmation port is exposed. make rollback rebuilds the recorded previous bot revision from its Git archive
and replaces the single installed image. make deploy-core schedules a durable host task after
building; the task drains/waits for idle and activates Core. Scheduling success
is not activation proof; inspect its unit journal and /health revision.

The bootstrap/migration must stop the old bot poller and old Core writer before
starting their replacements. The shared process locks are retained. Preserve private configuration and
data recovery snapshots; remove obsolete executable copies after cutover
verification.
A rollback stops the two containers before reactivating legacy writers; never
start both implementations over the same SQLite state.

## Backups

The Core CLI creates consistent private snapshots with online SQLite backups,
native history/auth, private application config and registered project sources.
The registered workspace includes its root Git tree, both child repositories and
uncommitted files. Legacy non-Git roots still use workspace.toml to select the
children. Root snapshots omit the absolute .env link; private Compose configuration
is captured under config/. Recreate that link through scripts/provision_host.py
after restoring the private configuration.
Home is never recursively included as a generic workspace. Rebuildable native
and build caches, logs and runtime helper links are excluded.

After migration, run scripts/install_operations.py --root <workspace> as alex
to install the remote-vibecoding CLI and snapshot timer. Disable the legacy
snapshot timer only after its replacement is ready. The CLI, snapshot timer and
scheduled updates use /srv/remote-vibecoding/runtime/core/ops.py,
without per-revision worker directories. Installation removes known legacy worker
copies once no in-flight update needs them. The old snapshot selection
archive identity remains codex-relay; update the offsite registry to the new
data/core/snapshots path during the room migration.

Successful activation prunes obsolete component images through the existing
host-maintenance helper. These repositories are excluded from its automatic
timer because a built Core candidate can wait for idle; only post-activation
scoped cleanup removes their old images. Git owns history, and rollback rebuilds
the requested revision without another persistent checkout.

The hourly host snapshot job calls the Core container; it does not add a third
application container. A held snapshot lock defers the duplicate attempt
successfully and preserves the last complete archive. Existing backup-service registration/retention continues
to select the same snapshot files. The owner declined Google OAuth changes.
Archives contain sensitive bot/native/executor credentials and must stay private.

Recovery verifies checksum, safe extraction, SQLite integrity, native rollouts,
both repositories and config in an independent staging directory. Reconcile host
identity, paths, UID/GID, executor key authorization and known_hosts before
activation. A new image or upload alone does not prove a recoverable system.

Keep an independent phone SSH recovery path. Voice, extra hosts and live session
migration between hosts remain deferred.

## Workspace entrypoint acceptance (24 October 2026)

The public RoTorEx/remote-vibecoding root checkout is installed on the Mac and VPS.
Its AGENTS.md router is version 2026-10-24.1; the root has no product version or
release tags. Root routing loads only the selected component's instructions.
Home and Remote Vibecoding remain registered launch locations with their existing
identities. The installed personal ~/.codex/AGENTS.md was copied unchanged to the
VPS and verified against the local SHA-256; it is outside all project Git trees.

Core 0.1.5 and Telegram Vibecoding 0.1.7 are deployed. Mac/VPS checks passed
(36 Core tests, 47 frontend tests, lint, formatting, types and CLI checks). A private
local snapshot restored the root router, all three Git trees, both component
sources and valid SQLite state using tar's safe data filter. The test archive and
restored private files were removed; no offsite upload was performed.

The frontend's real Telegram SDK refreshed the existing owner panel in place:
its message ID and selected session were unchanged. The API returned bold/code
entities for the retained answer, with no raw bold markers or table separators.
A deleted temporary owner-only message verified bold, italic, strikethrough,
links, inline code and preformatted code. Core was not restarted by that frontend
acceptance check. The final deployment retains exactly two healthy containers.

## GitHub access on the execution host

Native agents run as alex and use that host account's normal Git/SSH and GitHub
CLI configuration. The VPS GitHub identity is RoTorEx. github.com selects
~/.ssh/id_ed25519_github_account, an account authentication key; it is not limited
to one deployment repository. Existing repository-specific aliases remain valid.
GitHub CLI is separately authorized in ~/.config/gh for repositories, workflows
and SSH-key registration. These private files stay outside all source trees.

Use `gh api user --jq .login`, `gh repo list RoTorEx` and the repository's actual
URL rather than guessing names. Telegram Node Radar is the private
RoTorEx/telegram-node-radar repository; /srv/telegram-node-radar is its deployed
runtime, not necessarily a Git source checkout. GitHub's account permissions and
repository rules still apply. Credentials are not a reason to bypass those rules.

New-host recovery requires deliberate GitHub device authorization and registration
of that host's own public key. Never copy a Mac private SSH key or write tokens
into commands, logs, Git remotes or project files. This setup does not register
GitHub credentials for offsite backup or modify the backup producer's credentials.

## Containerized Web and media

Install Web's separately reviewed Compose manifest at runtime/web/compose.yaml.
The stable operator merges it only when installed. With Core media streaming
capability present, `remote-vibecoding --image ghcr.io/strelkov-inc/web-vibecoding:vVERSION deploy-web`
activates only Web, validates release labels and Web's actual Core-backed health,
and checks that Core identity is unchanged. Failure restores the prior Web image
without restoring a database or restarting Core/notifier.

The trusted Unix API exposes GET /sessions/{sid}/media-file?path=ABSOLUTE_PATH for
existing sessions and recognized image/audio files within the current Core host
view, limited to 20 MB. It supports Range requests and does not attach media, add
turns or mutate history. Web validates a requested media key against that session's
conversation/registered attachments before calling this route; its generic public
proxy does not expose the raw file route. Web mounts only its own state/config,
Core's socket directory and upload directory; it receives no host root mount.

Core/notifier stdout/stderr use journald and bounded host exports in logs/runtime.
Capture their prior Docker json-file records before recreating these containers
with the new driver. Retain the original native upload path as one compatibility
alias to the moved physical directory while historical inputs still refer to it.
Slot Sync remains independent and unchanged.
