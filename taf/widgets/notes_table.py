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

from ..watch.view import FYI, Group, WatchItem
from ..notes import TODO, Note, find_tags

# What a row of the table can show: the Watch tab's items look like todos
Entry = Note | WatchItem

# The links a watch item's row ends with, each a Nerd Font icon a click opens: nf-md-slack,
# nf-md-github, nf-fa-jenkins (failing CI's build, in red), and nf-md-numeric_7_circle for one the
# user or an agent added (7 is how the user signs)
LINK_ICONS = {"slack": "\U000f04b1", "github": "\U000f02a4", "jenkins": "\uf2ec", "added": "\U000f0cac"}
# Nerd Font check boxes (nf-md-checkbox_blank_outline, nf-md-checkbox_marked), as outils uses Nerd Font icons
OPEN = "\U000f0131"
DONE = "\U000f0132"
PINNED = "★"
UNPINNED = "☆"
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
    # The note's tags shown after its text
    extra_tag: str = ""
    # A watch item's failing CI icon
    failure: str = ""


class NoteChangeRequested(Message):
    """The user marked a todo or a Slack item done or not done, or pinned or unpinned one; None leaves
    that field as it is."""

    def __init__(self, note: Entry, done: bool | None = None, pinned: bool | None = None) -> None:
        super().__init__()
        self.note = note
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


class Spacer:
    """The blank row before a project's heading, after the first."""

    def __init__(self, before: Group) -> None:
        self.before = before


Row = Group | Spacer | Entry


def row_key(row: Row) -> str:
    """A row's key: a note's or a todo's id, as the cursor_on of load and show; Slack items and
    headings have their own, their ids being another count."""
    if isinstance(row, Spacer):
        return f"space:{row.before.name}"
    if isinstance(row, Group):
        return f"project:{row.name}"
    if isinstance(row, WatchItem):
        return f"slack:{row.id}"
    return str(row.id)


def lead_width(kind: str) -> int:
    """A todo's check box, two spaces, the star; a note has only the star."""
    return 4 if kind == TODO else 1


class NotesTable(DataTable):
    """One row per note of a kind, keyed by its id. A click on a todo's check box or the star changes
    the note, on a tag filters the list, on a link opens it.

    Cells carry their own one-space padding, the table none: a project's heading then runs on from
    the id column into the next ones, from the left edge, as one line of text."""

    BINDINGS = [
        Binding("enter", "select_cursor", "View", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, kind: str, colors: ListColors, **kwargs) -> None:
        super().__init__(
            cursor_type="row", zebra_stripes=False, show_header=False, cursor_foreground_priority="renderable", cell_padding=0, **kwargs
        )
        self.kind = kind
        self._colors = colors
        # The rows: notes, todos, or watch items under their project's heading
        self.notes: list[Row] = []
        # Clicks on a todo's box and star column left of this x, from the column's start, hit the box:
        # the cell's space, the box and the next space
        self._star_x = 3 if kind == TODO else 0
        # The longest id shown, which the id column fits
        self._id_digits = 1

    def on_mount(self) -> None:
        # As wide as the longest id shown (show), so the rest lines up
        self.add_column("", key="id", width=3)
        self.add_column("", key="lead", width=lead_width(self.kind) + 2)
        self.add_column("Summary", key="summary")

    @property
    def id_width(self) -> int:
        """The id column's width, its padding included."""
        return self.columns["id"].get_render_width(self)

    def show(self, notes: list[Group | Entry], colors: ListColors | None = None, cursor_on: int | str | None = None) -> None:
        """Show the rows, a blank one before each project's heading but the first, with the cursor
        on the one cursor_on names (a note's id, or a row key), else on the row it was on, else on
        the same line, and never on a heading or a blank row."""
        self._colors = colors or self._colors
        current = row_key(self.notes[self.cursor_row]) if 0 <= self.cursor_row < len(self.notes) else None
        current = str(cursor_on) if cursor_on is not None else current
        row = self.cursor_row
        self.clear()
        self.notes = []
        for note in notes:
            if isinstance(note, Group) and self.notes:
                self.notes.append(Spacer(note))
            self.notes.append(note)
        self._id_digits = max((len(str(note.id)) for note in notes if not isinstance(note, Group)), default=1)
        self.columns["id"].width = self._id_digits + 2
        for note in self.notes:
            # Text, not str: the table reads strings as markup, which eats brackets in a summary
            self.add_row(*self._cells(note), key=row_key(note))
        keys = [row_key(note) for note in self.notes]
        if keys:
            self.move_cursor(row=keys.index(current) if current in keys else min(max(row, 0), len(keys) - 1))
            self._step_off_headings(1)

    def _cells(self, note: Row) -> tuple[Text, Text, Text]:
        if isinstance(note, Spacer):
            return Text(), Text(), Text()
        if isinstance(note, Group):
            return self._heading(note)
        return Text(f" {note.id:>{self._id_digits}} "), self._lead(note), self._summary(note)

    def _heading(self, group: Group) -> tuple[Text, Text, Text]:
        """The project's name and count from the row's left edge, then its note, a link, cut where the
        columns meet."""
        label = Text(f" {group.name} ({group.count})", style=Style(color=self._colors.heading or None, bold=True))
        if group.note:
            label.append(" - ")
            label.append(group.note, style=Style(color=self._colors.link or None, link=group.note_link))
        id_end = self.columns["id"].width
        lead_end = id_end + self.columns["lead"].width
        return label[:id_end], label[id_end:lead_end], label[lead_end:]

    def _step_off_headings(self, step: int) -> None:
        """Move the cursor from a heading or a blank row to the next entry that way, else the other way."""
        for direction in (step, -step):
            row = self.cursor_row
            while 0 <= row < len(self.notes) and isinstance(self.notes[row], (Group, Spacer)):
                row += direction
            if 0 <= row < len(self.notes):
                self.move_cursor(row=row)
                return

    def action_cursor_down(self) -> None:
        self._move_to_entry(1)

    def action_cursor_up(self) -> None:
        self._move_to_entry(-1)

    def _move_to_entry(self, step: int) -> None:
        """The next entry that way, past headings and blank rows; the cursor stays when there is none."""
        row = self.cursor_row + step
        while 0 <= row < len(self.notes) and isinstance(self.notes[row], (Group, Spacer)):
            row += step
        if 0 <= row < len(self.notes):
            self.move_cursor(row=row)

    def replace(self, note: Entry) -> None:
        """Show the entry's new state in its row, which stays where it is."""
        key = row_key(note)
        for index, shown in enumerate(self.notes):
            if row_key(shown) == key:
                self.notes[index] = note
                self.update_cell(key, "lead", self._lead(note))
                self.update_cell(key, "summary", self._summary(note))
                return

    def selected(self) -> Entry | None:
        """The note, todo or Slack item under the cursor; None on a heading or a blank row."""
        note = self.notes[self.cursor_row] if 0 <= self.cursor_row < len(self.notes) else None
        return None if isinstance(note, (Group, Spacer)) else note

    def _lead(self, note: Entry) -> Text:
        text = Text(" ", style=self._colors.date)
        if note.is_todo:
            text.append(DONE if note.done else OPEN)
            text.append("  ")
        text.append(PINNED if note.pinned else UNPINNED, style=self._colors.heading if note.pinned else self._colors.date)
        text.append(" ")
        return text

    def _summary(self, note: Entry) -> Text:
        if isinstance(note, WatchItem):
            # An fyi only informs: gray, like a done one
            text = summary_text(note.summary, self._colors, done=note.done or note.item_kind == FYI)
            for kind, url in note.links:
                color = self._colors.failure if kind == "jenkins" else self._colors.link
                text.append(" ")
                text.append(f" {LINK_ICONS[kind]}", style=Style(color=color or None, link=url))
        else:
            text = summary_text(note.summary, self._colors, done=note.done, tags=note.tags)
        return Text(" ") + text

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # The highlight follows the pointer, as it does with the arrow keys
        row = event.style.meta.get("row")
        if isinstance(row, int) and 0 <= row < self.row_count and row != self.cursor_row and self._is_entry(row):
            self.move_cursor(row=row)

    def _is_entry(self, row: int) -> bool:
        return not isinstance(self.notes[row], (Group, Spacer))

    async def _on_click(self, event: events.Click) -> None:
        """A click on the box marks done, on the star pins, by which half of their column it hit: a
        terminal may draw the Nerd Font box wider than its cell, so the cell clicked is not always
        the one the icon was written to; a note's column is all star. A tag filters, a link
        opens, anything else opens the note."""
        row = event.style.meta.get("row")
        if not (isinstance(row, int) and 0 <= row < self.row_count):
            return
        event.prevent_default()
        event.stop()
        note = self.notes[row]
        if isinstance(note, (Group, Spacer)):
            # A heading's note may be a link
            if event.style.link:
                self.app.open_url(event.style.link)
            return
        self.move_cursor(row=row)
        if event.style.meta.get("column") == 1:
            if event.x - self.id_width < self._star_x:
                self.post_message(NoteChangeRequested(note, done=not note.done))
            else:
                self.post_message(NoteChangeRequested(note, pinned=not note.pinned))
        elif tag := event.style.meta.get("tag"):
            self.post_message(TagSelected(tag))
        elif event.style.link:
            self.app.open_url(event.style.link)
        else:
            self.action_select_cursor()
