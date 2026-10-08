"""The table of the Notes, Todos and Watch tabs: the id, a todo's check box and the star, then the
summary with its links and tags. The Watch tab's holds its items under a heading per project."""

import re
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..notes import HEADING, Note, find_tags
from ..watch.view import Group, WatchItem

# What a row of the table shows: a note, a todo, or a watch item, which reads like a todo
ListItem = Note | WatchItem

# A watch item's links, each a Nerd Font icon a click opens, before its summary: nf-md-slack,
# nf-md-github, and nf-md-numeric_7_circle for one the user or an agent added (7 is how the user signs)
LINK_ICONS = {"slack": "\U000f04b1", "github": "\U000f02a4", "added": "\U000f0cac"}
# Nerd Font check boxes (nf-md-checkbox_blank_outline, nf-md-checkbox_marked), as outils uses Nerd Font icons
OPEN = "\U000f0131"
DONE = "\U000f0132"
PINNED = "★"
UNPINNED = "☆"
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
    # The note's tags shown after its text
    extra_tag: str = ""
    # Failing CI, and CI that passes again
    failure: str = ""
    success: str = ""


def list_colors(palette: dict[str, str]) -> ListColors:
    return ListColors(
        date=palette["comment"], link=palette["blue"], heading=palette["yellow"], tag=palette["purple"],
        code=palette["orange"], extra_tag=palette["cyan"], failure=palette["red"], success=palette["green"],
    )


class ItemChangeRequested(Message):
    """The user marked a todo or a watch item done or not done, or pinned or unpinned one; None leaves
    that field as it is."""

    def __init__(self, item: ListItem, done: bool | None = None, pinned: bool | None = None) -> None:
        super().__init__()
        self.item = item
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
    meta for a click, then the note's other tags, those not in the summary, in the extra tag color;
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


def link_icons(links: list[tuple[str, str | None]], colors: ListColors) -> Text:
    """A watch item's links as icons a click opens, as its row starts and its view's header shows them."""
    icons = Text()
    for kind, url in links:
        icons.append("  " if icons else "")
        icons.append(LINK_ICONS[kind], style=Style(color=colors.link or None, link=url))
    return icons


class Spacer:
    """The blank row before a project's heading, after the first."""

    def __init__(self, before: Group) -> None:
        self.before = before


Row = Group | Spacer | ListItem


def row_key(row: Row) -> str:
    """A row's key: a note's or a todo's id, as the cursor_on of load and show, a watch item's own,
    as its ids are another count, or a heading's."""
    if isinstance(row, Spacer):
        return f"space:{row.before.name}"
    if isinstance(row, Group):
        return f"project:{row.name}"
    return row.row_key


class ItemsTable(DataTable):
    """One row per note, todo or watch item, keyed by row_key, and the Watch tab's headings and blank
    rows, which the cursor skips. A click on the check box or the star changes the item, on a tag
    filters the list, on a link opens it.

    Cells carry their own one-space padding, the table none: a project's heading then runs on from
    the id column into the next ones, from the left edge, as one line of text."""

    BINDINGS = [
        Binding("enter", "select_cursor", "View", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, has_box: bool, colors: ListColors, **kwargs) -> None:
        super().__init__(
            cursor_type="row", zebra_stripes=False, show_header=False, cursor_foreground_priority="renderable", cell_padding=0, **kwargs
        )
        # A check box before each star: the items can be done
        self.has_box = has_box
        self._colors = colors
        # What show was given, to show again in new colors
        self._shown: list[Group | ListItem] = []
        # The rows, a blank one before each heading but the first; not `rows`, which DataTable has
        self.lines: list[Row] = []
        # Clicks on a todo's box and star column left of this x, from the column's start, hit the box:
        # the cell's space, the box and the next space
        self._star_x = 3 if has_box else 0
        # The longest id shown, which the id column fits
        self._id_digits = 1

    def on_mount(self) -> None:
        self.add_column("", key="id", width=3)
        # The box, two spaces and the star, or the star alone; and the cell's own spaces
        self.add_column("", key="lead", width=(4 if self.has_box else 1) + 2)
        self.add_column("Summary", key="summary")

    @property
    def id_width(self) -> int:
        """The id column's width, its padding included."""
        return self.columns["id"].get_render_width(self)

    def show(self, shown: list[Group | ListItem], colors: ListColors | None = None, cursor_on: int | str | None = None) -> None:
        """Show the items and headings, with the cursor on the row cursor_on names (a note's id, or a
        row key), else on the row it was on, else on the same line, and never on a heading or a blank row."""
        self._colors = colors or self._colors
        self._shown = list(shown)
        current = row_key(self.lines[self.cursor_row]) if 0 <= self.cursor_row < len(self.lines) else None
        current = str(cursor_on) if cursor_on is not None else current
        line = self.cursor_row
        self.clear()
        self.lines = []
        for row in shown:
            if isinstance(row, Group) and self.lines:
                self.lines.append(Spacer(row))
            self.lines.append(row)
        self._id_digits = max((len(str(row.id)) for row in shown if not isinstance(row, Group)), default=1)
        self.columns["id"].width = self._id_digits + 2
        for row in self.lines:
            # Text, not str: the table reads strings as markup, which eats brackets in a summary
            self.add_row(*self._cells(row), key=row_key(row))
        keys = [row_key(row) for row in self.lines]
        if keys:
            self.move_cursor(row=keys.index(current) if current in keys else min(max(line, 0), len(keys) - 1))
            self._step_off_headings(1)

    def recolor(self, colors: ListColors) -> None:
        self.show(self._shown, colors)

    def replace(self, item: ListItem) -> None:
        """Show the item's new state in its row, which stays where it is."""
        key = row_key(item)
        for index, shown in enumerate(self.lines):
            if row_key(shown) == key:
                self.lines[index] = item
                self.update_cell(key, "lead", self._lead(item))
                self.update_cell(key, "summary", self._summary(item))
                return

    def selected(self) -> ListItem | None:
        """The item under the cursor; None on a heading or a blank row."""
        if 0 <= self.cursor_row < len(self.lines) and self._is_item(self.cursor_row):
            return self.lines[self.cursor_row]
        return None

    def _is_item(self, line: int) -> bool:
        return not isinstance(self.lines[line], (Group, Spacer))

    def _next_item(self, line: int, step: int) -> int | None:
        """The first item from line on, that way; None when there is none."""
        while 0 <= line < len(self.lines):
            if self._is_item(line):
                return line
            line += step
        return None

    def _step_off_headings(self, step: int) -> None:
        """Move the cursor from a heading or a blank row to the next item that way, else the other way."""
        line = self._next_item(self.cursor_row, step)
        if line is None:
            line = self._next_item(self.cursor_row, -step)
        if line is not None and line != self.cursor_row:
            self.move_cursor(row=line)

    def action_cursor_down(self) -> None:
        if (line := self._next_item(self.cursor_row + 1, 1)) is not None:
            self.move_cursor(row=line)

    def action_cursor_up(self) -> None:
        if (line := self._next_item(self.cursor_row - 1, -1)) is not None:
            self.move_cursor(row=line)

    def action_page_down(self) -> None:
        super().action_page_down()
        self._step_off_headings(1)

    def action_page_up(self) -> None:
        super().action_page_up()
        self._step_off_headings(-1)

    def action_scroll_top(self) -> None:
        super().action_scroll_top()
        self._step_off_headings(1)

    def action_scroll_bottom(self) -> None:
        super().action_scroll_bottom()
        self._step_off_headings(-1)

    def _cells(self, row: Row) -> tuple[Text, Text, Text]:
        if isinstance(row, Spacer):
            return Text(), Text(), Text()
        if isinstance(row, Group):
            return self._heading(row)
        return Text(f" {row.id:>{self._id_digits}} "), self._lead(row), self._summary(row)

    def _heading(self, group: Group) -> tuple[Text, Text, Text]:
        """The heading's name and count from the row's left edge, then its note, a link, cut where the
        columns meet."""
        label = Text(f" {group.name} ({group.count})", style=Style(color=self._colors.heading or None, bold=True))
        if group.note:
            label.append(" - ")
            label.append(group.note, style=Style(color=self._colors.link or None, link=group.note_link))
        id_end = self.columns["id"].width
        lead_end = id_end + self.columns["lead"].width
        return label[:id_end], label[id_end:lead_end], label[lead_end:]

    def _lead(self, item: ListItem) -> Text:
        text = Text(" ", style=self._colors.date)
        if self.has_box:
            text.append(DONE if item.done else OPEN)
            text.append("  ")
        text.append(PINNED if item.pinned else UNPINNED, style=self._colors.heading if item.pinned else self._colors.date)
        text.append(" ")
        return text

    def _summary(self, item: ListItem) -> Text:
        text = Text(" ")
        if item.links:
            # Where it comes from first, before what it says
            text.append_text(link_icons(item.links, self._colors))
            text.append("  ")
        summary = summary_text(item.summary, self._colors, done=item.gray, tags=item.tags)
        if item.tone and not item.done:
            # CI is hard to miss: red while it fails, green once it passes again
            summary.stylize(Style(color=(self._colors.failure if item.tone == "failure" else self._colors.success) or None))
        return text + summary

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # The highlight follows the pointer, as it does with the arrow keys
        line = event.style.meta.get("row")
        if isinstance(line, int) and 0 <= line < self.row_count and line != self.cursor_row and self._is_item(line):
            self.move_cursor(row=line)

    async def _on_click(self, event: events.Click) -> None:
        """A click on the box marks done, on the star pins, by which half of their column it hit: a
        terminal may draw the Nerd Font box wider than its cell, so the cell clicked is not always
        the one the icon was written to; a note's column is all star. A tag filters, a link
        opens (a heading's too), anything else opens the item."""
        line = event.style.meta.get("row")
        if not (isinstance(line, int) and 0 <= line < self.row_count):
            return
        event.prevent_default()
        event.stop()
        if not self._is_item(line):
            if event.style.link:
                self.app.open_url(event.style.link)
            return
        item = self.lines[line]
        self.move_cursor(row=line)
        if event.style.meta.get("column") == 1:
            if event.x - self.id_width < self._star_x:
                self.post_message(ItemChangeRequested(item, done=not item.done))
            else:
                self.post_message(ItemChangeRequested(item, pinned=not item.pinned))
        elif tag := event.style.meta.get("tag"):
            self.post_message(TagSelected(tag))
        elif event.style.link:
            self.app.open_url(event.style.link)
        else:
            self.action_select_cursor()
