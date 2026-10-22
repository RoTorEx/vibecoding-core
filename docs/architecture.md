# Architecture

One repository builds two services. Bot polls Telegram and owns bot.db. Engine
listens on a mode-0600 Unix socket, owns engine.db, and supervises one private
Codex app-server child over stdio. Neither service opens a public listener.
Engine session identifiers are independent of Telegram, Codex thread IDs, and
project names. A host_id accompanies presentation and future host routing.

## Native conversation boundary

thread/start and thread/resume use never approvals and danger-full-access as
explicitly requested. No baseInstructions or developerInstructions are supplied.
Codex reads its native personal/project instructions. Native agent delegation
is disabled. turn/start receives original text and localImage inputs; turn/steer
receives subsequent messages while a turn is active. UI controls use protocol
actions instead of injecting bot control instructions into the conversation.
Questions from Codex remain distinct from execution permission policy.

## Persistence and ordering

SQLite uses WAL, FULL synchronous commits, foreign keys and a busy timeout.
Transactions never contain await. Telegram updates enter the inbox and advance
the durable offset in one transaction, before the next getUpdates request.
Unauthorized input only advances the cursor. Capture binds message input to
its session and navigation mode; later selection changes cannot retarget it.
An album inherits its first message's binding and collects a one-second quiet
window. Text/image requests receive a stable Telegram update-based request ID.

Engine records each request before acknowledging acceptance. Requests move from
queued to dispatching to accepted, failed or uncertain. Duplicate request IDs
must have identical session and payload. queued work may resume; dispatching
work becomes uncertain on restart and is never automatically repeated. Native
RPC notifications own active turn state, including a completion that arrives
before its turn/start response. Per-session locks order sends and lifecycle
changes without serializing independent conversations.

Native completed agent messages and terminal states are durable events. Bot
imports them into an outbox and advances its event cursor transactionally.
Telegram sends are at least once: a lost successful send response can produce
a duplicate display message on retry. This never resubmits the agent command.
Transient streaming previews are replaceable and bounded; final text is split
losslessly below Telegram limits. Operational logs exclude message payloads,
credentials, token-bearing URLs and native stderr.

## Restart and update boundaries

Bot restart preserves the engine, active turns, inbox, outbox, selected session
and dialog state. Engine or Codex restart can interrupt a turn, but retains
native history and project files. Agent tasks cannot transparently resume an
arbitrary half-executed external operation. Unknown requests require inspection.
An advisory host lock prevents two engines or two local bot processes from
owning one runtime directory. Telegram conflicts with a different host fail
rather than continuously fighting another poller.

Installed code lives in independent bot and engine release links. A bot-only
update cannot switch the engine link or restart its service. Engine updates
run in an external systemd task, drain new input, and wait for idle turns before
restarting. The deployment lock serializes updates and rollback. Data and
credentials remain outside releases. Versioned code is copied from a clean,
checked commit; dirty development sources are never installed implicitly.

## Security and limitations

The only Telegram operator is a numeric allowlisted user in their private chat.
Bot callbacks, archived-session controls, questions and media share that check.
The engine socket is accessible only to the developer identity. Full sudo means
an agent can affect production services; the relay does not claim host isolation.
A personal GitHub key can access more than the projects shown in the menu.
No production bot token or deployment key is reused. Voice, other host
transports and live cross-host session migration remain later work.
