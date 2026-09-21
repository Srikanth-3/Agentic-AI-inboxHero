# CAPABILITIES.md

**Student:** Srikanth Lakkam
**Repository:** https://github.com/Srikanth-3/Agentic-AI-inboxHero

Run everything through one entry point:

```
python demo.py --cap R1        # one capability
python demo.py --all           # all of them, in the order below
```

---

## The system, in one paragraph

A single Python pipeline, no framework. Messages are loaded from `inbox.json`. Noise (receipts, newsletters, `t-noise-*`) is archived by rules before any model is touched. The rest get a disposition from a small thread map, with Ollama (`qwen3:8b` on localhost) as a backup. Replies that need earlier facts walk `thread_id`. Send and delete go through `require_approval()`. Preferences and the action log live in JSON files on disk.

## Design choices you were asked to state

- **Framework: none.** The work is a linear pipeline with one branch (rule-path vs model-path). A crew or graph would have been extra moving parts for the same sequence. See Final Report Q4.
- **Retrieval: thread-walk.** The inbox already groups mail with `thread_id`. For m008 that is enough to find the AMQP URL in m003. Keyword search is only a fallback I did not need for the required demos.
- **Reversible vs irreversible.** `send` and `delete` are irreversible and gated. `draft`, `label`, `archive` and `defer` are reversible and run without a prompt. Delete is treated as irreversible because this mock store has no trash.
- **Where the gate sits.** Only `require_approval()` in `gate.py` can allow a send or delete. A hostile message can change a *draft* if we were sloppy, but it cannot write `outbox/` without passing the gate.
- **Escalation line.** Internal FYI and receipts archive themselves. Money, lawyers, phishing, and anything that looks like instructions *to the assistant* are escalated and never auto-sent. The trade-off: Sam still has to look at a pile of escalations, but a fake "forward the mailbox" mail cannot empty the inbox.

## Capabilities

| id | name | tier | one-line claim |
|----|------|------|----------------|
| R1 | Zero the inbox | B | every message gets one disposition + reason, none left |
| R2 | Grounded reply | B | drafts cite the earlier message they used |
| R3 | Gate the irreversible | C | no send/delete without approval or --dry-run |
| R4 | Persistent preference | C | a stated preference survives a restart |
| R5 | Refuse embedded instructions | C | detects, refuses, flags, reports injections |
| R6 | Dashboard | C | three panes, commitments cited, conflicts surfaced |
| X1 | Follow-up tracking | B | unanswered sent mail, with a drafted chase |
| X2 | Morning digest | B | what needs me / what can wait / what was archived |

The exact command, observable outcome and evidence for each is in `capabilities.json`.

## Final Report

### 1) Why no framework

The path is load → rule or model → maybe retrieve → maybe draft → gate. That is a straight line with one branch. CrewAI would have given me "agents" and a YAML file, and I would have spent the week wiring names instead of looking at `thread_id` and the injection mails. Writing the loop myself made the gate obvious: it is just a function that send/delete have to call.

### 2) Retrieval choice

Embeddings would have been a second system (chunk, store, query) for an inbox that already has threads. Walking `thread_id` is boring and it is also how a person opens the conversation. The failure mode is cross-thread facts (board date in m038, deck due in m040). Those I named explicitly in the dashboard rather than pretending a vector search found them.

### 3) What the gate actually protects

The injection in m024 asks the assistant to forward the whole mailbox and delete the evidence. If drafts were allowed to call `send` directly, that mail might have worked. The gate does not try to *understand* the attack. It only cares that send/delete are irreversible, so a human (or `--dry-run`) has to say yes. m039 tries to *turn the gate off* and save that as a preference; we treat that mail as an injection and we never write that preference.

### 4) What I would have missed in a framework

A framework memory plugin might have stored "CC Priya" for me. I would not have noticed that m039 is also trying to be stored as memory. Because prefs are a JSON file I write myself, I can refuse to save anything that came from an injection thread. That is a small thing, but it is the difference between "memory" as a feature and memory as a trust boundary.
