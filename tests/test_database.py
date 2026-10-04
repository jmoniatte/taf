import sqlite3
import tempfile
import unittest
from pathlib import Path

from travail.database import MIGRATIONS, migrate, open_database, version

# The schema a Ruby fini database has, as read from one with sqlite_master
RUBY_SCHEMA = """
CREATE TABLE `schema_migrations` (`filename` varchar(255) NOT NULL PRIMARY KEY);
CREATE TABLE `logs` (`id` integer NOT NULL PRIMARY KEY AUTOINCREMENT, `message` varchar(255), `logged_at` timestamp, `text` varchar(255), `action` varchar(255), `context` varchar(255), `duration` integer, `created_at` timestamp);
CREATE INDEX `logs_logged_at_index` ON `logs` (`logged_at`);
CREATE INDEX `logs_action_index` ON `logs` (`action`);
CREATE INDEX `logs_context_index` ON `logs` (`context`);
INSERT INTO schema_migrations VALUES ('20251025223900_create_logs.rb'), ('20260128000000_add_indexes_to_logs.rb');
INSERT INTO logs (message, logged_at, text, action, context, duration, created_at)
    VALUES ('Reviewed PR @15m', '2026-09-30 15:14:26.000000', 'Reviewed PR', 'review', 'rails', 15, '2026-09-30 15:14:26.000000');
"""


def schema(connection: sqlite3.Connection) -> dict:
    """The logs table's columns (name, type, not null, primary key) and its indexes' columns."""
    return {
        "columns": [tuple(row)[1:] for row in connection.execute("PRAGMA table_info(logs)")],
        "indexes": {
            row[1]: [column[2] for column in connection.execute(f"PRAGMA index_info({row[1]})")]
            for row in connection.execute("PRAGMA index_list(logs)")
        },
        "autoincrement": "AUTOINCREMENT" in connection.execute("SELECT sql FROM sqlite_master WHERE name = 'logs'").fetchone()[0],
    }


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_new_database_gets_the_same_tables_as_a_ruby_one(self) -> None:
        connection = open_database(self.dir / "data" / "travail.sqlite3")
        self.assertEqual(version(connection), len(MIGRATIONS))
        ruby = sqlite3.connect(":memory:")
        ruby.executescript(RUBY_SCHEMA)
        self.assertEqual(schema(connection), schema(ruby))
        self.assertEqual(len(schema(ruby)["indexes"]), 3)
        # Nothing to back up: there was no data
        self.assertEqual(sorted(path.name for path in (self.dir / "data").iterdir()), ["travail.sqlite3"])

    def test_a_ruby_database_is_marked_migrated_without_running_anything_and_backed_up_once(self) -> None:
        path = self.dir / "logs.sqlite3"
        with sqlite3.connect(path) as ruby:
            ruby.executescript(RUBY_SCHEMA)
        ruby.close()

        connection = open_database(path)
        self.assertEqual(version(connection), len(MIGRATIONS))
        self.assertEqual([tuple(row) for row in connection.execute("SELECT text, duration FROM logs")], [("Reviewed PR", 15)])
        # Left alone, like everything else the Ruby fini made
        self.assertEqual(connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0], 2)
        backup = self.dir / "logs.backup-v0.sqlite3"
        with sqlite3.connect(backup) as copy:
            self.assertEqual(copy.execute("SELECT count(*), max(id) FROM logs").fetchone(), (1, 1))
            self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], 0)
        copy.close()
        connection.close()

        # Up to date: opening again changes nothing and backs up nothing
        before = path.read_bytes()
        backup.unlink()
        open_database(path).close()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(backup.exists())

    def test_todos_become_notes_of_the_kind_todo(self) -> None:
        connection = sqlite3.connect(":memory:")
        for sql in MIGRATIONS[:2]:
            connection.executescript(sql)
        connection.execute("PRAGMA user_version = 2")
        connection.execute(
            "INSERT INTO todos (content, tags, done_at, created_at, updated_at) VALUES ('Pay taxes', '[]', NULL, '2026-09-30 10:00:00.000000', '2026-09-30 10:00:00.000000')"
        )
        migrate(connection)
        self.assertEqual(connection.execute("SELECT kind, content FROM notes").fetchall(), [("todo", "Pay taxes")])
        self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'todos'").fetchall())
        connection.execute("INSERT INTO notes (content, created_at, updated_at) VALUES ('x', '', '')")
        self.assertEqual(connection.execute("SELECT kind FROM notes WHERE content = 'x'").fetchone(), ("note",))
        connection.close()


if __name__ == "__main__":
    unittest.main()
