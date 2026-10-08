"""The Watch tab: the items collected from Slack and GitHub, under their project, to star and close;
one in full in place of the list. The collectors write them; nothing here makes or edits one."""

import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from textual import on
from textual.worker import get_current_worker
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Select, Static
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..watch.config import from_taf
from ..watch.github import ready_to_deploy
from ..watch.view import ago, last_collected, WatchItem, get_item, grouped, set_done, set_pinned, shown_items
from ..notes import DEFAULT_STATUS, STATUS_WORD, STATUSES, TODO, split_status
from .dashed_rule import DashedRule
from .note_detail import NoteDetail, ViewClosed
from .notes_table import ListColors, NoteChangeRequested, NotesTable
from .notes_view import NoteOpened

# How often the list reads again what the watch timer may have added
RELOAD_SECONDS = 60
# How often GitHub is asked how many PRs are ready to deploy
DEPLOY_SECONDS = 5 * 60


class WatchView(Vertical):
    """The list: a search box and the status, then the items under a heading per project."""

    BINDINGS = [
        Binding("x", "toggle_done", "Mark done, or not done", group=ACTIONS),
        Binding("p", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("space", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("f", "next_status", "Show open, done or all", group=ACTIONS),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy", "Copy the item", group=ACTIONS),
        Binding("c", "collect", "Collect now: GitHub, then Slack (a paid run)", group=ACTIONS),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = DEFAULT_STATUS
        # The search box's text, is:open or is:done included: the dropdown only mirrors it
        self.query_text = f"is:{DEFAULT_STATUS}"
        # How many PRs are ready to deploy and their list on GitHub, once GitHub said
        self.ready: tuple[int, str] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="notes-controls"):
            yield Input(self.query_text, placeholder="Search items", id="search")
            yield Select(STATUSES, value=DEFAULT_STATUS, allow_blank=False, id="todo-status")
        yield Static("", id="notes-status")
        yield DashedRule(id="notes-rule")
        yield NotesTable(TODO, self._colors(), id="notes-table")

    def on_mount(self) -> None:
        self.call_after_refresh(self.load)
        self.set_interval(RELOAD_SECONDS, self._reload_quietly)
        self.ask_ready()
        self.set_interval(DEPLOY_SECONDS, self.ask_ready)

    @property
    def table(self) -> NotesTable:
        return self.query_one(NotesTable)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def set_colors(self) -> None:
        self.table.show(self.table.notes, self._colors())

    def _colors(self) -> ListColors:
        palette = self.app.palette
        return ListColors(
            date=palette["comment"], link=palette["blue"], heading=palette["yellow"], tag=palette["purple"], code=palette["orange"],
            extra_tag=palette["cyan"], failure=palette["red"],
        )

    # -- loading

    def load(self, query: str | None = None) -> None:
        if query is not None:
            self.query_text = query.strip()
        self.status, words = split_status(self.query_text)
        selector = self.query_one("#todo-status", Select)
        with selector.prevent(Select.Changed):
            selector.value = self.status
        if self.database is None:
            self._set_count(self.app.database_error)
            return
        items = shown_items(self.database, words, self.status)
        self.table.show(grouped(items, self.ready))
        status = "" if self.status == "all" else f" {self.status}"
        text = f"{len(items)}{status} {'item' if len(items) == 1 else 'items'}"
        self._set_count(f"{text} matching '{words}'" if words else text)

    def ask_ready(self) -> None:
        """Ask GitHub, in a thread, how many PRs are ready to deploy; a second or so, so never in the way."""
        try:
            github = from_taf(self.app.config).github
        except ValueError:
            return
        if github.deploy_repo:
            self.run_worker(lambda: self._ready(github), thread=True, group="ready", exclusive=True)

    def _ready(self, github) -> None:
        ready = ready_to_deploy(github)
        if ready is not None:
            self.app.call_from_thread(self._ready_known, ready)

    def _ready_known(self, ready: tuple[int, str]) -> None:
        if ready != self.ready:
            self.ready = ready
            self.load()

    def _reload_quietly(self) -> None:
        """Read again what the watch timer may have added, unless the search is being typed."""
        if self.display and self.database is not None and not self.query_one("#search", Input).has_focus:
            self.load()

    def _set_count(self, text: str) -> None:
        self.query_one("#notes-status", Static).update(text)

    def action_refresh(self) -> None:
        self.load()
        self.ask_ready()

    # -- searching

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    @on(Input.Submitted, "#search")
    def _search_submitted(self, event: Input.Submitted) -> None:
        self.table.focus()
        self.load(event.value)

    def on_key(self, event) -> None:
        # Escape in the search box goes back to the list without changing the search
        if event.key == "escape" and self.query_one("#search", Input).has_focus:
            event.stop()
            self.table.focus()

    def action_next_status(self) -> None:
        values = [value for _, value in STATUSES]
        self.query_one("#todo-status", Select).value = values[(values.index(self.status) + 1) % len(values)]

    @on(Select.Changed, "#todo-status")
    def _status_picked(self, event: Select.Changed) -> None:
        """Put is:open or is:done first in the search in place of the one there, or none for All, and run it."""
        event.stop()
        if event.value == self.status:
            return
        words = [word for word in self.query_one("#search", Input).value.split() if not STATUS_WORD.fullmatch(word)]
        query = " ".join([f"is:{event.value}", *words] if event.value != "all" else words)
        self.query_one("#search", Input).value = query
        self.table.focus()
        self.load(query)

    # -- changing items

    def action_toggle_done(self) -> None:
        if (item := self.table.selected()) is not None:
            self.change(NoteChangeRequested(item, done=not item.done))

    def action_toggle_pin(self) -> None:
        if (item := self.table.selected()) is not None:
            self.change(NoteChangeRequested(item, pinned=not item.pinned))

    @on(NoteChangeRequested)
    def _change_clicked(self, event: NoteChangeRequested) -> None:
        event.stop()
        self.change(event)

    def change(self, event: NoteChangeRequested) -> WatchItem | None:
        """Mark done or pin in its row, which stays where it is: the order and the status filter apply
        on the next load."""
        if self.database is None:
            return None
        if event.done is not None:
            item = set_done(self.database, event.note.id, event.done)
            self.notify("Marked done" if event.done else "Marked not done")
        elif event.pinned is not None:
            item = set_pinned(self.database, event.note.id, event.pinned)
            self.notify("Pinned" if event.pinned else "Unpinned")
        else:
            return None
        if item is not None:
            self.table.replace(item)
        return item

    def action_collect(self) -> None:
        self.app.query_one(WatchTab).collect()

    def action_copy(self) -> None:
        if (item := self.table.selected()) is not None:
            self.app.copy_to_clipboard(item.content)
            self.notify("Item copied")

    @on(DataTable.RowSelected, "#notes-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if (item := self.table.selected()) is not None:
            self.post_message(NoteOpened(item))


class WatchDetail(NoteDetail):
    """One item in full: its box and star as in the list, and the link to Slack or GitHub; it cannot be
    edited or deleted."""

    KIND = TODO
    CRUMB = "Watch"
    BINDINGS = [
        Binding("escape", "close", "Back to the list", group=ACTIONS),
        Binding("q", "close", "Back to the list", show=False),
        Binding("y", "copy", "Copy the selection, or the item", group=ACTIONS),
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]

    def on_mount(self) -> None:
        self.query_one("#btn-edit").display = False
        self.query_one("#btn-delete").display = False

    def action_edit(self) -> None:
        """Nothing: Slack or GitHub is where an item changes."""



class WatchTab(Vertical):
    """The Watch tab: the list, or one item in full in its place."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The item on show, or None while the list is
        self.viewing: WatchItem | None = None
        self.collecting = False
        # When the last collect ended, read again with the list
        self.collected_at: datetime | None = None

    def on_mount(self) -> None:
        self.read_collected_at()
        self.set_interval(1, self.show_collected_at)
        # For the timer's collects, which only the database tells of
        self.set_interval(15, self.read_collected_at)

    def read_collected_at(self) -> None:
        database = self.app.database
        self.collected_at = last_collected(database) if database is not None else None
        self.show_collected_at()

    def show_collected_at(self) -> None:
        """"5 minutes ago" by the footer's Collect, every second; nothing while a collect runs."""
        text = ""
        if self.collected_at is not None and not self.collecting:
            text = ago((datetime.now() - self.collected_at).total_seconds())
        self.app.query_one("#collected-at", Static).update(text)

    def compose(self) -> ComposeResult:
        # The Notes and Todos tabs' ids, for their styles
        yield WatchView(id="notes-list")
        yield WatchDetail(self.app.palette["purple"], id="note-detail")

    @property
    def list(self) -> WatchView:
        return self.query_one(WatchView)

    @property
    def detail(self) -> WatchDetail:
        return self.query_one(WatchDetail)

    def help_section(self) -> tuple[str, tuple]:
        if self.viewing is not None:
            return "Item", (WatchDetail.BINDINGS,)
        return "Watch", (WatchView.BINDINGS, NotesTable.BINDINGS)

    def tab_shown(self) -> None:
        if self.viewing is not None:
            self.detail.focus_content()
        else:
            self.list.load()
            self.list.table.focus()

    def set_colors(self) -> None:
        self.list.set_colors()
        self.detail.set_colors(self.app.palette["purple"])

    def reload(self) -> None:
        """The footer's Refresh."""
        self.list.action_refresh()

    # -- collecting now, as the timer does

    def collect(self) -> None:
        """Run `taf watch collect`: GitHub, then Slack, which takes a minute or more and costs a Claude
        run. Its own process, as the timer's: its lock keeps the two apart, its prints stay out of the
        screen, and it finishes even when taf quits first (then only its desktop notification tells)."""
        if self.collecting:
            return
        self.collecting = True
        button = self.app.query_one("#btn-collect")
        button.disabled = True
        button.label = "Collecting..."
        self.show_collected_at()
        self.run_worker(self._collect, thread=True, group="collect")

    def _collect(self) -> None:
        """In a worker thread: start the collect apart from taf, then look every second whether it
        ended. Quitting taf cancels the worker, which stops looking; Python would otherwise wait for
        this thread, and the terminal for the collect, before exiting."""
        worker = get_current_worker()
        command = [sys.executable, "-m", "taf", "watch", "collect"]
        # Files, not pipes: once taf is gone, a pipe nobody reads would break the collect's prints
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            try:
                # Its own session: quitting taf or closing the terminal does not stop it
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, text=True, start_new_session=True
                )
            except OSError as error:
                self.app.call_from_thread(self._collected, 1, "", str(error))
                return
            while (code := process.poll()) is None:
                if worker.is_cancelled:
                    return
                time.sleep(1)
            out.seek(0)
            err.seek(0)
            result = (code, out.read().strip(), err.read().strip())
        self.app.call_from_thread(self._collected, *result)

    def _collected(self, code: int, out: str, err: str) -> None:
        self.collecting = False
        button = self.app.query_one("#btn-collect")
        button.disabled = False
        button.label = "Collect"
        self.read_collected_at()
        # Done: the time by the button says so; only a failure has a message
        if code != 0:
            self.notify("\n".join(part for part in (out, err) if part) or "Collect failed", severity="error", timeout=10)
        self.list.action_refresh()

    def show_list(self) -> None:
        self.viewing = None
        self.detail.display = False
        self.list.display = True
        self.list.table.focus()
        self.app.refresh_footer()

    @on(NoteOpened)
    def _open(self, event: NoteOpened) -> None:
        event.stop()
        database = self.app.database
        item = (get_item(database, event.note.id) if database is not None else None) or event.note
        self.viewing = item
        self.detail.show(item)
        self.list.display = False
        self.detail.display = True
        self.detail.focus_content()
        self.app.refresh_footer()

    @on(ViewClosed)
    def _close(self, event: ViewClosed) -> None:
        event.stop()
        self.show_list()

    @on(NoteChangeRequested)
    def _change(self, event: NoteChangeRequested) -> None:
        """The detail's box or star: changes the item there and in its row in the list."""
        event.stop()
        item = self.list.change(event)
        if item is not None:
            self.detail.show_header(item)
            self.viewing = item
