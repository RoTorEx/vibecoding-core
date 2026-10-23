# Vibecoding Core

## Purpose and ownership

The host service of Remote Vibecoding owns agent sessions, native execution,
history, project/location registration and a versioned Unix-socket JSON API.
Telegram interaction is owned by the sibling telegram-vibecoding repository.

The accepted deployment is one Compose project with exactly two containers.
Core launches native Codex on the execution host through the existing SSH
daemon, as alex with the owner's existing sudo rights. The SSH executor is a
short-lived entrypoint, not another permanent service. Each future execution
host owns its state; live cross-host session migration is deferred.

## Native execution contract

Text/images pass directly to Codex, with no extra LLM, rewriting, translation
or custom execution approval layer. Native delegation is disabled. User
questions remain distinct from command execution approvals. Supported native
model/effort settings and Default/Plan collaboration modes apply to the next
turn. Steering appends input to the active turn. Stop interrupts; Close stops
and archives without deleting files. Multiple sessions share project files.

The host account, home directory and source paths retain their host semantics
inside the containerized control plane. Native commands execute on the host,
not in the Core container. No Docker socket, privileged container or host PID
namespace is needed for that access.

## State and recovery

Core owns engine.db and native host threads. The frontend owns bot.db.
Stable request IDs deduplicate accepted input. Unknown RPC outcomes are never
blindly replayed. Bot restart must preserve active native execution. Core restart
can interrupt work and must preserve thread identity, history and source files.

Backups use online SQLite snapshots, preserve private configuration, native
history/auth and registered Git source changes, and exclude rebuildable caches.
An explicitly registered Remote Vibecoding workspace includes both child Git
repositories. Home is never recursively backed up as a generic project.
Existing offsite backup credentials/retention remain unchanged; the owner
explicitly declined Google OAuth credential changes after the earlier exposure.

## Boundaries and verification

The native protocol baseline is Codex 0.163.0 plus its matching code-mode host.
Source and host path validation, request/lifecycle ordering, migration, backup
integrity, container-to-host execution, Stop and independent bot updates require
meaningful checks. No subagents. Voice and additional hosts remain deferred.

## Independent versioning

This component owns its semantic version, changelog, release commit and annotated
vMAJOR.MINOR.PATCH tag. The sibling version and deployment revision do not change
when this repository is released. API protocol compatibility is separate from
product versions. Follow the local Kernel release contract through make release
and make release-push. Source package version, built metadata, CLI and runtime
version reports must agree.
