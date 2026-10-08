"""What the Notes, Todos and Watch tabs share: the list, or one item in full in its place, as
yafyaf-tui's MainArea switches between its list and YafDetail."""

import sqlite3

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical

from .list_view import ItemOpened, ListView
from .note_detail import NoteDetail, ViewClosed
from .notes_table import ItemChangeRequested, ListItem, NotesTable


class ListTab(Vertical):
    """A tab of LIST, with DETAIL in its place while an item is on show (viewing). A subclass says how
    to read an item again (fetch)."""

    LIST: type[ListView] = ListView
    DETAIL: type[NoteDetail] = NoteDetail
    # Help's title for the list
    TITLE = ""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The item on show, or None while the list is
        self.viewing: ListItem | None = None

    def compose(self) -> ComposeResult:
        # The same ids in every tab, for their styles: a test scopes its queries to the tab
        yield self.LIST(id="notes-list")
        yield self.DETAIL(self.app.palette["purple"], id="note-detail")

    @property
    def list(self) -> ListView:
        return self.query_one(ListView)

    @property
    def detail(self) -> NoteDetail:
        return self.query_one(NoteDetail)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def fetch(self, item: ListItem) -> ListItem | None:
        raise NotImplementedError

    def help_section(self) -> tuple[str, tuple]:
        """The title and the keys of Help's right column: the list's, or the item's while one is on show."""
        if self.viewing is not None:
            return self.DETAIL.NOUN.capitalize(), (self.DETAIL.BINDINGS,)
        return self.TITLE, (self.LIST.BINDINGS, NotesTable.BINDINGS)

    def tab_shown(self) -> None:
        if self.viewing is not None:
            self.detail.focus_content()
        else:
            self.list.table.focus()

    def set_colors(self) -> None:
        self.list.set_colors()
        self.detail.set_colors(self.app.palette["purple"])

    def reload(self) -> None:
        self.list.action_refresh()

    def show_list(self) -> None:
        self.viewing = None
        self.detail.display = False
        self.list.display = True
        self.list.table.focus()
        self.app.refresh_footer()

    def show_item(self, item: ListItem) -> None:
        self.viewing = item
        self.detail.show(item)
        self.list.display = False
        self.detail.display = True
        self.detail.focus_content()
        self.app.refresh_footer()

    @on(ItemOpened)
    def _open(self, event: ItemOpened) -> None:
        event.stop()
        # The database's copy, so a change made since the list loaded shows
        if self.database is not None:
            self.show_item(self.fetch(event.item) or event.item)

    @on(ViewClosed)
    def _close(self, event: ViewClosed) -> None:
        event.stop()
        self.show_list()

    @on(ItemChangeRequested)
    def _change(self, event: ItemChangeRequested) -> None:
        """The view's box or star: marks done or pins there, and in the item's row in the list."""
        event.stop()
        item = self.list.change(event)
        if item is not None:
            self.detail.show_header(item)
            self.viewing = item
