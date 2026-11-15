import json
import os
import urllib.request


def send_summary(
    completed: list[str],
    updated: list[str] | None = None,
    added: list[str] | None = None,
    remaining: list[str] | None = None,
    next_plan_preview: str = "",
) -> bool:
    """Zero-dependency webhook dispatcher for Discord/Slack/Telegram."""
    url = os.getenv("WEBHOOK_URL", "").strip()
    if not url or "your_webhook_id" in url or "example" in url:
        return False
    lines = ["🚀 **Jarvis Project Lead Sync**"]
    if completed:
        lines.append("✅ **Done:** " + ", ".join(completed))
    if updated:
        lines.append("🛠️ **Progress:** " + ", ".join(updated))
    if added:
        lines.append("➕ **Added:** " + ", ".join(added))
    if remaining is not None:
        lines.append(f"📋 **Open ({len(remaining)}):** " + (", ".join(remaining[:5]) if remaining else "None"))
    if next_plan_preview:
        lines.append(f"📐 **Next:** `{next_plan_preview[:120]}...`")
    body = "\n".join(lines)
    payload = {"text": body} if "slack.com" in url else ({"chat_id": os.getenv("TELEGRAM_CHAT_ID", ""), "text": body} if "telegram.org" in url else {"content": body})
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
