#!/usr/bin/env python3
"""Extract the Cookie header from a cURL command and save it as a cookie file.

Handles the three shapes DevTools produce:
  * "Copy as cURL"        (bash,  -b 'a=1; b=2'  or  -H 'cookie: a=1; b=2')
  * "Copy as cURL (cmd)"  (Windows, ^" wrappers and ^%^22 escapes)
  * "Copy as cURL (bash)" on macOS/Linux with line continuations

Usage:
  import_cookie.py                 # paste, Enter, Ctrl-D
  import_cookie.py file.txt        # read from file
  pbpaste | import_cookie.py       # macOS clipboard

Reads stdin when no file argument is given. Writes the destination from
$SINAR_COOKIE_FILE (default ~/.config/sinarcloud/cookies.txt) with mode 600.
"""

from __future__ import annotations

import os
import re
import stat
import sys

DEFAULT_DEST = os.path.expanduser("~/.config/sinarcloud/cookies.txt")

# Windows cmd escaping used by "Copy as cURL (cmd)".
CMD_ESCAPES = (
    ("^%^22", '"'),
    ("^%^3a", ":"),
    ("^%^3A", ":"),
    ("^%^2c", ","),
    ("^%^2C", ","),
    ("^%^7b", "{"),
    ("^%^7B", "{"),
    ("^%^7d", "}"),
    ("^%^7D", "}"),
    ("^%^3d", "="),
    ("^%^3D", "="),
    ('^"', '"'),
)


def normalize(raw: str) -> str:
    """Join line continuations only — escapes stay intact for the parser."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\\\s*\n", " ", raw)   # bash line continuations
    raw = re.sub(r"\^\s*\n", " ", raw)   # cmd line continuations
    return raw


def unescape(val: str) -> str:
    for esc, ch in CMD_ESCAPES:
        val = val.replace(esc, ch)
    return val.replace("^", "")


def _read_quoted(s: str, start: int) -> tuple[str, int]:
    """Read a quoted argument beginning at `start`.

    Delimiters: cmd's ^" ... ^" , or plain ' ... ' / " ... " .
    Reading happens BEFORE unescaping, because an unescaped cookie value can
    itself contain quotes (twk_uuid_...={"uuid":"..."}) and would truncate.
    """
    for delim in ('^"', "'", '"'):
        if s.startswith(delim, start):
            i = start + len(delim)
            end = s.find(delim, i)
            if end == -1:
                return s[i:], len(s)
            return s[i:end], end + len(delim)
    return "", start


def find_cookie(raw: str) -> str:
    # -b / --cookie <quoted>
    for m in re.finditer(r"(?:-b|--cookie)\s+", raw):
        val, _ = _read_quoted(raw, m.end())
        val = unescape(val).strip()
        if val:
            return val

    # -H '<name>: <value>' where name is cookie
    for m in re.finditer(r"-H\s+", raw):
        val, _ = _read_quoted(raw, m.end())
        val = unescape(val).strip()
        low = val.lower()
        if low.startswith("cookie:"):
            return val.split(":", 1)[1].strip()
    return ""


def main() -> None:
    dest = os.environ.get("SINAR_COOKIE_FILE") or DEFAULT_DEST
    arg = sys.argv[1] if len(sys.argv) > 1 else None

    if arg in ("-h", "--help"):
        print(__doc__)
        return

    if arg:
        if not os.path.exists(arg):
            sys.exit(f"file not found: {arg}")
        raw = open(arg, encoding="utf-8", errors="replace").read()
    else:
        print("Paste hasil 'Copy as cURL' di bawah, lalu tekan Enter dan Ctrl-D:", flush=True)
        raw = sys.stdin.read()

    if not raw.strip():
        sys.exit("input kosong")

    cookie = find_cookie(normalize(raw))
    if not cookie:
        sys.exit(
            "tidak menemukan header Cookie / -b di input itu.\n"
            "Pastikan yang di-copy adalah request ke console-api.sinarcloud.com."
        )

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(cookie + "\n")
    os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)  # 600

    count = sum(1 for c in cookie.split(";") if "=" in c)
    names = [c.split("=", 1)[0].strip() for c in cookie.split(";") if "=" in c]
    has_session = any("session" in n.lower() for n in names)

    print(f"OK — {count} cookie disimpan ke {dest}")
    if not has_session:
        print("PERINGATAN: tidak ada cookie bernama *SESSION* di dalamnya.")
        print("Kemungkinan kamu meng-copy request yang salah — coba request ke")
        print("console-api.sinarcloud.com (bukan ke console.sinarcloud.com).")
    print("\nTes sekarang:\n  " + os.path.join(os.path.dirname(os.path.abspath(__file__)), "sinar.py") + " --check")


if __name__ == "__main__":
    main()