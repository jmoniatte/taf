"""The watch: section of ~/.config/taf/config.yml: the model, budget, Slack and GitHub settings of
the collectors, which use taf's database."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..config import CONFIG_FILE, DEFAULT_DATABASE
from ..config import Config as TafConfig
from ..config import load_config as load_taf_config


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
    # The repo ("org/repo") whose open PRs with deploy_label the Watch tab counts; none when empty
    deploy_repo: str = ""
    deploy_label: str = "ready-for-deploy"


@dataclass
class Config:
    database_path: Path = DEFAULT_DATABASE
    model: str = "sonnet"
    # Stops one collector run from spending more than this
    max_budget_usd: float = 1.0
    slack: SlackConfig = field(default_factory=SlackConfig)
    github: GithubConfig = field(default_factory=GithubConfig)


def load_config(path: Path = CONFIG_FILE) -> Config:
    """taf's database and the watch: section; no section means defaults, a broken one raises ValueError."""
    return from_taf(load_taf_config(path))


def from_taf(taf: TafConfig) -> Config:
    """The watch settings in a taf config already read, as the app has it."""
    path = taf.path
    data = taf.watch
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: watch must be a mapping of settings")
    try:
        slack = data.get("slack") or {}
        github = data.get("github") or {}
        return Config(
            database_path=taf.database_path,
            model=str(data.get("model", Config.model)),
            max_budget_usd=float(data.get("max_budget_usd", Config.max_budget_usd)),
            slack=SlackConfig(
                skip_channels=[str(c).lstrip("#") for c in slack.get("skip_channels", [])],
                max_pages=int(slack.get("max_pages", SlackConfig.max_pages)),
                first_run_hours=int(slack.get("first_run_hours", SlackConfig.first_run_hours)),
            ),
            github=GithubConfig(
                review_teams=[str(t) for t in github.get("review_teams", [])],
                ignore_users=[str(u) for u in github.get("ignore_users", [])],
                deploy_repo=str(github.get("deploy_repo", "")),
                deploy_label=str(github.get("deploy_label", GithubConfig.deploy_label)),
            ),
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"{path}: watch: {error}") from error
