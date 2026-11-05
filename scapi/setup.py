"""Easy channel setup: find credentials, prove they work, write notify.json.

Two ways in:

  * `sc-api setup --detect`  reuse credentials already on this machine
  * `sc-api setup`           answer a few questions

Either way the credentials are validated by sending one real message before
anything is written, so a typo is caught immediately instead of at 3am when the
balance finally runs low. Secrets are never echoed back in full.
"""

from __future__ import annotations

import json
import os
import stat

from .notify import (
    CONFIG_PATH,
    build_telegram_text,
    build_discord_embed,
    send_discord,
    send_discord_bot,
    send_telegram,
)

# file -> {source_key: config_key}. Only uncommented assignments count.
_SOURCES = [
    ("~/.hermes/.telegram_watchdog", {
        "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "TELEGRAM_CHAT_ID": "telegram_chat_id",
    }),
    ("~/.hermes/.env", {
        "DISCORD_BOT_TOKEN": "discord_bot_token",
        "DISCORD_HOME_CHANNEL": "discord_channel_id",
        "DISCORD_ALLOWED_USERS": "discord_dm_user_id",
        "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "TELEGRAM_HOME_CHANNEL": "telegram_chat_id",
    }),
    ("~/.hermes/.env.local", {
        "SINAR_DISCORD_WEBHOOK": "discord_webhook",
        "SINAR_DISCORD_BOT_TOKEN": "discord_bot_token",
        "SINAR_DISCORD_CHANNEL_ID": "discord_channel_id",
        "SINAR_TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "SINAR_TELEGRAM_CHAT_ID": "telegram_chat_id",
    }),
]


def mask(value: str | None) -> str:
    """Show enough to recognise a credential, never enough to use it."""
    if not value:
        return "—"
    if len(value) <= 8:
        return value[:2] + "…"
    return f"{value[:6]}…{value[-4:]} (len {len(value)})"


def _read_assignments(path: str) -> dict[str, str]:
    """Parse KEY=value lines, skipping comments. Never logs the values."""
    out: dict[str, str] = {}
    real = os.path.expanduser(path)
    if not os.path.exists(real):
        return out
    try:
        with open(real, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, value = s.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    out[key] = value
    except OSError:
        return out
    return out


def discover() -> dict:
    """Collect candidate credentials already present on this machine.

    Returns {"found": {config_key: value}, "sources": [(file, [keys])]}.
    """
    found: dict[str, str] = {}
    where: dict[str, list[str]] = {}
    for path, mapping in _SOURCES:
        assignments = _read_assignments(path)
        hits = []
        for src_key, cfg_key in mapping.items():
            value = assignments.get(src_key)
            if value and cfg_key not in found:
                found[cfg_key] = value
                hits.append(src_key)
        if hits:
            where[path] = hits
    return {"found": found, "sources": where}


def describe(found: dict, sources: dict) -> list[str]:
    """Human-readable summary of what was found, without secrets."""
    lines = []
    for path, keys in sources.items():
        lines.append(f"  {path}: {', '.join(keys)}")
    for key in (
        "discord_webhook",
        "discord_bot_token",
        "discord_channel_id",
        "discord_dm_user_id",
        "telegram_bot_token",
        "telegram_chat_id",
    ):
        if found.get(key):
            lines.append(f"  {key:<20} {mask(found[key])}")
    return lines


def verify(cfg: dict, *, quiet: bool = True) -> dict[str, tuple[bool, str]]:
    """Send one real message to every configured target."""
    from .notify import notify_all

    return notify_all(
        balance=0,
        currency="IDR",
        threshold=0,
        severity="info",
        config=cfg,
        title="sc-api connected",
    )


def write_config(cfg: dict, path: str | None = None) -> str:
    """Merge into notify.json with mode 600. Returns the path written."""
    target = os.path.expanduser(path or CONFIG_PATH)
    existing: dict = {}
    if os.path.exists(target):
        try:
            existing = json.load(open(target, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update({k: v for k, v in cfg.items() if v})

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
        fh.write("\n")
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 600
    return target


def ask(prompt: str, current: str | None = None) -> str | None:
    """Prompt with a masked current value; blank input keeps it."""
    shown = f" [{mask(current)}]" if current else ""
    try:
        answer = input(f"{prompt}{shown}: ").strip()
    except EOFError:
        return current
    return answer or current