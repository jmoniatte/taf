from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..todos import Todo, long_date
from .todo_markdown import TodoMarkdown
from .todos_table import DONE, OPEN, PINNED, UNPINNED, TodoChangeRequested
from .todos_view import EditRequested


class ViewClosed(Message):
    """The user asked to go back to the list."""


class DoneBox(Static):
    """The todo's check box, as in the list; a click marks it done or not."""

    def show(self, todo: Todo) -> None:
        # Two spaces after it, as in the list, which also widen the target: Alacritty draws the
        # Nerd Font box wider than its cell
        self.update(f"{DONE if todo.done else OPEN}  ")

    def on_click(self) -> None:
        todo = self.parent.parent.todo
        if todo is not None:
            self.post_message(TodoChangeRequested(todo, done=not todo.done))


class PinStar(Static):
    """The todo's star: yellow when pinned, an outline when not; a click pins or unpins."""

    def show(self, todo: Todo) -> None:
        # The spaces after it widen the target and keep the date clear of it: Alacritty draws the
        # star wider than its cell
        self.update(f"{PINNED if todo.pinned else UNPINNED}  ")
        self.set_class(todo.pinned, "-pinned")

    def on_click(self) -> None:
        todo = self.parent.parent.todo
        if todo is not None:
            self.post_message(TodoChangeRequested(todo, pinned=not todo.pinned))


class TodoDetail(Vertical):
    """One todo rendered as markdown in place of the list, under a line with its check box and star,
    as in the list, and when it was last updated."""

    BINDINGS = [
        Binding("escape", "close", "Back to the list", group=ACTIONS),
        # Takes q from the app while the view is up, so it leaves the view rather than the app
        Binding("q", "close", "Back to the list", show=False),
        Binding("e", "edit", "Edit todo", group=ACTIONS),
        Binding("shift+enter", "edit", "Edit todo", key_display="⇧+enter", group=ACTIONS),
        Binding("y", "copy", "Copy the selection, or the todo", group=ACTIONS),
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]

    def __init__(self, tag_color: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.todo: Todo | None = None
        self._tag_color = tag_color

    def compose(self) -> ComposeResult:
        with Horizontal(id="todo-detail-header"):
            yield DoneBox("", id="todo-detail-done")
            yield PinStar("", id="todo-detail-pin")
            yield Static("", id="todo-detail-date")
        with VerticalScroll(id="todo-detail-scroll"):
            yield TodoMarkdown(tag_color=self._tag_color, id="todo-detail-markdown")

    def show(self, todo: Todo) -> None:
        self.show_header(todo)
        self.query_one(TodoMarkdown).update(todo.content)
        self.query_one(VerticalScroll).scroll_home(animate=False)

    def show_header(self, todo: Todo) -> None:
        """The box, the star and the date for the todo as it is now; the content stays as it was."""
        self.todo = todo
        self.query_one(DoneBox).show(todo)
        self.query_one(PinStar).show(todo)
        self.query_one("#todo-detail-date", Static).update(f"Updated {long_date(todo.updated_at)}")

    def focus_content(self) -> None:
        self.query_one(VerticalScroll).focus()

    def set_colors(self, tag_color: str) -> None:
        """Repaint the tags against a new palette; the markdown bakes their color in."""
        markdown = self.query_one(TodoMarkdown)
        markdown.tag_color = tag_color
        if self.todo is not None:
            markdown.update(self.todo.content)

    def action_close(self) -> None:
        self.post_message(ViewClosed())

    def action_edit(self) -> None:
        if self.todo is not None:
            self.post_message(EditRequested(self.todo))

    def action_copy(self) -> None:
        """Copy the text selected with the mouse, or the whole todo when nothing is selected."""
        if self.todo is None:
            return
        selection = self.screen.get_selected_text()
        self.app.copy_to_clipboard(selection or self.todo.content)
        self.notify("Selection copied" if selection else "Todo copied")

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()
