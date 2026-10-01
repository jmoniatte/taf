import sqlite3

from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from tui_kit.dialog import ConfirmDialog

from ..editor import EditorError, edit_text, with_front_matter, without_front_matter
from ..todos import Todo, create_todo, delete_todo, front_matter, get_todo, set_done, set_pinned, update_todo
from .todo_detail import TodoDetail, ViewClosed
from .todos_table import TagSelected, TodoChangeRequested, TodosTable
from .todos_view import EditRequested, NewTodoRequested, TodoOpened, TodosView


class TodosTab(Vertical):
    """The Todos tab: the list, or one todo in full in its place, as in yafyaf-tui. Editing returns
    where it started, the list or the todo."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The todo on show, or None while the list is
        self.viewing: Todo | None = None

    def compose(self) -> ComposeResult:
        yield TodosView(id="todos-list")
        yield TodoDetail(self.app.palette["purple"], id="todo-detail")

    @property
    def list(self) -> TodosView:
        return self.query_one(TodosView)

    @property
    def detail(self) -> TodoDetail:
        return self.query_one(TodoDetail)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def help_section(self) -> tuple[str, tuple]:
        """The title and the keys of Help's right column: the list's, or the todo's while one is on show."""
        if self.viewing is not None:
            return "Todo", (TodoDetail.BINDINGS,)
        return "Todos", (TodosView.BINDINGS, TodosTable.BINDINGS)

    def tab_shown(self) -> None:
        if self.viewing is not None:
            self.detail.focus_content()
        else:
            self.list.table.focus()

    def set_colors(self) -> None:
        self.list.set_colors()
        self.detail.set_colors(self.app.palette["purple"])

    # -- the list or one todo

    def show_list(self) -> None:
        self.viewing = None
        self.detail.display = False
        self.list.display = True
        self.list.table.focus()
        self.app.refresh_footer()

    def show_todo(self, todo: Todo) -> None:
        self.viewing = todo
        self.detail.show(todo)
        self.list.display = False
        self.detail.display = True
        self.detail.focus_content()
        self.app.refresh_footer()

    @on(TodoOpened)
    def _open(self, event: TodoOpened) -> None:
        event.stop()
        # The database's copy, so a change made since the list loaded shows
        if self.database is not None:
            self.show_todo(get_todo(self.database, event.todo.id) or event.todo)

    @on(ViewClosed)
    def _close(self, event: ViewClosed) -> None:
        event.stop()
        self.show_list()

    @on(TodoChangeRequested)
    def _change(self, event: TodoChangeRequested) -> None:
        """The view's box or star: marks done or pins in place, the todo's row in the list too."""
        event.stop()
        if self.database is None:
            return
        if event.done is not None:
            todo = set_done(self.database, event.todo.id, event.done)
            message = "Marked done" if event.done else "Marked not done"
        elif event.pinned is not None:
            todo = set_pinned(self.database, event.todo.id, event.pinned)
            message = "Pinned" if event.pinned else "Unpinned"
        else:
            return
        if todo is not None:
            self.notify(message)
            self.detail.show_header(todo)
            self.viewing = todo
            self.list.table.replace(todo)

    @on(TagSelected)
    def _tag_selected(self, event: TagSelected) -> None:
        """A tag clicked in a todo filters the list on it, so that means going back to the list."""
        event.stop()
        self.show_list()
        self.list.add_tag(event.name)

    # -- editing

    @on(NewTodoRequested)
    def _new(self, event: NewTodoRequested) -> None:
        event.stop()
        self.edit(None)

    @on(EditRequested)
    def _edit_requested(self, event: EditRequested) -> None:
        event.stop()
        self.edit(event.todo)

    def edit_viewed(self) -> None:
        """Edit the todo on show; the footer's Edit button."""
        if self.viewing is not None:
            self.edit(self.viewing)

    def edit(self, todo: Todo | None) -> None:
        """Edit the todo in $EDITOR, or write a new one, then go back where this started, the list or
        the todo; emptied, a todo is deleted once confirmed."""
        if self.database is None:
            return
        if todo is not None:
            # The database's copy, so a change made since the list loaded is not lost
            todo = get_todo(self.database, todo.id) or todo
        original = todo.content if todo else ""
        # A todo's dates and pin, for the eye only: what is changed there is not saved
        text = with_front_matter(front_matter(todo), original) if todo else original
        content = ""
        failure: Exception | None = None
        try:
            with self.app.suspend():
                try:
                    content = without_front_matter(edit_text(text, "fini-todo-"))
                except EditorError as error:
                    # Textual only restores the TUI when the suspend block exits without raising
                    failure = error
        except SuspendNotSupported as error:
            failure = error
        if failure is not None:
            self.notify(str(failure), severity="error")
            return
        if content == original.strip("\r\n"):
            return
        if not content.strip():
            if todo is not None:
                self._confirm_delete(todo)
            return
        if todo is None:
            saved = create_todo(self.database, content)
            self.notify("Todo created")
        else:
            saved = update_todo(self.database, todo.id, content)
            self.notify("Todo updated")
        self.list.load(cursor_on=saved.id)
        if self.viewing is not None:
            self.show_todo(saved)

    def delete_viewed(self) -> None:
        """Delete the todo on show, once confirmed; the footer's Delete button."""
        if self.viewing is not None:
            self._confirm_delete(self.viewing)

    def _confirm_delete(self, todo: Todo) -> None:
        dialog = ConfirmDialog("Delete this todo?", title="Delete Todo", confirm_label="Delete", cancel_label="Cancel", detail=todo.summary)

        def chosen(confirmed: bool | None) -> None:
            if confirmed:
                delete_todo(self.database, todo.id)
                self.notify("Todo deleted")
                self.list.load()
                if self.viewing is not None:
                    self.show_list()

        self.app.push_screen(dialog, chosen)
