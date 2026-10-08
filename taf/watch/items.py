"""Items (things to do or know), the collectors' cursors and their runs."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

FYI = "fyi"
KINDS = ("action", "question", "decision", FYI)
ITEM_STATUSES = ("open", "done")
# Items with their project's name, and open or done from done_at, as the command line and agents see them
SELECT_ITEMS = (
    "SELECT i.*, p.name AS project, CASE WHEN i.done_at IS NULL THEN 'open' ELSE 'done' END AS status "
    "FROM watch_items i LEFT JOIN watch_projects p ON p.id = i.project_id"
)


def is_ci(source: str, key: str) -> bool:
    """Failing checks on one of the user's PRs (github.ci_item): its url is the build, its key the PR's."""
    return source == "github" and key.startswith("ci:")


def is_review(source: str, key: str) -> bool:
    """A PR waiting on the user's review (github.review_requests)."""
    return source == "github" and key.startswith("review:")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def local_iso(stamp: str) -> str | None:
    """A UTC time, as GitHub gives it, in the local zone, as the items store their times."""
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone().isoformat(timespec="seconds")


def parse_local(stamp: str | None) -> datetime | None:
    """A stored time, with its zone, as the naive local time taf's own dates are."""
    if not stamp:
        return None
    moment = datetime.fromisoformat(stamp)
    return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment


def project_id(db: sqlite3.Connection, name: str | None) -> int | None:
    """An item or a PR names its project; the tables hold its id."""
    row = db.execute("SELECT id FROM watch_projects WHERE name = ?", (name,)).fetchone() if name else None
    return row["id"] if row else None


@dataclass
class Item:
    source: str
    # Unique within the source, so a thread seen again updates its item instead of adding one
    key: str
    kind: str
    summary: str
    project: str | None = None
    details: str = ""
    people: str = ""
    url: str | None = None
    due: str | None = None
    happened_at: str | None = None
    # The source says it is finished: the item is stored as done
    resolved: bool = False


def save_item(db: sqlite3.Connection, item: Item) -> None:
    """Add the item, or update the one with the same source and key, keeping it open or done unless resolved."""
    stamp = now()
    db.execute(
        """
        INSERT INTO watch_items (source, key, project_id, kind, summary, details, people, url, due, done_at,
                                  happened_at, created_at, updated_at)
        VALUES (:source, :key, :project_id, :kind, :summary, :details, :people, :url, :due,
                CASE WHEN :resolved THEN :stamp END, :happened_at, :stamp, :stamp)
        ON CONFLICT (source, key) DO UPDATE SET
            project_id = coalesce(excluded.project_id, project_id), kind = excluded.kind,
            summary = excluded.summary, details = excluded.details, people = excluded.people,
            url = coalesce(excluded.url, url), due = coalesce(excluded.due, due),
            done_at = CASE WHEN :resolved THEN coalesce(done_at, :stamp) ELSE done_at END,
            happened_at = coalesce(excluded.happened_at, happened_at), updated_at = :stamp
        """,
        {**item.__dict__, "project_id": project_id(db, item.project), "stamp": stamp},
    )


def update_item(db: sqlite3.Connection, item_id: int, item: Item) -> bool:
    """Rewrite an open item of the same source with what a later conversation said; done if resolved."""
    cursor = db.execute(
        """
        UPDATE watch_items SET
            project_id = coalesce(:project_id, project_id), kind = :kind, summary = :summary,
            details = :details, people = :people, url = coalesce(url, :url), due = coalesce(:due, due),
            done_at = CASE WHEN :resolved THEN :stamp END,
            happened_at = coalesce(:happened_at, happened_at), updated_at = :stamp
        WHERE id = :id AND source = :source AND done_at IS NULL
        """,
        {**item.__dict__, "id": item_id, "project_id": project_id(db, item.project), "stamp": now()},
    )
    return cursor.rowcount > 0


def list_items(
    db: sqlite3.Connection, project: str | None = None, status: str | None = "open", words: list[str] = (),
    source: str | None = None,
) -> list[sqlite3.Row]:
    """Items, the latest first; project None means every project, status None every status."""
    sql = f"{SELECT_ITEMS} WHERE 1"
    params: list = []
    if source is not None:
        sql += " AND i.source = ?"
        params.append(source)
    if project is not None:
        sql += " AND p.name = ?"
        params.append(project)
    if status is not None:
        sql += " AND i.done_at IS NULL" if status == "open" else " AND i.done_at IS NOT NULL"
    for word in words:
        sql += " AND (i.summary || ' ' || i.details || ' ' || i.people) LIKE ?"
        params.append(f"%{word}%")
    sql += " ORDER BY coalesce(i.happened_at, i.created_at) DESC, i.id DESC"
    return db.execute(sql, params).fetchall()


def get_item(db: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return db.execute(f"{SELECT_ITEMS} WHERE i.id = ?", (item_id,)).fetchone()


def update_each(db: sqlite3.Connection, item_ids: list[int], sql: str, params: tuple) -> list[int]:
    """Run sql, whose last parameter is the item's id, for each item; returns the ids that do not exist."""
    return [item_id for item_id in item_ids if db.execute(sql, (*params, item_id)).rowcount == 0]


def set_done(db: sqlite3.Connection, item_ids: list[int], done: bool = True) -> list[int]:
    """Mark the items done, or open again; returns the ids that do not exist."""
    stamp = now()
    sql = "UPDATE watch_items SET done_at = CASE WHEN ? THEN coalesce(done_at, ?) END, updated_at = ? WHERE id = ?"
    return update_each(db, item_ids, sql, (done, stamp, stamp))


def set_pinned(db: sqlite3.Connection, item_ids: list[int], pinned: bool) -> list[int]:
    """Pin or unpin the items; returns the ids that do not exist."""
    return update_each(db, item_ids, "UPDATE watch_items SET pinned = ? WHERE id = ?", (pinned,))


def set_project(db: sqlite3.Connection, item_ids: list[int], project: str | None) -> list[int]:
    """Move the items to the project (None: no project); returns the ids that do not exist."""
    sql = "UPDATE watch_items SET project_id = ?, updated_at = ? WHERE id = ?"
    return update_each(db, item_ids, sql, (project_id(db, project), now()))


def get_cursor(db: sqlite3.Connection, source: str) -> str | None:
    row = db.execute("SELECT value FROM watch_cursors WHERE source = ?", (source,)).fetchone()
    return row["value"] if row else None


def set_cursor(db: sqlite3.Connection, source: str, value: str) -> None:
    db.execute(
        "INSERT INTO watch_cursors (source, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (source) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (source, value, now()),
    )


def record_run(
    db: sqlite3.Connection, source: str, started_at: str, cost_usd: float | None,
    pages: int | None, items: int, error: str | None,
) -> None:
    db.execute(
        "INSERT INTO watch_runs (source, started_at, finished_at, cost_usd, pages, items, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source, started_at, now(), cost_usd, pages, items, error),
    )


def recent_runs(db: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM watch_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
