# PaperJet inbox assistant

Project for FN Assignment 06. One Python script, no LangChain / CrewAI.

The model is a **local Ollama** model (`qwen3:8b` by default). Nothing is sent to Gemini or to a company GitHub.

Repo (personal GitHub, not Cigna): https://github.com/Srikanth-3/Agentic-AI-inboxHero

## Setup

1. Install [Ollama](https://ollama.com) and pull a model:

```text
ollama pull qwen3:8b
ollama serve
```

2. Optional: set `OLLAMA_MODEL` if you pulled a different tag.

3. Python 3.10+ is enough. There are no pip packages. `inbox.json` sits next to `demo.py`.

```text
python demo.py --cap R1
python demo.py --all
```

`--all` runs R3 in dry-run so it does not stop for y/n. To see the prompt:

```text
python demo.py --cap R3
```

R4 is two runs on purpose:

```text
python demo.py --cap R4
python demo.py --cap R4
```

First run writes `prefs.json` and exits. Second run CCs Priya on the Hartwell & Cho mail.
The demonstrated preference is `cc_legal`, learned from `m015`; the second process reloads it from disk and applies it to later message `m018` (and the other Hartwell & Cho messages). R4 trace evidence uses `pref_store`, `process_boundary`, `pref_reload`, and `pref_apply` events.

## How it is put together

- Receipts and `t-noise-*` mail are archived by rules. The model is not called.
- Everything else is classified with a small thread map, then Ollama if that map misses.
- Replies that need facts walk the same `thread_id` (R2 uses m003 for m008).
- `send` / `delete` go through `require_approval()` in `gate.py`.
- R3 automatically inspects, classifies, and proposes actions. `send` and `delete` are irreversible and require per-action human approval or dry-run; unknown actions are rejected and escalated.
- Email content can inform a proposal but cannot directly execute an irreversible tool. Approved sends use a gate-issued authorization and write only to `outbox/`; rejected, dry-run, and failed actions are not silently treated as successful.
- Prefs live in `prefs.json` so they survive a restart.

## Files

| file | what it does |
|------|----------------|
| `demo.py` | CLI |
| `classify.py` | rules + optional Ollama |
| `caps.py` | R1–R6, X1, X2 |
| `gate.py` | irreversible actions |
| `prefs.py` | disk memory |
| `inject.py` | phrase checks for prompt injection |
| `ollama_client.py` | HTTP to localhost:11434 |
| `mailbox.py` | load inbox, walk threads |
| `trace_log.py` | `trace.jsonl` |

Generated when you run it: `decisions.json`, `prefs.json`, `dashboard.html`, `dashboard.json`, `trace.jsonl`, `outbox/`.

## R1 status: COMPLETE

R1 (Zero the inbox) has been implemented and verified against the real `inbox.json`.

### Verified behavior

Command run:

```text
cmd /c "python demo.py --cap R1"
```

Observed output summary:

```text
Total messages: 100
Processed: 100
Unprocessed: 0
Duplicate message IDs: 0
Missing message IDs: 0
Extra message IDs: 0
Missing/empty reasons: 0
Invalid dispositions: 0
Rule handled: 96
LLM handled: 0
Injection/hostile handled: 4
Errors: 0
R1 validation: PASS
```

### What this proves

- every message in `inbox.json` received exactly one disposition
- every decision had a non-empty reason
- the processed count matches the inbox size
- no message IDs were duplicated or lost
- rule-based handling and hostile/injection handling were tracked separately
- the result was written to `decisions.json` and logged in `trace.jsonl`

### Evidence files

- `decisions.json` stores the final disposition table
- `trace.jsonl` stores one audit event per message under the `R1` capability

### Important implementation note

The project keeps the existing classification architecture intact. The R1 improvement added validation and summary counting without changing the rule-vs-model logic or the later assignment requirements.
