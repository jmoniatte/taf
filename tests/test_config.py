import tempfile
import unittest
from pathlib import Path

from taf.config import DEFAULT_DATABASE, Config, load_config


class LoadConfigTest(unittest.TestCase):
    def test_reads_the_theme_and_ignores_the_ruby_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text("theme: one-light\ndatabase_path: '~/taf.sqlite3'\nstats_show: percentages\naction:\n  default: code\n")
            config = load_config(path)
        self.assertEqual((config.theme, config.stats_show, config.path, config.warnings), ("one-light", "percentages", path, []))
        self.assertEqual(config.database_path, Path.home() / "taf.sqlite3")
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
            path.write_text("stats_show: minutes\n")
            bad_show = load_config(path)
        self.assertIn("'onelight' is not installed", unknown.warnings[0])
        self.assertEqual(broken.theme, "terminal")
        self.assertIn("not valid YAML", broken.warnings[0])
        self.assertEqual(not_a_mapping.warnings, ["Config file must contain a mapping of settings"])
        self.assertEqual(bad_path.database_path, DEFAULT_DATABASE)
        self.assertIn("database_path: must be a file path", bad_path.warnings[0])
        self.assertEqual(bad_show.stats_show, "hours")
        self.assertEqual(bad_show.warnings, ["stats_show: must be hours or percentages, using hours"])

    def test_action_and_context_rules_keep_their_order_and_skip_bad_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yml"
            path.write_text(
                "action:\n  default: code\n  rules:\n    meet:\n      - '^Met\\b'\n    admin:\n      - null\n"
                "    review:\n      - '['\n      - '^Reviewed'\n"
                "context:\n  rules: [not, a, mapping]\n"
            )
            config = load_config(path)
        self.assertEqual(config.action.default, "code")
        self.assertEqual([(name, [p.pattern for p in patterns]) for name, patterns in config.action.rules], [("meet", [r"^Met\b"]), ("admin", []), ("review", ["^Reviewed"])])
        self.assertEqual(config.action.infer("Reviewed a PR"), "review")
        self.assertEqual((config.context.default, config.context.rules), (None, []))
        self.assertEqual(len(config.warnings), 2)
        self.assertIn("action.rules.review: '[' is not a valid pattern", config.warnings[0])
        self.assertIn("context.rules: must be a mapping", config.warnings[1])


if __name__ == "__main__":
    unittest.main()
