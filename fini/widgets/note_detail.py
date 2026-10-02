from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..notes import NOTE, TODO, Note, long_date
from .note_markdown import NoteMarkdown
from .notes_table import DONE, OPEN, PINNED, UNPINNED, NoteChangeRequested
from .notes_view import EditRequested


class ViewClosed(Message):
    """The user asked to go back to the list."""


class DoneBox(Static):
    """A todo's check box, as in the list; a click marks it done or not."""

    def show(self, note: Note) -> None:
        # Two spaces after it, as in the list, which also widen the target: Alacritty draws the
        # Nerd Font box wider than its cell
        self.update(f"{DONE if note.done else OPEN}  ")

    def on_click(self) -> None:
        note = self.parent.parent.note
        if note is not None:
            self.post_message(NoteChangeRequested(note, done=not note.done))


class PinStar(Static):
    """The note's star: yellow when pinned, an outline when not; a click pins or unpins."""

    def show(self, note: Note) -> None:
        # The spaces after it widen the target and keep the date clear of it: Alacritty draws the
        # star wider than its cell
        self.update(f"{PINNED if note.pinned else UNPINNED}  ")
        self.set_class(note.pinned, "-pinned")

    def on_click(self) -> None:
        note = self.parent.parent.note
        if note is not None:
            self.post_message(NoteChangeRequested(note, pinned=not note.pinned))


def detail_bindings(kind: str) -> list[Binding]:
    return [
        Binding("escape", "close", "Back to the list", group=ACTIONS),
        # Takes q from the app while the view is up, so it leaves the view rather than the app
        Binding("q", "close", "Back to the list", show=False),
        Binding("e", "edit", f"Edit {kind}", group=ACTIONS),
        Binding("shift+enter", "edit", f"Edit {kind}", key_display="⇧+enter", group=ACTIONS),
        Binding("y", "copy", f"Copy the selection, or the {kind}", group=ACTIONS),
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]


class NoteDetail(Vertical):
    """One note rendered as markdown in place of the list, under a line with its id and star, as in
    the list, and when it was last updated. TodoDetail adds the check box."""

    KIND = NOTE
    BINDINGS = detail_bindings(NOTE)

    def __init__(self, tag_color: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.note: Note | None = None
        self._tag_color = tag_color

    def compose(self) -> ComposeResult:
        with Horizontal(id="note-detail-header"):
            yield Static("", id="note-detail-id")
            if self.KIND == TODO:
                yield DoneBox("", id="note-detail-done")
            yield PinStar("", id="note-detail-pin")
            yield Static("", id="note-detail-date")
        with VerticalScroll(id="note-detail-scroll"):
            yield NoteMarkdown(tag_color=self._tag_color, id="note-detail-markdown")

    def show(self, note: Note) -> None:
        self.show_header(note)
        self.query_one(NoteMarkdown).update(note.content)
        self.query_one(VerticalScroll).scroll_home(animate=False)

    def show_header(self, note: Note) -> None:
        """The box, the star and the date for the note as it is now; the content stays as it was."""
        self.note = note
        for box in self.query(DoneBox):
            box.show(note)
        self.query_one(PinStar).show(note)
        self.query_one("#note-detail-id", Static).update(f"#{note.id}")
        self.query_one("#note-detail-date", Static).update(f"Updated {long_date(note.updated_at)}")

    def focus_content(self) -> None:
        self.query_one(VerticalScroll).focus()

    def set_colors(self, tag_color: str) -> None:
        """Repaint the tags against a new palette; the markdown bakes their color in."""
        markdown = self.query_one(NoteMarkdown)
        markdown.tag_color = tag_color
        if self.note is not None:
            markdown.update(self.note.content)

    def action_close(self) -> None:
        self.post_message(ViewClosed())

    def action_edit(self) -> None:
        if self.note is not None:
            self.post_message(EditRequested(self.note))

    def action_copy(self) -> None:
        """Copy the text selected with the mouse, or the whole note when nothing is selected."""
        if self.note is None:
            return
        selection = self.screen.get_selected_text()
        self.app.copy_to_clipboard(selection or self.note.content)
        self.notify("Selection copied" if selection else f"{self.KIND.capitalize()} copied")

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()


class TodoDetail(NoteDetail):
    """One todo: a note with its check box before the star."""

    KIND = TODO
    BINDINGS = detail_bindings(TODO)
