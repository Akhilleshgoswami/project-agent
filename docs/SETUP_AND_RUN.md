# Setup and run — Support Ticket Agent

Step-by-step guide to install dependencies, configure the API key, and run triage / eval / tests.

## Prerequisites

- **Python 3.15+** (see `.python-version`)
- **[uv](https://docs.astral.sh/uv/)** package manager
- An **OpenAI API key** with permission to call models (`model.request` / unrestricted key)  
  — optional if you only use `--dry-run`

Check tools:

```bash
python3 --version   # should be 3.15.x (or compatible)
uv --version
```

Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/

---

## 1. Clone / open the project

```bash
cd support-ticket-agent
```

---

## 2. Create the virtualenv and install packages

```bash
uv sync
```

This creates `.venv`, installs runtime deps (LangChain, LangGraph, OpenAI, pandas, …) and dev deps (pytest, ruff).

Verify the CLI is available:

```bash
uv run support-ticket-agent --help
```

---

## 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=sk-your-real-key-here
MODEL_NAME=gpt-4o-mini
CONFIDENCE_THRESHOLD=0.75
AUTO_APPROVE_THRESHOLD=0.90
```

| Variable | Meaning |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI key (must allow chat/completions) |
| `MODEL_NAME` | Default `gpt-4o-mini` |
| `CONFIDENCE_THRESHOLD` | Below this → escalate (no auto-reply) |
| `AUTO_APPROVE_THRESHOLD` | Under `--supervision`, drafts at/above this can auto-approve |

Confirm settings load (key is masked in the log):

```bash
uv run python -c "from support_agent.settings import get_settings; get_settings.cache_clear(); get_settings()"
```

You should see `OPENAI_API_KEY: sk-... (len=...)` and `exists=True` for the `.env` path.

> **401 `Missing scopes: model.request`:** the key loaded, but OpenAI rejects it. Create a new key with model access (or an unrestricted project key) and update `.env`.

---

## 4. Run the agent

Input data ships in the repo: [`data/tickets.csv`](../data/tickets.csv) (30 tickets).

### A) Offline dry-run (no LLM / no API spend)

Same pipeline (classify → guardrail → supervision), heuristics only:

```bash
uv run support-ticket-agent run --dry-run
uv run support-ticket-agent run --dry-run --supervision
uv run support-ticket-agent run --dry-run --limit 5
```

### B) Live LLM run (uses OpenAI)

```bash
# Process all tickets (4 worker threads by default)
uv run support-ticket-agent run --input data/tickets.csv

# Recommended: automatic supervisor (no keyboard prompts)
uv run support-ticket-agent run --supervision

# Tune parallelism
uv run support-ticket-agent run --supervision --workers 8

# Small smoke
uv run support-ticket-agent run --supervision --limit 3
```

Tickets are processed in a **thread pool** (`--workers`, default `4`) so classify + guardrail LLM calls overlap. `--hitl` forces `--workers 1` because prompts are interactive.

### C) Interactive human-in-the-loop

Pauses on every remaining draft; type `a` / `e` / `r`:

```bash
uv run support-ticket-agent run --hitl --limit 5
# or offline:
uv run support-ticket-agent run --dry-run --hitl --limit 5
```

Do **not** combine `--hitl` and `--supervision`.

### What each mode does

| Flag | Behavior |
| --- | --- |
| *(none)* | Classify + LLM guardrail; drafts kept as-is (no supervisor) |
| `--supervision` | Auto-approve safe high-confidence drafts; else auto-escalate to human queue |
| `--hitl` | Interactive approve / edit / reject on drafts |
| `--dry-run` | No OpenAI calls (heuristic classifier + guardrail) |

---

## 5. Run the eval set

10 hand-labeled tickets in [`evals/labels.json`](../evals/labels.json).

```bash
# Live LLM
uv run support-ticket-agent eval --labels evals/labels.json

# Offline
uv run support-ticket-agent eval --dry-run
```

Prints category / priority / action accuracy and writes `outputs/eval_summary.json`.

---

## 6. Outputs

After `run` or `eval`, check:

```text
outputs/
  results.jsonl        # one JSON object per ticket (thread_id, decision_log, usage, …)
  threads.json         # lookup table: thread_id → ticket_id / subject / action
  run_summary.json     # counts + estimated $/100 tickets + run_id
  eval_results.jsonl
  eval_threads.json
  eval_summary.json    # accuracy metrics
```

Each ticket chat gets a **thread_id** like `ticket-T004-run-a1b2c3d4e5f6` (shared `run_id` for the batch). Use it to refer to that conversation later in logs or `threads.json`.

### Show / re-run a particular thread

```bash
# 1) List thread ids
python -m json.tool outputs/threads.json

# 2) Show the full saved result for one thread
uv run support-ticket-agent show --thread-id ticket-T004-run-f7370974f598

# 3) Re-run that ticket (creates a NEW thread_id; appends to results.jsonl)
uv run support-ticket-agent rerun --thread-id ticket-T004-run-f7370974f598 --dry-run --supervision

# 4) Or run only that ticket from CSV using the thread_id filter
uv run support-ticket-agent run --thread-id ticket-T004-run-f7370974f598 --dry-run --supervision
```

Inspect one ticket / find a thread:

```bash
head -n 1 outputs/results.jsonl | python -m json.tool
python -m json.tool outputs/threads.json
```

Look for `decision_log` steps: `classify` → `guardrail` → `supervision` / `hitl` → `finalize`.

---

## 7. Tests and lint

```bash
uv run pytest
uv run ruff check src tests
```

---

## 8. Common commands cheat sheet

```bash
# Setup
uv sync
cp .env.example .env   # then edit OPENAI_API_KEY

# Offline demo
uv run support-ticket-agent run --dry-run --supervision

# Live demo
uv run support-ticket-agent run --supervision

# Eval + cost
uv run support-ticket-agent eval

# Quality
uv run pytest
```

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `OPENAI_API_KEY` empty / `(empty)` in settings log | Ensure `.env` is in the project root; re-run after editing; avoid quotes unless needed |
| `401 Missing scopes: model.request` | Key lacks model permission — new unrestricted / model-enabled key |
| `ModuleNotFoundError: support_agent` | Run via `uv run …` from project root after `uv sync` |
| Env log prints every time | Expected while debugging; `get_settings()` logs masked settings once per process |

---

## Pipeline reminder

```text
CSV → classify (LLM) → guardrail (LLM) → supervision | HITL | finalize → outputs/*.jsonl
```

See the main [README](../README.md) for design choices, eval numbers, and cost notes.
