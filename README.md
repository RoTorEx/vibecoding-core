# Codex Relay

A private Telegram client for native Codex conversations on your own host.
One chat, named sessions, text and images, immediate steering, and independent
bot/engine services. No added LLM, translated prompts or command approval layer.

## Use

Open the bot and send `/menu`. Continue the last session, choose an existing
one, or create a session in a registered project, Home, or another directory.
Send text or images directly. `/stop` interrupts the selected turn; `/menu`
leaves it running. Actions offers rename, history export, live model/effort
selection, directory changes and archival. Archived sessions retain files and
can be reopened. Multiple conversations in one project share its files.

## Development

Python 3.13+, uv, and official Codex 0.163.0 with its matching code-mode host.

```sh
make install
make check
make engine          # one terminal
make run             # another terminal; requires private bot settings
```

Only run one polling process for a bot token. All Telegram operations require
its configured numeric owner ID in their private chat.

## First Linux installation

1. Clone this private repository into the developer's project directory.
2. Run `python3 scripts/install_codex.py` if the matching CLI/runtime are absent.
   Both official assets are SHA-256 checked. Run `codex login --device-auth`.
3. Create private configuration and a mode-0600 token file as described in
   [operations](docs/operations.md). Check the intended bot with getMe.
4. From a clean, committed checkout, run `python3 scripts/bootstrap_host.py`.
5. Check `codex-relay doctor`, Telegram `/menu`, and a real file-changing task.

The agent has full developer/sudo access by owner choice. This is not an
isolated sandbox for untrusted users or repositories. Preserve independent SSH
access from your phone for recovery.

## Project registration and self-update

```sh
codex-relay project add /home/alex/Development/personal/bots/example --name Example
codex-relay project clone git@github.com:RoTorEx/example.git --name example --category bots
codex-relay session list
make deploy-bot       # checked clean commit; engine stays alive
make deploy-engine    # schedules an independent update after current turns finish
make rollback        # previous bot code; data and engine remain intact
```

Runtime settings: `~/.config/codex-relay/config.toml` and `bot-token`.
Data: `~/.local/state/codex-relay/`. Installed code:
`~/.local/share/codex-relay/releases/<commit>` with independent current links.
No public port, Redis, database server, Docker or model API key is required.

See [product rules](BUSINESS.md), [architecture](docs/architecture.md), and
[operations and recovery](docs/operations.md). The first VPS installation and
its remaining owner checks are recorded in [deployment evidence](docs/verification.md).
Voice and other host transports
are later stages. Native history survives restarts; interrupted commands and
RPCs with unknown outcomes are not blindly replayed. Telegram display delivery
is at least once and can duplicate a response after an ambiguous network failure.
