# Remote Vibecoding architecture

One workspace under personal/apps contains a small root Git repository and two
independent component Git repositories. The root owns its versioned AGENTS.md
router, README and ignore rules, with no product version or release process.
Component folders are ignored by the root, not submodules. Compose, common Make
targets and workspace metadata remain versioned in Core and linked at the root.

## Two containers

Telegram Vibecoding owns Telegram polling, numeric-owner/private-chat checks,
captured input, UI state and output refreshes in bot.db. It talks to Core over a
mode-0600 Unix socket on shared host state. Production code imports no Core
implementation. Its container receives only state and its own configuration/token.

Vibecoding Core owns engine.db, stable session/request/event identities, native
thread lifecycle and the versioned JSON API. Its native client invokes SSH to
the existing developer account on the host. A dedicated forced-command SSH key
permits the Codex app-server entrypoint and read-only host directory inspection.
The existing SSH daemon is reused; no third executor daemon/container is added.

Native Codex and code-mode host remain installed on the execution host, preserving
alex's source paths, ChatGPT authentication and sudo rights. Core's container is
not a sandbox for the agent. It has a developer-home bind for source/credentials
and a read-only host-root view for consistent source backups. No privileged
container, Docker socket mount, public Core port or extra LLM is used.

## Durability

SQLite WAL/FULL transactions never cross await. Captured Telegram targets cannot
change during media download or later navigation. Stable request IDs deduplicate
input; unknown native outcomes are never blindly replayed. Native events remain
host-owned. Output edits the current panel and cannot retarget another session.

Restart/update of the bot container preserves Core/native work, UI, inbox and
outbox. A per-boot nonce prevents a previous container's ready PID from satisfying
the replacement bot's healthcheck. Core/SSH/native restart can interrupt work but
preserves conversation identity and files; arbitrary half-executed commands do not
transparently resume.

## Operations

Common host-side operations use one explicit Compose project and commit-tagged
images. Bot updates use --no-deps and verify Core container identity. Failed
activation restores the prior image. Native self-updates of Core schedule an
immutable external operator task, drain new input, wait for current work and
then replace only Core. Rebuilding a source tree is not itself deployment proof.

Existing private state paths remain stable for the migration. The source checkout
moves into the apps workspace; only matching project/session directory metadata
changes, and the prior source path remains compatible. Legacy releases/config and
a pre-cutover snapshot remain recoverable. No data is restored over a live writer.
