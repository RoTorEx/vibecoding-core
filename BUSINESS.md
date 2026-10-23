# Codex Relay

## Purpose and actors

Aleksey uses a private Telegram bot to work directly with Codex while travelling.
The first host is his existing personal Debian VPS. The first development
project is Codex Relay itself. Corporate projects are excluded from onboarding.

## Product contract

- One editable Telegram panel follows Main Deck → Location → Session. Main Deck
  has a full-width primary Settings button first, then Location. Every screen
  ends with one paired row: Deck, Back. Back follows the actual navigation path.
- Home means the host developer's home directory and is the default location.
  Location lists put Home first, show names and paths in the message, and use
  numbered 1–10 buttons with pagination. Choosing a location never starts Codex.
- Sessions and their archive are scoped to the selected location. New session
  appears only at that level. Other location registers an existing directory
  without creating a session. No Projects or Actions navigation is exposed.
- A session normally shows a compact title/status and a paged request/response.
  Previous/Next browse exchanges and long text parts in the same panel; Latest
  returns to live output. All retained exchanges remain accessible via cursors.
  Editing the panel does not produce a new Telegram push notification. The
  user's original Telegram messages are preserved rather than silently deleted.
- Config belongs to the selected session: model picker, one-tap reasoning cycle,
  and native Plan mode toggle. It remains accessible from session-related views
  and Settings. The picker shows the latest available Sol and up to two latest
  Astra models from the live catalog, with at most three choices. Config changes
  apply to the next native turn and do not interrupt active work.
- Details shows name, directory, location, machine, creation time, last request,
  response and completion times, and available disk space. Rename and Close live
  here. Clock times are displayed in Europe/Warsaw with their actual UTC offset.
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
- Locations are registered host paths, not hardcoded project buttons;
  registration changes appear without a bot restart. The Engine/CLI still use
  the internal project registry as their supported noninteractive interface.
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
| 3200 UTF-16 units per conversation part | Headroom for header and inline notices below Telegram's 4096 limit | Long-answer paging tests |
| 10 numbered entries per location/session page | Owner's requested compact numeric controls | Location pagination and scope tests |
| At most 3 curated model choices | Owner's requested Sol/Astra picker, limited by actual availability | Catalog selection tests |
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

## Current external access decisions

The VPS alex SSH key is a write-enabled deploy key for RoTorEx/codex-relay,
named `codex-relay / personal-vps / alex`. It permits this repository's Git
operations, not account-wide access or GitHub API authentication. Additional
private repositories require their own approved access. Existing broad personal
credentials are not copied to achieve that.

The owner explicitly chose to retain the existing backup-service Google OAuth
credential after the earlier audit exposure was identified. No rotation,
revocation or Google reauthorization is part of the current task.

## Later stages

Voice and additional hosts follow the accepted roadmap. Each future host owns
its state and credentials; moving a live session between hosts is not included.
No analytics platform, database server, automatic deployment on every commit,
or changes to existing application deployment policies belong to the MVP.
