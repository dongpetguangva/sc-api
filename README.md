# sc-api — monitor your SinarCloud balance without opening the dashboard

Read-only client for `console.sinarcloud.com`. Every request is a `GET`; nothing
in this project writes, mutates, or deletes anything on your account.

It exists because SinarCloud exposes no billing endpoint for API keys. The only
credential the console API accepts is a **browser session cookie**.

```
$ ./sc-api

Saldo          : IDR 17,714
Rata-rata/hari : IDR 3,277
Bulan berjalan : IDR 18,996
Proyeksi bulan : IDR 101,335
Sisa bertahan : 5.4 hari

Request        : 6,765
Token          : masuk 918,702,063 / keluar 4,958,973
Total terpakai : IDR 52,307

Token credits  : tidak ada
```

---

## Quick start

Requires **Python 3.9+**. No dependencies — standard library only.

```bash
git clone https://github.com/dongpetguangva/sc-api.git
cd sc-api

./import_cookie.py     # paste the cURL from DevTools, Enter, Ctrl-D
./sc-api check         # confirm the session works
./sc-api               # summary
```

### Getting the cookie (once per session)

1. Log in at <https://console.sinarcloud.com>
2. Press **F12** → **Network** tab
3. Reload the page (**F5**)
4. Click any request to `console-api.sinarcloud.com` — usually `csrf` or `me`
5. Right-click → **Copy** → **Copy as cURL**
6. Run `./import_cookie.py`, paste, **Enter**, then **Ctrl-D**

All three cURL flavours work: bash/Linux (`-b '...'`), macOS, and Windows `cmd`
(the one full of `^"` and `^%^22`).

The cookie is stored at `~/.config/sinarcloud/cookies.txt` with mode `600`.
It is never sent anywhere except `console-api.sinarcloud.com`.

---

## Commands

| Command | What it does |
|---|---|
| `./sc-api` | Summary: balance, runway, usage, credits |
| `./sc-api summary --json` | Same data as raw JSON |
| `./sc-api daily` | Per-day requests and tokens |
| `./sc-api models` | Spend per model |
| `./sc-api check` | Verify the cookie still works |
| `./sc-api watch …` | Refresh on an interval; fire reminders |
| `./sc-api notify-test` | Send one reminder now, ignore thresholds |

Global options: `--days {7,30}`, `--cookie PATH`, `--runway DAYS`, `--version`.

---

## Watch mode

`watch` refreshes on an interval and sends a reminder when balance or runway
crosses a threshold you set. It is **not** a daemon that must stay running —
`--once` makes it a single evaluation for cron.

```bash
# live terminal view, refresh every 5 minutes, alert under IDR 25,000
./sc-api watch --balance 25000 --interval 300 --notify

# headless: check once, notify if below threshold, exit (cron-friendly)
./sc-api watch --balance 25000 --once --notify --quiet

# JSON per tick — for a dashboard or another script
./sc-api watch --runway 3 --interval 60 --json

# just look, never send anything
./sc-api watch --balance 25000 --interval 30
```

| Flag | Meaning |
|---|---|
| `--interval SEC` | Seconds between refreshes (default `60`) |
| `--balance AMOUNT` | Breach when balance `< AMOUNT` |
| `--runway DAYS` | Breach when projected runway `< DAYS` |
| `--notify` | Actually send to Discord/Telegram (off by default) |
| `--once` | One evaluation, then exit |
| `--json` | One JSON object per tick |
| `--quiet` | No terminal output, notifications only |
| `--ticks N` | Stop after N ticks (0 = forever) |
| `--state PATH` | Reminder state file |

### Reminders fire once, not on every tick

State is kept in `~/.local/state/sinarcloud/state.json`. A breach is announced
once when it appears, and again only if it **escalates** (warning → critical at
half the threshold). When the balance recovers, the flag clears. Without this a
5-second interval would post 12 times a minute.

---

## Reminders: Discord and Telegram (no LLM)

Two plain HTTP transports. Credentials come from the environment first, then
`~/.config/sinarcloud/notify.json`:

```json
{
  "discord_webhook": "https://discord.com/api/webhooks/...",
  "telegram_bot_token": "123456:ABC-DEF...",
  "telegram_chat_id": "123456789"
}
```

```bash
chmod 600 ~/.config/sinarcloud/notify.json
./sc-api notify-test          # prove both channels work
```

Environment variables override the file:
`SINAR_DISCORD_WEBHOOK`, `SINAR_TELEGRAM_BOT_TOKEN`, `SINAR_TELEGRAM_CHAT_ID`.

**Discord** sends a rich embed (title, colour by severity, balance, threshold,
runway, average daily spend, top-up link). **Telegram** sends HTML text via
`sendMessage`. A channel with no credential is reported as `skipped`, so a
Telegram-only setup does not look broken.

### Cron examples

```bash
# every 30 minutes: evaluate once, speak only on a breach
*/30 * * * * cd ~/sc-api && ./sc-api watch --balance 25000 --once --notify --quiet

# daily 07:00: append a summary to a log
0 7 * * * cd ~/sc-api && ./sc-api >> ~/.local/state/sinar-usage.log 2>&1
```

### Testing without real credentials

`tests/mock_server.py` accepts any POST and records it, so the reminder path can
be verified end to end:

```bash
./tests/mock_server.py 8765 &
SINAR_DISCORD_WEBHOOK="http://127.0.0.1:8765/discord" ./sc-api notify-test
cat /tmp/scapi-mock.jsonl
```

---

## Why not just use an API key?

Tried, it does not exist:

- `console-api.sinarcloud.com` rejects API keys on every route (401). Its auth
  filter runs **before** routing, so even unknown paths answer 401 instead of
  404.
- `ai.sinarcloud.com` (the inference host) has no billing routes at all:
  `/v1/dashboard/billing/subscription`, `/v1/dashboard/billing/usage`,
  `/v1/usage`, `/v1/credits`, `/v1/auth/key` → all 404
  `inference endpoint is not supported`.

Login also cannot be automated: the sign-in form sits behind Cloudflare
Turnstile, which never issues a token in headless Chromium.

And the cookie **will** expire — SinarCloud has no refresh token (verified:
`refresh_token` and `expiresIn` appear zero times in the frontend bundle), and a
single 401 triggers a logout in the dashboard. When `./sc-api check` starts
failing, rerun `./import_cookie.py` (about 30 seconds).

---

## Architecture

The CLI is a thin wrapper; all behaviour lives in an importable package, so a
dashboard, a bot, or a cron script can reuse it.

```
sc-api                 CLI: argparse + text output only
scapi/
  auth.py              cookie loading and classification
  client.py            HTTP transport, one method per endpoint
  models.py            dataclasses: Wallet, Totals, Forecast, Snapshot, …
  report.py            build Snapshot, render summary/daily/models
  notify.py            Discord embed + Telegram message, fan-out
  watch.py             interval loop, threshold evaluation, dedupe state
import_cookie.py       extract Cookie header from bash/macOS/Windows cURL
tests/mock_server.py   local webhook recorder for offline testing
```

Adding a feature means adding one method to `client.py` and one dataclass to
`models.py` — not editing the CLI:

```python
from scapi import Client, load_cookie
from scapi.report import build_snapshot

client = Client(load_cookie())
snap = build_snapshot(client, days=30)
print(snap.balance, snap.runway_days, snap.currency)
if snap.below_runway(3):
    ...  # your own alerting
```

---

## API reference

Base `https://console-api.sinarcloud.com` · required header `API-Version: 1.0`
· session via cookie · `X-XSRF-TOKEN` from `/api/auth/bff/csrf` only for
non-GET (this client sends no non-GET requests).

| Path | Contents |
|---|---|
| `GET /api/auth/bff/me` | identity, organisation, timezone |
| `GET /api/wallet/current` | `availableBalance`, `reservedBalance`, `currency` |
| `GET /api/ai/usage/overview` | totals + `daily[]` (requests/tokens only) |
| `GET /api/ai/usage/dashboard?days=7\|30` | `totals`, `daily[]`, `apiKeys[]`, `recentRequests[]` |
| `GET /api/ai/usage/reports?days=7\|30` | `forecast`, `modelPerformance[]`, `spending`, `promotionSavings` |
| `GET /api/ai/credits/grants?page=&size=` | token credit grants |
| `GET /api/ai/credits/ledger?page=&size=` | credit movements |
| `GET /api/auth/bff/csrf` | CSRF bootstrap (the only unauthenticated route) |

Shape notes:

- Money is always an object `{ "amount": "18113.60", "currency": "IDR" }`,
  never a bare number.
- `runwayDays` lives in `reports.forecast`, not in the dashboard payload.
- The API reports **no per-day money**; `overview.daily` carries requests and
  tokens only. `./sc-api daily` therefore shows counts and says so, rather than
  inventing an allocation.

---

## Limits & etiquette

- Read-only by construction: there is no generic POST surface in `scapi.client`.
- The cookie is a full account credential — never commit it, never share it.
  `.gitignore` covers `cookies.txt`, `*.cookie`, `.env`, and `notify.json`.
- If several people use this, each uses **their own** cookie. Never share one.
- Unofficial client. Endpoints can change without notice; `--json` is the
  fastest way to inspect the new shape.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cookie file not found` | `import_cookie.py` was never run. |
| `WARNING: … none look like a session cookie` | Copied from `console.sinarcloud.com` instead of `console-api.sinarcloud.com`. Redo step 4. |
| `HTTP 401 — session cookie missing or expired` | Session gone. Log in, re-import. |
| `Token credits: tidak ada` | The account has no active grants. Not an error. |
| `daily` has no cost column | Normal — the API reports no per-day money. |
| Discord `FAIL HTTP 404` | Webhook URL is wrong or revoked. |
| Telegram `FAIL HTTP 401` | Bot token invalid, or the bot was never added to the chat. |
| Reminder never fires | Check `--notify` is passed; delete `~/.local/state/sinarcloud/state.json` if a stale breach flag is stuck. |

---

MIT licensed. Not affiliated with SinarCloud.