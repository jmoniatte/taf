from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static
from tui_kit.shortcuts import ACTIONS, GENERAL

from ..notes import NOTE, TODO
from .buttons import flat_button
from .note_markdown import NoteMarkdown
from .notes_table import DONE, OPEN, PINNED, UNPINNED, ItemChangeRequested, ListItem, link_icons, list_colors
from .notes_view import EditRequested


class ViewClosed(Message):
    """The user asked to go back to the list."""


class DeleteRequested(Message):
    """The user asked to delete the note on show."""

    def __init__(self, item: ListItem) -> None:
        super().__init__()
        self.item = item


class DoneBox(Static):
    """The check box, as in the list."""

    def show(self, item: ListItem) -> None:
        # Two spaces after it, as in the list, which also widen the target: Alacritty draws the
        # Nerd Font box wider than its cell
        self.update(f"{DONE if item.done else OPEN}  ")


class PinStar(Static):
    """The star: yellow when pinned, an outline when not."""

    def show(self, item: ListItem) -> None:
        # The spaces after it widen the target and keep what follows clear of it: Alacritty draws the
        # star wider than its cell
        self.update(f"{PINNED if item.pinned else UNPINNED}  ")
        self.set_class(item.pinned, "-pinned")


class LinkIcons(Static):
    """A watch item's icons, as at the end of its row in the list: a click on one opens its page."""

    def on_click(self, event: events.Click) -> None:
        if event.style.link:
            event.stop()
            self.app.open_url(event.style.link)


def detail_bindings(noun: str, editable: bool = True) -> list[Binding]:
    return [
        Binding("escape", "close", "Back to the list", group=ACTIONS),
        # Takes q from the app while the view is up, so it leaves the view rather than the app
        Binding("q", "close", "Back to the list", show=False),
        *([Binding("e", "edit", f"Edit {noun}", group=ACTIONS),
           Binding("shift+enter", "edit", f"Edit {noun}", key_display="⇧+enter", group=ACTIONS)] if editable else []),
        Binding("y", "copy", f"Copy the selection, or the {noun}", group=ACTIONS),
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]


class NoteDetail(Vertical):
    """One note, todo or watch item in place of the list: a header line, then its content as markdown.
    The header: the breadcrumbs' "Notes >" (CRUMB), a link back to the list as in maison, the id, when
    it was created or updated, a watch item's icons; on the right, the check box (KIND todo) and the
    star, as in the list, which a click toggles, then Edit and Delete (when EDITABLE)."""

    KIND = NOTE
    NOUN = "note"
    CRUMB = "Notes"
    EDITABLE = True
    BINDINGS = detail_bindings(NOUN)

    def __init__(self, tag_color: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.item: ListItem | None = None
        self._tag_color = tag_color

    def compose(self) -> ComposeResult:
        with Horizontal(id="note-detail-header"):
            yield Static(self.CRUMB, id="breadcrumb-list")
            yield Static(">", classes="breadcrumb-separator")
            yield Static("", id="note-detail-id")
            yield Static("", id="note-detail-date")
            yield LinkIcons("", id="note-detail-links")
            yield Static("", classes="spacer")
            if self.KIND == TODO:
                yield DoneBox("", id="note-detail-done")
            yield PinStar("", id="note-detail-pin")
            if self.EDITABLE:
                yield flat_button("Edit", "btn-edit", classes="tinted")
                yield flat_button("Delete", "btn-delete", classes="tinted -red")
        with VerticalScroll(id="note-detail-scroll"):
            yield NoteMarkdown(tag_color=self._tag_color, id="note-detail-markdown")

    def show(self, item: ListItem) -> None:
        self.show_header(item)
        self.query_one(NoteMarkdown).update(item.content)
        self.query_one(VerticalScroll).scroll_home(animate=False)

    def show_header(self, item: ListItem) -> None:
        """The header for the item as it is now; the content stays as it was."""
        self.item = item
        for box in self.query(DoneBox):
            box.show(item)
        self.query_one(PinStar).show(item)
        self.query_one("#note-detail-id", Static).update(f"#{item.id}")
        self.query_one("#note-detail-date", Static).update(item.date_text)
        self.query_one(LinkIcons).update(link_icons(item.links, list_colors(self.app.palette)))

    def focus_content(self) -> None:
        self.query_one(VerticalScroll).focus()

    def set_colors(self, tag_color: str) -> None:
        """Repaint the tags and the icons against a new palette; they bake their color in."""
        markdown = self.query_one(NoteMarkdown)
        markdown.tag_color = tag_color
        if self.item is not None:
            markdown.update(self.item.content)
            self.show_header(self.item)

    @on(events.Click, "#breadcrumb-list")
    def _crumb_clicked(self) -> None:
        self.action_close()

    @on(events.Click, "#note-detail-done")
    def _box_clicked(self) -> None:
        if self.item is not None:
            self.post_message(ItemChangeRequested(self.item, done=not self.item.done))

    @on(events.Click, "#note-detail-pin")
    def _star_clicked(self) -> None:
        if self.item is not None:
            self.post_message(ItemChangeRequested(self.item, pinned=not self.item.pinned))

    @on(Button.Pressed, "#btn-edit")
    def _edit_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_edit()

    @on(Button.Pressed, "#btn-delete")
    def _delete_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if self.item is not None:
            self.post_message(DeleteRequested(self.item))

    def action_close(self) -> None:
        self.post_message(ViewClosed())

    def action_edit(self) -> None:
        if self.item is not None:
            self.post_message(EditRequested(self.item))

    def action_copy(self) -> None:
        """Copy the text selected with the mouse, or the whole item when nothing is selected."""
        if self.item is None:
            return
        selection = self.screen.get_selected_text()
        self.app.copy_to_clipboard(selection or self.item.content)
        self.notify("Selection copied" if selection else f"{self.NOUN.capitalize()} copied")

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()


class TodoDetail(NoteDetail):
    """One todo: a note with its check box before the star."""

    KIND = TODO
    NOUN = "todo"
    CRUMB = "Todos"
    BINDINGS = detail_bindings(NOUN)
