"""The footer's Collect button and, by it, when the last collect ended: on the Watch tab only."""

import subprocess
import sys
import tempfile
import time
from datetime import datetime

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static
from textual.worker import get_current_worker

from ..watch.view import ago, last_collected
from .buttons import flat_button


class Collected(Message):
    """A collect started here ended: the Watch list reads again."""


class CollectControl(Horizontal):
    """Collect runs `taf watch collect` as the timer does: GitHub, then Slack, a minute or more and a
    paid Claude run. By it, "5 minutes ago": the last collect's end, the timer's or the button's,
    nothing while the button's runs."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.collecting = False
        self.collected_at: datetime | None = None

    def compose(self) -> ComposeResult:
        yield flat_button("Collect", "btn-collect", classes="tinted -cyan")
        yield Static("", id="collected-at")

    def on_mount(self) -> None:
        self.read_collected_at()
        self.set_interval(1, self.show_collected_at)
        # The timer's collects, which only the database tells of
        self.set_interval(15, self.read_collected_at)

    def read_collected_at(self) -> None:
        database = self.app.database
        self.collected_at = last_collected(database) if database is not None else None
        self.show_collected_at()

    def show_collected_at(self) -> None:
        text = ""
        if self.collected_at is not None and not self.collecting:
            text = ago((datetime.now() - self.collected_at).total_seconds())
        self.query_one("#collected-at", Static).update(text)

    @on(Button.Pressed, "#btn-collect")
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.collect()

    def collect(self) -> None:
        if self.collecting:
            return
        self.collecting = True
        button = self.query_one("#btn-collect", Button)
        button.disabled = True
        button.label = "Collecting..."
        self.show_collected_at()
        self._collect()

    @work(thread=True, exit_on_error=False, group="collect")
    def _collect(self) -> None:
        """Its own process and session, so it finishes even when taf quits first, its prints in files
        rather than pipes nobody would read then. Quitting cancels this worker, which only looks every
        second whether the collect ended, so taf exits at once."""
        worker = get_current_worker()
        command = [sys.executable, "-m", "taf", "watch", "collect"]
        try:
            with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, text=True, start_new_session=True
                )
                while (code := process.poll()) is None:
                    if worker.is_cancelled:
                        return
                    time.sleep(1)
                out.seek(0)
                err.seek(0)
                result = (code, out.read().strip(), err.read().strip())
        except OSError as error:
            result = (1, "", str(error))
        self.app.call_from_thread(self._collected, *result)

    def _collected(self, code: int, out: str, err: str) -> None:
        self.collecting = False
        button = self.query_one("#btn-collect", Button)
        button.disabled = False
        button.label = "Collect"
        self.read_collected_at()
        # Done: the time by the button says so; only a failure has a message
        if code != 0:
            self.notify("\n".join(part for part in (out, err) if part) or "Collect failed", severity="error", timeout=10)
        self.post_message(Collected())
