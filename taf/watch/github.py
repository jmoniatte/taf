"""GitHub through `gh`, in one GraphQL request: the user's open PRs name projects, and give items for
replies, failing CI and review requests."""

import json
import sqlite3
import subprocess
import urllib.parse
import time
from dataclasses import dataclass, field

from .config import GithubConfig
from .items import FYI, Item, list_items, local_iso, now, project_id, record_run, save_item, set_done
from .projects import add_project, get_project, link, linked_project, name_from_branch

SOURCE = "github"
# SEARCHES becomes one search per kind of review request (query())
QUERY = """
query {
  viewer {
    login
    pullRequests(states: OPEN, first: 100) {
      nodes {
        url number title headRefName repository { name }
        comments(last: 100) { nodes { author { login } createdAt } }
        reviews(last: 100) { nodes { author { login } state submittedAt } }
        commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
          ... on CheckRun { name conclusion startedAt completedAt detailsUrl }
          ... on StatusContext { context state createdAt targetUrl }
        } } } } } }
      }
    }
  }
SEARCHES}
"""
REQUEST = """  %s: search(type: ISSUE, first: 100, query: "%s") {
    nodes { ... on PullRequest { url number title repository { name } author { login } createdAt } }
  }
"""
REVIEW_STATES = {"APPROVED": "approved", "CHANGES_REQUESTED": "requested changes", "COMMENTED": "commented"}
# CANCELLED is left out: a cancelled run is almost always replaced by a newer one
FAILED = {"FAILURE", "ERROR", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"}


@dataclass
class SyncReport:
    open_prs: int = 0
    new_projects: int = 0
    archived: int = 0
    # Summaries of the items added or reopened
    found: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


def gh(args: list[str]) -> list | dict:
    done = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout)


def requests(teams: list[str]) -> list[tuple[str, str, str]]:
    """(alias, who it was asked of, search) for each kind of review request: the user, then each team.
    A team request stays after a teammate reviews, so PRs already approved or reviewed by the user
    are left out of the teams'."""
    rest = "is:pr is:open -author:@me draft:false"
    found = [("you", "you", f"user-review-requested:@me {rest}")]
    found += [(f"team{i}", f"team {team.split('/')[-1]}", f"team-review-requested:{team} -reviewed-by:@me -review:approved {rest}")
              for i, team in enumerate(teams)]
    return found


def query(teams: list[str]) -> str:
    return QUERY.replace("SEARCHES", "".join(REQUEST % (alias, terms) for alias, _, terms in requests(teams)))


def ask(run, teams: list[str]) -> dict:
    """GitHub's answer to the one request; a GraphQL error raises, as gh's own do."""
    answer = run(["gh", "api", "graphql", "-f", f"query={query(teams)}"])
    if answer.get("errors"):
        raise RuntimeError(f"gh api graphql: {answer['errors'][0].get('message', answer['errors'][0])}")
    return answer["data"]


def nodes(connection: dict | None) -> list:
    return [node for node in ((connection or {}).get("nodes") or []) if node]


def sync(db: sqlite3.Connection, config: GithubConfig = GithubConfig(), run=gh) -> SyncReport:
    """Record the user's open PRs, give each a project (its branch's, else one named after the branch),
    save items for what needs the user on GitHub, close the ones that no longer do, and archive
    projects whose PRs are all closed and that have nothing open. The run is recorded."""
    started, started_at = time.time(), now()
    try:
        data = ask(run, config.review_teams)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError) as error:
        # Before anything changed
        report = SyncReport(error=f"github: {error}")
    else:
        report = record(db, data, config)
    report.seconds = time.time() - started
    record_run(db, SOURCE, started_at, None, None, len(report.found), report.error)
    return report


def record(db: sqlite3.Connection, data: dict, config: GithubConfig) -> SyncReport:
    """Save GitHub's answer: the PRs and their projects, then the items."""
    report = SyncReport()
    me = data["viewer"]["login"]
    found = nodes(data["viewer"]["pullRequests"])
    requested = review_requests(data, config.review_teams)
    known = {r["url"] for r in db.execute("SELECT url FROM watch_prs")}
    for pr in found:
        url = pr["url"]
        if url in known:
            db.execute("UPDATE watch_prs SET title = ?, state = 'open', updated_at = ? WHERE url = ?",
                       (pr["title"], now(), url))
        else:
            db.execute(
                "INSERT INTO watch_prs (url, repo, number, title, branch, state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (url, pr["repository"]["name"], pr["number"], pr["title"], pr["headRefName"], now()),
            )
    open_urls = {pr["url"] for pr in found}
    report.open_prs = len(open_urls)
    for row in db.execute("SELECT url FROM watch_prs WHERE state = 'open'").fetchall():
        if row["url"] not in open_urls:
            db.execute("UPDATE watch_prs SET state = 'closed', updated_at = ? WHERE url = ?", (now(), row["url"]))

    prs = db.execute("SELECT * FROM watch_prs WHERE state = 'open' AND project_id IS NULL").fetchall()
    prefixes = {row["branch"].split("/")[0] for row in db.execute("SELECT branch FROM watch_prs") if "/" in row["branch"]}
    for pr in prs:
        project = linked_project(db, "branch", pr["branch"])
        if project is None:
            project = name_from_branch(pr["branch"], prefixes)
            if get_project(db, project) is None:
                add_project(db, project, pr["title"])
                report.new_projects += 1
            link(db, project, "branch", pr["branch"])
        db.execute("UPDATE watch_prs SET project_id = ? WHERE url = ?", (project_id(db, project), pr["url"]))
        # A new PR on an archived project's branch means the work started again
        db.execute("UPDATE watch_projects SET status = 'active', updated_at = ? WHERE name = ? AND status = 'archived'",
                   (now(), project))

    items = list(requested)
    for pr in found:
        project = db.execute(
            "SELECT p.name FROM watch_prs pr LEFT JOIN watch_projects p ON p.id = pr.project_id WHERE pr.url = ?",
            (pr["url"],),
        ).fetchone()["name"]
        items += [i for i in (reply_item(pr, me, config.ignore_users, project), ci_item(pr, project)) if i]
    for item in items:
        if track(db, item):
            report.found.append(item.summary)
    # Merged PRs, passing CI, answered comments and fulfilled requests: nothing left to do
    keys = {i.key for i in items}
    stale = [r for r in list_items(db, source=SOURCE) if r["key"] not in keys]
    set_done(db, [r["id"] for r in stale])
    report.closed = [r["summary"] for r in stale]
    report.archived = archive_finished(db)
    return report




def track(db: sqlite3.Connection, item: Item) -> bool:
    """Save the item only when it is new or something happened since it was saved (its latest event
    changed), reopening it then if it was done; an item with nothing new is left as it is. True when
    it is new or reopened."""
    row = db.execute("SELECT done_at, happened_at FROM watch_items WHERE source = ? AND key = ?",
                     (SOURCE, item.key)).fetchone()
    if row is not None and item.happened_at == row["happened_at"]:
        return False
    save_item(db, item)
    if row is None:
        return True
    if row["done_at"] is not None:
        db.execute("UPDATE watch_items SET done_at = NULL WHERE source = ? AND key = ?", (SOURCE, item.key))
        return True
    return False


def ready_to_deploy(config: GithubConfig, run=gh) -> tuple[int, str] | None:
    """How many open PRs of deploy_repo have deploy_label, and their list on GitHub; None when no
    repo is set or gh fails. Asked live by the Watch tab, never stored."""
    if not config.deploy_repo:
        return None
    try:
        found = run(["gh", "pr", "list", "--repo", config.deploy_repo, "--label", config.deploy_label,
                     "--state", "open", "--limit", "500", "--json", "number"])
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    query = urllib.parse.quote_plus(f"is:open is:pr label:{config.deploy_label}")
    return len(found), f"https://github.com/{config.deploy_repo}/pulls?q={query}"


def review_requests(data: dict, teams: list[str]) -> list[Item]:
    """PRs waiting on the user's review, asked of them or of one of their teams."""
    found: dict[str, Item] = {}
    for alias, who, _ in requests(teams):
        for pr in nodes(data.get(alias)):
            if pr["url"] in found:
                continue
            author = pr["author"]["login"]
            found[pr["url"]] = Item(
                source=SOURCE, key=f"review:{pr['url']}", kind="action",
                summary=f"Review {pr['repository']['name']}#{pr['number']} {pr['title']}",
                details=f"Review requested from {who}; opened by {author}.", people=author,
                url=pr["url"], happened_at=local_iso(pr["createdAt"]),
            )
    return list(found.values())


def reply_item(pr: dict, me: str, ignore: list[str], project: str | None) -> Item | None:
    """What others said or decided on the user's PR since the user last commented or reviewed it."""
    def login(entry):
        return (entry.get("author") or {}).get("login") or ""

    comments, reviews = nodes(pr.get("comments")), nodes(pr.get("reviews"))
    mine = [c["createdAt"] for c in comments if login(c) == me]
    mine += [r["submittedAt"] for r in reviews if login(r) == me]
    since = max(mine, default="")
    events = [(c["createdAt"], login(c), "commented") for c in comments]
    events += [(r["submittedAt"], login(r), REVIEW_STATES[r["state"]]) for r in reviews if r["state"] in REVIEW_STATES]
    events = sorted(e for e in events if e[0] > since and e[1] not in (me, "", *ignore) and not e[1].endswith("[bot]"))
    if not events:
        return None
    said: dict[str, list[str]] = {}
    for _, person, what in events:
        if what not in said.setdefault(person, []):
            said[person].append(what)
    name = f"{pr['repository']['name']}#{pr['number']}"
    return Item(
        source=SOURCE, key=f"replies:{pr['url']}",
        kind=FYI if all(w == "approved" for _, _, w in events) else "action",
        summary=f"{name}: " + ", ".join(f"{p} {listed(w)}" for p, w in said.items()),
        details="\n".join([pr["title"], *(f"{local_iso(t)} {p} {w}" for t, p, w in events)]),
        people=", ".join(said), project=project, url=pr["url"], happened_at=local_iso(events[-1][0]),
    )


def ci_item(pr: dict, project: str | None) -> Item | None:
    """The checks failing on the PR's last commit, with links to their builds."""
    commits = nodes(pr.get("commits"))
    rollup = (commits[0].get("commit") or {}).get("statusCheckRollup") or {} if commits else {}
    latest: dict[str, tuple[str, str, str]] = {}
    for check in nodes(rollup.get("contexts")):
        name = check.get("context") or check.get("name") or "?"
        state = check.get("state") or check.get("conclusion") or ""
        when = check.get("startedAt") or check.get("completedAt") or check.get("createdAt") or ""
        # A check run again shows up once per run
        if name not in latest or when >= latest[name][0]:
            latest[name] = (when, state, check.get("targetUrl") or check.get("detailsUrl") or "")
    failing = {name: check for name, check in latest.items() if check[1] in FAILED}
    if not failing:
        return None
    first = next(iter(failing.values()))
    return Item(
        source=SOURCE, key=f"ci:{pr['url']}", kind="action",
        summary=f"CI fails on {pr['repository']['name']}#{pr['number']}: {', '.join(failing)}",
        details="\n".join([pr["title"], *(f"{name}: {url}" for name, (_, _, url) in failing.items())]),
        project=project, url=first[2] or pr["url"],
        happened_at=local_iso(max(when for when, _, _ in failing.values())),
    )


def listed(words: list[str]) -> str:
    return " and ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 1 else words[0]



def archive_finished(db: sqlite3.Connection) -> int:
    """Projects with PRs, all closed, and no open item or channel: the work is over."""
    cursor = db.execute(
        """
        UPDATE watch_projects SET status = 'archived', updated_at = ?
        WHERE status = 'active'
          AND EXISTS (SELECT 1 FROM watch_prs pr WHERE pr.project_id = watch_projects.id)
          AND NOT EXISTS (SELECT 1 FROM watch_prs pr WHERE pr.project_id = watch_projects.id AND pr.state = 'open')
          AND NOT EXISTS (SELECT 1 FROM watch_items i WHERE i.project_id = watch_projects.id AND i.done_at IS NULL)
          AND NOT EXISTS (SELECT 1 FROM watch_project_links l WHERE l.project_id = watch_projects.id AND l.kind = 'channel')
        """,
        (now(),),
    )
    return cursor.rowcount
