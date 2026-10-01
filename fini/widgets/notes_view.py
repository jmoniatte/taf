import sqlite3

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Select, Static
from tui_kit.shortcuts import ACTIONS

from ..notes import (
    DEFAULT_STATUS,
    NOTE,
    STATUS_WORD,
    STATUSES,
    TAG,
    TODO,
    Note,
    list_notes,
    set_done,
    set_pinned,
    split_query,
    split_status,
    tag_counts,
)
from .dashed_rule import DashedRule
from .notes_table import ListColors, NoteChangeRequested, NotesTable, TagSelected, lead_width


# The Tags dropdown's first choice, which takes the tags out of the search; not a tag name, which has no space
ANY_TAG = "any tag"


class NoteOpened(Message):
    """The user asked to see one note in full."""

    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note = note


class EditRequested(Message):
    """The user asked to edit one note in the editor."""

    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note = note


class NewNoteRequested(Message):
    """The user asked to write a new note."""


def list_bindings(kind: str) -> list[Binding]:
    """The list's keys, worded for its kind; a todo also has x and f, for its status."""
    todo = kind == TODO
    return [
        Binding("n", "new", f"New {kind}", group=ACTIONS),
        Binding("e", "edit", f"Edit {kind}", group=ACTIONS),
        # Only terminals with the kitty keyboard protocol can tell this from enter; e works everywhere
        Binding("shift+enter", "edit", f"Edit {kind}", key_display="⇧+enter", group=ACTIONS),
        *([Binding("x", "toggle_done", "Mark done, or not done", group=ACTIONS)] if todo else []),
        Binding("p", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("space", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        *([Binding("f", "next_status", "Show open, done or all", group=ACTIONS)] if todo else []),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("number_sign", "tags", "Tags", key_display="#", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy", f"Copy the {kind}", group=ACTIONS),
    ]


class NotesView(Vertical):
    """The Notes tab's list, like YafYaf's: a search box, the Tags dropdown and New Note, then the
    notes, the last updated first. TodosView adds the status."""

    KIND = NOTE
    BINDINGS = list_bindings(NOTE)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = "all"
        # The search box's text, is:open or is:done and #tags included: the dropdowns only mirror it
        self.query_text = ""
        # The search's last tag, or None for any
        self.tag: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="notes-controls"):
            yield Input(self.query_text, placeholder=f"Search {self.KIND}s", id="search")
            # The search's tag, or Any tag; picking one puts "#name" in the search
            yield Select([("Any tag", ANY_TAG)], value=ANY_TAG, allow_blank=False, id="tag-selector")
            yield from self._compose_status()
            yield Button(f"New {self.KIND.capitalize()}", id="btn-new-note", classes="tinted")
        # The table's own header cannot hold the count, so it is hidden and drawn here instead
        with Horizontal(id="notes-header"):
            yield Static("", id="notes-header-lead")
            yield Static(self.KIND.capitalize(), id="notes-header-summary")
            yield Static("", id="notes-status")
        yield DashedRule(id="notes-header-rule")
        yield NotesTable(self.KIND, self._colors(), id="notes-table")

    def _compose_status(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        table = self.table
        # Line the header labels up with the cells, which are padded on both sides
        self.query_one("#notes-header-lead").styles.width = lead_width(self.KIND) + 2 * table.cell_padding
        self.query_one("#notes-header-summary").styles.padding = (0, table.cell_padding)
        self.call_after_refresh(self.load)

    @property
    def table(self) -> NotesTable:
        return self.query_one(NotesTable)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def set_colors(self) -> None:
        """Re-render the rows against a new palette; their colors are baked into Rich text."""
        self.table.show(self.table.notes, self._colors())

    def _colors(self) -> ListColors:
        palette = self.app.palette
        return ListColors(
            date=palette["comment"], link=palette["blue"], heading=palette["yellow"], tag=palette["purple"], code=palette["orange"], extra_tag=palette["cyan"]
        )

    # -- loading

    def load(self, query: str | None = None, cursor_on: int | None = None) -> None:
        """Read the notes again, with a new search if given, and the tags with their counts; the
        cursor goes to the note cursor_on names when it is listed."""
        if query is not None:
            self.query_text = query.strip()
        status, words = split_status(self.query_text)
        self._set_search_status(status)
        tags = split_query(words)[1]
        self.tag = tags[-1] if tags else None
        if self.database is None:
            self._set_count(self.app.database_error)
            return
        notes = list_notes(self.database, self.KIND, words, self.status)
        self.table.show(notes, cursor_on=cursor_on)
        counts = tag_counts(self.database, self.KIND)
        selector = self.query_one("#tag-selector", Select)
        # Changed here, not chosen: no message. A tag no note has is not in the list: "Any tag" stands for it
        with selector.prevent(Select.Changed):
            selector.set_options([("Any tag", ANY_TAG), *((f"{name} ({count})", name) for name, count in counts)])
            selector.value = self.tag if self.tag in dict(counts) else ANY_TAG
        self._set_count(self._describe(len(notes)))

    def _set_search_status(self, status: str) -> None:
        """A note has no status: is:open or is:done in its search is left out."""

    def _describe(self, count: int) -> str:
        noun = self.KIND if count == 1 else f"{self.KIND}s"
        status = "" if self.status == "all" else f" {self.status}"
        text = f"{count}{status} {noun}"
        words = split_status(self.query_text)[1]
        return f"{text} matching '{words}'" if words else text

    def _set_count(self, text: str) -> None:
        self.query_one("#notes-status", Static).update(text)

    def action_refresh(self) -> None:
        self.load()

    # -- searching and filtering

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

    def action_tags(self) -> None:
        selector = self.query_one("#tag-selector", Select)
        selector.focus()
        selector.action_show_overlay()

    @on(TagSelected)
    def _tag_clicked(self, event: TagSelected) -> None:
        event.stop()
        self.add_tag(event.name)

    @on(Select.Changed, "#tag-selector")
    def _tag_picked(self, event: Select.Changed) -> None:
        event.stop()
        name = None if event.value == ANY_TAG else str(event.value)
        # A Select also sends Changed when mounted, and the focus add_tag gives would open this tab
        if name != self.tag:
            self.add_tag(name)

    def add_tag(self, name: str | None) -> None:
        """Add "#name" to the search, or take every tag out for None (Any tag), keep its words, and
        run it; how every way of picking a tag ends up. A note may have many tags, so they add up."""
        search = self.query_one("#search", Input)
        words = search.value.split()
        if name is None:
            words = [word for word in words if not TAG.fullmatch(word)]
        elif name not in split_query(search.value)[1]:
            words.append(f"#{name}")
        self._run_search(" ".join(words))

    def _run_search(self, query: str) -> None:
        self.query_one("#search", Input).value = query
        self.table.focus()
        self.load(query)

    # -- changing notes

    def action_toggle_pin(self) -> None:
        if (note := self.table.selected()) is not None:
            self._change(NoteChangeRequested(note, pinned=not note.pinned))

    @on(NoteChangeRequested)
    def _change(self, event: NoteChangeRequested) -> None:
        event.stop()
        if self.database is None:
            return
        if event.done is not None:
            note = set_done(self.database, event.note.id, event.done)
            self.notify("Marked done" if event.done else "Marked not done")
        elif event.pinned is not None:
            note = set_pinned(self.database, event.note.id, event.pinned)
            self.notify("Pinned" if event.pinned else "Unpinned")
        else:
            return
        # In its row, without moving it, which would be confusing: the order and the status filter
        # apply on the next load
        if note is not None:
            self.table.replace(note)

    def action_copy(self) -> None:
        if (note := self.table.selected()) is not None:
            self.app.copy_to_clipboard(note.content)
            self.notify(f"{self.KIND.capitalize()} copied")

    @on(Button.Pressed, "#btn-new-note")
    def action_new(self) -> None:
        # A clicked button keeps focus; hand it back to the list the editor returns to
        self.table.focus()
        self.post_message(NewNoteRequested())

    def action_edit(self) -> None:
        if (note := self.table.selected()) is not None:
            self.post_message(EditRequested(note))

    @on(DataTable.RowSelected, "#notes-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if (note := self.table.selected()) is not None:
            self.post_message(NoteOpened(note))


class TodosView(NotesView):
    """The Todos tab's list: the notes' list with the status dropdown, open todos first shown."""

    KIND = TODO
    BINDINGS = list_bindings(TODO)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = DEFAULT_STATUS
        self.query_text = f"is:{DEFAULT_STATUS}"

    def _compose_status(self) -> ComposeResult:
        yield Select(STATUSES, value=DEFAULT_STATUS, allow_blank=False, id="todo-status")

    def _set_search_status(self, status: str) -> None:
        self.status = status
        # Changed here, not chosen: no message
        selector = self.query_one("#todo-status", Select)
        with selector.prevent(Select.Changed):
            selector.value = status

    def add_tag(self, name: str | None) -> None:
        """Put "#name" in the search in place of any other tag: a todo has one tag at most, so two
        would find nothing."""
        words = [word for word in self.query_one("#search", Input).value.split() if not TAG.fullmatch(word)]
        self._run_search(" ".join([*words, f"#{name}"] if name else words))

    def action_toggle_done(self) -> None:
        if (note := self.table.selected()) is not None:
            self._change(NoteChangeRequested(note, done=not note.done))

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
        self._run_search(" ".join([f"is:{event.value}", *words] if event.value != "all" else words))
