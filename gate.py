from pathlib import Path

from trace_log import log_event

OUTBOX = Path("outbox")
IRREVERSIBLE = ("send", "delete")
REVERSIBLE = ("display", "propose")
_GATE_SECRET = object()


class GateAuthorization:
    def __init__(self, secret, action, detail, action_id):
        if secret is not _GATE_SECRET:
            raise TypeError("GateAuthorization objects must come from the gate")
        self.action = action
        self.detail = detail
        self.action_id = action_id
        self._secret = _GATE_SECRET


def classify_action(action):
    if action in REVERSIBLE:
        return "reversible"
    if action in IRREVERSIBLE:
        return "irreversible"
    return "unknown"


def require_approval(action, detail, action_id, cap="R3", dry_run=False):
    """
    Return a gate-issued authorization only after approval.
    Dry-run and unknown actions never authorize execution.
    """
    classification = classify_action(action)
    if classification == "unknown":
        log_event(
            cap,
            "human_response",
            action_id=action_id,
            action=action,
            classification=classification,
            response="rejected",
            reason="unknown action",
        )
        return None
    if classification == "reversible":
        return None

    print(f"  GATE {action}: {detail}")
    if dry_run:
        log_event(
            cap,
            "human_response",
            action_id=action_id,
            action=action,
            classification=classification,
            response="dry_run",
        )
        return None

    answer = input(f"    approve {action}? [y/n] ").strip().lower()
    ok = answer in ("y", "yes")
    log_event(
        cap,
        "human_response",
        action_id=action_id,
        action=action,
        classification=classification,
        response="approved" if ok else "rejected",
    )
    if not ok:
        return None
    return GateAuthorization(_GATE_SECRET, action, detail, action_id)


def write_outbox(filename, text, authorization=None):
    if not isinstance(authorization, GateAuthorization):
        raise PermissionError("outbox writes require gate-issued authorization")
    if authorization._secret is not _GATE_SECRET or authorization.action != "send":
        raise PermissionError("authorization is not valid for sending")
    OUTBOX.mkdir(exist_ok=True)
    path = OUTBOX / filename
    path.write_text(text, encoding="utf-8")
    return path


def outbox_count():
    if not OUTBOX.exists():
        return 0
    return len([p for p in OUTBOX.iterdir() if p.is_file()])
