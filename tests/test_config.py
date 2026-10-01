import tempfile
import unittest
from pathlib import Path

from fini.config import DEFAULT_DATABASE, Config, load_config


class LoadConfigTest(unittest.TestCase):
    def test_reads_the_theme_and_ignores_the_ruby_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text("theme: one-light\ndatabase_path: '~/fini.sqlite3'\naction:\n  default: code\n")
            config = load_config(path)
        self.assertEqual((config.theme, config.warnings), ("one-light", []))
        self.assertEqual(config.database_path, Path.home() / "fini.sqlite3")
        self.assertEqual(load_config(Path("/nonexistent/config.yml")), Config())
        self.assertEqual((Config().theme, Config().database_path), ("terminal", DEFAULT_DATABASE))

    def test_bad_files_fall_back_to_defaults_with_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text("theme: onelight\n")
            unknown = load_config(path)
            path.write_text("theme: [unclosed\n")
            broken = load_config(path)
            path.write_text("- just\n- a list\n")
            not_a_mapping = load_config(path)
            path.write_text("database_path: [a, list]\n")
            bad_path = load_config(path)
        self.assertIn("'onelight' is not installed", unknown.warnings[0])
        self.assertEqual(broken.theme, "terminal")
        self.assertIn("not valid YAML", broken.warnings[0])
        self.assertEqual(not_a_mapping.warnings, ["Config file must contain a mapping of settings"])
        self.assertEqual(bad_path.database_path, DEFAULT_DATABASE)
        self.assertIn("database_path: must be a file path", bad_path.warnings[0])


if __name__ == "__main__":
    unittest.main()
