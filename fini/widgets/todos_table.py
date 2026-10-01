"""The Todos tab's table: a check box and a star, then the summary with its links and tags."""

import re
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..todos import Todo, find_tags

# Nerd Font check boxes (nf-md-checkbox_blank_outline, nf-md-checkbox_marked), as outils uses Nerd Font icons
OPEN = "\U000f0131"
DONE = "\U000f0132"
PINNED = "★"
UNPINNED = "☆"
# The check box, two spaces, the star
LEAD_WIDTH = 4
HEADING = re.compile(r"#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
# A markdown link, or a bare URL; trailing punctuation and closing brackets are left out of a bare URL
LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<target>[^)\s]+)\)|(?P<url>https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"])")
# Inline code first, so a URL or a tag inside backticks stays code, as in the view
INLINE = re.compile(r"`(?P<code>[^`\n]+)`|" + LINK.pattern)


@dataclass(frozen=True, slots=True)
class ListColors:
    """The palette entries the list bakes into Rich text, where TCSS variables do not reach."""

    date: str = ""
    link: str = ""
    heading: str = ""
    tag: str = ""
    code: str = ""
    # The todo's tags shown after its text
    extra_tag: str = ""


class TodoChangeRequested(Message):
    """The user marked a todo done or not done, or pinned or unpinned it; None leaves that field as it is."""

    def __init__(self, todo: Todo, done: bool | None = None, pinned: bool | None = None) -> None:
        super().__init__()
        self.todo = todo
        self.done = done
        self.pinned = pinned


class TagSelected(Message):
    """A tag in a summary was clicked, to filter the list on."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


def summary_text(summary: str, colors: ListColors, *, done: bool = False, tags: tuple[str, ...] = ()) -> Text:
    """Links by their label in the link color, inline code without its backticks in the code color,
    a markdown heading without its # marks, tags in the tag color with their name in the style's
    meta for a click, then the todo's other tags, those not in the summary, in the extra tag color;
    all of it gray once done."""
    heading = HEADING.match(summary)
    if heading:
        summary = heading.group(1)
    text = Text(style=colors.heading if heading and colors.heading else "")
    code: list[tuple[int, int]] = []
    end = 0
    for match in INLINE.finditer(summary):
        text.append(summary[end : match.start()])
        if match.group("code") is not None:
            code.append((len(text), len(text) + len(match.group("code"))))
            text.append(match.group("code"), style=colors.code or "")
        else:
            url = match.group("target") or match.group("url")
            text.append(match.group("label") or url, style=Style(color=colors.link or None, link=url))
        end = match.end()
    text.append(summary[end:])
    shown = set()
    for start, stop, name in find_tags(text.plain):
        if not any(a <= start < b for a, b in code):
            text.stylize(Style(color=colors.tag or None, meta={"tag": name}), start, stop)
            shown.add(name)
    for name in tags:
        if name not in shown:
            text.append(" ")
            text.append(f"#{name}", style=Style(color=colors.extra_tag or None, meta={"tag": name}))
    if done:
        text.stylize(Style(color=colors.date or None))
    return text


class TodosTable(DataTable):
    """One row per todo, keyed by its id. A click on the check box or the star changes the todo,
    on a tag filters the list, on a link opens it."""

    BINDINGS = [
        Binding("enter", "select_cursor", "View todo", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, colors: ListColors, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=False, show_header=False, cursor_foreground_priority="renderable", **kwargs)
        self._colors = colors
        self.todos: list[Todo] = []
        # Clicks in the first column left of this x hit the box, the others the star
        self._star_x = self.cell_padding + 2

    def on_mount(self) -> None:
        self.add_column("", key="lead", width=LEAD_WIDTH)
        self.add_column("Todo", key="summary")

    def show(self, todos: list[Todo], colors: ListColors | None = None, cursor_on: int | None = None) -> None:
        """Show the todos, with the cursor on the todo cursor_on names, else on the todo it was on,
        else on the same row."""
        self._colors = colors or self._colors
        current = self.todos[self.cursor_row].id if 0 <= self.cursor_row < len(self.todos) else None
        current = cursor_on or current
        row = self.cursor_row
        self.clear()
        self.todos = list(todos)
        for todo in todos:
            # Text, not str: the table reads strings as markup, which eats brackets in a summary
            self.add_row(self._lead(todo), self._summary(todo), key=str(todo.id))
        ids = [todo.id for todo in todos]
        if ids:
            self.move_cursor(row=ids.index(current) if current in ids else min(max(row, 0), len(ids) - 1))

    def replace(self, todo: Todo) -> None:
        """Show the todo's new state in its row, which stays where it is."""
        for index, shown in enumerate(self.todos):
            if shown.id == todo.id:
                self.todos[index] = todo
                self.update_cell(str(todo.id), "lead", self._lead(todo))
                self.update_cell(str(todo.id), "summary", self._summary(todo))
                return

    def selected(self) -> Todo | None:
        return self.todos[self.cursor_row] if 0 <= self.cursor_row < len(self.todos) else None

    def _lead(self, todo: Todo) -> Text:
        text = Text(DONE if todo.done else OPEN, style=self._colors.date)
        text.append("  ")
        text.append(PINNED if todo.pinned else UNPINNED, style=self._colors.heading if todo.pinned else self._colors.date)
        return text

    def _summary(self, todo: Todo) -> Text:
        return summary_text(todo.summary, self._colors, done=todo.done, tags=todo.tags)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # The highlight follows the pointer, as it does with the arrow keys
        row = event.style.meta.get("row")
        if isinstance(row, int) and 0 <= row < self.row_count and row != self.cursor_row:
            self.move_cursor(row=row)

    async def _on_click(self, event: events.Click) -> None:
        """A click on the box marks done, on the star pins, by which half of the first column it hit:
        a terminal may draw the Nerd Font box wider than its cell, so the cell clicked is not always
        the one the icon was written to. A tag filters, a link opens, anything else opens the todo."""
        row = event.style.meta.get("row")
        if not (isinstance(row, int) and 0 <= row < self.row_count):
            return
        event.prevent_default()
        event.stop()
        todo = self.todos[row]
        self.move_cursor(row=row)
        if event.style.meta.get("column") == 0:
            if event.x < self._star_x:
                self.post_message(TodoChangeRequested(todo, done=not todo.done))
            else:
                self.post_message(TodoChangeRequested(todo, pinned=not todo.pinned))
        elif tag := event.style.meta.get("tag"):
            self.post_message(TagSelected(tag))
        elif event.style.link:
            self.app.open_url(event.style.link)
        else:
            self.action_select_cursor()
