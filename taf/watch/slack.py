"""The Slack collector: a headless Claude run reads new messages through the claude.ai Slack connector."""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.resources import files

from .claude import ClaudeResult, run_claude
from .config import Config
from .projects import Project, add_project, list_projects, valid_name
from .items import KINDS, Item, get_cursor, list_items, now, record_run, save_item, set_cursor, set_done, update_item

SOURCE = "slack"
PREFIX = "mcp__claude_ai_Slack__"
SEARCH_TOOL = PREFIX + "slack_search_public_and_private"
READ_TOOLS = [SEARCH_TOOL, PREFIX + "slack_read_thread", PREFIX + "slack_get_reactions"]
# Refused by name too, in case a setting ever allows them
WRITE_TOOLS = [PREFIX + name for name in (
    "slack_send_message", "slack_send_message_draft", "slack_schedule_message", "slack_add_reaction",
    "slack_create_conversation", "slack_create_canvas", "slack_update_canvas", "slack_create_list",
    "slack_update_list", "slack_add_list_record", "slack_update_list_record", "slack_get_file_upload_url",
    "slack_complete_file_upload",
)]
MAX_EXTRA_CALLS = 10
# Open items shown to the run so it can close or update them; the most recent first
MAX_OPEN_ITEMS = 60
# Messages posted while a run reads are caught by the next one; the item key removes duplicates
OVERLAP_SECONDS = 120

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "existing_id": {"type": ["integer", "null"]},
        "key": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "summary": {"type": "string"},
        "details": {"type": "string"},
        "people": {"type": "string"},
        "project": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "due": {"type": ["string", "null"]},
        "happened_at": {"type": ["string", "null"]},
        "resolved": {"type": "boolean"},
    },
    "required": ["existing_id", "key", "kind", "summary", "details", "people", "project", "url", "due", "happened_at", "resolved"],
}
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "closed_ids": {"type": "array", "items": {"type": "integer"}},
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "about": {"type": "string"},
                    "channels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "about", "channels"],
            },
        },
        "pages": {"type": "integer"},
        "more_pages_left": {"type": "boolean"},
        "last_message_ts": {"type": ["string", "null"]},
        "error": {"type": ["string", "null"]},
    },
    "required": ["items", "closed_ids", "projects", "pages", "more_pages_left", "last_message_ts", "error"],
}


@dataclass
class RunReport:
    # Summaries of the items found and closed
    found: list[str]
    closed: list[str]
    cost_usd: float | None
    pages: int | None
    more_pages_left: bool
    error: str | None
    seconds: float


def build_prompt(
    config: Config, since: float, open_items: list[sqlite3.Row] = (), projects: list[Project] = ()
) -> str:
    # Slack's after: filter takes a day and excludes it; the exact time goes in the after parameter
    day_before = (datetime.fromtimestamp(since) - timedelta(days=1)).date().isoformat()
    filters = " ".join([f"after:{day_before}", *(f"-in:#{c}" for c in config.slack.skip_channels)])
    listed = "\n".join(open_item_line(r) for r in open_items) or "(none)"
    template = files(__package__).joinpath("prompts/slack.md").read_text(encoding="utf-8")
    return template.format(
        after_time=datetime.fromtimestamp(since).astimezone().isoformat(timespec="minutes"),
        now=now(), filters=filters, after_ts=str(int(since)), max_pages=config.slack.max_pages,
        max_extra_calls=MAX_EXTRA_CALLS, open_items=listed,
        projects="\n".join(project_line(p) for p in projects) or "(none yet)",
    )


def project_line(project: Project) -> str:
    lines = [f"- {project.name}: {project.about}"]
    if project.channels:
        lines.append(f"  channels: {', '.join('#' + c for c in project.channels)}")
    if project.branches:
        lines.append(f"  branches: {', '.join(project.branches)}")
    lines.extend(f"  PR {pr}" for pr in project.prs[:5])
    return "\n".join(lines)


def open_item_line(row: sqlite3.Row) -> str:
    project = f" [{row['project']}]" if row["project"] else ""
    return f"- id {row['id']}, key {row['key']}{project} {row['kind']}: {row['summary']}"


def collect(db: sqlite3.Connection, config: Config, since: float | None = None, run=run_claude) -> RunReport:
    """Read Slack since the cursor (or since), save the items found, and move the cursor on success."""
    started = time.time()
    started_at = now()
    if since is None:
        saved = get_cursor(db, SOURCE)
        since = float(saved) if saved else started - config.slack.first_run_hours * 3600
    open_items = list_items(db, source=SOURCE)[:MAX_OPEN_ITEMS]
    open_ids = {r["id"] for r in open_items}
    projects = list_projects(db)
    result: ClaudeResult = run(
        build_prompt(config, since, open_items, projects), model=config.model, allowed_tools=READ_TOOLS,
        denied_tools=WRITE_TOOLS, schema=SCHEMA, max_budget_usd=config.max_budget_usd,
    )
    output = result.output or {}
    error = result.error or output.get("error") or search_error(result)
    found: list[str] = []
    to_close: list[int] = []
    if result.output is not None:
        known = {p.name for p in projects}
        for raw in output.get("projects", []):
            name = raw.get("name", "")
            if valid_name(name):
                add_project(db, name, (raw.get("about") or "").strip(), [str(c) for c in raw.get("channels", [])])
                known.add(name)
        for raw in output.get("items", []):
            item = to_item(raw, known)
            if item is None:
                continue
            if raw.get("existing_id") not in open_ids or not update_item(db, raw["existing_id"], item):
                save_item(db, item)
            found.append(item.summary)
        # Only ids the run was shown: a made-up id must not close someone else's item
        to_close = sorted(open_ids & {i for i in output.get("closed_ids", []) if isinstance(i, int)})
        set_done(db, to_close)
    if error is None:
        set_cursor(db, SOURCE, str(next_cursor(output, since, started)))
    record_run(db, SOURCE, started_at, result.cost_usd, output.get("pages"), len(found), error)
    closed = [r["summary"] for r in open_items if r["id"] in to_close]
    return RunReport(found, closed, result.cost_usd, output.get("pages"), bool(output.get("more_pages_left")), error,
                     time.time() - started)


def search_error(result: ClaudeResult) -> str | None:
    """An empty answer moves the cursor past messages for good, so check that the search really ran."""
    failed = [e for e in result.tool_errors if e.startswith(SEARCH_TOOL)]
    if failed:
        return f"search failed: {failed[0]}"
    if not result.tool_successes.get(SEARCH_TOOL):
        return "the run never searched Slack (connector not connected?)"
    return None


def next_cursor(output: dict, since: float, started: float) -> float:
    """Where the next run starts: after the last message read when pages were left, else near now."""
    if output.get("more_pages_left"):
        try:
            last = float(output.get("last_message_ts") or "")
        except ValueError:
            last = 0
        if since < last <= started:
            return last
    return max(since, started - OVERLAP_SECONDS)


def to_item(raw: dict, known_projects: set[str]) -> Item | None:
    if not raw.get("key") or not raw.get("summary") or raw.get("kind") not in KINDS:
        return None
    project = raw.get("project")
    return Item(
        source=SOURCE, key=raw["key"], kind=raw["kind"], summary=raw["summary"].strip(),
        project=project if project in known_projects else None,
        details=(raw.get("details") or "").strip(), people=raw.get("people") or "",
        url=raw.get("url"), due=raw.get("due"), happened_at=raw.get("happened_at"),
        resolved=bool(raw.get("resolved")),
    )
