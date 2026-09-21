"""
Inbox assistant for Sam @ PaperJet.

    python demo.py --cap R1
    python demo.py --all
"""

import argparse

from caps import (
    run_r1,
    run_r2,
    run_r3,
    run_r4,
    run_r5,
    run_r6,
    run_x1,
    run_x2,
)
from mailbox import load_inbox
from trace_log import clear_trace


def main():
    parser = argparse.ArgumentParser(description="PaperJet inbox demo")
    parser.add_argument("--cap", help="one capability, e.g. R1")
    parser.add_argument("--all", action="store_true", help="run R1-R6 then X1 X2")
    parser.add_argument("--msg", default="m008", help="message id for R2")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="R3: show send/delete but do not write outbox",
    )
    args = parser.parse_args()

    if not args.cap and not args.all:
        parser.print_help()
        return

    messages = load_inbox()
    if args.all:
        run_all(messages, args)
        return

    clear_trace(args.cap.upper())
    run_one(args.cap.upper(), messages, args)


def run_one(cap, messages, args):
    if cap == "R1":
        run_r1(messages)
    elif cap == "R2":
        run_r2(messages, msg_id=args.msg)
    elif cap == "R3":
        run_r3(messages, dry_run=args.dry_run)
    elif cap == "R4":
        run_r4(messages)
    elif cap == "R5":
        run_r5(messages)
    elif cap == "R6":
        run_r6(messages)
    elif cap == "X1":
        run_x1(messages)
    elif cap == "X2":
        run_x2(messages)
    else:
        print("unknown capability", cap)


def run_all(messages, args):
    print("\n=== R1 ===")
    clear_trace("R1")
    run_r1(messages)
    print("\n=== R2 ===")
    clear_trace("R2")
    run_r2(messages, msg_id=args.msg)
    print("\n=== R3 ===")
    clear_trace("R3")
    run_r3(messages, dry_run=True)
    print("\n=== R4 ===")
    clear_trace("R4")
    run_r4(messages, apply_now=True)
    print("\n=== R5 ===")
    clear_trace("R5")
    run_r5(messages)
    print("\n=== R6 ===")
    clear_trace("R6")
    run_r6(messages)
    print("\n=== X1 ===")
    clear_trace("X1")
    run_x1(messages)
    print("\n=== X2 ===")
    clear_trace("X2")
    run_x2(messages)


if __name__ == "__main__":
    main()
