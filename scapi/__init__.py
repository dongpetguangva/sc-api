"""scapi — read-only client for the SinarCloud console API.

Public surface:

    from scapi import Client, load_cookie

    client = Client(load_cookie("~/.config/sinarcloud/cookies.txt"))
    snap = client.snapshot(days=30)
    print(snap.wallet.available, snap.forecast.runway_days)
"""

from .auth import load_cookie, cookie_path
from .client import Client, ApiError, AuthError
from .models import (
    Forecast,
    Grant,
    ModelCost,
    Snapshot,
    Totals,
    UsageDay,
    Wallet,
)
from .notify import send_discord, send_telegram, notify_all
from .report import build_snapshot, format_summary

__version__ = "1.0.0"

__all__ = [
    "Client",
    "ApiError",
    "AuthError",
    "load_cookie",
    "cookie_path",
    "Wallet",
    "Totals",
    "UsageDay",
    "ModelCost",
    "Forecast",
    "Grant",
    "Snapshot",
    "build_snapshot",
    "format_summary",
    "send_discord",
    "send_telegram",
    "notify_all",
]