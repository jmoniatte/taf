from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class TodosView(Vertical):
    """The Todos tab; a placeholder until the todos are in the database."""

    def compose(self) -> ComposeResult:
        yield Static("No todos yet", classes="empty")
