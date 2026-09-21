import json
from pathlib import Path

INBOX_PATH = Path("inbox.json")
ME = "Srikanth.testuser@mail.com"


def load_inbox():
    with INBOX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def by_id(messages):
    messages_by_id = {}
    for msg in messages:
        messages_by_id[msg["id"]] = msg
    return messages_by_id


def thread_messages(messages, thread_id):
    found = [msg for msg in messages if msg["thread_id"] == thread_id]
    found.sort(key=lambda msg: msg["timestamp"])
    return found


def earlier_in_thread(messages, msg):
    """Messages in the same thread that arrived before this one."""
    return [
        other
        for other in thread_messages(messages, msg["thread_id"])
        if other["timestamp"] < msg["timestamp"]
    ]
