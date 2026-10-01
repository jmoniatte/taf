import re
import unittest

from fini.message import Inference, parse_message

# The Ruby fini's message_parser_spec.rb: message -> (text, action, context, duration)
CASES = {
    "working on task @30m": ("working on task", None, None, 30),
    "meeting @2h": ("meeting", None, None, 120),
    "planning session @1.5h": ("planning session", None, None, 90),
    "working on feature @1h30": ("working on feature", None, None, 90),
    "workshop @2h15": ("workshop", None, None, 135),
    "@2h working on project": ("working on project", None, None, 120),
    "worked for @2h on project": ("worked for on project", None, None, 120),
    "implementing feature +coding": ("implementing feature", "coding", None, None),
    "+review pull request": ("pull request", "review", None, None),
    "working on feature @backend": ("working on feature", None, "backend", None),
    "task @my-awesome_context": ("task", None, "my-awesome_context", None),
    "@api refactoring endpoints": ("refactoring endpoints", None, "api", None),
    "spent @backend time on coding": ("spent time on coding", None, "backend", None),
    "on auth system +coding @backend @2h": ("on auth system", "coding", "backend", 120),
    "code changes +review @frontend @1h30": ("code changes", "review", "frontend", 90),
    "daily standup @team @15m +meeting": ("daily standup", "meeting", "team", 15),
    "daily standup @team +meeting @15m": ("daily standup", "meeting", "team", 15),
    "worked @2h +coding the @backend system": ("worked the system", "coding", "backend", 120),
    "+coding @backend task @2h": ("task", "coding", "backend", 120),
    "working on feature @backend @2h": ("working on feature", None, "backend", 120),
    "on something +coding @1h": ("on something", "coding", None, 60),
    "issue +debugging @backend": ("issue", "debugging", "backend", None),
    "just working": ("just working", None, None, None),
    # Not in the spec: @0m comes to nothing, and @1h30m takes the m
    "nothing @0m": ("nothing", None, None, None),
    "long one @1h30m": ("long one", None, None, 90),
}


class ParseMessageTest(unittest.TestCase):
    def test_the_ruby_specs(self) -> None:
        for message, expected in CASES.items():
            with self.subTest(message=message):
                parsed = parse_message(message)
                self.assertEqual((parsed.text, parsed.action, parsed.context, parsed.duration), expected)

    def test_rules_name_what_the_message_does_not_give_first_match_wins_else_the_default(self) -> None:
        action = Inference("code", [("meet", [re.compile(r"^Met\b")]), ("comm", [re.compile(r"\bEmailed\b"), re.compile(r"(?i)\bemail\b")])])
        context = Inference("rails", [("public-api", [re.compile(r"(?i)\bpublic api\b")])])
        parsed = parse_message("Met to talk about the Public API @30m", action, context)
        self.assertEqual((parsed.action, parsed.context), ("meet", "public-api"))
        parsed = parse_message("Answered an EMAIL", action, context)
        self.assertEqual((parsed.action, parsed.context), ("comm", "rails"))
        # Given in the message, the rules are not asked
        parsed = parse_message("Met for lunch +pto @time-off", action, context)
        self.assertEqual((parsed.action, parsed.context), ("pto", "time-off"))
        self.assertEqual(parse_message("Coded", action, Inference()).context, None)


if __name__ == "__main__":
    unittest.main()
