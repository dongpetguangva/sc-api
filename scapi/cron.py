"""Manage the cron entry that runs `sc-api watch --once`.

Everything is done through `crontab`, so no sudo and no systemd unit. The entry
is tagged with a comment marker, which means install/remove can find and replace
exactly one line without disturbing anything else in the user's crontab.
"""

from __future__ import annotations

import os
import shutil
import subprocess

MARKER = "# sc-api: reminder"
DEFAULT_EVERY = 10


def _run(argv: list[str], stdin: str | None = None) -> str:
    proc = subprocess.run(
        argv, input=stdin, capture_output=True, text=True, timeout=20
    )
    if proc.returncode != 0 and "no crontab" not in proc.stderr.lower():
        raise RuntimeError(proc.stderr.strip() or f"{argv[0]} failed")
    return proc.stdout


def read_crontab() -> str:
    return _run(["crontab", "-l"])


def write_crontab(text: str) -> None:
    _run(["crontab", "-"], stdin=text if text.endswith("\n") or not text else text + "\n")


def managed_lines(text: str) -> list[str]:
    """Return the marker comment plus the schedule line, if present."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == MARKER:
            block = [line]
            if index + 1 < len(lines):
                block.append(lines[index + 1])
            return block
    return []


def without_managed(text: str) -> str:
    """Drop our marker, the schedule line beneath it, and any legacy entry.

    Older setups wrote a bare line pointing at sinarcloud-watch.sh with no
    marker. Keeping it would run the reminder twice, so it is removed too.
    """
    lines = text.splitlines()
    out: list[str] = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.strip() == MARKER:
            skip_next = True
            continue
        if "sinarcloud-watch.sh" in line:
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


def schedule(every_minutes: int) -> str:
    """Cron field for `every N minutes`.

    N < 60 and dividing 60 evenly uses the `*/N` form. Anything else would
    silently drift, so it is rejected rather than approximated.
    """
    if every_minutes < 1:
        raise ValueError("interval must be at least 1 minute")
    if every_minutes == 1:
        return "* * * * *"
    if every_minutes < 60 and 60 % every_minutes == 0:
        return f"*/{every_minutes} * * * *"
    raise ValueError("interval must divide 60 evenly (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30)")


def build_line(every_minutes: int, workdir: str) -> str:
    return (
        f"{schedule(every_minutes)} cd {workdir} && "
        f"./sc-api watch --once --notify --quiet >/dev/null 2>&1"
    )


def install(every_minutes: int, workdir: str) -> str:
    """Replace any existing sc-api entry with a fresh one. Returns the line."""
    if not shutil.which("crontab"):
        raise RuntimeError("crontab is not installed on this machine")
    line = build_line(every_minutes, workdir)
    base = without_managed(read_crontab())
    merged = (base + "\n" if base else "") + f"{MARKER}\n{line}\n"
    write_crontab(merged)
    return line


def remove() -> bool:
    """Delete our entry. Returns True if something was removed."""
    current = read_crontab()
    if not managed_lines(current):
        return False
    write_crontab(without_managed(current) + "\n")
    return True


def parse_interval(text: str) -> int | None:
    """Recover N from our own schedule line, for `cron status`."""
    block = managed_lines(text)
    if len(block) < 2:
        return None
    field = block[1].split()[0]
    if field == "*":
        return 1
    if field.startswith("*/"):
        try:
            return int(field[2:])
        except ValueError:
            return None
    return None


def last_run() -> str | None:
    path = os.path.expanduser("~/.local/state/sinarcloud/last-run")
    try:
        return open(path, encoding="utf-8").read().strip() or None
    except OSError:
        return None