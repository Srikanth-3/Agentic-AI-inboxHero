import json
from datetime import datetime
from pathlib import Path

TRACE_PATH = Path("trace.jsonl")


def clear_trace(cap=None):
    if not TRACE_PATH.exists():
        return
    if cap is None:
        TRACE_PATH.unlink()
        return
    rows = TRACE_PATH.read_text(encoding="utf-8").splitlines()
    kept = [row for row in rows if json.loads(row).get("cap") != cap]
    TRACE_PATH.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


def log_event(cap, event, **fields):
    row = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "cap": cap,
        "event": event,
    }
    row.update(fields)
    with TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
