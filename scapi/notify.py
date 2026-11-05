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
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

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
        "discord_bot_token": os.environ.get("SINAR_DISCORD_BOT_TOKEN") or cfg.get("discord_bot_token"),
        "discord_channel_id": os.environ.get("SINAR_DISCORD_CHANNEL_ID") or cfg.get("discord_channel_id"),
        "discord_dm_user_id": os.environ.get("SINAR_DISCORD_DM_USER_ID") or cfg.get("discord_dm_user_id"),
        "telegram_bot_token": os.environ.get("SINAR_TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token"),
        "telegram_chat_id": os.environ.get("SINAR_TELEGRAM_CHAT_ID") or cfg.get("telegram_chat_id"),
    }


def _post(url: str, payload: dict, headers: dict | None = None, attempts: int = 3) -> tuple[bool, str]:
    """POST JSON, retrying only on transient network faults.

    A dropped connection is normal on this link (observed: `Connection reset by
    peer` from api.telegram.org, succeeding on the next try). A 4xx is a real
    answer — a bad token or a bad webhook — and is never retried.
    """
    data = json.dumps(payload).encode()
    last = "unreachable: unknown error"
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "sc-api/1.0")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode(errors="replace")
                return 200 <= resp.status < 300, body[:200]
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
        except (urllib.error.URLError, OSError) as exc:
            last = f"unreachable: {getattr(exc, 'reason', exc)}"
            if attempt < attempts:
                time.sleep(attempt)  # 1s, then 2s
                continue
    return False, last


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
def _now_local() -> str:
    """Local timestamp, e.g. `05 Nov 21:26`. Timezone follows the machine."""
    return datetime.now().astimezone().strftime("%d %b %H:%M")


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
    # Values go in inline code so the digits line up in Discord's 2x2 field grid.
    fields = [
        {"name": "Balance", "value": f"`{currency} {balance:,.0f}`", "inline": True},
        {"name": "Threshold", "value": f"`{currency} {threshold:,.0f}`", "inline": True},
    ]
    if runway_days is not None:
        fields.append({"name": "Runway", "value": f"`{runway_days:.1f} days`", "inline": True})
    if average_daily:
        fields.append(
            {"name": "Average spend", "value": f"`{currency} {average_daily:,.0f}/day`", "inline": True}
        )
    return {
        "embeds": [
            {
                "title": f"{icon} {title}",
                "description": "Your SinarCloud credit is below the configured threshold.",
                "color": colour,
                "fields": fields,
                "footer": {"text": f"sc-api · read-only monitor · {_now_local()}"},
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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


def send_discord_dm(bot_token: str, user_id: str, embed_payload: dict) -> tuple[bool, str]:
    """Open (or reuse) a DM channel with a user, then post the embed into it."""
    url = "https://discord.com/api/v10/users/@me/channels"
    data = json.dumps({"recipient_id": user_id}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "sc-api/1.0")
    req.add_header("Authorization", f"Bot {bot_token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            channel_id = json.load(resp)["id"]
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:160]}"
    except (urllib.error.URLError, OSError) as exc:
        return False, f"unreachable: {getattr(exc, 'reason', exc)}"
    return send_discord_bot(bot_token, channel_id, embed_payload)


def _tg_call(bot_token: str, method: str, params: dict) -> tuple[bool, str, dict | None]:
    base = os.environ.get("SINAR_TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
    url = f"{base}/bot{bot_token}/{method}"
    body = json.dumps(params).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "sc-api/1.0")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            doc = json.load(resp)
            return True, "ok", doc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        return False, f"HTTP {exc.code}: {detail}", None
    except (urllib.error.URLError, OSError) as exc:
        return False, f"unreachable: {getattr(exc, 'reason', exc)}", None


def resolve_discord_channel(bot_token: str, name: str) -> tuple[str | None, str]:
    """Find a text channel by name across the bot's guilds. Returns (id, detail).

    Lets config say `"uptime"` instead of a 19-digit snowflake, which is easier
    to write and survives a channel being recreated with a new id only if the
    name stays the same.
    """
    try:
        req = urllib.request.Request(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bot {bot_token}", "User-Agent": "sc-api/1.0"},
        )
        guilds = json.load(urllib.request.urlopen(req, timeout=TIMEOUT))
        for guild in guilds:
            req = urllib.request.Request(
                f"https://discord.com/api/v10/guilds/{guild['id']}/channels",
                headers={"Authorization": f"Bot {bot_token}", "User-Agent": "sc-api/1.0"},
            )
            for channel in json.load(urllib.request.urlopen(req, timeout=TIMEOUT)):
                if channel.get("name") == name and channel.get("type") == 0:
                    return channel["id"], f"{guild['name']}#{name}"
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code} while listing channels"
    except (urllib.error.URLError, OSError) as exc:
        return None, f"unreachable: {getattr(exc, 'reason', exc)}"
    return None, f"no text channel named {name!r} found"


def send_telegram(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    ok, detail, doc = _tg_call(
        bot_token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    if ok and doc is not None:
        return True, json.dumps({"ok": True, "id": doc.get("result", {}).get("message_id")})
    return ok, detail


def build_telegram_text(
    *,
    balance: float,
    currency: str,
    threshold: float,
    runway_days: float | None = None,
    average_daily: float | None = None,
    severity: str = "warning",
    title: str = "SinarCloud balance low",
) -> str:
    icon, _ = _SEVERITY.get(severity, _SEVERITY["warning"])
    # Monospace block keeps the labels and the numbers in two aligned columns.
    rows = [("Balance", f"{currency} {balance:,.0f}"), ("Threshold", f"{currency} {threshold:,.0f}")]
    if runway_days is not None:
        rows.append(("Runway", f"{runway_days:.1f} days"))
    if average_daily:
        rows.append(("Avg spend", f"{currency} {average_daily:,.0f}/day"))
    width = max(len(label) for label, _ in rows)
    table = "\n".join(f"{label:<{width}}  {value}" for label, value in rows)

    lines = [
        f"{icon} <b>{_tg_escape(title)}</b>",
        f"<i>{_now_local()}</i>",
        "",
        f"<pre>{table}</pre>",
        "",
        '<a href="https://console.sinarcloud.com/billing/top-up">Top up</a>',
    ]
    return "\n".join(lines)


def send_discord_bot(bot_token: str, channel_id: str, embed_payload: dict) -> tuple[bool, str]:
    """Post through the Discord Bot API (needs a bot token, no webhook).

    Use this when the bot is already in the guild: it delivers to the channel id
    directly and does not require creating a webhook.
    """
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    return _post(url, embed_payload, headers={"Authorization": f"Bot {bot_token}"})


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
    title: str = "SinarCloud balance low",
) -> dict[str, tuple[bool, str]]:
    """Send the same reminder to every configured target.

    Targets are independent, so one broken channel never suppresses the others:

      * `discord:<channel>`  — a guild channel, by id or by name
      * `discord:dm`         — a direct message to one user
      * `telegram`           — a chat id (a private chat id *is* a DM)

    Returns {target: (ok, detail)}.
    """
    cfg = config if config is not None else load_config()
    results: dict[str, tuple[bool, str]] = {}

    embed = build_discord_embed(
        balance=balance,
        currency=currency,
        threshold=threshold,
        runway_days=runway_days,
        average_daily=average_daily,
        severity=severity,
        title=title,
    )
    text = build_telegram_text(
        balance=balance,
        currency=currency,
        threshold=threshold,
        runway_days=runway_days,
        average_daily=average_daily,
        severity=severity,
        title=title,
    )

    # -- Discord --------------------------------------------------------
    token = cfg.get("discord_bot_token")
    if cfg.get("discord_webhook"):
        results["discord:webhook"] = send_discord(cfg["discord_webhook"], embed)

    if token:
        target = cfg.get("discord_channel_id")
        if target:
            channel_id, where = (target, target) if str(target).isdigit() else resolve_discord_channel(token, target)
            if channel_id:
                results[f"discord:{target}"] = send_discord_bot(token, channel_id, embed)
            else:
                results[f"discord:{target}"] = (False, where)
        if cfg.get("discord_dm_user_id"):
            results["discord:dm"] = send_discord_dm(token, cfg["discord_dm_user_id"], embed)

    if not any(key.startswith("discord") for key in results):
        results["discord"] = (False, "skipped: no discord_webhook or discord_bot_token+channel_id")

    # -- Telegram -------------------------------------------------------
    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        results["telegram"] = send_telegram(
            cfg["telegram_bot_token"], cfg["telegram_chat_id"], text
        )
    else:
        results["telegram"] = (False, "skipped: no telegram_bot_token/chat_id configured")

    return results