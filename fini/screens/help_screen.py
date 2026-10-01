from collections.abc import Iterable

from textual.binding import Binding
from tui_kit.help_screen import HelpScreen
from tui_kit.shortcuts import SECTIONS, Shortcut


def documented(*sources: Iterable[object]) -> tuple[Shortcut, ...]:
    """The bindings Help lists, of either group, in the order they are declared."""
    return tuple(
        Shortcut(binding.key_display or binding.key, binding.description)
        for source in sources
        for binding in source
        if isinstance(binding, Binding) and binding.group in SECTIONS and binding.description
    )


class FiniHelpScreen(HelpScreen):
    """tui-kit's Help as outils has it: the app's keys, which every tab shares, on the left, and the
    tab's own on the right under its name. Both columns keep some width, so a tab with few keys of
    its own still gets a panel of a fair size.
    """

    def __init__(self, title: str, sources: tuple[Iterable[object], ...]) -> None:
        super().__init__()
        self.title = title
        self.sources = sources

    def _sections(self) -> list[tuple[str, tuple[Shortcut, ...]]]:
        return [("General", documented(self.app.BINDINGS)), (self.title, documented(*self.sources))]
