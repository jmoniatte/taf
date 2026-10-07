"""GitHub through `gh`: the user's open PRs name projects, and give items for replies, failing CI and review requests."""

import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from .config import GithubConfig
from .items import Item, list_items, now, save_item, set_done
from .projects import add_project, get_project, link, linked_project, name_from_branch

SOURCE = "github"
ME = ["gh", "api", "user"]
SEARCH = ["gh", "search", "prs", "--author", "@me", "--state", "open", "--limit", "100",
          "--json", "number,title,url,repository"]
REQUESTS = ["gh", "search", "prs", "--state", "open", "--limit", "100",
            "--json", "number,title,url,repository,author,createdAt", "--"]
VIEW_FIELDS = "headRefName,comments,reviews,statusCheckRollup"
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


def gh(args: list[str]) -> list | dict:
    done = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {done.stderr.strip()[:300]}")
    return json.loads(done.stdout)


def sync(db: sqlite3.Connection, config: GithubConfig = GithubConfig(), run=gh) -> SyncReport:
    """Record the user's open PRs, give each a project (its branch's, else one named after the branch),
    save items for what needs the user on GitHub, close the ones that no longer do, and archive
    projects whose PRs are all closed and that have nothing open."""
    report = SyncReport()
    try:
        me = run(ME)["login"]
        found = run(SEARCH)
        views = {pr["url"]: run(["gh", "pr", "view", pr["url"], "--json", VIEW_FIELDS]) for pr in found}
        requested = review_requests(run, config.review_teams)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError) as error:
        report.error = f"github: {error}"
        return report
    known = {r["url"] for r in db.execute("SELECT url FROM veille_prs")}
    for pr in found:
        url = pr["url"]
        if url in known:
            db.execute("UPDATE veille_prs SET title = ?, state = 'open', updated_at = ? WHERE url = ?",
                       (pr["title"], now(), url))
        else:
            db.execute(
                "INSERT INTO veille_prs (url, repo, number, title, branch, state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (url, pr["repository"]["name"], pr["number"], pr["title"], views[url]["headRefName"], now()),
            )
    open_urls = {pr["url"] for pr in found}
    report.open_prs = len(open_urls)
    for row in db.execute("SELECT url FROM veille_prs WHERE state = 'open'").fetchall():
        if row["url"] not in open_urls:
            db.execute("UPDATE veille_prs SET state = 'closed', updated_at = ? WHERE url = ?", (now(), row["url"]))

    prs = db.execute("SELECT * FROM veille_prs WHERE state = 'open' AND project_id IS NULL").fetchall()
    prefixes = {row["branch"].split("/")[0] for row in db.execute("SELECT branch FROM veille_prs") if "/" in row["branch"]}
    for pr in prs:
        project = linked_project(db, "branch", pr["branch"])
        if project is None:
            project = name_from_branch(pr["branch"], prefixes)
            if get_project(db, project) is None:
                add_project(db, project, pr["title"])
                report.new_projects += 1
            link(db, project, "branch", pr["branch"])
        db.execute("UPDATE veille_prs SET project_id = (SELECT id FROM veille_projects WHERE name = ?) WHERE url = ?",
                   (project, pr["url"]))
        # A new PR on an archived project's branch means the work started again
        db.execute("UPDATE veille_projects SET status = 'active', updated_at = ? WHERE name = ? AND status = 'archived'",
                   (now(), project))

    items = list(requested)
    for pr in found:
        project = db.execute(
            "SELECT p.name FROM veille_prs pr LEFT JOIN veille_projects p ON p.id = pr.project_id WHERE pr.url = ?",
            (pr["url"],),
        ).fetchone()["name"]
        view = views[pr["url"]]
        items += [i for i in (reply_item(pr, view, me, config.ignore_users, project), ci_item(pr, view, project)) if i]
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
    """Save the item, reopening a closed one when something newer happened; True when it is new or reopened."""
    row = db.execute("SELECT done_at, happened_at FROM veille_items WHERE source = ? AND key = ?",
                     (SOURCE, item.key)).fetchone()
    save_item(db, item)
    if row is None:
        return True
    if row["done_at"] is not None and item.happened_at != row["happened_at"]:
        db.execute("UPDATE veille_items SET done_at = NULL WHERE source = ? AND key = ?", (SOURCE, item.key))
        return True
    return False


def review_requests(run, teams: list[str]) -> list[Item]:
    """PRs waiting on the user's review, asked of them or of one of their teams."""
    searches = [("you", ["user-review-requested:@me"])]
    # A team request stays after a teammate reviews, so skip PRs already approved or reviewed by the user
    searches += [(f"team {team.split('/')[-1]}", [f"team-review-requested:{team}", "-reviewed-by:@me", "-review:approved"])
                 for team in teams]
    found: dict[str, Item] = {}
    for who, terms in searches:
        for pr in run([*REQUESTS, *terms, "-author:@me", "draft:false"]):
            if pr["url"] in found:
                continue
            author = pr["author"]["login"]
            found[pr["url"]] = Item(
                source=SOURCE, key=f"review:{pr['url']}", kind="action",
                summary=f"Review {pr['repository']['name']}#{pr['number']} {pr['title']}",
                details=f"Review requested from {who}; opened by {author}.", people=author,
                url=pr["url"], happened_at=local(pr["createdAt"]),
            )
    return list(found.values())


def reply_item(pr: dict, view: dict, me: str, ignore: list[str], project: str | None) -> Item | None:
    """What others said or decided on the user's PR since the user last commented or reviewed it."""
    def login(entry):
        return (entry.get("author") or {}).get("login") or ""

    mine = [c["createdAt"] for c in view["comments"] if login(c) == me]
    mine += [r["submittedAt"] for r in view["reviews"] if login(r) == me]
    since = max(mine, default="")
    events = [(c["createdAt"], login(c), "commented") for c in view["comments"]]
    events += [(r["submittedAt"], login(r), REVIEW_STATES[r["state"]]) for r in view["reviews"]
               if r["state"] in REVIEW_STATES]
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
        kind="fyi" if all(w == "approved" for _, _, w in events) else "action",
        summary=f"{name}: " + ", ".join(f"{p} {listed(w)}" for p, w in said.items()),
        details="\n".join([pr["title"], *(f"{local(t)} {p} {w}" for t, p, w in events)]),
        people=", ".join(said), project=project, url=pr["url"], happened_at=local(events[-1][0]),
    )


def ci_item(pr: dict, view: dict, project: str | None) -> Item | None:
    """The checks failing on the PR's last commit, with links to their builds."""
    latest: dict[str, tuple[str, str, str]] = {}
    for check in view.get("statusCheckRollup") or []:
        name = check.get("context") or check.get("name") or "?"
        state = check.get("state") or check.get("conclusion") or ""
        when = check.get("startedAt") or check.get("completedAt") or ""
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
        happened_at=local(max(when for when, _, _ in failing.values())),
    )


def listed(words: list[str]) -> str:
    return " and ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 1 else words[0]


def local(stamp: str) -> str | None:
    """GitHub's UTC times in the local zone, like the rest of the items."""
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone().isoformat(timespec="seconds")


def archive_finished(db: sqlite3.Connection) -> int:
    """Projects with PRs, all closed, and no open item or channel: the work is over."""
    cursor = db.execute(
        """
        UPDATE veille_projects SET status = 'archived', updated_at = ?
        WHERE status = 'active'
          AND EXISTS (SELECT 1 FROM veille_prs pr WHERE pr.project_id = veille_projects.id)
          AND NOT EXISTS (SELECT 1 FROM veille_prs pr WHERE pr.project_id = veille_projects.id AND pr.state = 'open')
          AND NOT EXISTS (SELECT 1 FROM veille_items i WHERE i.project_id = veille_projects.id AND i.done_at IS NULL)
          AND NOT EXISTS (SELECT 1 FROM veille_project_links l WHERE l.project_id = veille_projects.id AND l.kind = 'channel')
        """,
        (now(),),
    )
    return cursor.rowcount
