"""The table of the Notes and Todos tabs: the id, a todo's check box and the star, then the summary
with its links and tags."""

import re
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..notes import TODO, Note, find_tags

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


class NoteChangeRequested(Message):
    """The user marked a todo done or not done, or pinned or unpinned a note; None leaves that field as it is."""

    def __init__(self, note: Note, done: bool | None = None, pinned: bool | None = None) -> None:
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


def lead_width(kind: str) -> int:
    """A todo's check box, two spaces, the star; a note has only the star."""
    return 4 if kind == TODO else 1


class NotesTable(DataTable):
    """One row per note of a kind, keyed by its id. A click on a todo's check box or the star changes
    the note, on a tag filters the list, on a link opens it."""

    BINDINGS = [
        Binding("enter", "select_cursor", "View", show=False, group=ACTIONS),
        Binding("j", "cursor_down", "Move down", show=False, group=GENERAL),
        Binding("k", "cursor_up", "Move up", show=False, group=GENERAL),
    ]

    def __init__(self, kind: str, colors: ListColors, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=False, show_header=False, cursor_foreground_priority="renderable", **kwargs)
        self.kind = kind
        self._colors = colors
        self.notes: list[Note] = []
        # Clicks on a todo's box and star column left of this x, from the column's start, hit the box
        self._star_x = self.cell_padding + 2 if kind == TODO else 0

    def on_mount(self) -> None:
        # As wide as the longest id shown (show), so the rest lines up
        self.add_column("", key="id", width=1)
        self.add_column("", key="lead", width=lead_width(self.kind))
        self.add_column("Summary", key="summary")

    @property
    def id_width(self) -> int:
        """The id column's width, its padding included."""
        return self.columns["id"].get_render_width(self)

    def show(self, notes: list[Note], colors: ListColors | None = None, cursor_on: int | None = None) -> None:
        """Show the notes, with the cursor on the note cursor_on names, else on the note it was on,
        else on the same row."""
        self._colors = colors or self._colors
        current = self.notes[self.cursor_row].id if 0 <= self.cursor_row < len(self.notes) else None
        current = cursor_on or current
        row = self.cursor_row
        self.clear()
        self.notes = list(notes)
        self.columns["id"].width = max((len(str(note.id)) for note in notes), default=1)
        for note in notes:
            # Text, not str: the table reads strings as markup, which eats brackets in a summary
            self.add_row(Text(str(note.id), justify="right"), self._lead(note), self._summary(note), key=str(note.id))
        ids = [note.id for note in notes]
        if ids:
            self.move_cursor(row=ids.index(current) if current in ids else min(max(row, 0), len(ids) - 1))

    def replace(self, note: Note) -> None:
        """Show the note's new state in its row, which stays where it is."""
        for index, shown in enumerate(self.notes):
            if shown.id == note.id:
                self.notes[index] = note
                self.update_cell(str(note.id), "lead", self._lead(note))
                self.update_cell(str(note.id), "summary", self._summary(note))
                return

    def selected(self) -> Note | None:
        return self.notes[self.cursor_row] if 0 <= self.cursor_row < len(self.notes) else None

    def _lead(self, note: Note) -> Text:
        text = Text(style=self._colors.date)
        if note.is_todo:
            text.append(DONE if note.done else OPEN)
            text.append("  ")
        text.append(PINNED if note.pinned else UNPINNED, style=self._colors.heading if note.pinned else self._colors.date)
        return text

    def _summary(self, note: Note) -> Text:
        return summary_text(note.summary, self._colors, done=note.done, tags=note.tags)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # The highlight follows the pointer, as it does with the arrow keys
        row = event.style.meta.get("row")
        if isinstance(row, int) and 0 <= row < self.row_count and row != self.cursor_row:
            self.move_cursor(row=row)

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
