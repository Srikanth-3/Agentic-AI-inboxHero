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

## How it is put together

- Receipts and `t-noise-*` mail are archived by rules. The model is not called.
- Everything else is classified with a small thread map, then Ollama if that map misses.
- Replies that need facts walk the same `thread_id` (R2 uses m003 for m008).
- `send` / `delete` go through `require_approval()` in `gate.py`.
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
