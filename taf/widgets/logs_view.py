import sqlite3
from datetime import date, timedelta

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..editor import EditorError, edit_written_text, keep
from ..logs import Log, by_day, create_log, format_duration, logs_between, meta_text, parse_markdown, render_markdown, replace_days
from ..message import Parsed, parse_message
from .buttons import flat_button
from .dashed_rule import DashedRule

HINT = "@30m for the time spent, +action and @context, or the config's rules name them; Enter logs it"


class LogsScroll(VerticalScroll):
    """The logs as plain text, which the mouse selects like any text and y copies."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]


class NewLogScreen(ModalScreen[str | None]):
    """A wide window to log a message, as `taf log` does, with the message as it will be stored
    under the box, read again on every key. Returns the message logged, or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-log"):
            yield Static("New Log", id="dialog-title")
            yield Input(placeholder="What did you do? Reviewed PR @20m", id="log-input")
            yield Static("", id="log-preview")
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="btn-cancel-log")
                yield Button("Log", id="btn-log")

    def on_mount(self) -> None:
        self._show_preview("")
        self.query_one("#log-input", Input).focus()

    @on(Input.Changed, "#log-input")
    def _typed(self, event: Input.Changed) -> None:
        self._show_preview(event.value)

    def _show_preview(self, message: str) -> None:
        palette = self.app.palette
        preview = self.query_one("#log-preview", Static)
        if message.strip():
            preview.update(parsed_text(self._parse(message), palette))
        else:
            preview.update(Text(HINT, style=palette["comment"]))

    def _parse(self, message: str) -> Parsed:
        return parse_message(message, self.app.config.action, self.app.config.context)

    @on(Input.Submitted, "#log-input")
    @on(Button.Pressed, "#btn-log")
    def _log(self, event) -> None:
        event.stop()
        message = self.query_one("#log-input", Input).value.strip()
        if not message:
            return
        try:
            create_log(self.app.database, message, self.app.config.action, self.app.config.context)
        except sqlite3.Error as error:
            # Shown in the window, which stays open with the message in it, to try again
            self.query_one("#log-preview", Static).update(Text(f"Cannot log: {error}", style=self.app.palette["red"]))
            return
        self.notify(f"Logged: {parsed_text(self._parse(message), self.app.palette).plain}", markup=False)
        self.dismiss(message)

    @on(Button.Pressed, "#btn-cancel-log")
    def action_cancel(self) -> None:
        self.dismiss(None)


class DayClicked(Message):
    def __init__(self, day: date) -> None:
        super().__init__()
        self.day = day


class LogsText(Static):
    """The logs' text, whose days a click edits."""

    def action_edit_day(self, day: str) -> None:
        # A drag that selects text also ends in a click
        if not self.screen.get_selected_text():
            self.post_message(DayClicked(date.fromisoformat(day)))


class LogsView(Vertical):
    """The Logs tab: a week of logs, Monday to Sunday, the way the Ruby fini printed them, the last
    day first; Previous week and Next week, or [ and ], page through the weeks.

    2026-09-30 - Wednesday 3h05
    * 09:00 - Reviewed PR 15m [+review @rails]
    """

    BINDINGS = [
        Binding("n", "write", "New log", group=ACTIONS),
        Binding("e", "edit", "Edit the last day, or click a day", group=ACTIONS),
        Binding("left_square_bracket", "older", "Previous week", key_display="[", group=ACTIONS),
        Binding("right_square_bracket", "newer", "Next week", key_display="]", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logs: list[Log] = []
        # How many weeks back from this one
        self.page = 0

    def compose(self) -> ComposeResult:
        # The week in the middle between Previous and Next; the sides as wide, so it stays centered
        with Horizontal(id="logs-controls"):
            yield Static("", classes="logs-side")
            with Horizontal(id="logs-week"):
                yield flat_button("Previous", "btn-previous-week", classes="tinted -plain")
                # As wide as the longest dates, so the buttons never move
                with Vertical(id="logs-period"):
                    yield Static("", id="logs-dates")
                    yield Static("", id="logs-week-number")
                yield flat_button("Next", "btn-next-week", classes="tinted -plain")
            with Horizontal(classes="logs-side"):
                yield Button("New Log", id="btn-new-log", classes="tinted")
        yield DashedRule(id="logs-rule")
        # Always shown, even with no logs, so it keeps focus and the tab's keys
        with LogsScroll(id="logs-scroll"):
            yield Static("", id="logs-empty", classes="empty")
            yield LogsText("", id="logs-text")

    def on_mount(self) -> None:
        self.load()

    def help_section(self) -> tuple[str, tuple]:
        """The title and the keys of Help's right column."""
        return "Logs", (self.BINDINGS, LogsScroll.BINDINGS)

    def tab_shown(self) -> None:
        self.query_one(LogsScroll).focus()

    @property
    def span(self) -> tuple[date, date]:
        """The Monday and the Sunday of the week on show."""
        monday = today() - timedelta(days=today().weekday() + 7 * self.page)
        return monday, monday + timedelta(days=6)

    def load(self) -> None:
        """Read the logs of the days on show from the database again."""
        database = self.app.database
        self.logs = logs_between(database, *self.span) if database is not None else []
        self._show_logs()
        self.query_one(LogsScroll).scroll_home(animate=False)

    def set_colors(self) -> None:
        """Re-render the logs against a new palette; their colors are baked into Rich text."""
        self._show_logs()

    def _show_logs(self) -> None:
        palette = self.app.palette
        days = [day_text(day, logs, palette) for day, logs in by_day(self.logs)]
        self.query_one("#logs-text", Static).update(Text("\n\n").join(days))
        first, last = self.span
        week = f"Week {first.isocalendar().week}"
        self.query_one("#logs-dates", Static).update(f"{short_date(first)} to {short_date(last)}, {last.year}")
        self.query_one("#logs-week-number", Static).update(week)
        empty = self.query_one("#logs-empty", Static)
        empty.update(self.app.database_error or f"No logs in {week.lower()}")
        empty.display = not self.logs
        self.query_one("#btn-next-week", Button).disabled = self.page == 0

    # -- paging

    @on(Button.Pressed, "#btn-previous-week")
    def action_older(self) -> None:
        self.page += 1
        self.load()

    @on(Button.Pressed, "#btn-next-week")
    def action_newer(self) -> None:
        if self.page > 0:
            self.page -= 1
            self.load()

    def action_refresh(self) -> None:
        self.load()

    # The footer's Refresh
    reload = action_refresh

    # -- logging

    @on(Button.Pressed, "#btn-new-log")
    def action_write(self) -> None:
        if self.app.database is None:
            return
        # A clicked button keeps focus; hand it back to the logs for when the window closes
        self.query_one(LogsScroll).focus()
        self.app.push_screen(NewLogScreen(), self._logged)

    def _logged(self, message: str | None) -> None:
        if message:
            # Back to the last days, where the new log is
            self.page = 0
            self.load()

    # -- editing

    def action_edit(self) -> None:
        """Edit the last day with logs on show; with none, today in this week, else the Sunday."""
        days = by_day(self.logs)
        self.edit_day(days[0][0] if days else min(today(), self.span[1]))

    @on(DayClicked)
    def _day_clicked(self, event: DayClicked) -> None:
        event.stop()
        self.edit_day(event.day)

    def edit_day(self, day: date) -> None:
        """Edit the day in $EDITOR as `taf log -e` does, then replace its logs with the file's, read
        again with the current rules once the file is written, even unchanged; quitting without
        writing saves nothing."""
        database = self.app.database
        if database is None:
            return
        # The database's copy, so a log written since the tab loaded is not lost
        original = render_markdown(logs_between(database, day, day), [day]).strip("\r\n")
        content: str | None = None
        failure: Exception | None = None
        try:
            with self.app.suspend():
                try:
                    content = edit_written_text(original, "taf-edit-")
                except EditorError as error:
                    # Textual only restores the TUI when the suspend block exits without raising
                    failure = error
        except SuspendNotSupported as error:
            failure = error
        if failure is not None:
            self.notify(str(failure), severity="error", markup=False)
            return
        if content is None:
            return
        try:
            edited_days, entries = parse_markdown(content)
        except ValueError as error:
            self.notify(f"{error}. Nothing saved; your edit is kept in {keep(content)}", severity="error", markup=False)
            return
        if day not in edited_days:
            self.notify(f"The header of {day} is gone. Nothing saved; your edit is kept in {keep(content)}", severity="error", markup=False)
            return
        # A day with no logs yet may be added under its own header; one with logs would lose them,
        # as they were never in the file
        if taken := sorted({other for other in edited_days if other != day and logs_between(database, other, other)}):
            names = ", ".join(map(str, taken))
            self.notify(f"{names} already has logs: edit it on its own. Nothing saved; your edit is kept in {keep(content)}", severity="error", markup=False)
            return
        try:
            replace_days(database, edited_days, entries, self.app.config.action, self.app.config.context)
        except sqlite3.Error as error:
            self.notify(f"Cannot save: {error}. Your edit is kept in {keep(content)}", severity="error", markup=False)
            return
        self.load()
        names = ", ".join(f"{edited:%A} {short_date(edited)}" for edited in sorted(set(edited_days), reverse=True))
        self.notify(f"Logs of {names} updated")


def today() -> date:
    # Apart, so that tests can say which week is this one
    return date.today()


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def day_text(day: date, logs: list[Log], palette: dict[str, str]) -> Text:
    """The day, its weekday and the time spent on it all, then its logs; a click on the day edits it."""
    total = sum(log.duration or 0 for log in logs)
    text = Text()
    clickable = Style(color=palette["red"]) + Style.from_meta({"@click": f"edit_day({day.isoformat()!r})"})
    text.append(f"{day.isoformat()} - {day.strftime('%A')}", style=clickable)
    text.append(" ")
    text.append(format_duration(total), style=palette["cyan"])
    for log in logs:
        text.append("\n")
        text.append(f"* {log.logged_at.strftime('%H:%M')} - ")
        text.append_text(parsed_text(Parsed(log.text, log.action, log.context, log.duration), palette))
    return text


def parsed_text(parsed: Parsed, palette: dict[str, str]) -> Text:
    """The text, the time spent and [+action @context]."""
    text = Text(parsed.text, style="bold")
    if parsed.duration is not None:
        text.append(" ")
        text.append(format_duration(parsed.duration), style=palette["cyan"])
    if meta := meta_text(parsed.action, parsed.context):
        text.append(" ")
        text.append(meta, style=Style(color=palette["comment"], italic=True))
    return text
