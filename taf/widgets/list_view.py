"""What the Notes, Todos and Watch lists share: the search box, the count over a dashed rule, and the
table; with a status, the status dropdown, done and the f key."""

import sqlite3

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Select, Static

from ..notes import DEFAULT_STATUS, STATUS_WORD, STATUSES, split_status
from ..watch.view import Group
from .dashed_rule import DashedRule
from .items_table import ItemChangeRequested, ListItem, ItemsTable, list_colors


class ItemOpened(Message):
    """The user asked to see one note, todo or watch item in full."""

    def __init__(self, item: ListItem) -> None:
        super().__init__()
        self.item = item


class ListView(Vertical):
    """A search box and the controls a subclass adds, then the count over a dashed rule and the table,
    which has no header. With HAS_DONE, the search holds is:open or is:done, as on GitHub, which the
    status dropdown only mirrors. A subclass says what to list (fetch) and how to mark an item done
    or pinned."""

    # What the count, the search box and the messages call one
    NOUN = ""
    # Items can be done: a check box in each row, x, and the open, done or all status
    HAS_DONE = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = DEFAULT_STATUS if self.HAS_DONE else "all"
        # The search box's text, is:open or is:done and #tags included: the dropdowns only mirror it
        self.query_text = f"is:{DEFAULT_STATUS}" if self.HAS_DONE else ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="items-controls"):
            yield Input(self.query_text, placeholder=f"Search {self.NOUN}s", id="search")
            yield from self.compose_controls()
        yield Static("", id="items-status")
        yield DashedRule(id="items-rule")
        yield ItemsTable(self.HAS_DONE, list_colors(self.app.palette), id="items-table")

    def compose_controls(self) -> ComposeResult:
        if self.HAS_DONE:
            yield Select(STATUSES, value=DEFAULT_STATUS, allow_blank=False, id="status-selector")

    def on_mount(self) -> None:
        self.call_after_refresh(self.load)

    @property
    def table(self) -> ItemsTable:
        return self.query_one(ItemsTable)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def set_colors(self) -> None:
        """Re-render the rows against a new palette; their colors are baked into Rich text."""
        self.table.recolor(list_colors(self.app.palette))

    # -- what a subclass says

    def fetch(self, words: str) -> list[Group | ListItem]:
        raise NotImplementedError

    def mark_done(self, item_id: int, done: bool) -> ListItem | None:
        raise NotImplementedError

    def mark_pinned(self, item_id: int, pinned: bool) -> ListItem | None:
        raise NotImplementedError

    def loaded(self, words: str) -> None:
        """After each load, for what else follows the search."""

    # -- loading

    def load(self, query: str | None = None, cursor_on: int | None = None) -> None:
        """Read the items again, with a new search if given; the cursor goes to the one cursor_on
        names when it is listed."""
        if query is not None:
            self.query_text = query.strip()
        status, words = split_status(self.query_text)
        if self.HAS_DONE:
            self.status = status
            selector = self.query_one("#status-selector", Select)
            # Changed here, not chosen: no message
            with selector.prevent(Select.Changed):
                selector.value = status
        if self.database is None:
            self._set_count(self.app.database_error)
            return
        rows = self.fetch(words)
        self.table.show(rows, cursor_on=cursor_on)
        self.loaded(words)
        self._set_count(self.describe(sum(not isinstance(row, Group) for row in rows), words))

    def describe(self, count: int, words: str) -> str:
        """"2 open todos", "1 note matching 'x'"."""
        noun = self.NOUN if count == 1 else f"{self.NOUN}s"
        status = "" if self.status == "all" else f" {self.status}"
        text = f"{count}{status} {noun}"
        return f"{text} matching '{words}'" if words else text

    def _set_count(self, text: str) -> None:
        self.query_one("#items-status", Static).update(text)

    def action_refresh(self) -> None:
        self.load()

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

    def run_search(self, query: str) -> None:
        self.query_one("#search", Input).value = query
        self.table.focus()
        self.load(query)

    def action_next_status(self) -> None:
        values = [value for _, value in STATUSES]
        self.query_one("#status-selector", Select).value = values[(values.index(self.status) + 1) % len(values)]

    @on(Select.Changed, "#status-selector")
    def _status_picked(self, event: Select.Changed) -> None:
        """Put is:open or is:done first in the search in place of the one there, or none for All, and run it."""
        event.stop()
        if event.value == self.status:
            return
        words = [word for word in self.query_one("#search", Input).value.split() if not STATUS_WORD.fullmatch(word)]
        self.run_search(" ".join([f"is:{event.value}", *words] if event.value != "all" else words))

    # -- changing items

    def action_toggle_done(self) -> None:
        if (item := self.table.selected()) is not None:
            self.change(ItemChangeRequested(item, done=not item.done))

    def action_toggle_pin(self) -> None:
        if (item := self.table.selected()) is not None:
            self.change(ItemChangeRequested(item, pinned=not item.pinned))

    @on(ItemChangeRequested)
    def _change_clicked(self, event: ItemChangeRequested) -> None:
        event.stop()
        self.change(event)

    def change(self, event: ItemChangeRequested) -> ListItem | None:
        """Mark done or pin in the item's row, which stays where it is, as moving it would be
        confusing: the order and the status filter apply on the next load."""
        if self.database is None:
            return None
        if event.done is not None:
            item = self.mark_done(event.item.id, event.done)
            message = "Marked done" if event.done else "Marked not done"
        elif event.pinned is not None:
            item = self.mark_pinned(event.item.id, event.pinned)
            message = "Pinned" if event.pinned else "Unpinned"
        else:
            return None
        if item is not None:
            self.notify(message)
            self.table.replace(item)
        return item

    def action_copy(self) -> None:
        if (item := self.table.selected()) is not None:
            self.app.copy_to_clipboard(item.content)
            self.notify(f"{self.NOUN.capitalize()} copied")

    @on(DataTable.RowSelected, "#items-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if (item := self.table.selected()) is not None:
            self.post_message(ItemOpened(item))
