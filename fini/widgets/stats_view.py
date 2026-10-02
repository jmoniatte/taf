from datetime import date, timedelta

from rich.color import Color, blend_rgb
from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Select, Static
from tui_kit.config import save_setting
from tui_kit.shortcuts import GENERAL

from ..stats import (
    Entry,
    Period,
    level,
    levels,
    load_entries,
    time_off_days,
    minutes_by_action,
    minutes_by_day,
    minutes_by_month,
    periods,
    within,
)

# The actions' colors, the most time first; the others in comment
ACTION_COLORS = ("blue", "purple", "yellow", "orange", "cyan", "red", "green")
# How much of the green each shade has over the background, for 1 to 4
SHADES = (0.35, 0.55, 0.8, 1.0)
BAR_WIDTH = 40
WEEKDAYS = ("Mon", "", "Wed", "", "Fri", "", "")
# The action dropdown's value for all of them
ALL_ACTIONS = ""
DAY = "■"


class StatsScroll(VerticalScroll):
    """The stats as plain text, which the mouse selects like any text and y copies."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll down", show=False, group=GENERAL),
        Binding("k", "scroll_up", "Scroll up", show=False, group=GENERAL),
    ]


class StatsView(Vertical):
    """The Stats tab: a few figures, a GitHub-like graph of the days, and where the time goes, for
    a period and all actions or one."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entries: list[Entry] = []
        self.periods: list[Period] = []
        self.period = 0
        # None is all of them
        self.action: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="stats-controls"):
            yield Select([("Last 12 months", 0)], value=0, allow_blank=False, id="stats-period")
            yield Select([("All actions", ALL_ACTIONS)], value=ALL_ACTIONS, allow_blank=False, id="stats-action")
            yield Select(
                [("Hours", "hours"), ("Percentages", "percentages")],
                value=self.app.config.stats_show,
                allow_blank=False,
                id="stats-show",
            )
        yield Static("", id="stats-empty", classes="empty")
        with StatsScroll(id="stats-scroll"):
            yield Static("", id="stats-text")

    def help_section(self) -> tuple[str, tuple]:
        """The title and the keys of Help's right column."""
        return "Stats", (StatsScroll.BINDINGS,)

    def tab_shown(self) -> None:
        # Again on every show, for the logs written meanwhile
        self.load()
        self.query_one(StatsScroll).focus()

    def load(self) -> None:
        database = self.app.database
        self.entries = load_entries(database) if database is not None else []
        self.time_off = time_off_days(database, self.entries) if database is not None else set()
        self.periods = periods(self.entries, date.today())
        self.period = min(self.period, len(self.periods) - 1)
        selector = self.query_one("#stats-period", Select)
        # Changed here, not chosen: no message
        with selector.prevent(Select.Changed):
            selector.set_options([(period.label, index) for index, period in enumerate(self.periods)])
            selector.value = self.period
        self._show()

    @on(Select.Changed, "#stats-period")
    def _period_picked(self, event: Select.Changed) -> None:
        event.stop()
        self.period = int(event.value)
        self._show()
        self._back_to_stats(event.select)

    @on(Select.Changed, "#stats-action")
    def _action_picked(self, event: Select.Changed) -> None:
        event.stop()
        self.action = None if event.value == ALL_ACTIONS else str(event.value)
        self._show()
        self._back_to_stats(event.select)

    @on(Select.Changed, "#stats-show")
    def _show_picked(self, event: Select.Changed) -> None:
        event.stop()
        config = self.app.config
        if event.value == config.stats_show:
            return
        config.stats_show = str(event.value)
        # Kept for next time, so a screen being shared stays without hours
        warning = save_setting("stats_show", config.stats_show, config.path)
        if warning:
            self.app.notify(warning, severity="warning")
        self._show()
        self._back_to_stats(event.select)

    def _back_to_stats(self, select: Select) -> None:
        # Only after a pick: a Select also sends Changed when mounted, and focus would open this tab
        if select.has_focus:
            self.query_one(StatsScroll).focus()

    def set_colors(self) -> None:
        """Re-render against a new palette; the colors are baked into Rich text."""
        self._show()

    def _show(self) -> None:
        # Not loaded yet: the tab has not shown
        if not self.periods:
            return
        self._set_actions()
        empty = self.query_one("#stats-empty", Static)
        empty.update(self.app.database_error or "No logs with a duration yet")
        empty.display = not self.entries
        self.query_one(StatsScroll).display = bool(self.entries)
        if self.entries:
            percentages = self.app.config.stats_show == "percentages"
            text = stats_text(
                self.entries, self.periods[self.period], self.action, self.app.palette, date.today(), percentages, self.time_off
            )
            self.query_one("#stats-text", Static).update(text)

    def _set_actions(self) -> None:
        """The period's actions, the most time first, with their hours or share; one the period lacks is All."""
        period = self.periods[self.period]
        totals = minutes_by_action(within(self.entries, period))
        everything = sum(minutes for _, minutes in totals)
        percentages = self.app.config.stats_show == "percentages"
        if self.action not in dict(totals):
            self.action = None
        selector = self.query_one("#stats-action", Select)
        # Changed here, not chosen: no message
        with selector.prevent(Select.Changed):
            selector.set_options([("All actions", ALL_ACTIONS), *((f"{name} ({amount(minutes, everything, percentages)})", name) for name, minutes in totals)])
            selector.value = self.action or ALL_ACTIONS


def stats_text(
    entries: list[Entry],
    period: Period,
    action: str | None,
    palette: dict[str, str],
    today: date,
    percentages: bool = False,
    time_off: set[date] = frozenset(),
) -> Text:
    """The figures, the graph, the time per action, then per month; with percentages, no hours anywhere.
    The days of time off only have their own color in the graph."""
    period_entries = within(entries, period)
    shown = within(entries, period, action)
    colors = action_colors(period_entries, palette)
    parts = [
        figures(period_entries, shown, action, percentages),
        graphs(shown, period, palette, today, time_off),
        section("Where the time goes", palette),
        action_bars(period_entries, action, colors, palette, percentages),
        section(month_title(action, percentages), palette),
        month_bars(period_entries, action, colors, percentages),
    ]
    text = Text("\n\n").join(parts)
    text.no_wrap = True
    return text


def figures(period_entries: list[Entry], shown: list[Entry], action: str | None, percentages: bool) -> Text:
    """All actions: hours, days, and hours a day, or the share of the first actions; one action:
    its hours, its share of the time, its days and its hours on those days, or only its share."""
    days = minutes_by_day(shown)
    total = sum(days.values())
    everything = sum(entry.duration for entry in period_entries)
    average = hours(total // len(days)) if days else "0 h"
    if action is None and percentages:
        parts = [f"{name} {percent(minutes, everything)}" for name, minutes in minutes_by_action(shown)[:5]]
    elif action is None:
        parts = [f"{hours(total)} logged", f"{len(days)} days", f"{average} a day"]
    elif percentages:
        parts = [f"+{action} {percent(total, everything)} of the time"]
    else:
        parts = [
            f"{hours(total)} of +{action}",
            f"{percent(total, everything)} of the time",
            f"on {len(days)} days",
            f"{average} on those days",
        ]
    return Text("   ".join(parts), style="bold")


def graphs(shown: list[Entry], period: Period, palette: dict[str, str], today: date, time_off: set[date] = frozenset()) -> Text:
    """One graph, or one per year for all of them, the last year first."""
    days = minutes_by_day(shown)
    thresholds = levels(list(days.values()))
    if period.last.year == period.first.year or period.last - period.first < timedelta(days=366):
        return graph(days, thresholds, period.first, period.last, palette, today, time_off)
    years = range(period.last.year, period.first.year - 1, -1)
    return Text("\n\n").join(
        Text(str(year), style="bold") + Text("\n") + graph(days, thresholds, max(date(year, 1, 1), period.first), date(year, 12, 31), palette, today, time_off)
        for year in years
    )


def graph(
    days: dict[date, int],
    thresholds: list[int],
    first: date,
    last: date,
    palette: dict[str, str],
    today: date,
    time_off: set[date] = frozenset(),
) -> Text:
    """A row per weekday and a column per week, as GitHub has it, with the months over the weeks;
    a day after today is left blank, a day of time off only is blue."""
    start = first - timedelta(days=first.weekday())
    weeks = (last - start).days // 7 + 1
    shades = day_shades(palette)
    label_width = 4
    months = [" "] * (label_width + 2 * weeks)
    for week in range(weeks):
        monday = start + timedelta(weeks=week)
        week_days = [day for day in (monday + timedelta(days=n) for n in range(7)) if first <= day <= last]
        # The week a month starts in, and the first week for a month already under way
        starts = [day for day in week_days if day.day == 1 or (week == 0 and day == week_days[0])]
        column = label_width + 2 * week
        name = starts[0].strftime("%b") if starts else ""
        # Unless the previous month's name is still in the way
        if name and all(cell == " " for cell in months[column - 1 : column + len(name)]):
            months[column : column + len(name)] = name
    text = Text("".join(months).rstrip(), style=palette["comment"])
    for weekday, label in enumerate(WEEKDAYS):
        text.append("\n")
        text.append(label.ljust(label_width), style=palette["comment"])
        for week in range(weeks):
            day = start + timedelta(weeks=week, days=weekday)
            if first <= day <= min(last, today):
                minutes = days.get(day, 0)
                if not minutes and day in time_off:
                    text.append(DAY, style=palette["blue"])
                else:
                    text.append(DAY, style=shades[level(minutes, thresholds)])
            else:
                text.append(" ")
            text.append(" ")
    # Under the last weeks, as GitHub has it
    legend = Text("Less ", style=palette["comment"])
    for shade in shades:
        legend.append(DAY + " ", style=shade)
    legend.append("More", style=palette["comment"])
    legend.append("   ")
    legend.append(DAY, style=palette["blue"])
    legend.append(" Time off", style=palette["comment"])
    text.append("\n")
    text.append(" " * max(label_width + 2 * weeks - 1 - legend.cell_len, 0))
    text.append_text(legend)
    return text


def day_shades(palette: dict[str, str]) -> list[str]:
    """The colors of no logs, then of the four levels: the green blended into the background."""
    green = Color.parse(palette["green"]).triplet
    background = Color.parse(palette["bg"]).triplet
    if green is None or background is None:
        return [palette["bg-light"], *[palette["green"]] * 4]
    return [palette["bg-light"], *(blend_rgb(background, green, shade).hex for shade in SHADES)]


def action_colors(period_entries: list[Entry], palette: dict[str, str]) -> dict[str, str]:
    """Each action's color, by its time in the period, the most first."""
    ranked = [action for action, _ in minutes_by_action(period_entries)]
    return {action: palette[ACTION_COLORS[rank]] if rank < len(ACTION_COLORS) else palette["comment"] for rank, action in enumerate(ranked)}


def section(title: str, palette: dict[str, str]) -> Text:
    return Text(title, style=Style(color=palette["yellow"], bold=True))


def action_bars(
    period_entries: list[Entry], action: str | None, colors: dict[str, str], palette: dict[str, str], percentages: bool
) -> Text:
    """A bar per action, as long as its share of the time; the action picked in bold, the others dim
    while one is."""
    totals = minutes_by_action(period_entries)
    everything = sum(minutes for _, minutes in totals)
    width = max(len(name) for name, _ in totals) if totals else 0
    lines = []
    for name, minutes in totals:
        share = minutes / everything if everything else 0
        filled = round(share * BAR_WIDTH)
        picked = action is None or name == action
        line = Text(name.ljust(width) + " ", style="bold" if action == name else "")
        line.append("█" * filled, style=colors[name] if picked else palette["comment"])
        line.append("░" * (BAR_WIDTH - filled), style=palette["bg-light"])
        line.append(f" {round(100 * share):>3}%")
        if not percentages:
            line.append(f"  {hours(minutes):>7}")
        lines.append(line)
    return Text("\n").join(lines)


def month_title(action: str | None, percentages: bool) -> str:
    if percentages:
        return f"Per month, share of +{action}" if action else "Per month, share of each action"
    return f"Per month, +{action}" if action else "Per month"


def month_bars(period_entries: list[Entry], action: str | None, colors: dict[str, str], percentages: bool) -> Text:
    """A bar per month, its actions stacked in their colors, or the action picked alone. In hours,
    the longest month is the full width; in percentages, every month is, so a bar is shares."""
    months = minutes_by_month(period_entries)
    if not months:
        return Text("No time logged")
    shown = [(month, {name: minutes for name, minutes in totals.items() if action in (None, name)}, totals) for month, totals in months]
    longest = max(sum(picked.values()) for _, picked, _ in shown) or 1
    lines = []
    for month, picked, totals in shown:
        everything = sum(totals.values())
        width = everything if percentages else longest
        line = Text(month.strftime("%b %Y") + " ")
        used = 0
        done = 0
        # The actions in the order of the colors, so the stacks line up from month to month
        for name in sorted(picked, key=lambda name: list(colors).index(name)):
            done += picked[name]
            # Rounded on the running total, so the stack's length is the month's
            end = round(done / width * BAR_WIDTH)
            line.append("█" * (end - used), style=colors[name])
            used = end
        line.append(" " * (BAR_WIDTH - used))
        if percentages and action:
            line.append(f" {percent(done, everything):>4}")
        elif not percentages:
            line.append(f" {hours(done):>6}")
        lines.append(line)
    return Text("\n").join(lines)


def amount(minutes: int, everything: int, percentages: bool) -> str:
    return percent(minutes, everything) if percentages else hours(minutes)


def percent(minutes: int, everything: int) -> str:
    return f"{round(100 * minutes / everything) if everything else 0}%"


def hours(minutes: int) -> str:
    """Hours, with a decimal under 10."""
    value = minutes / 60
    return f"{value:.1f} h" if value < 10 else f"{value:,.0f} h"
