"""The SQLite database: opening it and bringing its tables up to date; no Textual."""

import sqlite3
from pathlib import Path

# In order, never edited once released: PRAGMA user_version is how many of them a database has run.
MIGRATIONS = (
    # 1: the logs table and indexes exactly as the Ruby fini's Sequel migrations made them
    """
    CREATE TABLE `logs` (
        `id` integer NOT NULL PRIMARY KEY AUTOINCREMENT,
        `message` varchar(255),
        `logged_at` timestamp,
        `text` varchar(255),
        `action` varchar(255),
        `context` varchar(255),
        `duration` integer,
        `created_at` timestamp
    );
    CREATE INDEX `logs_logged_at_index` ON `logs` (`logged_at`);
    CREATE INDEX `logs_action_index` ON `logs` (`action`);
    CREATE INDEX `logs_context_index` ON `logs` (`context`);
    """,
    # 2: todos; tags is a JSON array of the #tags in the content, written on every save
    """
    CREATE TABLE todos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        tags TEXT NOT NULL DEFAULT '[]',
        pinned INTEGER NOT NULL DEFAULT 0,
        done_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL
    );
    """,
)
# The last migration a Ruby fini database already has
RUBY_VERSION = 1


def open_database(path: Path) -> sqlite3.Connection:
    """Open the database at path, creating it if needed, and run the migrations it lacks."""
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrate(connection, path if existed else None)
    return connection


def version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def migrate(connection: sqlite3.Connection, backup_path: Path | None = None) -> None:
    """Run the migrations the database lacks, each in its own transaction.

    A Ruby fini database has the logs table at user_version 0: it is marked as having run the
    migrations it already has, and none of them runs again. With backup_path, the database is
    copied next to it before the first change.
    """
    current = version(connection)
    if current >= len(MIGRATIONS):
        return
    if backup_path is not None:
        backup(connection, backup_path.with_name(f"{backup_path.stem}.backup-v{current}{backup_path.suffix}"))
    if current == 0 and _has_table(connection, "logs"):
        connection.execute(f"PRAGMA user_version = {RUBY_VERSION}")
        current = RUBY_VERSION
    for number, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        # executescript commits first, so BEGIN and COMMIT make the migration and its number one transaction
        connection.executescript(f"BEGIN; {sql} PRAGMA user_version = {number}; COMMIT;")


def backup(connection: sqlite3.Connection, path: Path) -> None:
    """Copy the database to path, unless a copy is there already."""
    if path.exists():
        return
    with sqlite3.connect(path) as target:
        connection.backup(target)
    target.close()


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    found = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
    return found.fetchone() is not None
