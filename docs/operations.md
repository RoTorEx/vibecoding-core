# Remote Vibecoding operations

## Workspace

Use personal/apps/remote-vibecoding with sibling telegram-vibecoding and
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

scripts/provision_host.py prepares ~/.config/remote-vibecoding from the existing
private deployment, preserving credentials. The bot token stays in a mode-0600
file. Separate bot.toml/core.toml define component settings. compose.env holds
host paths, UID/GID and selected image revisions; the workspace .env links to it.
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
--no-deps. The operation verifies Core container identity. make rollback rebuilds the recorded previous bot revision from its Git archive
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
scheduled updates use the single reviewed scripts/ops.py in this checkout,
without per-revision worker directories. Installation removes known legacy worker
copies once no in-flight update needs them. The old snapshot selection
path is intentionally retained for the existing offsite backup service.

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
