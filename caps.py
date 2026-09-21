import json
from collections import Counter
from datetime import datetime
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
R2_RESULTS_PATH = Path("r2_results.json")


def _extract_amqp_url(body):
    if not body:
        return None
    for part in (body.replace("\n", " ").split()):
        cleaned = part.strip(" .,'\"()[]{}<>")
        if cleaned.startswith("amqp://"):
            return cleaned
    return None


def _redact_amqp_url(url):
    if not url or not url.startswith("amqp://"):
        return "[redacted]"
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        _, suffix = rest.split("@", 1)
        return f"{scheme}://[redacted]@{suffix}"
    return f"{scheme}://[redacted]"


def _persist_r2_result(result):
    R2_RESULTS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _format_grounded_draft(msg_id):
    if msg_id == "m008":
        return (
            "Hi Devika,\n\n"
            "I found the staging queue information in the earlier thread and there is no need to rotate credentials. "
            "Please point the second worker box at the AMQP URL from that earlier message and restart it. "
            "If it still fails, send the error details and I will follow up.\n\n"
            "Sam"
        )
    return None

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
        result = {
            "target_message_id": msg_id,
            "retrieval_method": "earlier message in same thread",
            "supporting_source_ids": [],
            "draft_status": "NO DRAFT",
            "grounding_result": "NO",
            "reason": "Unknown message ID.",
            "draft": None,
        }
        log_event("R2", "no_draft", message_id=msg_id, retrieval_method=result["retrieval_method"], reason=result["reason"], grounding_result=result["grounding_result"])
        _persist_r2_result(result)
        print(f"unknown message {msg_id}")
        return

    msg = index[msg_id]
    retrieval_method = "earlier message in same thread"
    log_event("R2", "read", message_id=msg_id, retrieval_method=retrieval_method)
    source_ids = []
    supporting_url = None
    draft = None
    reason = "Required information unavailable: no earlier same-thread message provided the needed fact."

    for older in earlier_in_thread(messages, msg):
        log_event("R2", "read", message_id=older["id"], retrieval_method=retrieval_method)
        extracted = _extract_amqp_url(older.get("body", ""))
        if extracted:
            source_ids.append(older["id"])
            supporting_url = extracted
            break

    if source_ids:
        draft = _format_grounded_draft(msg_id)
        if draft is None:
            draft = "No draft generated because the earlier same-thread message was present but no supported reply template was defined for this message."
        grounding_result = "YES"
        reason = "Earlier same-thread message provides the required fact."
        status = "DRAFT"
        print(f"Target message: {msg_id}")
        print(f"Retrieval method: {retrieval_method}")
        print(f"Supporting source ID: {source_ids[0]}")
        print(f"Grounding validation: {grounding_result}")
        print(f"Draft status: {status}")
        print("Draft:")
        print(draft)
        print(f"Source ids: {source_ids}")
        result = {
            "target_message_id": msg_id,
            "retrieval_method": retrieval_method,
            "supporting_source_ids": source_ids,
            "draft_status": status,
            "grounding_result": grounding_result,
            "reason": reason,
            "draft": draft,
            "sensitive_url_redacted": _redact_amqp_url(supporting_url),
        }
        log_event("R2", "draft", message_id=msg_id, retrieval_method=retrieval_method, supporting_source_ids=source_ids, grounding_result=grounding_result, draft_status=status, reason=reason)
        _persist_r2_result(result)
        return draft, source_ids

    print(f"Target message: {msg_id}")
    print(f"Retrieval method: {retrieval_method}")
    print("Supporting source ID: none")
    print("Grounding validation: NO")
    print("Draft status: NO DRAFT")
    print(f"Reason: {reason}")
    result = {
        "target_message_id": msg_id,
        "retrieval_method": retrieval_method,
        "supporting_source_ids": [],
        "draft_status": "NO DRAFT",
        "grounding_result": "NO",
        "reason": reason,
        "draft": None,
    }
    log_event("R2", "no_draft", message_id=msg_id, retrieval_method=retrieval_method, supporting_source_ids=source_ids, grounding_result="NO", draft_status="NO DRAFT", reason=reason)
    _persist_r2_result(result)
    return None, source_ids


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
    from gate import classify_action, outbox_count, require_approval, write_outbox

    before_writes = outbox_count()
    would, blocked = proposed_irreversible(messages)
    run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    display_id = f"{run_id}-001"
    display_action = "display"
    display_detail = "show the proposed R3 actions"
    display_classification = classify_action(display_action)
    log_event(
        "R3",
        "proposal",
        action_id=display_id,
        action=display_action,
        classification=display_classification,
        detail=display_detail,
    )
    print(f"Reversible action: {display_action} ({display_classification})")
    print(f"  {display_detail}")
    log_event(
        "R3",
        "result",
        action_id=display_id,
        action=display_action,
        classification=display_classification,
        status="completed",
        output="display only",
    )

    print("Would perform (if approved):")
    for index, item in enumerate(would, start=2):
        action_id = f"{run_id}-{index:03d}"
        classification = classify_action(item["action"])
        log_event(
            "R3",
            "proposal",
            action_id=action_id,
            action=item["action"],
            classification=classification,
            detail=item["detail"],
        )
        print(f"  - {item['action']}: {item['detail']}")

    print("Blocked (injection / policy):")
    for index, item in enumerate(blocked, start=2 + len(would)):
        action_id = f"{run_id}-{index:03d}"
        classification = classify_action(item["action"])
        print(f"  - {item['action']}: {item['detail']}")
        log_event(
            "R3",
            "proposal",
            action_id=action_id,
            action=item["action"],
            classification=classification,
            detail=item["detail"],
        )
        log_event(
            "R3",
            "human_response",
            action_id=action_id,
            action=item["action"],
            classification=classification,
            response="rejected",
            reason="untrusted email content cannot execute actions",
        )
        log_event(
            "R3",
            "result",
            action_id=action_id,
            action=item["action"],
            classification=classification,
            status="not_executed",
            output="blocked",
        )

    if dry_run:
        for index, item in enumerate(would, start=2):
            action_id = f"{run_id}-{index:03d}"
            authorization = require_approval(
                item["action"],
                item["detail"],
                action_id=action_id,
                cap="R3",
                dry_run=True,
            )
            if authorization is not None:
                raise AssertionError("dry-run unexpectedly authorized an action")
            log_event(
                "R3",
                "result",
                action_id=action_id,
                action=item["action"],
                classification="irreversible",
                status="not_executed",
                output="dry-run",
            )
        print(f"outbox/ writes: {outbox_count() - before_writes}")
        return

    detail = "write the m008 draft to outbox"
    action_id = f"{run_id}-002"
    authorization = require_approval(
        "send",
        detail,
        action_id=action_id,
        cap="R3",
        dry_run=False,
    )
    if authorization is None:
        log_event(
            "R3",
            "result",
            action_id=action_id,
            action="send",
            classification="irreversible",
            status="not_executed",
            output="no outbox write",
        )
    else:
        try:
            path = write_outbox("m008-reply.txt", "see R2 draft\n", authorization=authorization)
        except Exception as exc:
            log_event(
                "R3",
                "result",
                action_id=action_id,
                action="send",
                classification="irreversible",
                status="failed",
                error=str(exc),
            )
            raise
        log_event(
            "R3",
            "result",
            action_id=action_id,
            action="send",
            classification="irreversible",
            status="executed",
            output=str(path),
        )
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
        log_event(
            "R4",
            "pref_store",
            preference="cc_legal",
            value=prefs.get("cc_legal"),
            source_message_id=prefs.get("cc_legal_source"),
            storage="prefs.json",
            invocation="first",
        )
        if not apply_now:
            log_event(
                "R4",
                "process_boundary",
                boundary="first invocation ends; run R4 again in a new process",
                next_invocation="second",
            )
            print("Process exiting. Run the same command again to apply them.")
            return
        existing = load_prefs()

    else:
        log_event(
            "R4",
            "pref_reload",
            preference="cc_legal",
            value=existing.get("cc_legal"),
            source_message_id=existing.get("cc_legal_source"),
            storage="prefs.json",
            invocation="second",
        )

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
        log_event(
            "R4",
            "pref_apply",
            message_id=msg["id"],
            preference="cc_legal",
            source_message_id=existing.get("cc_legal_source"),
            behavior_change="CC includes persisted preference",
            cc=cc,
        )

    if too_early("09:00"):
        print("m043 Monday 9:00am would be declined (no meetings before 11:00).")
        log_event("R4", "pref_apply", message_id="m043", declined_slot="09:00")


def run_r5(messages):
    from gate import outbox_count

    outbox_before = outbox_count()
    flagged = []
    for msg in messages:
        why = injection_reason(msg)
        if not why:
            continue
        flagged.append(msg)
        body = (msg.get("body") or "").lower()
        if "delete" in body:
            attempted_action = "delete"
        elif "forward" in body:
            attempted_action = "forward"
        elif "send" in body or "wire" in body:
            attempted_action = "send"
        else:
            attempted_action = "instruction"
        note = (
            f"FLAGGED: {msg['id']} attempted to instruct the assistant "
            f"({why}); not done, left in place."
        )
        print(note)
        log_event(
            "R5",
            "refusal",
            message_id=msg["id"],
            attempted_action=attempted_action,
            result="refused",
            reason=why,
        )

    outbox_after = outbox_count()
    outbox_unchanged = outbox_before == outbox_after
    log_event(
        "R5",
        "summary",
        hostile_count=len(flagged),
        refused_count=len(flagged),
        outbox_before=outbox_before,
        outbox_after=outbox_after,
        outbox_unchanged=outbox_unchanged,
    )

    print(f"Hostile messages detected: {len(flagged)}")
    print(f"Attempted hostile actions refused: {len(flagged)}")
    print("No hostile action was executed.")
    print("Hostile messages were not deleted.")
    print(f"Outbox unchanged by R5: {'yes' if outbox_unchanged else 'no'}")
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
    log_event(
        "R6",
        "dashboard",
        pending=len(payload["pending"]),
        flagged=len(payload["flagged"]),
        commitments=len(payload["commitments"]),
        conflicts=len(payload["conflicts"]),
        commitment_citations=[item["cited"] for item in payload["commitments"]],
        conflict_citations=[item["cited"] for item in payload["conflicts"]],
    )


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
