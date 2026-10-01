import sqlite3
from pathlib import Path

import tui_kit
from textual import on
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.notifications import Notification
from textual.widgets import Button, TabbedContent, TabPane, Tabs
from tui_kit.base_app import COPY_BINDING, HELP_BINDING, THEME_BINDING, BaseApp
from tui_kit.header_notification import HeaderNotification
from tui_kit.shortcuts import GENERAL

from . import REPOSITORY_URL, __version__
from .config import CONFIG_FILE, Config, load_config
from .database import open_database
from .screens import FiniHelpScreen
from .widgets import LogsView, TodosTab

STYLES_DIR = Path(__file__).parent / "styles"
# tui-kit's stylesheets first, so the app's own rules win where they differ
STYLE_FILES = (*tui_kit.STYLE_FILES, STYLES_DIR / "fini.tcss")
# Each tab by name, with its label and view; the first one opens first
TABS = {
    "todos": ("Todos", TodosTab),
    "logs": ("Logs", LogsView),
}


class FooterMessage(HeaderNotification):
    """tui-kit's messages, which find this widget wherever it is: here, in the footer, since fini
    has no title bar. Help hides while one shows, so the message ends where Help ends, on the right.
    """

    def show_notification(self, notification: Notification) -> None:
        self._show_help(False)
        super().show_notification(notification)

    def clear_notification(self) -> None:
        super().clear_notification()
        # Once the message is gone from the screen, so Help never sits over a message not yet cleared
        self.call_after_refresh(self._show_help, True)

    def _show_help(self, shown: bool) -> None:
        # Unless a new message came in meanwhile
        self.screen.query_one("#btn-help").display = shown and not self.display


def footer_button(label: str, id: str, classes: str = "") -> Button:
    button = Button(label, id=id, classes=classes)
    # A click must not take focus off the view, which keeps it for its keys
    button.can_focus = False
    return button


def load_stylesheet() -> str:
    return "\n".join(path.read_text() for path in STYLE_FILES)


class FiniApp(BaseApp):
    """Todos and a log of the work done, one tab each."""

    TITLE = "Fini"
    VERSION = __version__
    REPOSITORY_URL = REPOSITORY_URL
    # Nothing takes focus on its own: TabbedContent shows the tab of whatever has focus, so the logs
    # list would open on Logs; a tab's list gets focus when its tab shows
    AUTO_FOCUS = None
    CSS = load_stylesheet()

    BINDINGS = [
        HELP_BINDING,
        THEME_BINDING,
        COPY_BINDING,
        # Before the screen's own tab, which would move focus; skipped under a panel or dialog
        Binding("tab", "next_tab", "Next tab", group=GENERAL, priority=True),
        Binding("q", "quit", "Quit", group=GENERAL),
    ]

    def __init__(self, config: Config | None = None) -> None:
        self.config = config if config is not None else load_config()
        self.tab = next(iter(TABS))
        # None when it cannot be opened; database_error says why, and the tabs show it
        self.database: sqlite3.Connection | None = None
        self.database_error = ""
        try:
            self.database = open_database(self.config.database_path)
        except (sqlite3.Error, OSError) as error:
            self.database_error = f"Cannot open the database {self.config.database_path}: {error}"
        super().__init__(self.config.theme, CONFIG_FILE)

    def compose(self) -> ComposeResult:
        # No title bar: the tabs say where you are, and the messages sit by the buttons at the bottom
        # The panes' ids differ from their views' own, which a duplicate id would break
        with TabbedContent(initial=f"{self.tab}-tab", id="tabs"):
            for name, (label, view) in TABS.items():
                with TabPane(label, id=f"{name}-tab"):
                    yield view(id=f"{name}-view")
        # Over the right end of the tabs' row, which leaves it room for the tabs
        yield footer_button("Exit", "btn-exit", classes="tinted -red")
        # Under every tab: a rule, then Help on the right; a message takes Help's place while it shows.
        # While a todo is on show, Close, back to the list, and Edit on the left
        with Horizontal(id="app-footer"):
            yield footer_button("Close", "btn-close-todo")
            yield footer_button("Edit", "btn-edit", classes="tinted")
            yield footer_button("Delete", "btn-delete", classes="tinted -red")
            # Only on the todos list, like the Refresh under yafyaf-tui's list
            yield footer_button("Refresh", "btn-refresh", classes="tinted -green")
            yield footer_button("Help", "btn-help")
            yield FooterMessage()

    @on(Button.Pressed, "#btn-help")
    def _help(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_help()

    def action_help(self) -> None:
        """The app's keys on the left, the keys of the tab on show on the right."""
        view = self.query_one("#tabs", TabbedContent).active_pane.children[0]
        self.push_screen(FiniHelpScreen(*view.help_section()))

    @on(Button.Pressed, "#btn-exit")
    def _exit(self, event: Button.Pressed) -> None:
        event.stop()
        self.exit()

    @on(Button.Pressed, "#btn-close-todo")
    def _close_todo(self, event: Button.Pressed) -> None:
        event.stop()
        self.query_one(TodosTab).show_list()

    @on(Button.Pressed, "#btn-edit")
    def _edit_todo(self, event: Button.Pressed) -> None:
        event.stop()
        self.query_one(TodosTab).edit_viewed()

    @on(Button.Pressed, "#btn-delete")
    def _delete_todo(self, event: Button.Pressed) -> None:
        event.stop()
        self.query_one(TodosTab).delete_viewed()

    @on(Button.Pressed, "#btn-refresh")
    def _refresh_todos(self, event: Button.Pressed) -> None:
        event.stop()
        self.query_one(TodosTab).list.load()

    def refresh_footer(self) -> None:
        """Close, Edit and Delete show while a todo is on show, Refresh while the todos list is."""
        view = self.query_one("#tabs", TabbedContent).active_pane.children[0]
        viewing = getattr(view, "viewing", None) is not None
        for button in ("#btn-close-todo", "#btn-edit", "#btn-delete"):
            self.query_one(button).display = viewing
        self.query_one("#btn-refresh").display = isinstance(view, TodosTab) and not viewing

    def on_mount(self) -> None:
        # The view keeps focus for its keys; tabs switch by click or with tab
        self.tabs.can_focus = False
        for warning in self.config.warnings:
            self.notify(warning, severity="warning", timeout=10)
        if self.database_error:
            self.notify(self.database_error, severity="error", timeout=10)
        self._show_tab(self.query_one("#tabs", TabbedContent).active_pane)

    def on_unmount(self) -> None:
        super().on_unmount()
        if self.database is not None:
            self.database.close()

    def apply_theme(self, theme_name: str) -> None:
        super().apply_theme(theme_name)
        # refresh_css only re-applies TCSS; the lists bake their colors into Rich text
        self.query_one(TodosTab).set_colors()
        self.query_one(LogsView).set_colors()

    @property
    def tabs(self) -> Tabs:
        return self.query_one("#tabs > ContentTabs", Tabs)

    def action_next_tab(self) -> None:
        if len(self.screen_stack) > 1:
            raise SkipAction()
        self.tabs.action_next_tab()

    @on(TabbedContent.TabActivated, "#tabs")
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self.tab = event.pane.id.removesuffix("-tab")
        self._show_tab(event.pane)

    def _show_tab(self, pane: TabPane) -> None:
        # The tab's view gives focus to its list, for its keys
        pane.children[0].tab_shown()
        self.refresh_footer()
