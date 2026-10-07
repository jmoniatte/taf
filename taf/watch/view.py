"""The Watch tab's list: the items collected from Slack and GitHub, grouped by project; no Textual."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from ..notes import split_query
from . import items as stored
from .items import REVIEWS, is_ci, is_review

# The kind of item that only informs; shown gray
FYI = "fyi"


# What each of WatchItem.links is, in the full view
LINK_NAMES = {"slack": "Slack conversation", "github": "GitHub PR", "jenkins": "Jenkins build", "added": "Link"}


@dataclass(frozen=True, slots=True)
class WatchItem:
    """A watch item, from Slack or GitHub, shaped like a todo, so the notes' table and detail view show
    it the same way."""

    id: int
    source: str
    key: str
    item_kind: str
    title: str
    details: str
    people: str
    url: str | None
    due: str | None
    pinned: bool
    done_at: datetime | None
    created_at: datetime
    # When it last happened in Slack, else when it was saved: what the order goes by
    updated_at: datetime
    project: str | None = None
    tags: tuple[str, ...] = ()
    is_todo = True

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def summary(self) -> str:
        return self.title

    @property
    def is_review(self) -> bool:
        return is_review(self.source, self.key)

    @property
    def links(self) -> list[tuple[str, str | None]]:
        """What its row ends with, as (kind, url): failing CI links to the build (jenkins) and to the PR
        (github); any other item to where it comes from (slack, github, or added by hand)."""
        if is_ci(self.source, self.key):
            return [("jenkins", self.url), ("github", self.key.removeprefix("ci:"))]
        return [(self.source if self.source in ("slack", "github") else "added", self.url)]

    @property
    def source_name(self) -> str:
        return {"github": "GitHub", "slack": "Slack"}.get(self.source, self.source)

    @property
    def content(self) -> str:
        """What the detail view shows and y copies: the summary, the details, who and the link."""
        lines = [self.title]
        if self.details:
            lines += ["", self.details]
        facts = [f"{name}: {value}" for name, value in (("People", self.people), ("Due", self.due), ("Kind", self.item_kind)) if value]
        # Each address written out, so it can be read and copied; only the address is a link
        facts += [f"{LINK_NAMES[kind]}: [{url}]({url})" for kind, url in self.links if url]
        if facts:
            lines += ["", *(f"- {fact}" for fact in facts)]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Group:
    """A project's heading in the list; project None is for items with no project, unless title
    names the heading, as for the reviews."""

    project: str | None
    count: int
    title: str | None = None
    # After the count, as a link: "3 PRs ready to deploy"
    note: str | None = None
    note_link: str | None = None

    @property
    def name(self) -> str:
        return self.title or self.project or "No project"


def local(stamp: str | None) -> datetime | None:
    """The collectors' ISO times, with their zone, as the naive local times taf's own dates are."""
    if not stamp:
        return None
    moment = datetime.fromisoformat(stamp)
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def shown_items(connection: sqlite3.Connection, query: str = "", status: str = "all") -> list[WatchItem]:
    """The watch items with every word of the query and the status: open, done or all."""
    words, _ = split_query(query)
    rows = stored.list_items(connection, status=None if status == "all" else status, words=words)
    return [_item(row) for row in rows]


def grouped(items: list[WatchItem], ready: tuple[int, str] | None = None) -> list[Group | WatchItem]:
    """The reviews first, under their own heading, then the items under a heading per project, the
    project with the latest activity first and those with no project last; inside each, pinned first,
    then the latest first. ready, how many PRs are ready to deploy and their list, follows the reviews'
    count, a heading of its own when there is no review."""
    ordered = sorted(items, key=lambda item: (not item.pinned, -item.updated_at.timestamp()))
    reviews = [item for item in ordered if item.is_review]
    rows: list[Group | WatchItem] = []
    if reviews or (ready and ready[0]):
        note, link = (f"{ready[0]} {'PR' if ready[0] == 1 else 'PRs'} ready to deploy", ready[1]) if ready else (None, None)
        rows = [Group(None, len(reviews), REVIEWS, note, link), *reviews]
    ordered = [item for item in ordered if not item.is_review]
    groups: dict[str | None, list[WatchItem]] = {}
    for item in sorted(ordered, key=lambda item: -item.updated_at.timestamp()):
        groups.setdefault(item.project, [])
    for item in ordered:
        groups[item.project].append(item)
    for project in sorted(groups, key=lambda name: name is None):
        rows.append(Group(project, len(groups[project])))
        rows.extend(groups[project])
    return rows


# The timer's interval (taf-watch.timer): "N minutes ago" goes minute by minute up to it
COLLECT_MINUTES = 20


def last_collected(connection: sqlite3.Connection) -> datetime | None:
    """When the last collect, from the timer or the Collect button, ended."""
    row = connection.execute("SELECT max(finished_at) AS at FROM watch_runs").fetchone()
    return local(row["at"]) if row else None


def ago(seconds: float) -> str:
    """5, 10 or 30 seconds ago, then each minute up to the timer's interval, then by 10 minutes,
    then hours, then days."""
    if seconds < 5:
        return "just now"
    for limit, label in ((10, "5 seconds"), (30, "10 seconds"), (60, "30 seconds")):
        if seconds < limit:
            return f"{label} ago"
    minutes = int(seconds // 60)
    if minutes <= COLLECT_MINUTES:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if minutes < 60:
        return f"{minutes // 10 * 10} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return "1 day ago" if days == 1 else f"{days} days ago"


def get_item(connection: sqlite3.Connection, item_id: int) -> WatchItem | None:
    row = stored.get_item(connection, item_id)
    return _item(row) if row else None


def set_done(connection: sqlite3.Connection, item_id: int, done: bool) -> WatchItem | None:
    stored.set_done(connection, [item_id], done)
    return get_item(connection, item_id)


def set_pinned(connection: sqlite3.Connection, item_id: int, pinned: bool) -> WatchItem | None:
    stored.set_pinned(connection, item_id, pinned)
    return get_item(connection, item_id)


def _item(row: sqlite3.Row) -> WatchItem:
    created = local(row["created_at"])
    return WatchItem(
        id=row["id"],
        source=row["source"],
        key=row["key"],
        item_kind=row["kind"],
        title=row["summary"],
        details=row["details"],
        people=row["people"],
        url=row["url"],
        due=row["due"],
        pinned=bool(row["pinned"]),
        done_at=local(row["done_at"]),
        created_at=created,
        updated_at=local(row["happened_at"]) or created,
        project=row["project"],
    )
