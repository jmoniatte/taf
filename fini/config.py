import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from tui_kit.config import read_theme
from tui_kit.theme import TERMINAL_THEME

from .message import Inference

CONFIG_DIR = Path.home() / ".config" / "fini"
# .yml, not .yaml: the file the Ruby fini used, with its rules for actions and contexts
CONFIG_FILE = CONFIG_DIR / "config.yml"
DEFAULT_DATABASE = CONFIG_DIR / "fini.sqlite3"
# What the Stats tab shows: hours, or only percentages, to share without the hours
STATS_SHOW = ("hours", "percentages")


@dataclass
class Config:
    """Optional, hand-edited settings."""

    # Set with t in the app; "terminal" reads the terminal's own colours, otherwise any
    # scheme in tui-kit (see tui_kit.theme.list_themes()).
    theme: str = TERMINAL_THEME
    # The SQLite file with the logs, the notes and the todos; ~ is expanded
    database_path: Path = DEFAULT_DATABASE
    # How `fini log` names the action and the context a message does not give
    action: Inference = field(default_factory=Inference)
    context: Inference = field(default_factory=Inference)
    # Set with the Stats tab's Show dropdown, one of STATS_SHOW
    stats_show: str = STATS_SHOW[0]
    # Where settings picked in the app are written back
    path: Path = field(default=CONFIG_FILE, compare=False)
    # Why the config file was ignored; the UI shows these
    warnings: list[str] = field(default_factory=list)


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Read the config file if there is one; a missing file just means defaults."""
    config = Config(path=path)
    if not path.exists():
        return config

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        config.warnings.append(f"Config file is not valid YAML: {error}")
        return config
    if not isinstance(data, Mapping):
        config.warnings.append("Config file must contain a mapping of settings")
        return config

    config.theme, warning = read_theme(data.get("theme"))
    if warning:
        config.warnings.append(warning)
    _read_database_path(data.get("database_path"), config)
    _read_stats_show(data.get("stats_show"), config)
    config.action = _read_inference("action", data.get("action"), config.warnings)
    config.context = _read_inference("context", data.get("context"), config.warnings)
    return config


def _read_inference(key: str, value: object, warnings: list[str]) -> Inference:
    """`default` and `rules` (name: [patterns]); a pattern that is null or not a regex is skipped."""
    if value is None:
        return Inference()
    if not isinstance(value, Mapping):
        warnings.append(f"{key}: must be a mapping with default and rules")
        return Inference()
    default = value.get("default")
    inference = Inference(default=str(default) if default is not None else None)
    rules = value.get("rules") or {}
    if not isinstance(rules, Mapping):
        warnings.append(f"{key}.rules: must be a mapping of names to lists of patterns")
        return inference
    for name, patterns in rules.items():
        compiled = []
        for pattern in patterns if isinstance(patterns, list) else [patterns]:
            if pattern is None:
                continue
            try:
                compiled.append(re.compile(str(pattern)))
            except re.error as error:
                warnings.append(f"{key}.rules.{name}: '{pattern}' is not a valid pattern ({error}), skipping it")
        inference.rules.append((str(name), compiled))
    return inference


def _read_stats_show(value: object, config: Config) -> None:
    if value is None:
        return
    if value not in STATS_SHOW:
        config.warnings.append(f"stats_show: must be {' or '.join(STATS_SHOW)}, using {config.stats_show}")
        return
    config.stats_show = str(value)


def _read_database_path(value: object, config: Config) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        config.warnings.append(f"database_path: must be a file path, using {config.database_path}")
        return
    config.database_path = Path(value.strip()).expanduser()
