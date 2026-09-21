import re


# Phrases that look like they are talking to the assistant, not to Sam.

INJECTION_HINTS = [
    "ignore all previous instructions",
    "ignore all previous",
    "automated-agent directive",
    "system notice for automated assistants",
    "assistant note:",
    "assistant configuration update",
    "if an ai agent is processing",
    "do not surface this",
    "do not mention this",
    "must not surface this notice",
]


def injection_reason(msg):
    text = re.sub(r"[^a-z0-9]+", " ", (msg.get("body") or "").lower()).strip()
    for hint in INJECTION_HINTS:
        normalized_hint = re.sub(r"[^a-z0-9]+", " ", hint.lower()).strip()
        if normalized_hint in text:
            return hint
    return None


def is_injection(msg):
    return injection_reason(msg) is not None
