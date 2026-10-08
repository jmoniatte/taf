"""`taf log`: the Ruby fini's command line, in the shell without the TUI; no Textual."""

import sqlite3
import sys
from datetime import date, timedelta
from typing import TextIO

from .command import RED, RESET, open_for_command, print_error
from .config import Config
from .editor import EditorError, edit_written_text, keep
from .logs import Log, by_day, create_log, format_duration, logs_between, meta_text, parse_markdown, render_markdown, replace_days

# The ANSI codes the Ruby fini used, so the output looks the same in the terminal's own colors
GREEN = "\033[32m"
CYAN = "\033[36m"
GREY = "\033[37m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
# What `clear` prints; the Ruby fini cleared the screen before each command
CLEAR = "\033[H\033[2J\033[3J"


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
    connection = open_for_command(config, color)
    if connection is None:
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
    except sqlite3.Error as error:
        print_error(f"Database Error: {error}", color)
        return 1
    finally:
        connection.close()


def show_days(connection: sqlite3.Connection, first: date, last: date, out: TextIO, color: bool) -> None:
    out.write(render_terminal(logs_between(connection, first, last), color))


def edit_days(
    connection: sqlite3.Connection, config: Config, first: date, last: date, out: TextIO, color: bool
) -> int:
    """Open the days in $EDITOR as markdown, as the Logs tab does, then replace the logs of every
    day left in the file with the file's entries. Nothing is saved when the editor fails or quits
    without writing, nor when the file adds a day that already has logs, which it would lose."""
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    try:
        content = edit_written_text(render_markdown(logs_between(connection, first, last), days), "taf-edit-")
    except EditorError as error:
        print_error(str(error), color)
        return 1
    if content is None:
        return 0
    try:
        edited_days, entries = parse_markdown(content)
    except ValueError as error:
        print_error(f"{error}. Nothing saved; your edit is kept in {keep(content)}", color)
        return 1
    if taken := sorted({day for day in edited_days if not first <= day <= last and logs_between(connection, day, day)}):
        names = ", ".join(map(str, taken))
        print_error(f"{names} already has logs: edit it on its own. Nothing saved; your edit is kept in {keep(content)}", color)
        return 1
    if not edited_days:
        return 0
    try:
        replace_days(connection, edited_days, entries, config.action, config.context)
    except sqlite3.Error as error:
        print_error(f"Database Error: {error}. Nothing saved; your edit is kept in {keep(content)}", color)
        return 1

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
            if meta := meta_text(log.action, log.context):
                parts.append(paint(paint(meta, GREY, color), ITALIC, color))
            lines.append(" ".join(parts))
        lines.append("")
    return "".join(f"{line}\n" for line in lines)


def paint(text: str, code: str, color: bool) -> str:
    return f"{code}{text}{RESET}" if color else text
