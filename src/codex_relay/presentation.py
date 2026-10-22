"""Lossless Telegram splitting and compact, host-aware session labels."""

from pathlib import Path

PART_UNITS = 3500


def split_text(text: str, limit: int = PART_UNITS) -> list[str]:
    """Bound UTF-16 units and retain every source character, including newlines."""
    if not text:
        return []
    result: list[str] = []
    current: list[str] = []
    used = 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if used + units > limit:
            result.append("".join(current))
            current, used = [], 0
        current.append(char)
        used += units
    if current:
        result.append("".join(current))
    return result


def label(session: dict) -> str:
    icon = {"working": "🟢", "waiting": "🟡", "interrupted": "🟠", "failed": "🔴"}.get(
        session["status"], "⚪"
    )
    return f"{icon} {session['name'][:45]} · {Path(session['cwd']).name or '/'}"


def event_text(event: dict, session: dict | None, host: str) -> str:
    payload = event["payload"]
    name = session["name"] if session else "Codex Relay"
    heading = f"💬 {name} · {host}\n\n"
    if event["kind"] == "message":
        return heading + payload.get("text", "")
    if event["kind"] == "error":
        return heading + "⚠️ " + payload.get("text", "Unknown error")
    if event["kind"] == "completed":
        status = payload["status"]
        error = payload.get("error")
        text = payload.get("text") or (error.get("message") if isinstance(error, dict) else "")
        return (
            heading
            + {"completed": "✓ Completed", "interrupted": "⏹ Interrupted", "failed": "⚠️ Failed"}.get(
                status, status
            )
            + (f"\n{text}" if text else "")
        )
    return heading
