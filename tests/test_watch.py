import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taf.watch import cli
from taf.watch import github, slack
from taf.watch.claude import ClaudeResult, parse_result
from taf.watch import projects
from taf.watch.config import Config, GithubConfig, load_config
from taf.database import open_database
from taf.watch.items import Item, get_cursor, get_item, list_items, recent_runs, save_item, set_done


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.config = Config(database_path=self.tmp / "taf.sqlite3")
        self.db = open_database(self.config.database_path)
        self.addCleanup(self.db.close)
        projects.add_project(self.db, "rwgps", "Rails app")


class ConfigTest(Case):
    def test_load(self):
        path = self.tmp / "config.yml"
        path.write_text("database_path: '~/x.sqlite3'\nwatch:\n  model: haiku\n  slack:\n    skip_channels: ['#dev-notify']\n")
        config = load_config(path)
        self.assertEqual((config.model, config.max_budget_usd), ("haiku", 1.0))
        self.assertEqual(config.slack.skip_channels, ["dev-notify"])
        # The database is taf's
        self.assertEqual(config.database_path, Path("~/x.sqlite3").expanduser())
        self.assertEqual(load_config(self.tmp / "missing.yml"), Config())
        path.write_text("watch:\n  github:\n    deploy_repo: org/app\n")
        self.assertEqual((load_config(path).github.deploy_repo, load_config(path).github.deploy_label), ("org/app", "ready-for-deploy"))
        path.write_text("watch:\n  slack: nope\n")
        with self.assertRaises(ValueError):
            load_config(path)


class ProjectsTest(Case):
    def test_links_rename_merge_and_branch_match(self):
        projects.add_project(self.db, "follow-privacy-levels", "Followers-only privacy", ["#friends-follow"])
        projects.add_project(self.db, "other", "", ["friends-follow", "other-chan"])
        projects.link(self.db, "follow-privacy-levels", "branch", "jean-fpl")
        save_item(self.db, Item("slack", "C1:1", "action", "QA prod1", project="other"))

        found = {p.name: p for p in projects.list_projects(self.db)}
        self.assertEqual(found["follow-privacy-levels"].channels, ["friends-follow"])
        self.assertEqual(found["other"].channels, ["other-chan"])
        self.assertEqual(projects.project_for_branch(self.db, "jean-fpl"), "follow-privacy-levels")
        self.assertEqual(projects.project_for_branch(self.db, "jean-rwgps-fix"), "rwgps")
        self.assertIsNone(projects.project_for_branch(self.db, "main"))

        projects.merge(self.db, "other", "follow-privacy-levels")
        projects.rename(self.db, "follow-privacy-levels", "follow")
        found = {p.name: p for p in projects.list_projects(self.db)}
        self.assertEqual((found["follow"].open_items, found["follow"].channels), (1, ["friends-follow", "other-chan"]))
        self.assertEqual(list_items(self.db)[0]["project"], "follow")
        with self.assertRaises(projects.ProjectError):
            projects.rename(self.db, "follow", "rwgps")
        projects.set_project_status(self.db, "follow", "archived")
        self.assertIsNone(projects.project_for_branch(self.db, "jean-fpl"))
        self.assertEqual([p.name for p in projects.list_projects(self.db)], ["rwgps"])


class ItemsTest(Case):
    def test_save_updates_by_key_and_keeps_done(self):
        save_item(self.db, Item("slack", "C1:1", "action", "Review PR", project="rwgps"))
        [row] = list_items(self.db)
        set_done(self.db, [row["id"]])
        save_item(self.db, Item("slack", "C1:1", "action", "Review PR again"))
        [row] = list_items(self.db, status=None)
        self.assertEqual((row["summary"], row["status"], row["project"]), ("Review PR again", "done", "rwgps"))
        set_done(self.db, [row["id"]], done=False)
        self.assertEqual(get_item(self.db, row["id"])["done_at"], None)

        save_item(self.db, Item("slack", "C1:1", "action", "Merged", resolved=True))
        save_item(self.db, Item("slack", "C2:1", "fyi", "Deploy moved", details="to Friday"))
        self.assertEqual(list_items(self.db, status="done")[0]["summary"], "Merged")
        self.assertEqual([r["summary"] for r in list_items(self.db, words=["friday"])], ["Deploy moved"])
        self.assertEqual(set_done(self.db, [999]), [999])


class GithubTest(Case):
    def test_sync_names_projects_from_branches_and_archives_finished_ones(self):
        projects.add_project(self.db, "follow-privacy-levels", "Followers privacy", ["friends-follow"])
        branches = {"u/1": "jean/follow-privacy-levels", "u/2": "jean/follow-privacy-levels",
                    "u/3": "jean/Strong_Params", "u/4": "fix-typo"}
        calls = []

        def gh(args):
            calls.append(args)
            if args[1] == "api":
                return {"login": "jean"}
            if "--author" in args:
                return [{"url": url, "number": int(url[-1]), "title": f"PR {url[-1]}", "repository": {"name": "r"}}
                        for url in open_urls]
            if args[1] == "search":
                return []
            return {"headRefName": branches[args[3]], "comments": [], "reviews": [], "statusCheckRollup": []}

        open_urls = ["u/1", "u/2", "u/3", "u/4"]
        report = github.sync(self.db, run=gh)
        self.assertEqual((report.open_prs, report.new_projects, report.error), (4, 2, None))
        found = {p.name: p for p in projects.list_projects(self.db)}
        self.assertEqual(found["follow-privacy-levels"].branches, ["jean/follow-privacy-levels"])
        self.assertEqual(found["follow-privacy-levels"].prs, ["r#1 PR 1", "r#2 PR 2"])
        self.assertEqual(found["strong-params"].about, "PR 3")
        self.assertIn("fix-typo", found)
        self.assertEqual(projects.project_for_branch(self.db, "jean-follow-privacy-levels"), "follow-privacy-levels")

        open_urls = ["u/1", "u/2"]
        calls.clear()
        # An open item keeps its project going after the PRs close
        save_item(self.db, Item("slack", "C9:1", "action", "Fix the other typos", project="fix-typo"))
        report = github.sync(self.db, run=gh)
        self.assertEqual((len(calls), report.archived), (5, 1))
        self.assertEqual({p.name for p in projects.list_projects(self.db)} & {"strong-params", "fix-typo"}, {"fix-typo"})
        self.assertEqual(github.sync(self.db, run=lambda a: (_ for _ in ()).throw(RuntimeError("no gh"))).error,
                         "github: no gh")

    def test_replies_ci_and_review_requests(self):
        pr = {"url": "u/1", "number": 1, "title": "Add follows", "repository": {"name": "r"}}
        view = {
            "headRefName": "jean/follows",
            "comments": [{"author": {"login": "kevin"}, "createdAt": "2026-10-01T10:00:00Z"},
                         {"author": {"login": "jean"}, "createdAt": "2026-10-01T11:00:00Z"},
                         {"author": {"login": "ridebot"}, "createdAt": "2026-10-01T12:00:00Z"}],
            "reviews": [{"author": {"login": "pat"}, "state": "CHANGES_REQUESTED", "submittedAt": "2026-10-01T13:00:00Z"},
                        {"author": {"login": "pat"}, "state": "COMMENTED", "submittedAt": "2026-10-01T14:00:00Z"},
                        {"author": {"login": "pat"}, "state": "DISMISSED", "submittedAt": "2026-10-01T15:00:00Z"}],
            "statusCheckRollup": [
                {"context": "spec_tests", "state": "FAILURE", "startedAt": "2026-10-01T09:00:00Z",
                 "targetUrl": "https://ci/spec_tests/5"},
                {"context": "rubocop", "state": "SUCCESS", "startedAt": "2026-10-01T09:00:00Z"},
                {"name": "evaluate", "conclusion": "FAILURE", "startedAt": "2026-10-01T08:00:00Z"},
                {"name": "evaluate", "conclusion": "SUCCESS", "startedAt": "2026-10-01T09:30:00Z"},
                {"name": "lint", "conclusion": "CANCELLED", "startedAt": "2026-10-01T09:30:00Z"}],
        }
        request = {"url": "u/9", "number": 9, "title": "Fix maps", "repository": {"name": "r"},
                   "author": {"login": "kim"}, "createdAt": "2026-10-01T08:00:00Z"}
        searches = []

        def gh(args):
            if args[1] == "api":
                return {"login": "jean"}
            if "--author" in args:
                return [pr] if prs_open else []
            if args[1] == "search":
                searches.append(args)
                return [request] if requested and "team-review-requested:org/rails" in args else []
            return view

        prs_open, requested = True, True
        config = GithubConfig(review_teams=["org/rails"], ignore_users=["ridebot"])
        report = github.sync(self.db, config, run=gh)
        self.assertEqual(report.found, ["Review r#9 Fix maps", "r#1: pat requested changes and commented",
                                        "CI fails on r#1: spec_tests"])
        self.assertIn("-reviewed-by:@me", searches[1])
        rows = {r["key"]: r for r in list_items(self.db, source="github")}
        self.assertEqual(rows["review:u/9"]["details"], "Review requested from team rails; opened by kim.")
        self.assertEqual((rows["replies:u/1"]["kind"], rows["replies:u/1"]["project"]), ("action", "follows"))
        self.assertEqual(rows["ci:u/1"]["url"], "https://ci/spec_tests/5")

        set_done(self.db, [rows["ci:u/1"]["id"], rows["replies:u/1"]["id"]])
        view["reviews"].append({"author": {"login": "pat"}, "state": "APPROVED", "submittedAt": "2026-10-02T09:00:00Z"})
        report = github.sync(self.db, config, run=gh)
        self.assertEqual((report.found, report.closed), (["r#1: pat requested changes, commented and approved"], []))
        self.assertEqual(list_items(self.db, status="done")[0]["key"], "ci:u/1")

        view["comments"].append({"author": {"login": "jean"}, "createdAt": "2026-10-02T10:00:00Z"})
        view["comments"].append({"author": {"login": "pat"}, "createdAt": "2026-10-02T11:00:00Z"})
        view["reviews"].append({"author": {"login": "pat"}, "state": "APPROVED", "submittedAt": "2026-10-02T12:00:00Z"})
        github.sync(self.db, config, run=gh)
        replies = get_item(self.db, rows["replies:u/1"]["id"])
        self.assertEqual((replies["summary"], replies["kind"]), ("r#1: pat commented and approved", "action"))

        prs_open, requested = False, False
        report = github.sync(self.db, config, run=gh)
        self.assertEqual((report.found, report.closed), ([], ["r#1: pat commented and approved", "Review r#9 Fix maps"]))
        self.assertEqual(list_items(self.db, source="github"), [])


def fake_run(output, cost=0.05, error=None, searches=1, tool_errors=()):
    calls = []

    def run(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return ClaudeResult(output, cost, error, {slack.SEARCH_TOOL: searches} if searches else {}, list(tool_errors))

    run.calls = calls
    return run


def item(**overrides):
    return {"existing_id": None, "key": "C1:100.1", "kind": "action", "summary": "Answer Kevin", "details": "", "people": "Kevin",
            "project": "rwgps", "url": None, "due": None, "happened_at": None, "resolved": False, **overrides}


class ReadyToDeployTest(unittest.TestCase):
    def test_counts_the_labelled_prs_live(self):
        asked = []

        def gh(args):
            asked.append(args)
            return [{"number": 1}, {"number": 2}]

        self.assertIsNone(github.ready_to_deploy(GithubConfig(), run=gh))
        self.assertEqual(asked, [])
        count, url = github.ready_to_deploy(GithubConfig(deploy_repo="org/app"), run=gh)
        self.assertEqual((count, url), (2, "https://github.com/org/app/pulls?q=is%3Aopen+is%3Apr+label%3Aready-for-deploy"))
        self.assertEqual(asked[0][asked[0].index("--label") + 1], "ready-for-deploy")
        self.assertIsNone(github.ready_to_deploy(GithubConfig(deploy_repo="org/app"), run=lambda a: (_ for _ in ()).throw(RuntimeError("x"))))


class SlackTest(Case):
    def test_collect_saves_items_and_moves_cursor(self):
        run = fake_run({"items": [item(), item(key="C2:1", project="unknown"), item(kind="bogus"),
                                  item(key="C3:1", project="follow-privacy-levels")],
                        "projects": [{"name": "follow-privacy-levels", "about": "Followers-only privacy",
                                      "channels": ["#friends-follow"]},
                                     {"name": "Bad Name", "about": "", "channels": []}],
                        "pages": 1, "more_pages_left": False, "last_message_ts": None, "error": None})
        with mock.patch("time.time", return_value=10_000.0):
            report = slack.collect(self.db, self.config, since=5_000.0, run=run)
        self.assertEqual((report.items, report.error), (3, None))
        self.assertEqual(float(get_cursor(self.db, "slack")), 10_000.0 - slack.OVERLAP_SECONDS)
        self.assertEqual({r["project"] for r in list_items(self.db)}, {"rwgps", "follow-privacy-levels", None})
        self.assertEqual([p.channels for p in projects.list_projects(self.db) if p.name != "rwgps"],
                         [["friends-follow"]])
        self.assertIn(slack.WRITE_TOOLS[0], run.calls[0][1]["denied_tools"])
        self.assertEqual(recent_runs(self.db)[0]["cost_usd"], 0.05)

    def test_pages_left_and_errors(self):
        run = fake_run({"items": [], "pages": 10, "more_pages_left": True, "last_message_ts": "7000.5", "error": None})
        with mock.patch("time.time", return_value=10_000.0):
            slack.collect(self.db, self.config, since=5_000.0, run=run)
        self.assertEqual(float(get_cursor(self.db, "slack")), 7000.5)

        report = slack.collect(self.db, self.config, run=fake_run(None, error="claude timed out"))
        self.assertEqual(report.error, "claude timed out")
        self.assertEqual(float(get_cursor(self.db, "slack")), 7000.5)
        self.assertEqual(recent_runs(self.db)[0]["error"], "claude timed out")

        empty = {"items": [], "pages": 0, "more_pages_left": False, "last_message_ts": None, "error": None}
        report = slack.collect(self.db, self.config, run=fake_run(empty, searches=0))
        self.assertIn("never searched", report.error)
        failed = [f"{slack.SEARCH_TOOL}: execution_failed: parameter_validation_failed"]
        report = slack.collect(self.db, self.config, run=fake_run(empty, tool_errors=failed))
        self.assertIn("parameter_validation_failed", report.error)
        self.assertEqual(float(get_cursor(self.db, "slack")), 7000.5)

    def test_open_items_are_closed_or_updated(self):
        save_item(self.db, Item("slack", "C1:1", "action", "Deploy friends-follow", project="rwgps"))
        save_item(self.db, Item("slack", "C2:1", "action", "Fix flaky test"))
        save_item(self.db, Item("github", "pr:1", "action", "Review PR"))
        run = fake_run({"items": [item(existing_id=2, key="C3:1", summary="Fix flaky test with parkPointer")],
                        "closed_ids": [1, 3, 999], "pages": 1, "more_pages_left": False,
                        "last_message_ts": None, "error": None})
        report = slack.collect(self.db, self.config, run=run)

        self.assertIn("- id 1, key C1:1 [rwgps] action: Deploy friends-follow", run.calls[0][0])
        self.assertNotIn("Review PR", run.calls[0][0])
        self.assertEqual((report.items, report.closed), (1, 1))
        self.assertEqual((report.found, report.closed_summaries), (["Fix flaky test with parkPointer"], ["Deploy friends-follow"]))
        rows = {r["id"]: r for r in list_items(self.db, status=None)}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["status"], "done")
        self.assertEqual((rows[2]["summary"], rows[2]["key"]), ("Fix flaky test with parkPointer", "C2:1"))
        self.assertEqual(rows[3]["status"], "open")

    def test_notification(self):
        with mock.patch("subprocess.run") as run:
            cli.notify("Slack", ["Answer <Kevin>", "Deploy"], ["Fix test"], None, 192.4)
            cli.notify("GitHub", [], [], None, 30)
            cli.notify("Slack", [], [], "claude timed out", 1200)
        sent = [c.args[0] for c in run.call_args_list]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][-2:], ["taf watch: Slack 2 found, 1 closed (3m 12s)", "+ Answer &lt;Kevin&gt;\n+ Deploy\n✓ Fix test"])
        self.assertEqual(sent[1][-2:], ["taf watch: Slack run failed (20m 0s)", "claude timed out"])
        self.assertIn("--urgency=critical", sent[1])

    def test_prompt(self):
        self.config.slack.skip_channels = ["dev-notify"]
        prompt = slack.build_prompt(self.config, since=1_791_222_916.0)
        self.assertIn("-in:#dev-notify", prompt)
        self.assertIn("after: `1791222916`", prompt)
        self.assertIn("(none yet)", prompt)
        prompt = slack.build_prompt(self.config, 0, projects=projects.list_projects(self.db))
        self.assertIn("- rwgps: Rails app\n", prompt)


class ClaudeTest(unittest.TestCase):
    def test_parse_result(self):
        def event(role, block):
            return json.dumps({"type": role, "message": {"content": [block]}})

        ok = "\n".join([
            event("assistant", {"type": "tool_use", "id": "a", "name": "search"}),
            event("user", {"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": "20 results"}]}),
            event("assistant", {"type": "tool_use", "id": "b", "name": "thread"}),
            event("user", {"type": "tool_result", "tool_use_id": "b", "content": "execution_failed: nope"}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.1,
                        "structured_output": {"a": 1}}),
        ])
        self.assertEqual(parse_result(ok, "", 0),
                         ClaudeResult({"a": 1}, 0.1, None, {"search": 1}, ["thread: execution_failed: nope"]))
        budget = json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                             "total_cost_usd": 1.0})
        self.assertIn("error_max_budget_usd", parse_result(budget, "", 1).error)
        self.assertIn("not logged in", parse_result("", "not logged in", 1).error)


class CliTest(Case):
    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.object(cli, "load_config", return_value=self.config), contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_context_list_and_done(self):
        branch = mock.patch.object(cli, "current_branch", return_value="jean-rwgps-fix")
        self.assertEqual(self.run_cli("context"), (0, ""))
        save_item(self.db, Item("slack", "C1:1", "action", "Review PR", project="rwgps"))
        with branch:
            out = self.run_cli("context")[1]
            self.assertIn("branch jean-rwgps-fix is project rwgps", out)
            self.assertIn("#1 action [rwgps] Review PR", out)
            self.assertIn("Review PR", self.run_cli("list")[1])
        with mock.patch.object(cli, "current_branch", return_value="main"):
            out = self.run_cli("context")[1]
            self.assertIn("no project is linked to branch main. Projects with open items: rwgps (1 open)", out)
            self.assertEqual(self.run_cli("project", "link", "rwgps", "--branch")[0], 0)
            self.assertIn("is project rwgps", self.run_cli("context")[1])
        self.assertEqual(self.run_cli("project", "assign", "nope", "1")[0], 1)
        self.assertEqual(self.run_cli("project", "assign", "none", "1")[0], 0)
        self.assertEqual(list_items(self.db)[0]["project"], None)
        self.assertEqual(self.run_cli("project", "assign", "rwgps", "1")[0], 0)
        self.assertIn("rwgps  1 open  Rails app\n  branch main", self.run_cli("project")[1])
        # Alone: every open item by project
        self.assertEqual(self.run_cli()[1], "rwgps (1)\n  #1 action Review PR\n")
        self.assertEqual(self.run_cli("pin", "1", "9"), (1, ""))
        self.assertEqual(get_item(self.db, 1)["pinned"], 1)
        self.assertEqual(self.run_cli("unpin", "1"), (0, ""))

        with mock.patch.object(cli, "current_branch", return_value="main"):
            self.assertEqual(self.run_cli("add", "Fix the N+1 in feeds", "--details", "seen in logs"),
                             (0, "#2 action [rwgps] Fix the N+1 in feeds\n"))
            self.assertEqual(self.run_cli("add", "Ask about caching", "--kind", "question", "--project", "none")[1],
                             "#3 question Ask about caching\n")
            self.assertEqual(self.run_cli("add", "x", "--project", "nope")[0], 2)
        self.assertEqual(get_item(self.db, 2)["details"], "seen in logs")

        self.assertEqual(self.run_cli("done", "1", "2", "3")[0], 0)
        self.assertEqual(self.run_cli("list", "--all")[1], "")
        self.assertIn("#1 DONE action", self.run_cli("search", "review")[1])
        # Review requests come first, under their own heading
        save_item(self.db, Item("github", "review:u/9", "action", "Review r#9"))
        save_item(self.db, Item("slack", "C2:1", "action", "Answer Pat"))
        self.assertEqual(self.run_cli()[1], "Pull Requests (1)\n  #4 action Review r#9\nNo project (1)\n  #5 action Answer Pat\n")


class ImportTest(unittest.TestCase):
    def test_the_commands_never_load_the_tui(self):
        # A fresh interpreter: this one may already have loaded Textual for other tests
        code = (
            "import sys, taf.__main__, taf.watch.cli, taf.todo_command; "
            "print(sorted(m for m in ('textual', 'rich') if m in sys.modules))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "[]\n")


if __name__ == "__main__":
    unittest.main()
