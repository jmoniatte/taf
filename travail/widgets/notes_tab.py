import sqlite3

from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from tui_kit.dialog import ConfirmDialog

from ..editor import EditorError, edit_text, with_front_matter, without_front_matter
from ..notes import NOTE, TODO, Note, create_note, delete_note, front_matter, get_note, set_done, set_pinned, update_note
from .note_detail import DeleteRequested, NoteDetail, TodoDetail, ViewClosed
from .notes_table import NoteChangeRequested, NotesTable, TagSelected
from .notes_view import EditRequested, NewNoteRequested, NoteOpened, NotesView, TodosView


class NotesTab(Vertical):
    """The Notes tab: the list, or one note in full in its place, as in yafyaf-tui. Editing returns
    where it started, the list or the note. TodosTab is the same for todos."""

    KIND = NOTE
    LIST = NotesView
    DETAIL = NoteDetail

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The note on show, or None while the list is
        self.viewing: Note | None = None

    def compose(self) -> ComposeResult:
        yield self.LIST(id="notes-list")
        yield self.DETAIL(self.app.palette["purple"], id="note-detail")

    @property
    def noun(self) -> str:
        return self.KIND.capitalize()

    @property
    def list(self) -> NotesView:
        return self.query_one(NotesView)

    @property
    def detail(self) -> NoteDetail:
        return self.query_one(NoteDetail)

    @property
    def database(self) -> sqlite3.Connection | None:
        return self.app.database

    def help_section(self) -> tuple[str, tuple]:
        """The title and the keys of Help's right column: the list's, or the note's while one is on show."""
        if self.viewing is not None:
            return self.noun, (self.DETAIL.BINDINGS,)
        return f"{self.noun}s", (self.LIST.BINDINGS, NotesTable.BINDINGS)

    def tab_shown(self) -> None:
        if self.viewing is not None:
            self.detail.focus_content()
        else:
            self.list.table.focus()

    def set_colors(self) -> None:
        self.list.set_colors()
        self.detail.set_colors(self.app.palette["purple"])

    # -- the list or one note

    def reload(self) -> None:
        """The footer's Refresh."""
        self.list.load()

    def show_list(self) -> None:
        self.viewing = None
        self.detail.display = False
        self.list.display = True
        self.list.table.focus()
        self.app.refresh_footer()

    def show_note(self, note: Note) -> None:
        self.viewing = note
        self.detail.show(note)
        self.list.display = False
        self.detail.display = True
        self.detail.focus_content()
        self.app.refresh_footer()

    @on(NoteOpened)
    def _open(self, event: NoteOpened) -> None:
        event.stop()
        # The database's copy, so a change made since the list loaded shows
        if self.database is not None:
            self.show_note(get_note(self.database, event.note.id) or event.note)

    @on(ViewClosed)
    def _close(self, event: ViewClosed) -> None:
        event.stop()
        self.show_list()

    @on(NoteChangeRequested)
    def _change(self, event: NoteChangeRequested) -> None:
        """The view's box or star: marks done or pins in place, the note's row in the list too."""
        event.stop()
        if self.database is None:
            return
        if event.done is not None:
            note = set_done(self.database, event.note.id, event.done)
            message = "Marked done" if event.done else "Marked not done"
        elif event.pinned is not None:
            note = set_pinned(self.database, event.note.id, event.pinned)
            message = "Pinned" if event.pinned else "Unpinned"
        else:
            return
        if note is not None:
            self.notify(message)
            self.detail.show_header(note)
            self.viewing = note
            self.list.table.replace(note)

    @on(TagSelected)
    def _tag_selected(self, event: TagSelected) -> None:
        """A tag clicked in a note filters the list on it, so that means going back to the list."""
        event.stop()
        self.show_list()
        self.list.add_tag(event.name)

    # -- editing

    @on(NewNoteRequested)
    def _new(self, event: NewNoteRequested) -> None:
        event.stop()
        self.edit(None)

    @on(EditRequested)
    def _edit_requested(self, event: EditRequested) -> None:
        event.stop()
        self.edit(event.note)

    def edit(self, note: Note | None) -> None:
        """Edit the note in $EDITOR, or write a new one, then go back where this started, the list or
        the note; emptied, a note is deleted once confirmed."""
        if self.database is None:
            return
        if note is not None:
            # The database's copy, so a change made since the list loaded is not lost
            note = get_note(self.database, note.id) or note
        original = note.content if note else ""
        # A note's dates and pin, for the eye only: what is changed there is not saved
        text = with_front_matter(front_matter(note), original) if note else original
        content = ""
        failure: Exception | None = None
        try:
            with self.app.suspend():
                try:
                    content = without_front_matter(edit_text(text, f"travail-{self.KIND}-"))
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
            if note is not None:
                self._confirm_delete(note)
            return
        if note is None:
            saved = create_note(self.database, content, self.KIND)
            self.notify(f"{self.noun} created")
        else:
            saved = update_note(self.database, note.id, content)
            self.notify(f"{self.noun} updated")
        self.list.load(cursor_on=saved.id)
        if self.viewing is not None:
            self.show_note(saved)

    @on(DeleteRequested)
    def _delete_requested(self, event: DeleteRequested) -> None:
        event.stop()
        self._confirm_delete(event.note)

    def _confirm_delete(self, note: Note) -> None:
        dialog = ConfirmDialog(
            f"Delete this {self.KIND}?", title=f"Delete {self.noun}", confirm_label="Delete", cancel_label="Cancel", detail=note.summary
        )

        def chosen(confirmed: bool | None) -> None:
            if confirmed:
                delete_note(self.database, note.id)
                self.notify(f"{self.noun} deleted")
                self.list.load()
                if self.viewing is not None:
                    self.show_list()

        self.app.push_screen(dialog, chosen)


class TodosTab(NotesTab):
    """The Todos tab: notes of the kind todo, with their status."""

    KIND = TODO
    LIST = TodosView
    DETAIL = TodoDetail
