"""The optional ~/.config/veille/config.toml: model, budget, Slack and GitHub settings; the database is taf's."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_config as load_taf_config

CONFIG_FILE = Path.home() / ".config" / "veille" / "config.toml"


@dataclass
class SlackConfig:
    # Channels never read, as names without the #: bot feeds that cost money and hold nothing
    skip_channels: list[str] = field(default_factory=list)
    # Pages of 20 messages per run; what is left is read on the next run
    max_pages: int = 10
    # Hours read back on the very first run
    first_run_hours: int = 24


@dataclass
class GithubConfig:
    # Teams whose review requests count as the user's, as "org/team"
    review_teams: list[str] = field(default_factory=list)
    # Accounts whose comments never need a reply, like bots without "[bot]" in their name
    ignore_users: list[str] = field(default_factory=list)


@dataclass
class Config:
    database_path: Path = field(default_factory=lambda: load_taf_config().database_path)
    model: str = "sonnet"
    # Stops one collector run from spending more than this
    max_budget_usd: float = 1.0
    slack: SlackConfig = field(default_factory=SlackConfig)
    github: GithubConfig = field(default_factory=GithubConfig)


def load_config(path: Path = CONFIG_FILE) -> Config:
    """Read the config file; a missing file means defaults, a broken one raises ValueError."""
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from error

    config = Config()
    config.model = data.get("model", config.model)
    config.max_budget_usd = float(data.get("max_budget_usd", config.max_budget_usd))
    slack = data.get("slack", {})
    config.slack = SlackConfig(
        skip_channels=[c.lstrip("#") for c in slack.get("skip_channels", [])],
        max_pages=int(slack.get("max_pages", SlackConfig.max_pages)),
        first_run_hours=int(slack.get("first_run_hours", SlackConfig.first_run_hours)),
    )
    github = data.get("github", {})
    config.github = GithubConfig(
        review_teams=[str(t) for t in github.get("review_teams", [])],
        ignore_users=[str(u) for u in github.get("ignore_users", [])],
    )
    return config
