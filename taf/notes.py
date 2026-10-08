"""Notes in the database, todos among them: listing, searching, saving, done and pinned, and their
#tags; no Textual."""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from .logs import timestamp

# A note's kinds: a todo can be done, a note cannot
NOTE = "note"
TODO = "todo"

# What the todos' status dropdown offers, as (label, status)
STATUSES = (("Open", "open"), ("Done", "done"), ("All", "all"))
DEFAULT_STATUS = "open"

# YafYaf's rule for a tag: a #word starting with a letter, not glued to what precedes it
TAG = re.compile(r"(?<![\w&/#-])#(?P<name>[a-z][a-z0-9_-]*)", re.IGNORECASE)
INLINE_CODE = re.compile(r"`[^`\n]*`")
# A markdown heading, its text without the #s, a closing run of #s left out too
HEADING = re.compile(r"#{1,6}\s+(.*?)(?:\s+#+)?\s*$")


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    kind: str
    content: str
    tags: tuple[str, ...]
    pinned: bool
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_todo(self) -> bool:
        return self.kind == TODO

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def summary(self) -> str:
        """The first line with text, what the list shows."""
        return next((line.strip() for line in self.content.splitlines() if line.strip()), "")

    @property
    def links(self) -> list[tuple[str, str | None]]:
        """A watch item has links; a note has none."""
        return []

    @property
    def gray(self) -> bool:
        """Whether its row is drawn gray."""
        return self.done

    @property
    def row_key(self) -> str:
        """Its row's key in a table."""
        return str(self.id)

    @property
    def date_text(self) -> str:
        return date_line(self)


def front_matter(note: Note) -> dict[str, str]:
    """What the editor shows over a note's content, in this order; done_at only for a todo. The
    id is how an agent, or anyone, refers to the note."""
    fields = {
        "id": str(note.id),
        "created_at": f"{note.created_at:%Y-%m-%d %H:%M}",
        "updated_at": f"{note.updated_at:%Y-%m-%d %H:%M}",
    }
    if note.is_todo:
        fields["done_at"] = f"{note.done_at:%Y-%m-%d %H:%M}" if note.done_at else ""
    fields["pinned"] = "true" if note.pinned else "false"
    return fields


def long_date(moment: datetime, now: datetime | None = None) -> str:
    """Today at 3:09pm, Yesterday at 3:09pm, or October 5, 2026 at 3:09pm."""
    now = now or datetime.now()
    time = f"{moment:%I:%M}".lstrip("0") + ("am" if moment.hour < 12 else "pm")
    days = (now.date() - moment.date()).days
    day = "Today" if days == 0 else "Yesterday" if days == 1 else f"{moment:%B} {moment.day}, {moment.year}"
    return f"{day} at {time}"


def date_line(note: Note) -> str:
    """When the note was written, or last changed if it was since: "Created Today at 3:09pm"."""
    if note.updated_at == note.created_at:
        return f"Created {long_date(note.created_at)}"
    return f"Updated {long_date(note.updated_at)}"


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


def extra_tags(note: Note) -> tuple[str, ...]:
    """The note's tags that are not in its summary, which a one-line view adds after it."""
    shown = set(tags_of(note.summary))
    return tuple(name for name in note.tags if name not in shown)


def heading_text(summary: str) -> str:
    """A heading's text, without its #s; any other summary as it is."""
    match = HEADING.match(summary)
    return match.group(1) if match else summary


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


def list_notes(connection: sqlite3.Connection, kind: str, query: str = "", status: str = "all") -> list[Note]:
    """The notes of a kind and a status (open, done or all) whose content has every word of the
    query outside its tags (any case) and every #tag; the last updated first, pinned and done or not."""
    where, params = ["kind = ?"], [kind]
    if status == "open":
        where.append("done_at IS NULL")
    elif status == "done":
        where.append("done_at IS NOT NULL")
    words, tags = split_query(query)
    for tag in tags:
        where.append("EXISTS (SELECT 1 FROM json_each(notes.tags) WHERE value = ?)")
        params.append(tag)
    sql = "SELECT * FROM notes WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC, id DESC"
    notes = [_note(row) for row in connection.execute(sql, params)]
    # Words are matched here rather than with LIKE, which cannot leave the tags out: there are few notes
    words = [word.casefold() for word in words]
    return [note for note in notes if all(word in without_tags(note.content).casefold() for word in words)]


def without_tags(text: str) -> str:
    """text with its #tags blanked out, so a search for "api" does not find "#api"; a #word in
    inline code is not a tag, so it stays."""
    for start, end, _ in reversed(find_tags(text)):
        text = text[:start] + " " + text[end:]
    return text


def tag_counts(connection: sqlite3.Connection, kind: str) -> list[tuple[str, int]]:
    """Every tag of the notes of a kind with how many have it, the most used first."""
    rows = connection.execute(
        "SELECT value, count(*) FROM notes, json_each(notes.tags) WHERE kind = ? GROUP BY value ORDER BY count(*) DESC, value",
        (kind,),
    )
    return [(name, count) for name, count in rows]


def get_note(connection: sqlite3.Connection, note_id: int) -> Note | None:
    row = connection.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _note(row) if row else None


def create_note(connection: sqlite3.Connection, content: str, kind: str = NOTE) -> Note:
    now = timestamp(datetime.now())
    cursor = connection.execute(
        "INSERT INTO notes (kind, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (kind, content, json.dumps(tags_of(content)), now, now),
    )
    return get_note(connection, cursor.lastrowid)


def update_note(connection: sqlite3.Connection, note_id: int, content: str) -> Note | None:
    """Save new content and the tags in it; None when the note is gone."""
    connection.execute(
        "UPDATE notes SET content = ?, tags = ?, updated_at = ? WHERE id = ?",
        (content, json.dumps(tags_of(content)), timestamp(datetime.now()), note_id),
    )
    return get_note(connection, note_id)


def set_done(connection: sqlite3.Connection, note_id: int, done: bool) -> Note | None:
    """Mark a todo done now, or not done; marking a done todo done again keeps when it was done.
    A plain note is never done, so it is left as it is.

    updated_at is left alone, here and when pinning: it says when the content last changed.
    """
    connection.execute(
        "UPDATE notes SET done_at = CASE WHEN ? THEN coalesce(done_at, ?) END WHERE id = ? AND kind = ?",
        (done, timestamp(datetime.now()), note_id, TODO),
    )
    return get_note(connection, note_id)


def set_pinned(connection: sqlite3.Connection, note_id: int, pinned: bool) -> Note | None:
    connection.execute("UPDATE notes SET pinned = ? WHERE id = ?", (pinned, note_id))
    return get_note(connection, note_id)


def delete_note(connection: sqlite3.Connection, note_id: int) -> None:
    connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def _note(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        kind=row["kind"],
        content=row["content"],
        tags=tuple(json.loads(row["tags"])),
        pinned=bool(row["pinned"]),
        done_at=datetime.fromisoformat(row["done_at"]) if row["done_at"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
