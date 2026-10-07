"""Items (things to do or know), the collectors' cursors and their runs."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

KINDS = ("action", "question", "decision", "fyi")
STATUSES = ("open", "done")
# Items with their project's name, and open or done from done_at, as the command line and agents see them
SELECT_ITEMS = (
    "SELECT i.*, p.name AS project, CASE WHEN i.done_at IS NULL THEN 'open' ELSE 'done' END AS status "
    "FROM watch_items i LEFT JOIN watch_projects p ON p.id = i.project_id"
)
# An item names its project; the tables hold its id
PROJECT_ID = "(SELECT id FROM watch_projects WHERE name = :project)"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
        f"""
        INSERT INTO watch_items (source, key, project_id, kind, summary, details, people, url, due, done_at,
                                  happened_at, created_at, updated_at)
        VALUES (:source, :key, {PROJECT_ID}, :kind, :summary, :details, :people, :url, :due,
                CASE WHEN :resolved THEN :stamp END, :happened_at, :stamp, :stamp)
        ON CONFLICT (source, key) DO UPDATE SET
            project_id = coalesce(excluded.project_id, project_id), kind = excluded.kind,
            summary = excluded.summary, details = excluded.details, people = excluded.people,
            url = coalesce(excluded.url, url), due = coalesce(excluded.due, due),
            done_at = CASE WHEN :resolved THEN coalesce(done_at, :stamp) ELSE done_at END,
            happened_at = coalesce(excluded.happened_at, happened_at), updated_at = :stamp
        """,
        {**item.__dict__, "stamp": stamp},
    )


def update_item(db: sqlite3.Connection, item_id: int, item: Item) -> bool:
    """Rewrite an open item of the same source with what a later conversation said; done if resolved."""
    cursor = db.execute(
        f"""
        UPDATE watch_items SET
            project_id = coalesce({PROJECT_ID}, project_id), kind = :kind, summary = :summary,
            details = :details, people = :people, url = coalesce(url, :url), due = coalesce(:due, due),
            done_at = CASE WHEN :resolved THEN :stamp END,
            happened_at = coalesce(:happened_at, happened_at), updated_at = :stamp
        WHERE id = :id AND source = :source AND done_at IS NULL
        """,
        {**item.__dict__, "id": item_id, "stamp": now()},
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


def set_done(db: sqlite3.Connection, item_ids: list[int], done: bool = True) -> list[int]:
    """Mark the items done, or open again; returns the ids that do not exist."""
    missing = []
    for item_id in item_ids:
        stamp = now()
        cursor = db.execute(
            "UPDATE watch_items SET done_at = CASE WHEN ? THEN coalesce(done_at, ?) END, updated_at = ? WHERE id = ?",
            (done, stamp, stamp, item_id),
        )
        if cursor.rowcount == 0:
            missing.append(item_id)
    return missing


def set_pinned(db: sqlite3.Connection, item_id: int, pinned: bool) -> bool:
    """Pin or unpin the item; False when it does not exist. updated_at says what the source last said."""
    return db.execute("UPDATE watch_items SET pinned = ? WHERE id = ?", (pinned, item_id)).rowcount > 0


def set_project(db: sqlite3.Connection, item_ids: list[int], project: str | None) -> list[int]:
    """Move the items to the project (None: no project); returns the ids that do not exist."""
    missing = []
    for item_id in item_ids:
        cursor = db.execute(
            "UPDATE watch_items SET project_id = (SELECT id FROM watch_projects WHERE name = ?), updated_at = ? WHERE id = ?",
            (project, now(), item_id),
        )
        if cursor.rowcount == 0:
            missing.append(item_id)
    return missing


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
