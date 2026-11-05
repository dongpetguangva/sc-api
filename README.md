# sc-api — monitor your SinarCloud balance without opening the dashboard

A read-only client for the SinarCloud console. Every request it makes is a
`GET`; nothing here writes, mutates, or deletes anything on your account.

It exists because SinarCloud exposes no billing endpoint for API keys. The only
credential the console API accepts is a **browser session cookie**.

```
$ ./sc-api

Balance        : IDR 42,000
Average/day    : IDR 1,250
Month to date  : IDR 12,500
Projected month: IDR 38,750
Runway         : 33.6 days

Requests       : 1,204
Tokens         : in 12,345,678 / out 234,567
Total charged  : IDR 12,500

Token credits  : none
```

*(Sample output. Your own numbers appear when you run it.)*

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

1. Log in at `https://console.sinarcloud.com`
2. Press **F12** → **Network** tab
3. Reload the page (**F5**)
4. Click any request to `console-api.sinarcloud.com` — usually `csrf` or `me`
5. Right-click → **Copy** → **Copy as cURL**
6. Run `./import_cookie.py`, paste, **Enter**, then **Ctrl-D**

All three cURL flavours work: bash/Linux (`-b '...'`), macOS, and Windows `cmd`
(the one full of `^"` and `^%^22`).

The cookie is written to `~/.config/sinarcloud/cookies.txt` with mode `600`. It
is never sent anywhere except `console-api.sinarcloud.com`.

---

## Commands

| Command | What it does |
|---|---|
| `./sc-api` | Summary: balance, runway, usage, credits |
| `./sc-api summary --json` | Same data as raw JSON |
| `./sc-api daily` | Per-day requests and tokens |
| `./sc-api models` | Spend per model |
| `./sc-api check` | Verify the cookie still works |
| `./sc-api config get` | Show saved settings (secrets masked) |
| `./sc-api config set KEY VALUE` | Change one setting |
| `./sc-api cron install --every N` | Install/change the cron reminder |
| `./sc-api cron status` | Show schedule and last run |
| `./sc-api cron remove` | Delete the cron reminder |
| `./sc-api setup` | Connect Discord/Telegram: detect, test, save |
| `./sc-api watch …` | Refresh on an interval; fire reminders |
| `./sc-api notify-test` | Send one reminder now, ignoring thresholds |

Global options: `--days {7,30}`, `--cookie PATH`, `--runway DAYS`, `--version`.

### Everything is a command — no file editing

Configuration lives in `~/.config/sinarcloud/notify.json`, but you never have to
open it:

```bash
./sc-api config set threshold 14000     # alert below IDR 14,000
./sc-api config set channel uptime      # Discord channel by name
./sc-api config set runway 3            # also alert below 3 days of runway
./sc-api config get                     # show everything, secrets masked
./sc-api config get threshold           # show one key
./sc-api config set runway ""           # clear a setting
```

`config set` rejects unknown keys and lists the valid ones. Numbers are stored
as numbers, so a threshold of `"14000"` compares correctly. Known keys:

| Key | Meaning |
|---|---|
| `threshold` | Balance below which a reminder fires |
| `runway` | Runway in days below which a reminder fires |
| `channel` | Discord channel name or id |
| `discord_bot_token`, `discord_channel_id`, `discord_dm_user_id` | Discord bot transport |
| `discord_webhook` | Discord webhook transport (alternative to a bot) |
| `telegram_bot_token`, `telegram_chat_id` | Telegram transport |

### The cron reminder is a command too

```bash
./sc-api cron install --every 5     # check every 5 minutes
./sc-api cron install --every 15    # change it to 15
./sc-api cron status                # schedule + when it last ran
./sc-api cron remove                # stop the reminders
```

`install` writes one tagged line into your crontab and replaces it on every run,
so changing the interval never leaves duplicates behind. No sudo, no systemd.
`--every` must divide 60 evenly (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30) — anything
else would drift, so it is refused rather than approximated.

`cron status` reports the last completed run, because each tick writes a
timestamp to `~/.local/state/sinarcloud/last-run`. That is a timestamp only —
never a balance — and it is how you tell "nothing to report" apart from
"the job is dead".

---

## Watch mode

`watch` refreshes on an interval and sends a reminder when the balance or the
projected runway crosses a threshold you set. It is **not** a daemon that has to
stay running — `--once` turns it into a single evaluation for cron.

```bash
# live terminal view, refresh every 5 minutes, alert under IDR 25,000
./sc-api watch --balance 25000 --interval 300 --notify

# headless: check once, notify if below threshold, exit (cron-friendly)
./sc-api watch --balance 25000 --once --notify --quiet

# one JSON object per tick — for a dashboard or another script
./sc-api watch --runway 3 --interval 60 --json

# observe only, never send anything
./sc-api watch --balance 25000 --interval 30
```

| Flag | Meaning |
|---|---|
| `--interval SEC` | Seconds between refreshes (default `60`) |
| `--balance AMOUNT` | Breach when balance is below `AMOUNT` |
| `--channel NAME` | Discord channel by name for this run (overrides config) |
| `--runway DAYS` | Breach when projected runway is below `DAYS` |
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
5-second interval would post an alert twelve times a minute.

---

## Reminders: Discord and Telegram (no LLM)

Two plain HTTP transports. There is no LLM anywhere in this path — the message
is built from numbers with an f-string.

### One command to connect

```bash
./sc-api setup --detect
```

That looks for credentials already on this machine, sends one real test message
through each channel it finds, and writes `~/.config/sinarcloud/notify.json`
(mode 600) only if every channel answered OK. Sample:

```
Found credentials already on this machine:
  ~/.hermes/.telegram_watchdog: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  ~/.hermes/.env: DISCORD_BOT_TOKEN, DISCORD_HOME_CHANNEL
  discord_bot_token    MTAxNz…kQ2F (len 72)
  discord_channel_id   123456…5678 (len 19)
  telegram_bot_token   123456…Xy9Z (len 46)
  telegram_chat_id     123456…7890 (len 10)

Sending one test message to each channel...
  discord   OK
  telegram  OK

Saved to ~/.config/sinarcloud/notify.json (mode 600).
```

Values are always masked — `MTAxNz…kQ2F (len 72)` is enough to recognise which
credential was picked, never enough to use it.

No credentials on the machine? Run `./sc-api setup` without flags and paste them
in; blank fields are skipped.

### Getting the credentials

**Discord — webhook (simplest)**

Server Settings → Integrations → Webhooks → New Webhook → pick a channel →
Copy Webhook URL.

**Discord — bot token (no webhook needed)**

If a bot is already in your server: copy its token and the target channel id
(right-click the channel → Copy Channel ID, with Developer Mode on).

**Telegram**

Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token. Send
your bot a message once, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id`. A group id
starts with `-`.

### notify.json

```json
{
  "discord_bot_token": "MTU1...",
  "discord_channel_id": "uptime",
  "discord_dm_user_id": "123456789012345678",
  "telegram_bot_token": "123456:ABC-DEF...",
  "telegram_chat_id": "123456789"
}
```

`discord_channel_id` accepts either a snowflake or a **channel name** — the bot
looks the name up in its guilds at send time, so `"uptime"` is enough. Keep both
`discord_channel_id` and `discord_dm_user_id` to post in the channel *and* send a
direct message; each target is attempted independently, so one failing does not
block the others.

A webhook can be used instead of a bot token:

```json
{ "discord_webhook": "https://discord.com/api/webhooks/..." }
```

```bash
chmod 600 ~/.config/sinarcloud/notify.json
./sc-api notify-test          # prove both channels work
```

Environment variables override the file:
`SINAR_DISCORD_WEBHOOK`, `SINAR_DISCORD_BOT_TOKEN`, `SINAR_DISCORD_CHANNEL_ID`,
`SINAR_DISCORD_DM_USER_ID`, `SINAR_TELEGRAM_BOT_TOKEN`, `SINAR_TELEGRAM_CHAT_ID`.

### What the messages look like

Discord — one embed, colour by severity, values in monospace so the 2×2 field
grid lines up, footer and native timestamp:

```
🚨 SinarCloud balance low
Your SinarCloud credit is below the configured threshold.
──────────────────────────────────────────────
Balance             Threshold
IDR 15,814          IDR 500
Runway              Average spend
4.8 days            IDR 3,277/day
──────────────────────────────────────────────
sc-api · read-only monitor · 05 Nov 21:43
```

Telegram — the same numbers as an aligned monospace block:

```
🚨 SinarCloud balance low
05 Nov 21:43

Balance    IDR 15,814
Threshold  IDR 500
Runway     4.8 days
Avg spend  IDR 3,277/day

Top up
```

Discord posts through the Bot API (`POST /channels/{id}/messages`) or a webhook;
Telegram through `sendMessage`. A target with no credential is reported as
`skipped`, so a Telegram-only setup does not look broken.

### Cron examples

```bash
# install once, then change the interval any time with one command
./sc-api cron install --every 5
./sc-api cron status
```

Under the hood that is a single tagged line, which you can also see in
`crontab -l`:

```cron
# sc-api: reminder
*/5 * * * * cd ~/sc-api && ./sc-api watch --once --notify --quiet >/dev/null 2>&1
```

### Testing without real credentials

Three layers, cheapest first:

```bash
python3 tests/test_notify.py     # payload shape, colours, escaping, config — offline
./tests/mock_server.py 8765 &    # accepts any POST, records it to /tmp/scapi-mock.jsonl
SINAR_DISCORD_WEBHOOK="http://127.0.0.1:8765/discord" ./sc-api notify-test
cat /tmp/scapi-mock.jsonl
```

The third layer is the only one that proves a real delivery, and it needs real
credentials:

```bash
./sc-api notify-test    # hits discord.com / api.telegram.org for real
```

---

## Security and privacy

What this project stores, and where:

| Data | Location | Protection |
|---|---|---|
| Session cookie | `~/.config/sinarcloud/cookies.txt` | `chmod 600`, outside the repo |
| Webhook / bot token | `~/.config/sinarcloud/notify.json` | `chmod 600`, outside the repo |
| Reminder state | `~/.local/state/sinarcloud/state.json` | timestamps only, no amounts |
| Everything else | memory | nothing is logged or cached to disk |

Rules the code follows:

- **Read-only by construction.** `scapi.client` has no generic `post()` method,
  so no code path can modify your account.
- **Credentials never enter the repository.** `.gitignore` covers
  `cookies.txt`, `*.cookie`, `.env`, and `notify.json`.
- **The cookie is a full account credential** — treat it like a password. If it
  leaks, log out of the console (which invalidates the session) and import a
  fresh one.
- **Nothing is sent anywhere** except `console-api.sinarcloud.com` for reads, and
  the Discord/Telegram endpoints you explicitly configure.
- **`--json` prints raw API payloads**, which include your email and balance.
  Do not paste that output into an issue.

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
  notify.py            Discord webhook/bot + Telegram, retry, fan-out
  setup.py             discover credentials, verify, write notify.json
  cron.py              install/remove the tagged crontab entry
  watch.py             interval loop, threshold evaluation, dedupe state
import_cookie.py       extract Cookie header from bash/macOS/Windows cURL
tests/test_notify.py   offline assertions on payloads and thresholds
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
| `GET /api/ai/usage/overview` | totals + `daily[]` (requests and tokens only) |
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

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cookie file not found` | `import_cookie.py` was never run. |
| `WARNING: no cookie named *SESSION*` | Copied from `console.sinarcloud.com` instead of `console-api.sinarcloud.com`. Redo step 4. |
| `HTTP 401 — session cookie missing or expired` | Session gone. Log in, re-import. |
| `Token credits: none` | The account has no active grants. Not an error. |
| `daily` has no cost column | Normal — the API reports no per-day money. |
| Discord `FAIL HTTP 404` | Webhook URL is wrong or revoked. |
| Telegram `FAIL HTTP 401` | Bot token invalid, or the bot was never added to the chat. |
| Reminder never fires | Check that `--notify` is passed; delete `~/.local/state/sinarcloud/state.json` if a stale breach flag is stuck. |

---

MIT licensed. Not affiliated with SinarCloud.