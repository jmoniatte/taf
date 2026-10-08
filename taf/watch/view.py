"""The Watch tab's list: the watch items grouped by project, and when the last collect ended; no
Textual."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import items
from .items import FYI, is_ci, is_review, parse_local
from ..notes import long_date

# The heading of the review requests, which have no project
REVIEWS = "Pull Requests"
# What each of WatchItem.links is called in the full view
LINK_NAMES = {"slack": "Slack conversation", "github": "GitHub PR", "jenkins": "Jenkins build", "added": "Link"}


@dataclass(frozen=True, slots=True)
class WatchItem:
    """A watch item, with what the notes' table and detail view read from a todo: id, summary,
    content, tags, pinned, done, links, gray, row_key and date_text."""

    id: int
    source: str
    key: str
    # Action, question, decision or fyi; not `kind`, which a note uses for note or todo
    item_kind: str
    summary: str
    details: str
    people: str
    url: str | None
    due: str | None
    pinned: bool
    done_at: datetime | None
    created_at: datetime
    # When it last happened at its source, else when it was saved: what the order goes by
    updated_at: datetime
    project: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def gray(self) -> bool:
        """Done, or an fyi, which only informs."""
        return self.done or self.item_kind == FYI

    @property
    def row_key(self) -> str:
        # Its id is another count than the todos'
        return f"watch:{self.id}"

    @property
    def date_text(self) -> str:
        return f"Created {long_date(self.created_at)}"

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
    def content(self) -> str:
        """What the detail view shows and y copies: the summary, the details, who and the links."""
        lines = [self.summary]
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
    """A heading in the list: a project's name, "No project", or REVIEWS, with its count and, for the
    reviews, a linked note: "3 PRs ready to deploy"."""

    name: str
    count: int
    note: str | None = None
    note_link: str | None = None


def load_items(connection: sqlite3.Connection, query: str = "", status: str = "all") -> list[WatchItem]:
    """The watch items with every word of the query and the status: open, done or all."""
    rows = items.list_items(connection, status=None if status == "all" else status, words=query.split())
    return [_item(row) for row in rows]


def load_item(connection: sqlite3.Connection, item_id: int) -> WatchItem | None:
    row = items.get_item(connection, item_id)
    return _item(row) if row else None


def mark_done(connection: sqlite3.Connection, item_id: int, done: bool) -> WatchItem | None:
    items.set_done(connection, [item_id], done)
    return load_item(connection, item_id)


def mark_pinned(connection: sqlite3.Connection, item_id: int, pinned: bool) -> WatchItem | None:
    items.set_pinned(connection, [item_id], pinned)
    return load_item(connection, item_id)


def grouped(shown: list[WatchItem], ready: tuple[int, str] | None = None) -> list[Group | WatchItem]:
    """The reviews first, under REVIEWS, then a heading per project, the project with the latest
    activity first and "No project" last; inside each, pinned first, then the latest first. ready, how
    many PRs are ready to deploy and their list, is the reviews' note, and makes their heading show
    with no review."""
    ordered = sorted(shown, key=lambda item: (not item.pinned, -item.updated_at.timestamp()))
    reviews = [item for item in ordered if item.is_review]
    rows: list[Group | WatchItem] = []
    if reviews or (ready and ready[0]):
        note = f"{ready[0]} {'PR' if ready[0] == 1 else 'PRs'} ready to deploy" if ready else None
        rows += [Group(REVIEWS, len(reviews), note, ready[1] if ready else None), *reviews]
    others = [item for item in ordered if not item.is_review]
    groups: dict[str | None, list[WatchItem]] = {}
    for item in sorted(others, key=lambda item: -item.updated_at.timestamp()):
        groups.setdefault(item.project, [])
    for item in others:
        groups[item.project].append(item)
    for project in sorted(groups, key=lambda name: name is None):
        rows += [Group(project or "No project", len(groups[project])), *groups[project]]
    return rows


def last_collected(connection: sqlite3.Connection) -> datetime | None:
    """When the last collect, from the timer or the Collect button, ended."""
    return parse_local(connection.execute("SELECT max(finished_at) AS at FROM watch_runs").fetchone()["at"])


def ago(seconds: float) -> str:
    """5, 10 or 30 seconds ago, then each minute up to 10 (the timer runs every 5), then by 10
    minutes, then hours, then days."""
    if seconds < 5:
        return "just now"
    for limit, label in ((10, "5 seconds"), (30, "10 seconds"), (60, "30 seconds")):
        if seconds < limit:
            return f"{label} ago"
    minutes = int(seconds // 60)
    if minutes < 10:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if minutes < 60:
        return f"{minutes // 10 * 10} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return "1 day ago" if days == 1 else f"{days} days ago"


def _item(row: sqlite3.Row) -> WatchItem:
    created = parse_local(row["created_at"])
    return WatchItem(
        id=row["id"],
        source=row["source"],
        key=row["key"],
        item_kind=row["kind"],
        summary=row["summary"],
        details=row["details"],
        people=row["people"],
        url=row["url"],
        due=row["due"],
        pinned=bool(row["pinned"]),
        done_at=parse_local(row["done_at"]),
        created_at=created,
        updated_at=parse_local(row["happened_at"]) or created,
        project=row["project"],
    )
