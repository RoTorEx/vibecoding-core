# Operations

## Host prerequisites

Linux with Python 3.13+, systemd, git and uv; official Codex 0.163.0 on PATH or
configured by absolute path. Codex runs as the developer, never as root.
The first deployment uses alex on the existing personal VPS. Full sudo is the
owner's accepted choice. No firewall or existing application change is needed.

Install locked development dependencies with `make install`; run `make check`.
The package CLI is `uv run --frozen codex-relay --help` from a checkout.

Private settings live in ~/.config/codex-relay/config.toml; bot-token is a
separate mode-0600 file. Data lives in ~/.local/state/codex-relay. Do not put
credentials, conversation databases or uploads in Git.

Example settings:

```toml
host_id = "vps"
allowed_user_id = 123456789
codex_command = "/home/alex/.local/bin/codex"
development_root = "/home/alex/Development/personal"
```

Authenticate with `~/.local/bin/codex login --device-auth`. Complete the native
flow in the owner's browser; never paste auth.json into chat. Check `codex-relay
doctor` after engine startup. An available model catalog is not proof that an
inference turn can complete. Verify one real native turn before travel.

## Independent services

`scripts/install_host.py` installs separate codex-relay-engine and
codex-relay-bot system units running as the developer. The bot token must be
verified with Telegram getMe before starting polling. The owner initially
selected @GardenSandbox_bot from telegram-assistant's dev configuration.
Never run another poller or local dev process with the same token concurrently.
The existing product bots remain outside this deployment.

Routine commands on the VPS:

```sh
systemctl status codex-relay-engine codex-relay-bot
journalctl -u codex-relay-engine -u codex-relay-bot --since '-10 minutes'
/home/alex/.local/bin/codex-relay doctor
/home/alex/.local/bin/codex-relay project add /home/alex/Development/personal/bots/codex-relay --name 'Codex Relay'
/home/alex/.local/bin/codex-relay project list
/home/alex/.local/bin/codex-relay session list
```

The stable launcher uses the installed engine release for CLI operations and
never imports mutable checkout code. Keep the checkout available to Codex.

## Self-updates

From a clean source checkout, run `make deploy-bot`. It runs checks, stages the
exact commit in a new release/virtual environment, atomically switches only the
bot link, restarts only the bot, verifies service state and preserves the prior
link. A failed deployment restores the previous link. The engine stays running.

`make deploy-engine` starts a separate durable systemd update task. It waits for
active turns and accepted requests to finish while input is temporarily drained.
The submitting agent can finish normally before its engine is restarted.
Inspect the updater unit's journal for the installed outcome. Never treat
scheduling an update as proof that it completed. `make rollback` restores the
previous bot release without touching engine data. No release tag is required
for a checked private commit deployment; public publishing is not configured.

## Recovery without Telegram

Prepare an independent SSH client on the owner's phone before departure. Use
the existing trusted VPS operator key. Do not rely on Telegram for the only
recovery channel. Inspect service logs, restart the bot separately, or run the
rollback command from the source checkout. Do not restart the shared VPS for
verification. A bot restart does not stop work; an engine restart can.

## Backups

`codex-relay backup /private/path/snapshot.tar.gz --include-codex --project-sources`
drains new agent input and waits up to 300 seconds for current turns. It uses
SQLite online backups and archive readback, includes retained uploads and
private settings, and optionally native Codex history/auth plus registered Git
sources including uncommitted files. Build caches are excluded. Home is not
recursively archived merely because it is registered as a launch directory.
The archive and checksum must be stored privately. A busy host defers the backup
without interrupting a turn. Do not copy live database/WAL files blindly.

For recovery, verify the SHA-256, inspect archive paths, extract into a new
private directory and run SQLite quick_check. Do not activate restored data
over a live engine or overwrite current sources. Native credentials, source
paths and Git origins must be reconciled on a different host. A backup run is
not proof of successful off-host recovery; record both separately.

The existing backup-service integration is a separate host registration owned
by that project. Preserve its credential store and established retention.
