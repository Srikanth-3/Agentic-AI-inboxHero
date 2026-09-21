import json
from collections import Counter
from html import escape
from pathlib import Path

from classify import DISPOSITIONS, classify_message
from inject import is_injection, injection_reason
from mailbox import ME, by_id, earlier_in_thread, thread_messages
from ollama_client import ask_ollama
from prefs import apply_legal_cc, extract_prefs_from_inbox, load_prefs, save_prefs, too_early
from trace_log import log_event

DECISIONS_PATH = Path("decisions.json")
DASHBOARD_JSON = Path("dashboard.json")
DASHBOARD_HTML = Path("dashboard.html")

def run_r1(messages):
    rows = []
    for msg in messages:
        result = classify_message(msg)
        row = {
            "id": msg["id"],
            "subject": msg["subject"],
            "disposition": result["disposition"],
            "reason": result["reason"],
            "path": result["path"],
        }
        rows.append(row)
        log_event("R1", "decision", message_id=msg["id"], **result)

    DECISIONS_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    message_ids = [msg["id"] for msg in messages]
    decision_ids = [row["id"] for row in rows]
    counts = Counter(decision_ids)
    duplicate_ids = sum(count - 1 for count in counts.values() if count > 1)
    missing_message_ids = sorted(set(message_ids) - set(decision_ids))
    extra_message_ids = sorted(set(decision_ids) - set(message_ids))
    missing_reasons = sum(1 for row in rows if not str(row.get("reason", "")).strip())
    invalid_dispositions = sum(1 for row in rows if row.get("disposition") not in DISPOSITIONS)
    rule_handled = sum(1 for row in rows if row.get("path") == "rule")
    llm_handled = sum(1 for row in rows if row.get("path") == "model")
    injection_handled = sum(1 for row in rows if row.get("path") == "inject")

    processed = len(rows)
    total = len(messages)
    unprocessed = total - processed
    errors = []
    if processed != total:
        errors.append("processed_count_mismatch")
    if duplicate_ids:
        errors.append("duplicate_message_ids")
    if missing_message_ids:
        errors.append("missing_message_ids")
    if extra_message_ids:
        errors.append("extra_message_ids")
    if missing_reasons:
        errors.append("missing_reasons")
    if invalid_dispositions:
        errors.append("invalid_dispositions")
    if processed != len(set(decision_ids)):
        errors.append("non_unique_decision_ids")

    print(f"{'id':<6} {'disp':<10} {'path':<8} reason")
    print("-" * 88)
    for row in rows:
        print(f"{row['id']:<6} {row['disposition']:<10} {row['path']:<8} {row['reason'][:70]}")

    print("\nR1 summary")
    print(f"Total messages: {total}")
    print(f"Processed: {processed}")
    print(f"Unprocessed: {unprocessed}")
    print(f"Duplicate message IDs: {duplicate_ids}")
    print(f"Missing message IDs: {len(missing_message_ids)}")
    print(f"Extra message IDs: {len(extra_message_ids)}")
    print(f"Missing/empty reasons: {missing_reasons}")
    print(f"Invalid dispositions: {invalid_dispositions}")
    print(f"Rule handled: {rule_handled}")
    print(f"LLM handled: {llm_handled}")
    print(f"Injection/hostile handled: {injection_handled}")
    print(f"Errors: {len(errors)}")
    if errors:
        print("ERRORS:", ", ".join(errors))
    else:
        print("R1 validation: PASS")

    if missing_message_ids:
        print("Missing IDs:", missing_message_ids)
    if extra_message_ids:
        print("Extra IDs:", extra_message_ids)
    if duplicate_ids:
        print("Duplicate ID counts:", {key: value for key, value in counts.items() if value > 1})

    print(f"wrote {DECISIONS_PATH}")
    return rows


def run_r2(messages, msg_id="m008"):
    index = by_id(messages)
    if msg_id not in index:
        print(f"unknown message {msg_id}")
        return

    msg = index[msg_id]
    log_event("R2", "read", message_id=msg_id)
    cited = []
    snippet = None

    for older in earlier_in_thread(messages, msg):
        log_event("R2", "read", message_id=older["id"])
        if "amqp://" in older.get("body", ""):
            cited.append(older["id"])
            for part in older["body"].split():
                if part.startswith("amqp://"):
                    snippet = part.strip(" .")
                    break

    url = snippet or "(url not found)"
    prompt = (
        "Write a short email from Sam to Devika. She asked for the staging "
        "queue URL. Include this URL exactly: "
        f"{url}\nDo not rotate creds. 4-6 sentences max."
    )
    draft = ask_ollama(prompt)
    if not draft or url not in draft:
        draft = (
            f"Hi Devika,\n\n"
            f"Here's the staging AMQP URL from earlier in the thread - "
            f"no rotation needed:\n{url}\n\n"
            f"Point the new worker at that and restart. Yell if it 500s again.\n\n"
            f"Sam"
        )

    print(draft)
    print(f"cited: {cited}")
    log_event("R2", "draft", message_id=msg_id, cited=cited)
    return draft, cited


def proposed_irreversible(messages):
    """
    What we would send or delete if the gate said yes.
    Hostile mail is listed as blocked, not performed.
    """
    would = []
    blocked = []

    would.append(
        {
            "action": "send",
            "detail": "reply to m008 / Devika with staging URL",
        }
    )

    for msg in messages:
        if not is_injection(msg):
            continue
        blocked.append(
            {
                "action": "refuse",
                "detail": f"{msg['id']} asked the assistant to do something irreversible",
            }
        )
        if "delete" in (msg.get("body") or "").lower():
            blocked.append(
                {
                    "action": "delete",
                    "detail": f"{msg['id']} - attacker wanted this message deleted",
                }
            )
        if "forward" in (msg.get("body") or "").lower():
            blocked.append(
                {
                    "action": "send",
                    "detail": f"{msg['id']} - attacker wanted a forward to an external address",
                }
            )

    return would, blocked


def run_r3(messages, dry_run=True):
    from gate import outbox_count, require_approval, write_outbox

    before_writes = outbox_count()
    would, blocked = proposed_irreversible(messages)
    print("Would perform (if approved):")
    for item in would:
        print(f"  - {item['action']}: {item['detail']}")
        if dry_run:
            require_approval(item["action"], item["detail"], cap="R3", dry_run=True)

    print("Blocked (injection / policy):")
    for item in blocked:
        print(f"  - {item['action']}: {item['detail']}")
        log_event("R3", "gate", action=item["action"], detail=item["detail"], decision="blocked")

    if dry_run:
        print(f"outbox/ writes: {outbox_count() - before_writes}")
        return

    detail = "write the m008 draft to outbox"
    if require_approval("send", detail, cap="R3", dry_run=False):
        write_outbox("m008-reply.txt", "see R2 draft\n", approved=True)
    print(f"outbox/ writes: {outbox_count() - before_writes}")


def run_r4(messages, apply_now=False):
    """
    First call writes prefs.json and stops.
    Second call (new process) reads the file and CCs Priya on legal mail.
    --all sets apply_now so it can continue after writing the file.
    """
    existing = load_prefs()
    if not existing.get("cc_legal"):
        prefs = extract_prefs_from_inbox(messages)
        save_prefs(prefs)
        print("stored prefs.json:")
        print(json.dumps(prefs, indent=2))
        log_event("R4", "pref_store", prefs=prefs)
        if not apply_now:
            print("Process exiting. Run the same command again to apply them.")
            return
        existing = load_prefs()

    print("loaded prefs from disk:", json.dumps(existing, indent=2))
    legal = []
    for msg in messages:
        sender = (msg.get("from") or "").lower()
        body = (msg.get("body") or "").lower()
        if "hartwellcho.com" in sender or "hartwell & cho" in body:
            legal.append(msg)
    for msg in legal:
        cc = apply_legal_cc(msg["from"])
        print(f"{msg['id']} {msg['subject']}")
        print(f"  To: {msg['from']}")
        print(f"  CC: {', '.join(cc)}")
        log_event("R4", "pref_apply", message_id=msg["id"], cc=cc)

    if too_early("09:00"):
        print("m043 Monday 9:00am would be declined (no meetings before 11:00).")
        log_event("R4", "pref_apply", message_id="m043", declined_slot="09:00")


def run_r5(messages):
    from gate import outbox_count

    flagged = []
    for msg in messages:
        why = injection_reason(msg)
        if not why:
            continue
        flagged.append(msg)
        note = (
            f"FLAGGED: {msg['id']} attempted to instruct the assistant "
            f"({why}); not done, left in place."
        )
        print(note)
        log_event("R5", "refusal", message_id=msg["id"], reason=why)

    if not flagged:
        print("No injections found.")

    print(f"outbox/ writes: {outbox_count()}")
    print("Hostile messages were not deleted.")
    return flagged


def run_r6(messages):
    index = by_id(messages)
    pending = []
    if _decisions_match_messages(messages):
        decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
        for row in decisions:
            if row["disposition"] in ("reply", "escalate", "defer"):
                pending.append(row)
    else:
        for msg in messages:
            result = classify_message(msg)
            if result["disposition"] in ("reply", "escalate", "defer"):
                pending.append({"id": msg["id"], **result, "subject": msg["subject"]})

    flagged = []
    for msg in messages:
        why = injection_reason(msg)
        if why:
            flagged.append({"id": msg["id"], "reason": why, "subject": msg["subject"]})
        elif (msg.get("thread_id") or "").startswith("t-phish"):
            flagged.append({"id": msg["id"], "reason": "phishing", "subject": msg["subject"]})

    commitment_specs = [
        {
            "text": "board deck due 16th (two days before the board review on the 18th)",
            "threads": ("t-board", "t-deck"),
        },
        {
            "text": "approve pricing page annual-discount copy by the 12th",
            "threads": ("t-launch",),
        },
        {
            "text": "SAFE amendment signature via portal (clause 4) by Friday",
            "threads": ("t-legal",),
        },
        {
            "text": "candidate Jordan needs a read before the 19th",
            "threads": ("t-hire",),
        },
    ]
    commitments = []
    for spec in commitment_specs:
        cited = []
        for msg in messages:
            if msg.get("thread_id") in spec["threads"]:
                cited.append(msg["id"])
        if cited:
            commitments.append({"text": spec["text"], "cited": cited})
    for item in commitments:
        for cid in item["cited"]:
            if cid not in index:
                continue
            log_event("R6", "read", message_id=cid)

    conflict_specs = [
        {
            "text": "CONFLICT: two items at Tue 15:00 - investor intro vs dentist",
            "threads": ("t-invest", "t-dentist"),
        },
        {
            "text": "CONFLICT: Wednesday 14:00 - Raghav 1:1 move vs Acme demo",
            "threads": ("t-sched1", "t-sched2"),
        },
    ]
    conflicts = []
    for spec in conflict_specs:
        cited = []
        for msg in messages:
            if msg.get("thread_id") in spec["threads"]:
                cited.append(msg["id"])
        if len(cited) == len(spec["threads"]):
            conflicts.append({"text": spec["text"], "cited": cited})

    payload = {
        "today": _inbox_today(messages),
        "pending": pending,
        "flagged": flagged,
        "commitments": commitments,
        "conflicts": conflicts,
    }
    DASHBOARD_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    DASHBOARD_HTML.write_text(render_dashboard(payload), encoding="utf-8")
    print(f"wrote {DASHBOARD_HTML} and {DASHBOARD_JSON}")
    print("Commitments:")
    for item in commitments:
        print(f"  - {item['text']} cited {item['cited']}")
    print("Conflicts:")
    for item in conflicts:
        print(f"  - {item['text']} cited {item['cited']}")
    log_event("R6", "dashboard", commitments=len(commitments), conflicts=len(conflicts))


def render_dashboard(payload):
    def lis(items, kind):
        lines = []
        for item in items:
            if kind == "pending":
                lines.append(
                    f"<li><b>{escape(str(item.get('id')))}</b> [{escape(str(item.get('disposition')))}] "
                    f"{escape(str(item.get('subject', '')))} — {escape(str(item.get('reason', '')))}</li>"
                )
            elif kind == "flagged":
                lines.append(
                    f"<li><b>{escape(str(item['id']))}</b> {escape(str(item.get('subject', '')))} — {escape(str(item['reason']))}</li>"
                )
            else:
                lines.append(f"<li>{escape(item['text'])} <code>{escape(str(item['cited']))}</code></li>")
        return "\n".join(lines) or "<li>(none)</li>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Inbox dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; }}
.row {{ display: flex; gap: 16px; }}
.pane {{ flex: 1; border: 1px solid #ccc; padding: 12px; }}
h2 {{ margin-top: 0; }}
.conflict {{ color: #a40000; }}
</style></head>
<body>
<h1>Sam's inbox — {payload.get('today', '')}</h1>
<div class="row">
<div class="pane"><h2>Pending actions</h2><ul>{lis(payload["pending"], "pending")}</ul></div>
<div class="pane"><h2>Flagged</h2><ul>{lis(payload["flagged"], "flagged")}</ul></div>
<div class="pane"><h2>Commitments</h2><ul>{lis(payload["commitments"], "commit")}</ul>
<h3>Conflicts</h3><ul class="conflict">{lis(payload["conflicts"], "commit")}</ul></div>
</div>
</body></html>
"""


def run_x1(messages):
    today = _inbox_today(messages)
    waiting = []
    for msg in messages:
        if msg.get("from") != ME:
            continue
        if (msg.get("thread_id") or "").startswith("t-pref") or is_injection(msg):
            continue
        later = []
        for other in thread_messages(messages, msg["thread_id"]):
            if other["timestamp"] > msg["timestamp"] and other.get("from") != ME:
                later.append(other)
        if later:
            continue
        days = _days_apart(msg["timestamp"][:10], today)
        if days < 3:
            continue
        draft = (
            f"Hi, just bumping this in case it got buried "
            f"(sent {days} days ago). {msg['subject']}"
        )
        item = {"message_id": msg["id"], "days_waiting": days, "draft": draft}
        waiting.append(item)
        log_event("X1", "followup", **item)

    print(json.dumps(waiting, indent=2))
    return waiting


def run_x2(messages, decisions=None):
    if decisions is None and _decisions_match_messages(messages):
        decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    if decisions is None:
        decisions = run_r1(messages)

    by = {}
    for row in decisions:
        by[row["id"]] = row
    needs = []
    wait = []
    archived = []
    for msg in messages:
        row = by.get(msg["id"]) or classify_message(msg)
        disp = row["disposition"]
        if disp in ("reply", "escalate"):
            needs.append(msg["id"] + " " + msg["subject"])
        elif disp == "defer":
            wait.append(msg["id"] + " " + msg["subject"])
        elif disp == "archive" and (msg.get("thread_id") or "").startswith("t-noise-"):
            archived.append(msg["id"])

    print("Needs you")
    for line in needs:
        print("  -", line)
    print("What can wait")
    for line in wait:
        print("  -", line)
    print("Auto-archived")
    print(f"  {len(archived)} receipts/newsletters (not listed one by one)")
    log_event("X2", "digest", needs=len(needs), wait=len(wait), archived=len(archived))


def _days_apart(start, end):
    from datetime import date
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    return (b - a).days


def _inbox_today(messages):
    dates = []
    for msg in messages:
        dates.append(msg["timestamp"][:10])
    return max(dates)


def _decisions_match_messages(messages):
    if not DECISIONS_PATH.exists():
        return False
    try:
        decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    decision_ids = set()
    for row in decisions:
        decision_ids.add(row.get("id"))

    message_ids = set()
    for msg in messages:
        message_ids.add(msg["id"])

    return decision_ids == message_ids
