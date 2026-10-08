from textual import on
from textual.app import SuspendNotSupported
from tui_kit.dialog import ConfirmDialog

from ..editor import EditorError, edit_text, with_front_matter, without_front_matter
from ..notes import NOTE, TODO, Note, create_note, delete_note, front_matter, get_note, update_note
from .list_tab import ListTab
from .note_detail import DeleteRequested, NoteDetail, TodoDetail
from .notes_table import TagSelected
from .notes_view import EditRequested, NewNoteRequested, NotesView, TodosView


class NotesTab(ListTab):
    """The Notes tab, as in yafyaf-tui, with writing, editing and deleting: editing returns where it
    started, the list or the note. TodosTab is the same for todos."""

    KIND = NOTE
    LIST = NotesView
    DETAIL = NoteDetail
    TITLE = "Notes"

    @property
    def noun(self) -> str:
        return self.KIND.capitalize()

    def fetch(self, item: Note) -> Note | None:
        return get_note(self.database, item.id)

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
        self.edit(event.item)

    def edit(self, note: Note | None) -> None:
        """Edit the note in $EDITOR, or write a new one, then go back where this started, the list or
        the note; emptied, a note is deleted once confirmed."""
        if self.database is None:
            return
        if note is not None:
            # The database's copy, so a change made since the list loaded is not lost
            note = self.fetch(note) or note
        original = note.content if note else ""
        # A note's dates and pin, for the eye only: what is changed there is not saved
        text = with_front_matter(front_matter(note), original) if note else original
        content = ""
        failure: Exception | None = None
        try:
            with self.app.suspend():
                try:
                    content = without_front_matter(edit_text(text, f"taf-{self.KIND}-"))
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
            self.show_item(saved)

    @on(DeleteRequested)
    def _delete_requested(self, event: DeleteRequested) -> None:
        event.stop()
        self._confirm_delete(event.item)

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
    TITLE = "Todos"
