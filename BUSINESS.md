# Codex Relay

## Purpose and actors

Aleksey uses a private Telegram bot to work directly with Codex while travelling.
The first host is his existing personal Debian VPS. The first development
project is Codex Relay itself. Corporate projects are excluded from onboarding.

## Product contract

- One Telegram chat contains a shallow button menu and named agent sessions.
- Sessions are native Codex threads, owned and retained on their execution host.
- Text and images pass directly to Codex. No additional model, prompt rewriting,
  translation, hidden progress instructions, or custom execution approval layer.
- The agent runs as the host developer with full filesystem/network access and
  existing sudo rights, explicitly requested by the owner. Personal/project
  instructions and provider requirements still apply. Never spawn subagents.
- Messages sent during work immediately steer the active native turn.
- Multiple sessions in a project share its directory; no implicit worktree.
- Navigation never cancels a task. Stop interrupts a turn. Close interrupts and
  archives the conversation without deleting project files. Archived sessions
  can be reopened. Background responses retain their originating session.
- The Home project starts in the developer home directory. Projects are paths,
  not hardcoded buttons; registration changes appear without a bot restart.
- In a menu, ordinary messages never go to a previously selected agent.
- The first request supplies a default session title without a model call.
- Settings use live Codex model and effort catalogs. Native user questions are
  surfaced even though command execution does not need bot approval.
- Only the configured numeric Telegram user ID can interact, in their private
  chat. Authorization also covers callbacks, media, and replayed updates.

## Durability and lifecycle

The bot and host engine are independently managed processes. The engine owns
Codex; restarting or updating the bot must not stop agent turns. Each service
owns a SQLite database. Input is durable before the next Telegram acknowledgement.
A message target is captured before asynchronous media download. Completed
agent messages and terminal outcomes remain deliverable across bot restarts.
An RPC with an unknown outcome is never blindly repeated. A host process crash
can interrupt work; retaining a conversation does not resume an arbitrary
half-executed shell command. Source files are not deleted by session lifecycle.

## Decisions and limits

| Value | Meaning and source | Impact and verification |
| --- | --- | --- |
| One owner, one initial host | Owner's accepted travel MVP | Unauthorized-input and routing tests |
| 20 MB inbound file ceiling | Telegram cloud getFile API | Reject before downloading; media tests |
| 3500 UTF-16 units per output part | Headroom below Telegram's 4096-character limit | Unicode splitting tests |
| 1 second media-group quiet window | Collect Telegram albums without an extra Send action | Album routing tests |
| At least 1 second between outbound operations | Telegram single-chat rate guidance; retry_after takes precedence | Delivery recovery tests |
| 0.163.0 Codex protocol baseline | Installed and schema-checked CLI at implementation | Native VPS smoke check |

## Source map

- config.py: host settings and private credential locations.
- store.py: engine state, bot inbox, delivery, and recovery boundaries.
- codex.py and engine.py: native protocol and execution lifecycle.
- bot.py and dialogs.py: Telegram transport and shallow navigation.
- cli.py and deploy/: project registration, deployment, backup, and rollback.
- docs/architecture.md and docs/operations.md: technical and host contracts.

## Later stages

Voice and additional hosts follow the accepted roadmap. Each future host owns
its state and credentials; moving a live session between hosts is not included.
No analytics platform, database server, automatic deployment on every commit,
or changes to existing application deployment policies belong to the MVP.
