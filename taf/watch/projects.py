"""Projects: pieces of work like follow-privacy-levels, with the Slack channels and git branches linked to them."""

import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .items import now, project_id

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")


@dataclass
class Project:
    name: str
    about: str
    status: str
    open_items: int = 0
    channels: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    # The user's open pull requests, as "repo#number title"
    prs: list[str] = field(default_factory=list)


class ProjectError(Exception):
    pass


def valid_name(name: str) -> bool:
    return bool(NAME.match(name))


def list_projects(db: sqlite3.Connection, include_archived: bool = False) -> list[Project]:
    """Projects with their open item count and links, the most open items first."""
    rows = db.execute(
        """
        SELECT p.name, p.about, p.status,
               (SELECT count(*) FROM watch_items i WHERE i.project_id = p.id AND i.done_at IS NULL) AS open_items
        FROM watch_projects p WHERE ? OR p.status = 'active'
        ORDER BY open_items DESC, p.updated_at DESC
        """,
        (include_archived,),
    ).fetchall()
    projects = [Project(r["name"], r["about"], r["status"], r["open_items"]) for r in rows]
    by_name = {p.name: p for p in projects}
    for link in db.execute(
        "SELECT p.name AS project, l.kind, l.value FROM watch_project_links l JOIN watch_projects p ON p.id = l.project_id "
        "ORDER BY l.value"
    ):
        project = by_name.get(link["project"])
        if project:
            (project.channels if link["kind"] == "channel" else project.branches).append(link["value"])
    for pr in db.execute(
        "SELECT pr.*, p.name AS project FROM watch_prs pr JOIN watch_projects p ON p.id = pr.project_id "
        "WHERE pr.state = 'open' ORDER BY pr.repo, pr.number"
    ):
        project = by_name.get(pr["project"])
        if project:
            project.prs.append(f"{pr['repo']}#{pr['number']} {pr['title']}")
    return projects


def get_project(db: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM watch_projects WHERE name = ?", (name,)).fetchone()


def add_project(db: sqlite3.Connection, name: str, about: str = "", channels: list[str] = ()) -> None:
    """Create the project if it is new, and link the channels no other project has."""
    stamp = now()
    db.execute(
        "INSERT INTO watch_projects (name, about, created_at, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (name) DO UPDATE SET about = CASE WHEN about = '' THEN excluded.about ELSE about END, "
        "updated_at = excluded.updated_at",
        (name, about, stamp, stamp),
    )
    for channel in channels:
        db.execute(
            "INSERT OR IGNORE INTO watch_project_links (project_id, kind, value) VALUES (?, 'channel', ?)",
            (project_id(db, name), channel.lstrip("#")),
        )


def link(db: sqlite3.Connection, name: str, kind: str, value: str) -> None:
    """Link a channel or branch to the project, taking it from any project it was linked to."""
    if get_project(db, name) is None:
        raise ProjectError(f"no project named {name}")
    db.execute(
        "INSERT OR REPLACE INTO watch_project_links (project_id, kind, value) VALUES (?, ?, ?)",
        (project_id(db, name), kind, value.lstrip("#") if kind == "channel" else value),
    )


def unlink(db: sqlite3.Connection, kind: str, value: str) -> bool:
    cursor = db.execute(
        "DELETE FROM watch_project_links WHERE kind = ? AND value = ?",
        (kind, value.lstrip("#") if kind == "channel" else value),
    )
    return cursor.rowcount > 0


def rename(db: sqlite3.Connection, old: str, new: str) -> None:
    if get_project(db, old) is None:
        raise ProjectError(f"no project named {old}")
    if not valid_name(new):
        raise ProjectError(f"{new} is not a valid name: lowercase letters, digits and dashes")
    if get_project(db, new) is not None:
        raise ProjectError(f"{new} already exists; use merge")
    db.execute("UPDATE watch_projects SET name = ?, updated_at = ? WHERE name = ?", (new, now(), old))


def merge(db: sqlite3.Connection, source: str, target: str) -> None:
    """Move the source project's items, PRs and links into the target, then delete the source."""
    rows = [get_project(db, name) for name in (source, target)]
    for name, row in zip((source, target), rows):
        if row is None:
            raise ProjectError(f"no project named {name}")
    if source == target:
        raise ProjectError("cannot merge a project into itself")
    ids = (rows[1]["id"], rows[0]["id"])
    with db:
        db.execute("BEGIN")
        for table in ("watch_project_links", "watch_items", "watch_prs"):
            db.execute(f"UPDATE {table} SET project_id = ? WHERE project_id = ?", ids)
        db.execute("DELETE FROM watch_projects WHERE id = ?", (ids[1],))


def set_project_status(db: sqlite3.Connection, name: str, status: str) -> None:
    cursor = db.execute("UPDATE watch_projects SET status = ?, updated_at = ? WHERE name = ?", (status, now(), name))
    if cursor.rowcount == 0:
        raise ProjectError(f"no project named {name}")


def linked_project(db: sqlite3.Connection, kind: str, value: str, active_only: bool = False) -> str | None:
    row = db.execute(
        "SELECT p.name FROM watch_project_links l JOIN watch_projects p ON p.id = l.project_id "
        "WHERE l.kind = ? AND l.value = ? AND (NOT ? OR p.status = 'active')",
        (kind, value, active_only),
    ).fetchone()
    return row["name"] if row else None


def name_from_branch(branch: str, prefixes: set[str]) -> str:
    """follow-privacy-levels from jean/follow-privacy-levels or jean-follow-privacy-levels."""
    for prefix in prefixes:
        for separator in ("/", "-"):
            if branch.startswith(prefix + separator) and len(branch) > len(prefix) + 1:
                branch = branch[len(prefix) + 1:]
                break
    name = re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:60].rstrip("-")
    return name if valid_name(name) else f"branch-{name}"[:60]


def project_for_branch(db: sqlite3.Connection, branch: str | None) -> str | None:
    """The active project linked to the branch, else the one whose name the branch contains (the longest)."""
    if not branch:
        return None
    linked = linked_project(db, "branch", branch, active_only=True)
    if linked:
        return linked
    # Runs in agent hooks: only the names, not list_projects' links and PRs
    names = [row["name"] for row in db.execute("SELECT name FROM watch_projects WHERE status = 'active'") if row["name"] in branch]
    return max(names, key=len) if names else None


def current_branch(path: Path) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = done.stdout.strip()
    return branch if done.returncode == 0 and branch and branch != "HEAD" else None
