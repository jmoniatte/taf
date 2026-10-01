from datetime import date

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static
from tui_kit.shortcuts import GENERAL

from ..logs import Log, by_day, format_duration, recent_logs

# How many days back the tab shows, today included, like `fini -v 7` did
DAYS = 7


class LogsScroll(VerticalScroll):
    """The logs as plain text, which the mouse selects like any text and y copies."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]


class LogsView(Vertical):
    """The Logs tab, the way the Ruby fini printed them: the last DAYS days, the last day first.

    2026-09-30 - Wednesday 3h05
    * 09:00 - Reviewed PR 15m [+review @rails]
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logs: list[Log] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="logs-empty", classes="empty")
        with LogsScroll(id="logs-scroll"):
            yield Static("", id="logs-text")

    def on_mount(self) -> None:
        self.load()

    def load(self) -> None:
        """Read the logs of the last DAYS days from the database again."""
        database = self.app.database
        self.logs = recent_logs(database, DAYS) if database is not None else []
        self._show_logs()

    def set_colors(self) -> None:
        """Re-render the logs against a new palette; their colors are baked into Rich text."""
        self._show_logs()

    def _show_logs(self) -> None:
        palette = self.app.palette
        days = [day_text(day, logs, palette) for day, logs in by_day(self.logs)]
        # A blank line between days
        self.query_one("#logs-text", Static).update(Text("\n\n").join(days))
        empty = self.query_one("#logs-empty", Static)
        empty.update(self.app.database_error or f"No logs in the last {DAYS} days")
        empty.display = not self.logs
        self.query_one(LogsScroll).display = bool(self.logs)


def day_text(day: date, logs: list[Log], palette: dict[str, str]) -> Text:
    """The day, its weekday and the time spent on it all, then its logs."""
    total = sum(log.duration or 0 for log in logs)
    text = Text()
    text.append(f"{day.isoformat()} - {day.strftime('%A')}", style=palette["red"])
    text.append(" ")
    text.append(format_duration(total), style=palette["cyan"])
    for log in logs:
        text.append("\n")
        text.append_text(log_line(log, palette))
    return text


def log_line(log: Log, palette: dict[str, str]) -> Text:
    """* 09:00 - the text, the time spent and [+action @context]."""
    text = Text(f"* {log.logged_at.strftime('%H:%M')} - ")
    text.append(log.text, style="bold")
    if log.duration is not None:
        text.append(" ")
        text.append(format_duration(log.duration), style=palette["cyan"])
    meta = " ".join(part for part in (log.action and f"+{log.action}", log.context and f"@{log.context}") if part)
    if meta:
        text.append(" ")
        text.append(f"[{meta}]", style=Style(color=palette["comment"], italic=True))
    return text
