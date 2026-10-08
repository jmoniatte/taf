from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Button, Input, Select
from tui_kit.shortcuts import ACTIONS

from ..notes import NOTE, TAG, TODO, Note, list_notes, set_done, set_pinned, split_query, tag_counts
from .list_view import ListView
from .items_table import TagSelected

# The Tags dropdown's first choice, which takes the tags out of the search; not a tag name, which has no space
ANY_TAG = "any tag"


class EditRequested(Message):
    """The user asked to edit one note in the editor."""

    def __init__(self, item: Note) -> None:
        super().__init__()
        self.item = item


class NewNoteRequested(Message):
    """The user asked to write a new note."""


def list_bindings(kind: str) -> list[Binding]:
    """The list's keys, worded for its kind; a todo also has x and f, for its status."""
    todo = kind == TODO
    return [
        Binding("n", "new", f"New {kind}", group=ACTIONS),
        Binding("e", "edit", f"Edit {kind}", group=ACTIONS),
        # Only terminals with the kitty keyboard protocol can tell this from enter; e works everywhere
        Binding("shift+enter", "edit", f"Edit {kind}", key_display="⇧+enter", group=ACTIONS),
        *([Binding("x", "toggle_done", "Mark done, or not done", group=ACTIONS)] if todo else []),
        Binding("p", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("space", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        *([Binding("f", "next_status", "Show open, done or all", group=ACTIONS)] if todo else []),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("number_sign", "tags", "Tags", key_display="#", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy", f"Copy the {kind}", group=ACTIONS),
    ]


class NotesView(ListView):
    """The Notes tab's list, like YafYaf's: the search box, the Tags dropdown and New Note over the
    notes, the last updated first. TodosView adds the status."""

    # Which notes: plain notes, or todos
    KIND = NOTE
    NOUN = "note"
    BINDINGS = list_bindings(NOTE)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The search's last tag, or None for any
        self.tag: str | None = None

    def compose_controls(self) -> ComposeResult:
        # The search's tag, or Any tag; picking one puts "#name" in the search
        yield Select([("Any tag", ANY_TAG)], value=ANY_TAG, allow_blank=False, id="tag-selector")
        yield from super().compose_controls()
        yield Button(f"New {self.NOUN.capitalize()}", id="btn-new-note", classes="tinted")

    def fetch(self, words: str) -> list[Note]:
        return list_notes(self.database, self.KIND, words, self.status)

    def mark_done(self, item_id: int, done: bool) -> Note | None:
        return set_done(self.database, item_id, done)

    def mark_pinned(self, item_id: int, pinned: bool) -> Note | None:
        return set_pinned(self.database, item_id, pinned)

    def loaded(self, words: str) -> None:
        """The Tags dropdown: the tags with their counts, showing the search's last tag."""
        tags = split_query(words)[1]
        self.tag = tags[-1] if tags else None
        counts = tag_counts(self.database, self.KIND)
        selector = self.query_one("#tag-selector", Select)
        # Changed here, not chosen: no message. A tag no note has is not in the list: "Any tag" stands for it
        with selector.prevent(Select.Changed):
            selector.set_options([("Any tag", ANY_TAG), *((f"{name} ({count})", name) for name, count in counts)])
            selector.value = self.tag if self.tag in dict(counts) else ANY_TAG

    # -- tags

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
        name = None if event.value == ANY_TAG else str(event.value)
        # A Select also sends Changed when mounted, and the focus add_tag gives would open this tab
        if name != self.tag:
            self.add_tag(name)

    def add_tag(self, name: str | None) -> None:
        """Add "#name" to the search, or take every tag out for None (Any tag), keep its words, and
        run it; how every way of picking a tag ends up. A note may have many tags, so they add up."""
        words = self.query_one("#search", Input).value.split()
        if name is None:
            words = [word for word in words if not TAG.fullmatch(word)]
        elif name not in split_query(" ".join(words))[1]:
            words.append(f"#{name}")
        self.run_search(" ".join(words))

    # -- writing

    @on(Button.Pressed, "#btn-new-note")
    def action_new(self) -> None:
        # A clicked button keeps focus; hand it back to the list the editor returns to
        self.table.focus()
        self.post_message(NewNoteRequested())

    def action_edit(self) -> None:
        if (note := self.table.selected()) is not None:
            self.post_message(EditRequested(note))


class TodosView(NotesView):
    """The Todos tab's list: the notes' list with the status, open todos first shown."""

    KIND = TODO
    NOUN = "todo"
    HAS_DONE = True
    BINDINGS = list_bindings(TODO)

    def add_tag(self, name: str | None) -> None:
        """Put "#name" in the search in place of any other tag: a todo has one tag at most, so two
        would find nothing."""
        words = [word for word in self.query_one("#search", Input).value.split() if not TAG.fullmatch(word)]
        self.run_search(" ".join([*words, f"#{name}"] if name else words))
