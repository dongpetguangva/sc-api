"""Deliver a reminder to Discord and/or Telegram. No LLM anywhere.

Both transports are plain HTTP with a JSON body:
  * Discord  — webhook URL, rich embed in the payload
  * Telegram — bot token + chat id, HTML-formatted text

Credentials come from the environment first, then from
~/.config/sinarcloud/notify.json so a cron job does not need env plumbing:

    {
      "discord_webhook": "https://discord.com/api/webhooks/...",
      "telegram_bot_token": "123:ABC",
      "telegram_chat_id": "123456789"
    }
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.config/sinarcloud/notify.json")
TIMEOUT = 20

# Severity -> colour/marker. Kept small and literal.
_SEVERITY = {
    "critical": ("🚨", 0xE5484D),   # red
    "warning": ("⚠️", 0xF5A524),    # amber
    "info": ("ℹ️", 0x3E63DD),       # blue
}


def load_config(path: str | None = None) -> dict:
    """Read notify.json (if present) and overlay environment variables."""
    resolved = path or CONFIG_PATH
    cfg: dict = {}
    if os.path.exists(resolved):
        try:
            cfg = json.load(open(resolved, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = {}
    # Environment overrides the file, so CI/cron can inject secrets.
    return {
        "discord_webhook": os.environ.get("SINAR_DISCORD_WEBHOOK") or cfg.get("discord_webhook"),
        "telegram_bot_token": os.environ.get("SINAR_TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token"),
        "telegram_chat_id": os.environ.get("SINAR_TELEGRAM_CHAT_ID") or cfg.get("telegram_chat_id"),
    }


def _post(url: str, payload: dict) -> tuple[bool, str]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "sc-api/1.0")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode(errors="replace")
            return 200 <= resp.status < 300, body[:200]
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
    except urllib.error.URLError as exc:
        return False, f"unreachable: {exc.reason}"


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
def build_discord_embed(
    *,
    balance: float,
    currency: str,
    threshold: float,
    runway_days: float | None = None,
    average_daily: float | None = None,
    severity: str = "warning",
    title: str = "SinarCloud balance low",
) -> dict:
    icon, colour = _SEVERITY.get(severity, _SEVERITY["warning"])
    fields = [
        {"name": "Balance", "value": f"**{currency} {balance:,.0f}**", "inline": True},
        {"name": "Threshold", "value": f"{currency} {threshold:,.0f}", "inline": True},
    ]
    if runway_days is not None:
        fields.append({"name": "Runway", "value": f"{runway_days:.1f} days", "inline": True})
    if average_daily:
        fields.append(
            {"name": "Average spend", "value": f"{currency} {average_daily:,.0f}/day", "inline": True}
        )
    return {
        "embeds": [
            {
                "title": f"{icon} {title}",
                "description": "Your SinarCloud credit is below the configured threshold.",
                "color": colour,
                "fields": fields,
                "footer": {"text": "sc-api · read-only monitor"},
                "url": "https://console.sinarcloud.com/billing/top-up",
            }
        ]
    }


def send_discord(webhook_url: str, embed_payload: dict) -> tuple[bool, str]:
    # ?wait=true makes Discord answer with the created message, so a failure is visible.
    url = webhook_url if "wait=" in webhook_url else webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true"
    return _post(url, embed_payload)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def _tg_escape(text: str) -> str:
    """Escape for parse_mode=HTML (only < > & matter)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_telegram_text(
    *,
    balance: float,
    currency: str,
    threshold: float,
    runway_days: float | None = None,
    average_daily: float | None = None,
    severity: str = "warning",
) -> str:
    icon, _ = _SEVERITY.get(severity, _SEVERITY["warning"])
    lines = [
        f"{icon} <b>SinarCloud balance low</b>",
        "",
        f"Balance: <b>{currency} {balance:,.0f}</b>",
        f"Threshold: {currency} {threshold:,.0f}",
    ]
    if runway_days is not None:
        lines.append(f"Runway: {runway_days:.1f} days")
    if average_daily:
        lines.append(f"Average spend: {currency} {average_daily:,.0f}/day")
    lines += ["", '<a href="https://console.sinarcloud.com/billing/top-up">Top up</a>']
    return "\n".join(lines)


def send_telegram(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    base = os.environ.get("SINAR_TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{bot_token}/sendMessage"
    return _post(
        url,
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


# ---------------------------------------------------------------------------
# fan-out
# ---------------------------------------------------------------------------
def notify_all(
    *,
    balance: float,
    currency: str,
    threshold: float,
    runway_days: float | None = None,
    average_daily: float | None = None,
    severity: str = "warning",
    config: dict | None = None,
) -> dict[str, tuple[bool, str]]:
    """Send the same reminder to every configured channel.

    Returns {channel: (ok, detail)}. A channel with no credential is skipped,
    not reported as failure, so a Telegram-only setup does not look broken.
    """
    cfg = config if config is not None else load_config()
    results: dict[str, tuple[bool, str]] = {}

    if cfg.get("discord_webhook"):
        embed = build_discord_embed(
            balance=balance,
            currency=currency,
            threshold=threshold,
            runway_days=runway_days,
            average_daily=average_daily,
            severity=severity,
        )
        results["discord"] = send_discord(cfg["discord_webhook"], embed)
    else:
        results["discord"] = (False, "skipped: no discord_webhook configured")

    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        text = build_telegram_text(
            balance=balance,
            currency=currency,
            threshold=threshold,
            runway_days=runway_days,
            average_daily=average_daily,
            severity=severity,
        )
        results["telegram"] = send_telegram(cfg["telegram_bot_token"], cfg["telegram_chat_id"], text)
    else:
        results["telegram"] = (False, "skipped: no telegram_bot_token/chat_id configured")

    return results