"""Todos in the database: listing, searching, saving, done and pinned, and their #tags; no Textual."""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .logs import timestamp

# What the status dropdown offers, as (label, status)
STATUSES = (("Open", "open"), ("Done", "done"), ("All", "all"))
DEFAULT_STATUS = "open"

# YafYaf's rule for a tag: a #word starting with a letter, not glued to what precedes it
TAG = re.compile(r"(?<![\w&/#-])#(?P<name>[a-z][a-z0-9_-]*)", re.IGNORECASE)
INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True, slots=True)
class Todo:
    id: int
    content: str
    tags: tuple[str, ...]
    pinned: bool
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def summary(self) -> str:
        """The first line with text, what the list shows."""
        return next((line.strip() for line in self.content.splitlines() if line.strip()), "")


def front_matter(todo: Todo) -> dict[str, str]:
    """What the editor and the view show over a todo's content, in this order."""
    return {
        "created_at": f"{todo.created_at:%Y-%m-%d %H:%M}",
        "updated_at": f"{todo.updated_at:%Y-%m-%d %H:%M}",
        "done_at": f"{todo.done_at:%Y-%m-%d %H:%M}" if todo.done_at else "",
        "pinned": "true" if todo.pinned else "false",
    }


def long_date(moment: datetime) -> str:
    """Monday, July 1, 2026, as yafyaf-tui shows a yaf's date."""
    return f"{moment:%A}, {moment:%B} {moment.day}, {moment.year}"


def find_tags(text: str) -> list[tuple[int, int, str]]:
    """(start, end, name) of every tag in text, skipping inline code, names lowercased."""
    code = [(match.start(), match.end()) for match in INLINE_CODE.finditer(text)]
    return [
        (match.start(), match.end(), match.group("name").lower().rstrip("-"))
        for match in TAG.finditer(text)
        if not any(start <= match.start() < end for start, end in code)
    ]


def tags_of(content: str) -> list[str]:
    """The content's tags, each once, in the order they first appear."""
    return list(dict.fromkeys(name for _, _, name in find_tags(content)))


# is:open or is:done in a search, like GitHub's is:open and is:closed, which means done here too
STATUS_WORD = re.compile(r"is:(?P<status>open|done|closed)", re.IGNORECASE)


def split_status(query: str) -> tuple[str, str]:
    """The status a search asks for with is:open or is:done (all without one; the last one wins),
    and the search without it."""
    status, words = "all", []
    for word in query.split():
        if match := STATUS_WORD.fullmatch(word):
            status = "done" if match.group("status").lower() in ("done", "closed") else "open"
        else:
            words.append(word)
    return status, " ".join(words)


def split_query(query: str) -> tuple[list[str], list[str]]:
    """A search's plain words, and its #tags; like YafYaf, a tag is a whole word."""
    words, tags = [], []
    for word in query.split():
        match = TAG.fullmatch(word)
        if match:
            tags.append(match.group("name").lower().rstrip("-"))
        else:
            words.append(word)
    return words, tags


def list_todos(connection: sqlite3.Connection, query: str = "", status: str = DEFAULT_STATUS) -> list[Todo]:
    """The todos of a status (open, done or all) whose content has every word of the query outside
    its tags (any case) and every #tag; the last updated first, pinned and done or not."""
    where, params = [], []
    if status == "open":
        where.append("done_at IS NULL")
    elif status == "done":
        where.append("done_at IS NOT NULL")
    words, tags = split_query(query)
    for tag in tags:
        where.append("EXISTS (SELECT 1 FROM json_each(todos.tags) WHERE value = ?)")
        params.append(tag)
    sql = "SELECT * FROM todos"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC"
    todos = [_todo(row) for row in connection.execute(sql, params)]
    # Words are matched here rather than with LIKE, which cannot leave the tags out: there are few todos
    words = [word.casefold() for word in words]
    return [todo for todo in todos if all(word in without_tags(todo.content).casefold() for word in words)]


def without_tags(text: str) -> str:
    """text with its #tags blanked out, so a search for "api" does not find "#api"; a #word in
    inline code is not a tag, so it stays."""
    for start, end, _ in reversed(find_tags(text)):
        text = text[:start] + " " + text[end:]
    return text


def tag_counts(connection: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every tag with how many todos have it, the most used first."""
    rows = connection.execute(
        "SELECT value, count(*) FROM todos, json_each(todos.tags) GROUP BY value ORDER BY count(*) DESC, value"
    )
    return [(name, count) for name, count in rows]


def get_todo(connection: sqlite3.Connection, todo_id: int) -> Todo | None:
    row = connection.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _todo(row) if row else None


def create_todo(connection: sqlite3.Connection, content: str) -> Todo:
    now = timestamp(datetime.now())
    cursor = connection.execute(
        "INSERT INTO todos (content, tags, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (content, json.dumps(tags_of(content)), now, now),
    )
    return get_todo(connection, cursor.lastrowid)


def update_todo(connection: sqlite3.Connection, todo_id: int, content: str) -> Todo | None:
    """Save new content and the tags in it; None when the todo is gone."""
    connection.execute(
        "UPDATE todos SET content = ?, tags = ?, updated_at = ? WHERE id = ?",
        (content, json.dumps(tags_of(content)), timestamp(datetime.now()), todo_id),
    )
    return get_todo(connection, todo_id)


def set_done(connection: sqlite3.Connection, todo_id: int, done: bool) -> Todo | None:
    """Mark done now, or not done; marking a done todo done again keeps when it was done.

    updated_at is left alone, here and when pinning: it says when the content last changed.
    """
    connection.execute(
        "UPDATE todos SET done_at = CASE WHEN ? THEN coalesce(done_at, ?) END WHERE id = ?",
        (done, timestamp(datetime.now()), todo_id),
    )
    return get_todo(connection, todo_id)


def set_pinned(connection: sqlite3.Connection, todo_id: int, pinned: bool) -> Todo | None:
    connection.execute("UPDATE todos SET pinned = ? WHERE id = ?", (pinned, todo_id))
    return get_todo(connection, todo_id)


def delete_todo(connection: sqlite3.Connection, todo_id: int) -> None:
    connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))


def _todo(row: sqlite3.Row) -> Todo:
    return Todo(
        id=row["id"],
        content=row["content"],
        tags=tuple(json.loads(row["tags"])),
        pinned=bool(row["pinned"]),
        done_at=datetime.fromisoformat(row["done_at"]) if row["done_at"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
