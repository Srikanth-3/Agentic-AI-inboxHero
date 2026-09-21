# inboxHero — Agentic AI Assignment 06

**Student:** Srikanth Lakkam  
**Repository:** https://github.com/Srikanth-3/Agentic-AI-inboxHero  
**Model:** Qwen3:8b via local Ollama  
**Framework:** Plain Python  
**Input:** Local `inbox.json`  
**Execution:** Local filesystem only; no real email account is used

---

## 1. Project Overview

`inboxHero` is a local agentic email assistant built for Assignment 06.

The system processes a synthetic inbox of 100 messages and demonstrates:

- inbox classification
- thread-aware retrieval
- grounded reply drafting
- human approval before irreversible actions
- persistent user preferences
- prompt-injection / hostile-email handling
- commitments and conflict detection
- an auditable three-pane dashboard
- custom capabilities with observable evidence

The implementation intentionally uses simple Python modules instead of a large agent framework so that the behavior and safety boundaries remain easy to inspect.

---

## 2. Architecture

```text
                         inbox.json
                             |
                             v
                        mailbox.py
                             |
                             v
                        classify.py
                     /        |        \
                    /         |         \
               rules      injection    Ollama
                 |          check       fallback
                 \           |           /
                  \          |          /
                           decisions
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
            R2               R3               R6
         retrieval        safety gate      dashboard
             |                |                |
             v                v                v
       grounded draft    human approval    HTML/JSON
                              |
                              v
                           outbox/

       prefs.py ---> prefs.json

       trace_log.py ---> trace.jsonl
```

### Main implementation modules

| File | Purpose |
|---|---|
| `demo.py` | Command-line entry point |
| `caps.py` | R1–R6 and custom capability execution |
| `mailbox.py` | Inbox loading and thread/message retrieval |
| `classify.py` | Classification and deterministic rules |
| `inject.py` | Hostile/prompt-injection detection |
| `gate.py` | Reversible/irreversible action gate |
| `prefs.py` | Persistent preferences |
| `trace_log.py` | Structured capability trace |
| `ollama_client.py` | Local Ollama integration |

---

# 3. Setup

## Prerequisites

- Python 3.10+
- Ollama
- Qwen3:8b

Install the model:

```bash
ollama pull qwen3:8b
```

Start Ollama:

```bash
ollama serve
```

The local API used by the project is:

```text
http://localhost:11434/api/chat
```

Create a Python environment:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Environment configuration is provided through:

```text
.env.example
```

A real `.env` file should not be committed.

---

# 4. How to Run

From the project directory:

### R1

```bash
python demo.py --cap R1
```

### R2

```bash
python demo.py --cap R2
```

### R3

```bash
python demo.py --cap R3
```

### R4

```bash
python demo.py --cap R4
```

R4 is demonstrated across a process boundary so that the preference is stored and then reloaded.

### R5

```bash
python demo.py --cap R5
```

### R6

```bash
python demo.py --cap R6
```

### Main workflow

```bash
python demo.py --all
```

### Custom capabilities

```bash
python demo.py --cap X1
python demo.py --cap X2
python demo.py --cap X3
```

---

# 5. Implementation Details

## R1 — Inbox Zeroing

The inbox is loaded from `inbox.json`.

For each message the classifier produces exactly one disposition:

```text
reply
archive
defer
delegate
escalate
```

The classification flow is:

```text
message
   |
   v
prompt-injection check
   |
   v
deterministic rules
   |
   +---- obvious --> decision
   |
   +---- requires reasoning --> Ollama
```

The system records a reason for every decision.

`decisions.json` stores the resulting decisions.

R1 also validates:

- all inbox messages were processed
- no duplicate IDs
- no missing IDs
- no extra IDs
- every decision has a reason
- every disposition is valid

### Verified R1 evidence

```text
Total messages:          100
Processed:               100
Unprocessed:               0
Duplicate message IDs:     0
Missing message IDs:       0
Extra message IDs:         0
Missing/empty reasons:     0
Invalid dispositions:      0
Rule handled:             96
LLM handled:                0
Injection/hostile handled:  4
Errors:                     0

R1 validation: PASS
```

---

## R2 — Grounded Retrieval

R2 demonstrates that a reply can use information from an earlier message in the same thread.

The implementation uses the retrieval functions in `mailbox.py`:

```text
by_id()
thread_messages()
earlier_in_thread()
```

Flow:

```text
target message
      |
      v
find thread
      |
      v
retrieve earlier messages
      |
      v
check for supporting fact
      |
      +---- evidence found --> grounded draft
      |
      +---- evidence missing --> no draft
```

Verified example:

```text
Target: m008
Supporting source: m003
Grounding: YES
```

Missing-information example:

```text
Target: m012
Supporting source: unavailable
Draft: none
```

The system records the source message ID used for grounding and does not invent missing information.

---

## R3 — Safety Gate

R3 separates proposing an action from executing it.

Actions are classified as:

```text
reversible
irreversible
unknown
```

The basic flow is:

```text
action proposal
      |
      v
action classification
      |
      +---- reversible ------> allowed proposal/display
      |
      +---- irreversible ---> human approval gate
      |
      +---- unknown ---------> reject
```

The gate in `gate.py` creates authorization for approved actions.

The outbox writer only accepts a valid gate authorization.

This prevents an arbitrary caller from bypassing the approval step.

The project demonstrates:

- approval
- rejection
- dry-run
- simulated execution failure
- gate-bypass rejection
- hostile/untrusted action rejection

Every gated decision is recorded in `trace.jsonl`.

### Send boundary

No real email is sent.

A successful simulated send writes a file under:

```text
outbox/
```

Example:

```text
outbox/m008-reply.txt
```

---

## R4 — Persistent Preferences

Preferences are stored in:

```text
prefs.json
```

The demonstrated preferences include:

```json
{
  "no_meetings_before": "11:00",
  "no_meetings_before_source": "m041",
  "cc_legal": "priya@paperjet.io",
  "cc_legal_source": "m015"
}
```

The implementation demonstrates:

```text
Process 1
   |
   v
store preference
   |
   v
process exits

Process 2
   |
   v
reload prefs.json
   |
   v
apply preference
```

The `cc_legal` preference affects messages including:

```text
m018
m048
m055
```

The meeting preference affects:

```text
m043
```

The trace records:

```text
pref_store
process_boundary
pref_reload
pref_apply
```

---

## R5 — Hostile Inbox / Prompt Injection

Email content is treated as **untrusted data**, not as system instructions.

Prompt-injection detection is implemented in:

```text
inject.py
```

Detected hostile messages are refused/escalated instead of being allowed to perform actions.

Verified hostile messages:

```text
m017
m024
m039
m047
```

Verified R5 result:

```text
Hostile messages detected: 4
Attempted hostile actions refused: 4
No hostile action was executed.
Hostile messages were not deleted.
Outbox unchanged by R5: yes
```

Representative refused actions included:

```text
delete
send
forward
```

The refusal is logged with the source message ID and attempted action.

---

## R6 — Dashboard

R6 generates:

```text
dashboard.json
dashboard.html
```

The dashboard has exactly three primary panes:

```text
1. Pending actions
2. Flagged
3. Commitments
```

Conflicts are surfaced inside the Commitments pane.

Verified dashboard counts:

```text
Pending:     25
Flagged:      7
Commitments:  4
Conflicts:   1
```

Example commitments:

```text
board deck due 16th
    sources: m038, m040

approve pricing page annual-discount copy by the 12th
    sources: m026, m027, m028, m029, m030, m033, m034, m035, m036

SAFE amendment signature via portal (clause 4) by Friday
    source: m018

candidate Jordan needs a read before the 19th
    source: m042
```

A multi-message commitment is therefore demonstrated using:

```text
m038 + m040
```

The detected conflict is:

```text
Wednesday 14:00 - Raghav 1:1 move vs Acme demo
sources: m013, m016
```

---

# 6. Traceability and Evidence

The project maintains:

```text
trace.jsonl
```

for structured audit evidence.

Capability runs are logged separately so rerunning one capability does not remove evidence from the other capabilities.

The final trace contains evidence for:

```text
R1
R2
R3
R4
R5
R6
X3
```

Verified final trace counts:

```text
R1 = 100
R2 = 4
R3 = 29
R4 = 8
R5 = 5
R6 = 14
X3 = 1
```

The trace is used to connect:

```text
source message
     |
     v
decision
     |
     v
action proposal
     |
     v
human response
     |
     v
execution result
```

This provides accountability if an action is later found to be incorrect.

---

# 7. Safety / Trust Boundary

The main security principle is:

> **Email content is untrusted and cannot directly authorize an irreversible action.**

Trusted system components include:

- application code
- local configuration
- gate authorization
- persistent preference store

Untrusted input includes:

- email body
- email subject
- quoted email content
- sender instructions
- prompt-injection text

Therefore:

```text
Untrusted email
      |
      v
analysis / classification
      |
      X
cannot directly execute tools
      |
      v
action proposal
      |
      v
human gate
      |
      v
authorized execution
      |
      v
outbox/
```

The system deliberately trades some automation for safety and accountability.

---

# 8. Custom Capabilities

Custom capabilities are documented in:

```text
CAPABILITIES.md
capabilities.json
```

The machine-readable manifest contains:

```text
id
name
tier
claim
command
observable
evidence
```

The project currently contains:

```text
R1
R2
R3
R4
R5
R6
X1
X2
X3
```

Each capability can be run independently:

```bash
python demo.py --cap <CAPABILITY_ID>
```

---

# 9. X3 Evidence Audit

The evidence-audit capability verifies important project relationships.

Verified output:

```text
Evidence audit
Decisions match inbox: YES
Dashboard citations valid: YES
R2 grounded evidence: YES
Trace capabilities present: R1, R2, R3, R4, R5, R6
```

---

# 10. Agentic AI Mapping

The project is implemented using plain Python, but its components map to common agentic concepts.

## Agent

The system contains separate responsibilities for:

- inbox classification
- retrieval/grounding
- safety gating
- preference management
- commitment/dashboard analysis

These are implemented as Python modules/functions rather than separate framework agents.

## Tasks

The tasks include:

```text
classify messages
retrieve context
draft grounded replies
propose actions
request approval
execute authorized local sends
persist preferences
extract commitments
detect conflicts
```

## Router

The classification logic acts as a lightweight router:

```text
message
   |
   +-- obvious --> rule handler
   |
   +-- hostile --> refusal/escalation
   |
   +-- contextual --> retrieval/drafting
   |
   +-- action --> safety gate
```

## Framework choice

Plain Python was selected instead of LangChain/CrewAI because:

- the assignment allows a framework-free implementation
- the input is local
- the execution environment is local
- deterministic rules are sufficient for many messages
- the safety boundary is easier to inspect
- the project remains small and reproducible

The goal is to demonstrate the underlying agentic behavior rather than add framework complexity.

---

# 11. Project Files and Generated Evidence

Important files:

```text
inbox.json          input messages
decisions.json      R1 decisions
r2_results.json     R2 grounding results
prefs.json          persistent preferences
dashboard.json      R6 machine-readable dashboard
dashboard.html      R6 dashboard
trace.jsonl         audit trail
outbox/             simulated sends
capabilities.json   capability manifest
CAPABILITIES.md     capability documentation
```

Source files:

```text
demo.py
caps.py
mailbox.py
classify.py
inject.py
gate.py
prefs.py
trace_log.py
ollama_client.py
```

---

# 12. Validation

Check Python syntax:

```powershell
Get-ChildItem -Filter *.py | ForEach-Object { python -m py_compile $_.FullName }
```

Check Git whitespace/errors:

```bash
git diff --check
```

Check current files:

```bash
git status --short
```

---

# 13. Final Submission Checklist

The final ZIP should be a runnable Python project and should contain the required README, manifest, source code, evidence, and outbox.

Recommended contents:

```text
README.md
CAPABILITIES.md
capabilities.json

demo.py
caps.py
mailbox.py
classify.py
inject.py
gate.py
prefs.py
trace_log.py
ollama_client.py

inbox.json
requirements.txt
.env.example
.gitignore

decisions.json
r2_results.json
prefs.json
dashboard.json
dashboard.html
trace.jsonl

outbox/
    .gitkeep
    m008-reply.txt
```

Do not include:

```text
.git/
.venv/
__pycache__/
.env
```

Do not include real credentials or real email credentials.

---

# 14. Final Evidence Summary

| Requirement | Evidence |
|---|---|
| R1 | 100/100 processed, zero missing/unprocessed, valid dispositions |
| R2 | `m008` grounded using `m003`; `m012` produces no unsupported draft |
| R3 | reversible/irreversible classification, human gate, approval/rejection, dry-run, bypass rejection |
| R4 | preference persisted and reloaded across process boundary |
| R5 | 4 hostile messages detected, 4 refused, 0 executed, outbox unchanged |
| R6 | 25 pending, 7 flagged, 4 commitments, 1 conflict, message citations |
| X3 | evidence audit confirms decisions, dashboard citations, R2 grounding and trace presence |

---

# 15. Conclusion

This project demonstrates a small, inspectable agentic inbox system using:

- deterministic reasoning where possible
- local LLM support
- grounded retrieval
- persistent state
- human-in-the-loop safety
- prompt-injection defense
- structured audit trails
- reproducible evidence

The central design principle is:

> **Reason over email, but never let email authorize the system.**
