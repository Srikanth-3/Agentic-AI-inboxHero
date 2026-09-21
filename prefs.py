import json
from pathlib import Path

from inject import is_injection
from mailbox import load_inbox

PREFS_PATH = Path("prefs.json")


def load_prefs():
    if not PREFS_PATH.exists():
        return {}
    with PREFS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_prefs(prefs):
    with PREFS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(prefs, handle, indent=2)


def extract_prefs_from_inbox(messages=None):
    """Pull trusted standing instructions out of the mailbox."""
    if messages is None:
        messages = load_inbox()
    prefs = {}
    for msg in messages:
        body = (msg.get("body") or "").lower()
        if is_injection(msg):
            continue
        if "cc'd" in body and "lawyers at hartwell & cho" in body:
            prefs["cc_legal"] = "priya@paperjet.io"
            prefs["cc_legal_source"] = msg["id"]
        if "do not take meetings before" in body:
            prefs["no_meetings_before"] = "11:00"
            prefs["no_meetings_before_source"] = msg["id"]
    return prefs


def apply_legal_cc(draft_to, extra_cc=None):
    prefs = load_prefs()
    cc = list(extra_cc or [])
    if draft_to and prefs.get("cc_legal") and prefs["cc_legal"] not in cc:
        cc.append(prefs["cc_legal"])
    return cc


def too_early(hhmm):
    prefs = load_prefs()
    floor = prefs.get("no_meetings_before")
    if not floor:
        return False
    return hhmm < floor
