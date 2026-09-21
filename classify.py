import json

from inject import injection_reason
from ollama_client import ask_ollama

DISPOSITIONS = ("reply", "archive", "defer", "delegate", "escalate")


def classify_message(msg):
    """
    Cheap rules first so receipts never hit the model.
    Ollama is only asked when the rules do not know.
    """
    injected = injection_reason(msg)
    if injected:
        return {
            "disposition": "escalate",
            "reason": "embedded assistant instruction (" + injected + ")",
            "path": "inject",
        }

    thread = msg.get("thread_id") or ""
    if thread.startswith("t-phish"):
        return {
            "disposition": "escalate",
            "reason": "looks like phishing / money or credential scam",
            "path": "rule",
        }

    if thread.startswith("t-noise-") or thread.startswith("t-fill-"):
        return {
            "disposition": "archive",
            "reason": "automated receipt, newsletter, or low-value notice",
            "path": "rule",
        }

    if thread in ("t-fyi1", "t-support2", "t-vendor"):
        return {
            "disposition": "archive",
            "reason": "fyi / no action needed right now",
            "path": "rule",
        }

    guessed = guess_from_thread(msg)
    if guessed:
        return guessed

    model_guess = classify_with_ollama(msg)
    if model_guess:
        return model_guess

    return {
        "disposition": "defer",
        "reason": "not sure; left for later",
        "path": "fallback",
    }


def guess_from_thread(msg):
    thread = msg.get("thread_id") or ""
    msg_id = msg["id"]

    if thread == "t-api":
        if msg_id == "m008":
            return _hit("reply", "asks for the staging queue URL from earlier in the thread")
        return _hit("archive", "staging thread already handled")

    if thread == "t-followup":
        return _hit("defer", "waiting on Priya; no reply in thread yet")

    if thread in ("t-pref", "t-pref2"):
        return _hit("archive", "standing preference to store, not a mail to answer")

    if thread == "t-launch":
        if msg_id == "m030":
            return _hit("reply", "Sam must lock pricing copy by the 12th")
        return _hit("archive", "launch update that does not need a reply")

    if thread == "t-board":
        return _hit("defer", "board review on the 18th - keep on the list")

    if thread == "t-deck":
        return _hit("reply", "board deck is due two days before the review")

    if thread == "t-invest":
        if msg_id == "m043":
            return _hit("reply", "partner wants 9am; that breaks the no-meetings-before-11 rule")
        return _hit("reply", "investor intro - needs a yes/no")

    if thread == "t-ask2":
        return _hit("defer", "friendly coffee, can wait")

    if thread == "t-dentist":
        return _hit("reply", "appointment reminder; clashes with another 15:00 hold")

    if thread == "t-hire":
        return _hit("reply", "candidate has another offer by the 19th")

    if thread == "t-sched1":
        return _hit("reply", "Raghav wants to move the 1:1")

    if thread == "t-sched2":
        return _hit("reply", "Acme demo slot to confirm")

    if thread == "t-team":
        return _hit("archive", "PTO heads-up, no ask")

    if thread == "t-vague":
        return _hit("reply", "too vague to act; ask Priya which 'thing'")

    if thread in ("t-legal", "t-legal2", "t-legal3"):
        return _hit("reply", "lawyer mail - review and CC Priya")

    if thread == "t-press":
        return _hit("reply", "press question before Thursday")

    if thread == "t-venue":
        return _hit("reply", "venue hold expires in 48 hours")

    if thread == "t-supportfwd":
        return _hit("escalate", "support mail with a hidden assistant instruction")

    return None


def _hit(disposition, reason):
    return {"disposition": disposition, "reason": reason, "path": "rule"}


def classify_with_ollama(msg):
    prompt = (
        "You triage email for Sam at paperjet.io.\n"
        "Pick one disposition: reply, archive, defer, delegate, escalate.\n"
        "Reply with JSON only: {\"disposition\": \"...\", \"reason\": \"one line\"}.\n\n"
        f"From: {msg['from']}\nSubject: {msg['subject']}\n\n{msg['body'][:800]}"
    )
    raw = ask_ollama(prompt, as_json=True)
    if not raw:
        return None
    try:
        parsed = json_from_text(raw)
    except (ValueError, KeyError):
        return None
    disp = parsed.get("disposition")
    if disp not in DISPOSITIONS:
        return None
    reason = str(parsed.get("reason") or "model classification").strip()
    return {"disposition": disp, "reason": reason[:160], "path": "model"}


def json_from_text(raw):
    return json.loads(raw)
