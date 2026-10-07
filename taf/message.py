"""A log message's parts: @duration, @context and +action, the Ruby fini's rules; no Textual."""

import re
from dataclasses import dataclass, field

DURATION = re.compile(r"@(?:\d+h\d+m?|\d+\.?\d*[hm])")
CONTEXT = re.compile(r"@[A-Za-z0-9_-]+")
ACTION = re.compile(r"\+[A-Za-z]+")
DURATION_VALUE = re.compile(r"^@?(?:(\d+\.?\d*)h)?(\d+)?m?$")


@dataclass
class Inference:
    """How to name an action or a context the message does not give: the first rule whose pattern
    matches the message, else the default."""

    default: str | None = None
    # (name, patterns) in the config's order
    rules: list[tuple[str, list[re.Pattern]]] = field(default_factory=list)

    def infer(self, message: str) -> str | None:
        for name, patterns in self.rules:
            if any(pattern.search(message) for pattern in patterns):
                return name
        return self.default


@dataclass(frozen=True)
class Parsed:
    text: str
    action: str | None
    context: str | None
    # In minutes
    duration: int | None


def parse_message(message: str, action: Inference | None = None, context: Inference | None = None) -> Parsed:
    """Take the first @duration, then the first @context, then the first +action out of the text;
    an action or context not given is inferred from the whole message."""
    text, duration = _extract(message, DURATION, duration_minutes)
    text, found_context = _extract(text, CONTEXT, lambda match: match.replace("@", ""))
    text, found_action = _extract(text, ACTION, lambda match: match.replace("+", ""))
    return Parsed(
        text=re.sub(r"\s{2,}", " ", text).strip(),
        action=found_action or (action.infer(message) if action else None),
        context=found_context or (context.infer(message) if context else None),
        duration=duration,
    )


def duration_minutes(value: str) -> int | None:
    """@30m, @2h, @1.5h, @1h30 or @1h30m in minutes; None when it comes to nothing."""
    match = DURATION_VALUE.match(value)
    if not match:
        return None
    hours = float(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    total = int(hours * 60) + minutes
    return total if total > 0 else None


def _extract(text: str, pattern: re.Pattern, value):
    match = pattern.search(text)
    if not match:
        return text, None
    return (text[: match.start()] + text[match.end() :]).strip(), value(match.group(0))
