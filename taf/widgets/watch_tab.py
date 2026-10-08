"""The Watch tab: the items collected from Slack and GitHub or added by agents, under their project,
to close and star; one in full in place of the list. Nothing here makes or edits one."""

import time

from textual import work
from textual.binding import Binding
from tui_kit.shortcuts import ACTIONS

from ..watch.config import from_taf
from ..watch.github import ready_to_deploy
from ..watch import view
from ..watch.view import Group, WatchItem
from .collect import CollectControl
from .list_tab import ListTab
from .list_view import ListView
from .item_detail import ItemDetail, detail_bindings

# How often the list reads again what the watch timer may have added
RELOAD_SECONDS = 60
# How often GitHub is asked how many PRs are ready to deploy
DEPLOY_SECONDS = 5 * 60


class WatchView(ListView):
    """The list: the items under a heading per project, the reviews first with how many PRs are ready
    to deploy. While the tab is on show, it reads again every minute and asks GitHub every 5."""

    NOUN = "item"
    HAS_DONE = True
    BINDINGS = [
        Binding("x", "toggle_done", "Mark done, or not done", group=ACTIONS),
        Binding("p", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("space", "toggle_pin", "Pin, or unpin", group=ACTIONS),
        Binding("f", "next_status", "Show open, done or all", group=ACTIONS),
        Binding("slash", "search", "Search", key_display="/", group=ACTIONS),
        Binding("r", "refresh", "Refresh", group=ACTIONS),
        Binding("y", "copy", "Copy the item", group=ACTIONS),
        Binding("c", "collect", "Collect now: GitHub, then Slack (a paid run)", group=ACTIONS),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # How many PRs are ready to deploy and their list on GitHub, once GitHub said
        self.ready: tuple[int, str] | None = None
        # time.monotonic() of the last time GitHub was asked
        self.asked_at = 0.0

    def on_mount(self) -> None:
        super().on_mount()
        self.set_interval(RELOAD_SECONDS, self._while_shown(self.load))
        self.set_interval(DEPLOY_SECONDS, self._while_shown(self.ask_ready))

    def _while_shown(self, action):
        def run() -> None:
            # Not while the search is being typed, which a reload would undo
            if self.app.tab == "watch" and self.display and not self.query_one("#search").has_focus:
                action()
        return run

    def fetch(self, words: str) -> list[Group | WatchItem]:
        return view.grouped(view.load_items(self.database, words, self.status), self.ready)

    def mark_done(self, item_id: int, done: bool) -> WatchItem | None:
        return view.mark_done(self.database, item_id, done)

    def mark_pinned(self, item_id: int, pinned: bool) -> WatchItem | None:
        return view.mark_pinned(self.database, item_id, pinned)

    def action_refresh(self) -> None:
        self.load()
        self.ask_ready()

    def action_collect(self) -> None:
        self.app.query_one(CollectControl).collect()

    def ask_ready(self) -> None:
        """Ask GitHub, in a thread, how many PRs are ready to deploy; a second or so."""
        try:
            github = from_taf(self.app.config).github
        except ValueError:
            return
        if github.deploy_repo:
            self.asked_at = time.monotonic()
            self._ask_ready(github)

    @work(thread=True, exit_on_error=False, group="ready", exclusive=True)
    def _ask_ready(self, github) -> None:
        ready = ready_to_deploy(github)
        if ready is not None:
            self.app.call_from_thread(self._ready_known, ready)

    def _ready_known(self, ready: tuple[int, str]) -> None:
        if ready != self.ready:
            self.ready = ready
            self.load()


class WatchDetail(ItemDetail):
    """One item in full; Slack or GitHub is where it changes, so no Edit or Delete."""

    NOUN = "item"
    CRUMB = "Watch"
    HAS_DONE = True
    EDITABLE = False
    BINDINGS = detail_bindings(NOUN, editable=False)


class WatchTab(ListTab):
    LIST = WatchView
    DETAIL = WatchDetail
    TITLE = "Watch"

    def fetch(self, item: WatchItem) -> WatchItem | None:
        return view.load_item(self.database, item.id)

    def tab_shown(self) -> None:
        """Read again on every show, as the timers only run while the tab is on show."""
        if self.viewing is None:
            self.list.load()
            if time.monotonic() - self.list.asked_at > DEPLOY_SECONDS:
                self.list.ask_ready()
        super().tab_shown()
