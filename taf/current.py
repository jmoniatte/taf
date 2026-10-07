"""The Current tab's list: the items veille collects from Slack and GitHub, grouped by project; no Textual."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .notes import split_query
from .veille import items as veille_items

# The kind of item that only informs; shown gray
FYI = "fyi"


@dataclass(frozen=True, slots=True)
class VeilleItem:
    """A veille item, from Slack or GitHub, shaped like a todo, so the notes' table and detail view show
    it the same way."""

    id: int
    source: str
    item_kind: str
    title: str
    details: str
    people: str
    url: str | None
    due: str | None
    pinned: bool
    done_at: datetime | None
    created_at: datetime
    # When it last happened in Slack, else when veille saved it: what the order goes by
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
    def source_name(self) -> str:
        return {"github": "GitHub", "slack": "Slack"}.get(self.source, self.source)

    @property
    def content(self) -> str:
        """What the detail view shows and y copies: the summary, the details, who and the link."""
        lines = [self.title]
        if self.details:
            lines += ["", self.details]
        facts = [f"{name}: {value}" for name, value in (("People", self.people), ("Due", self.due), ("Kind", self.item_kind)) if value]
        if self.url:
            facts.append(f"[Open in {self.source_name}]({self.url})")
        if facts:
            lines += ["", *(f"- {fact}" for fact in facts)]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Group:
    """A project's heading in the list; project None is for items with no project."""

    project: str | None
    count: int

    @property
    def name(self) -> str:
        return self.project or "No project"


def local(stamp: str | None) -> datetime | None:
    """veille's ISO times, with their zone, as the naive local times taf's own dates are."""
    if not stamp:
        return None
    moment = datetime.fromisoformat(stamp)
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def current_items(connection: sqlite3.Connection, query: str = "", status: str = "all") -> list[VeilleItem]:
    """veille's items with every word of the query and the status: open, done or all."""
    words, _ = split_query(query)
    rows = veille_items.list_items(connection, status=None if status == "all" else status, words=words)
    return [_item(row) for row in rows]


def grouped(items: list[VeilleItem]) -> list[Group | VeilleItem]:
    """The items under a heading per project, the project with the latest activity first and those
    with no project last; inside each, pinned first, then the latest first."""
    ordered = sorted(items, key=lambda item: (not item.pinned, -item.updated_at.timestamp()))
    groups: dict[str | None, list[VeilleItem]] = {}
    for item in sorted(ordered, key=lambda item: -item.updated_at.timestamp()):
        groups.setdefault(item.project, [])
    for item in ordered:
        groups[item.project].append(item)
    rows: list[Group | VeilleItem] = []
    for project in sorted(groups, key=lambda name: name is None):
        rows.append(Group(project, len(groups[project])))
        rows.extend(groups[project])
    return rows


def get_item(connection: sqlite3.Connection, item_id: int) -> VeilleItem | None:
    row = veille_items.get_item(connection, item_id)
    return _item(row) if row else None


def set_done(connection: sqlite3.Connection, item_id: int, done: bool) -> VeilleItem | None:
    veille_items.set_done(connection, [item_id], done)
    return get_item(connection, item_id)


def set_pinned(connection: sqlite3.Connection, item_id: int, pinned: bool) -> VeilleItem | None:
    veille_items.set_pinned(connection, item_id, pinned)
    return get_item(connection, item_id)


def _item(row: sqlite3.Row) -> VeilleItem:
    created = local(row["created_at"])
    return VeilleItem(
        id=row["id"],
        source=row["source"],
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
