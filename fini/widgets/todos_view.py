import sqlite3

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Select, Static
from tui_kit.shortcuts import ACTIONS

from ..todos import (
    DEFAULT_STATUS,
    STATUS_WORD,
    STATUSES,
    TAG,
    Todo,
    list_todos,
    set_done,
    set_pinned,
    split_query,
    split_status,
    tag_counts,
)
from .dashed_rule import DashedRule
from .todos_table import LEAD_WIDTH, ListColors, TagSelected, TodoChangeRequested, TodosTable


# The Tags dropdown's first choice, which takes the tag out of the search; not a tag name, which has no space
ANY_TAG = "any tag"


class TodoOpened(Message):
    """The user asked to see one todo in full."""

    def __init__(self, todo: Todo) -> None:
        super().__init__()
        self.todo = todo


class EditRequested(Message):
    """The user asked to edit one todo in the editor."""

    def __init__(self, todo: Todo) -> None:
        super().__init__()
        self.todo = todo


class NewTodoRequested(Message):
    """The user asked to write a new todo."""


class TodosView(Vertical):
    """The Todos tab's list, like YafYaf's: a search box, the Tags and status dropdowns and New Todo,
    then the open todos, pinned first, or the done ones, or all."""

    BINDINGS = [
        Binding("n", "new", "New todo", group=ACTIONS),
        Binding("e", "edit", "Edit todo", group=ACTIONS),
        # Only terminals with the kitty keyboard protocol can tell this from enter; e works everywhere
        Binding("shift+enter", "edit", "Edit todo", key_display="⇧+enter", group=ACTIONS),
        Binding("x", "toggle_done", "Mark done, or not done", group=ACTIONS),
        Binding("p", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("space", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("f", "next_status", "Show open, done or all", group=ACTIONS),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("number_sign", "tags", "Tags", key_display="#", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy", "Copy the todo", group=ACTIONS),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.status = DEFAULT_STATUS
        # The search box's text, is:open or is:done and #tag included: the dropdowns only mirror it
        self.query_text = f"is:{DEFAULT_STATUS}"
        # The search's tag, or None for any
        self.tag: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="todos-controls"):
            yield Input(self.query_text, placeholder="Search todos", id="search")
            # The search's tag, or Any tag; picking one puts "#name" in the search
            yield Select([("Any tag", ANY_TAG)], value=ANY_TAG, allow_blank=False, id="tag-selector")
            yield Select(STATUSES, value=DEFAULT_STATUS, allow_blank=False, id="todo-status")
            yield Button("New Todo", id="btn-new-todo", classes="tinted")
        # The table's own header cannot hold the count, so it is hidden and drawn here instead
        with Horizontal(id="todos-header"):
            yield Static("", id="todos-header-lead")
            yield Static("Todo", id="todos-header-summary")
            yield Static("", id="todos-status")
        yield DashedRule(id="todos-header-rule")
        yield TodosTable(self._colors(), id="todos-table")

    def on_mount(self) -> None:
        table = self.table
        # Line the header labels up with the cells, which are padded on both sides
        self.query_one("#todos-header-lead").styles.width = LEAD_WIDTH + 2 * table.cell_padding
        self.query_one("#todos-header-summary").styles.padding = (0, table.cell_padding)
        self.call_after_refresh(self.load)

    @property
    def table(self) -> TodosTable:
        return self.query_one(TodosTable)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def set_colors(self) -> None:
        """Re-render the rows against a new palette; their colors are baked into Rich text."""
        self.table.show(self.table.todos, self._colors())

    def _colors(self) -> ListColors:
        palette = self.app.palette
        return ListColors(
            date=palette["comment"], link=palette["blue"], heading=palette["yellow"], tag=palette["purple"], code=palette["orange"], extra_tag=palette["cyan"]
        )

    # -- loading

    def load(self, query: str | None = None, cursor_on: int | None = None) -> None:
        """Read the todos again, with a new search if given, and the tags with their counts; the
        cursor goes to the todo cursor_on names when it is listed."""
        if query is not None:
            self.query_text = query.strip()
        self.status, words = split_status(self.query_text)
        tags = split_query(words)[1]
        self.tag = tags[-1] if tags else None
        # Changed here, not chosen: no message
        status = self.query_one("#todo-status", Select)
        with status.prevent(Select.Changed):
            status.value = self.status
        if self.database is None:
            self._set_status(self.app.database_error)
            return
        todos = list_todos(self.database, words, self.status)
        self.table.show(todos, cursor_on=cursor_on)
        counts = tag_counts(self.database)
        selector = self.query_one("#tag-selector", Select)
        # Changed here, not chosen: no message. A tag no todo has is not in the list: "Any tag" stands for it
        with selector.prevent(Select.Changed):
            selector.set_options([("Any tag", ANY_TAG), *((f"{name} ({count})", name) for name, count in counts)])
            selector.value = self.tag if self.tag in dict(counts) else ANY_TAG
        self._set_status(self._describe(len(todos)))

    def _describe(self, count: int) -> str:
        noun = "todo" if count == 1 else "todos"
        status = "" if self.status == "all" else f" {self.status}"
        text = f"{count}{status} {noun}"
        words = split_status(self.query_text)[1]
        return f"{text} matching '{words}'" if words else text

    def _set_status(self, text: str) -> None:
        self.query_one("#todos-status", Static).update(text)

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
        self.add_tag(None if event.value == ANY_TAG else str(event.value))

    def add_tag(self, name: str | None) -> None:
        """Put "#name" in the search in place of any other tag, or only take them out for None (Any tag),
        keep its words, and run it; how every way of picking a tag ends up. A todo has one tag at
        most, so two would find nothing."""
        search = self.query_one("#search", Input)
        words = [word for word in search.value.split() if not TAG.fullmatch(word)]
        search.value = " ".join([*words, f"#{name}"] if name else words)
        self.table.focus()
        self.load(search.value)

    def action_next_status(self) -> None:
        values = [value for _, value in STATUSES]
        self.query_one("#todo-status", Select).value = values[(values.index(self.status) + 1) % len(values)]

    @on(Select.Changed, "#todo-status")
    def _status_picked(self, event: Select.Changed) -> None:
        """Put is:open or is:done first in the search in place of the one there, or none for All, and run it."""
        event.stop()
        if event.value == self.status:
            return
        search = self.query_one("#search", Input)
        words = [word for word in search.value.split() if not STATUS_WORD.fullmatch(word)]
        search.value = " ".join([f"is:{event.value}", *words] if event.value != "all" else words)
        self.table.focus()
        self.load(search.value)

    # -- changing todos

    def action_toggle_done(self) -> None:
        if (todo := self.table.selected()) is not None:
            self._change(TodoChangeRequested(todo, done=not todo.done))

    def action_toggle_pin(self) -> None:
        if (todo := self.table.selected()) is not None:
            self._change(TodoChangeRequested(todo, pinned=not todo.pinned))

    @on(TodoChangeRequested)
    def _change(self, event: TodoChangeRequested) -> None:
        event.stop()
        if self.database is None:
            return
        if event.done is not None:
            todo = set_done(self.database, event.todo.id, event.done)
            self.notify("Marked done" if event.done else "Marked not done")
        elif event.pinned is not None:
            todo = set_pinned(self.database, event.todo.id, event.pinned)
            self.notify("Pinned" if event.pinned else "Unpinned")
        else:
            return
        # In its row, without moving it, which would be confusing: the order and the status filter
        # apply on the next load
        if todo is not None:
            self.table.replace(todo)

    def action_copy(self) -> None:
        if (todo := self.table.selected()) is not None:
            self.app.copy_to_clipboard(todo.content)
            self.notify("Todo copied")

    @on(Button.Pressed, "#btn-new-todo")
    def action_new(self) -> None:
        # A clicked button keeps focus; hand it back to the list the editor returns to
        self.table.focus()
        self.post_message(NewTodoRequested())

    def action_edit(self) -> None:
        if (todo := self.table.selected()) is not None:
            self.post_message(EditRequested(todo))

    @on(DataTable.RowSelected, "#todos-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if (todo := self.table.selected()) is not None:
            self.post_message(TodoOpened(todo))
