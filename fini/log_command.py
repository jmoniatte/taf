"""`fini log`: the Ruby fini's command line, in the shell without the TUI; no Textual."""

import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TextIO

from .config import Config
from .database import open_database
from .logs import Log, by_day, create_log, format_duration, logs_between, replace_days

# The ANSI codes the Ruby fini used, so the output looks the same in the terminal's own colors
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
GREY = "\033[37m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
# What `clear` prints; the Ruby fini cleared the screen before each command
CLEAR = "\033[H\033[2J\033[3J"

DAY_HEADER = re.compile(r"^# (\d{4}-\d{2}-\d{2})")
ENTRY = re.compile(r"^\* (\d{2}:\d{2}) - (.+)$")


def run(
    config: Config,
    message: str = "",
    view: int | None = None,
    edit: int | None = None,
    today: date | None = None,
    out: TextIO = sys.stdout,
) -> int:
    """Log the message, or show the last `view` days, or edit the last `edit` days; with none of
    them, show today. Returns the exit code."""
    today = today or date.today()
    color = out.isatty()
    for warning in config.warnings:
        print(warning, file=sys.stderr)
    try:
        connection = open_database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        print(paint(f"Database Error: cannot open {config.database_path}: {error}", RED, color), file=sys.stderr)
        return 1
    try:
        if color:
            out.write(CLEAR)
        if edit is not None:
            return edit_days(connection, config, today - timedelta(days=edit - 1), today, out, color)
        if view is not None:
            show_days(connection, today - timedelta(days=view - 1), today, out, color)
        elif message:
            logged_at = create_log(connection, message, config.action, config.context)
            show_days(connection, logged_at.date(), logged_at.date(), out, color)
        else:
            show_days(connection, today, today, out, color)
        return 0
    finally:
        connection.close()


def show_days(connection: sqlite3.Connection, first: date, last: date, out: TextIO, color: bool) -> None:
    out.write(render_terminal(logs_between(connection, first, last), color))


def edit_days(
    connection: sqlite3.Connection, config: Config, first: date, last: date, out: TextIO, color: bool
) -> int:
    """Open the days in $EDITOR as markdown, then replace the logs of every day left in the file
    with the file's entries."""
    content = render_markdown(logs_between(connection, first, last))
    with tempfile.NamedTemporaryFile("w", prefix="fini-edit-", suffix=".md", delete=False) as file:
        file.write(content)
    path = Path(file.name)
    editor = os.environ.get("EDITOR") or "vim"
    subprocess.run([*shlex.split(editor), str(path)])

    try:
        days, entries = parse_markdown(path.read_text(encoding="utf-8"))
    except ValueError as error:
        print(paint(f"{error}. Nothing saved; your edit is kept in {path}", RED, color), file=sys.stderr)
        return 1
    if not days:
        path.unlink()
        return 0
    replace_days(connection, days, entries, config.action, config.context)
    path.unlink()

    show_days(connection, first, last, out, color)
    span = f"{last}" if first == last else f"{first} to {last}"
    out.write(paint(f"✓ Logs updated for {span}", GREEN, color) + "\n")
    return 0


def render_terminal(logs: list[Log], color: bool = True) -> str:
    """The logs by day as the Ruby fini printed them:

    2026-09-30 - Wednesday 3h05
    * 09:00 - Reviewed PR 15m [+review @rails]
    """
    lines = []
    for day, day_logs in by_day(logs):
        total = sum(log.duration or 0 for log in day_logs)
        lines.append(f"{paint(f'{day} - {day:%A}', RED, color)} {paint(format_duration(total), CYAN, color)}")
        for log in day_logs:
            parts = ["*", f"{log.logged_at:%H:%M}", "-", paint(log.text, BOLD, color)]
            if log.duration is not None:
                parts.append(paint(format_duration(log.duration), CYAN, color))
            meta = " ".join(part for part in (log.action and f"+{log.action}", log.context and f"@{log.context}") if part)
            if meta:
                parts.append(paint(paint(f"[{meta}]", GREY, color), ITALIC, color))
            lines.append(" ".join(parts))
        lines.append("")
    return "".join(f"{line}\n" for line in lines)


def render_markdown(logs: list[Log]) -> str:
    """The logs by day for the editor, each as it was typed:

    # 2026-09-30 - Wednesday
    * 09:00 - Reviewed PR @15m
    """
    days = []
    for day, day_logs in by_day(logs):
        lines = [f"# {day} - {day:%A}", *(f"* {log.logged_at:%H:%M} - {log.message}" for log in day_logs), ""]
        days.append("\n".join(lines))
    return "\n".join(days)


def parse_markdown(content: str) -> tuple[list[date], list[tuple[datetime, str]]]:
    """The days whose header is in the file, and every entry under one, as (when, message).

    Other lines are ignored; ValueError for a date or time that does not exist.
    """
    days: list[date] = []
    entries: list[tuple[datetime, str]] = []
    day = None
    for line in content.splitlines():
        if header := DAY_HEADER.match(line):
            day = _parse(header.group(1), "%Y-%m-%d", f"'{line}' has no valid date").date()
            days.append(day)
        elif day is not None and (entry := ENTRY.match(line)):
            time = _parse(entry.group(1), "%H:%M", f"'{line}' has no valid time").time()
            entries.append((datetime.combine(day, time), entry.group(2)))
    return days, entries


def paint(text: str, code: str, color: bool) -> str:
    return f"{code}{text}{RESET}" if color else text


def _parse(value: str, format: str, error: str) -> datetime:
    try:
        return datetime.strptime(value, format)
    except ValueError:
        raise ValueError(error) from None
