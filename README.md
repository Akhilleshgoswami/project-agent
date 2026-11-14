# Support Ticket Agent

Take-home agent that reads support tickets, classifies them, assigns priority, drafts replies for simple questions, escalates uncertain/sensitive cases, logs decisions, and reports eval accuracy + rough cost.

**Full setup & run guide:** [`docs/SETUP_AND_RUN.md`](docs/SETUP_AND_RUN.md)

---

## Setup (short)

```bash
# Prerequisites: Python 3.15+, uv
cd support-ticket-agent
uv sync
cp .env.example .env
# Edit .env → set OPENAI_API_KEY (key must allow model calls)
```

Confirm env loads (key is masked):

```bash
uv run python -c "from support_agent.settings import get_settings; get_settings.cache_clear(); get_settings()"
```

---

## Run

```bash
# Offline (no API / no LLM spend)
uv run support-ticket-agent run --dry-run --supervision

# Live LLM + automatic supervisor (recommended; 4 threads by default)
uv run support-ticket-agent run --supervision
uv run support-ticket-agent run --supervision --workers 8

# Eval on 10 labeled tickets
uv run support-ticket-agent eval
uv run support-ticket-agent eval --dry-run --workers 4

# Interactive HITL (type a/e/r on drafts; always single-threaded)
uv run support-ticket-agent run --hitl --limit 5

# Tests
uv run pytest
```

Outputs: `outputs/results.jsonl`, `outputs/run_summary.json`, `outputs/eval_summary.json`.

---

## What it does

LangGraph pipeline per ticket:

1. **Classify** — LLM structured output → category, priority + reason, confidence, action, optional draft  
2. **LLM guardrail** — second LLM call → `allow_draft` or `escalate` (+ reasons / risk flags)  
3. **Supervision** (`--supervision`) — auto-approve safe high-confidence drafts; otherwise auto-escalate to a human queue (no typing)  
   or **HITL** (`--hitl`) — interactive approve / edit / reject  
4. **Finalize + log** — JSONL with full decision trail and token/cost usage  

Categories: `bug` | `billing` | `feature_request` | `question` | `other`  
Actions: `draft_reply` | `human_review`

---

## Choices

| Choice | Why |
| --- | --- |
| **LangGraph** | Explicit classify → guardrail → review → finalize; easy to demo/extend |
| **Structured output** | Reliable schema vs free-text parsing |
| **LLM guardrail** | Second model judges allow vs escalate with reasons/risk flags |
| **Hard confidence floor** | Escalate when triage confidence &lt; `CONFIDENCE_THRESHOLD` |
| **`--supervision`** | Humans don’t approve every ticket; only queued borderline/unsafe cases |
| **`--hitl`** | Optional interactive review for demos |
| **`gpt-4o-mini`** | Low cost for ~200 tickets/week |
| **Synthetic 30-ticket CSV** | No client CSV in repo; covers bugs, billing, features, questions, phishing, praise |
| **10-ticket hand labels** | Primary metric: category accuracy |

---

## Assumptions

- English tickets; subject + message only  
- “Simple question” = FAQ / docs-style answers — not refunds, access changes, or engineering fixes  
- Cost uses gpt-4o-mini list prices: **$0.15 / 1M input**, **$0.60 / 1M output**  
- No help-center RAG in this time box  

---

## Eval

Labels: [`evals/labels.json`](evals/labels.json).

**Dry-run heuristic** (offline smoke):

| Metric | Score |
| --- | --- |
| Category accuracy | **10/10 (100%)** |
| Priority accuracy | 9/10 (90%) |
| Action accuracy | **10/10 (100%)** |

Replace with live numbers from `outputs/eval_summary.json` after an LLM eval run.

---

## Cost (per 100 tickets)

```text
cost = prompt_tokens * 0.15/1e6 + completion_tokens * 0.60/1e6
per_100 = (run_cost / n_tickets) * 100
```

CLI prints estimated **$/100 tickets**. Expect roughly **$0.05–$0.25 / 100** with gpt-4o-mini (classify + guardrail). Dry-run is `$0`.

---

## Project layout

```text
data/tickets.csv
evals/labels.json
docs/SETUP_AND_RUN.md
src/support_agent/
  classifier.py      # triage LLM
  guardrail.py       # LLM allow/escalate guardrail
  supervision.py     # auto-approve vs auto-escalate
  hitl.py            # interactive approve/edit/reject
  graph.py           # LangGraph
  cli.py             # run / eval commands
outputs/             # run artifacts (gitignored)
CLAUDE.md
```

---

## Loom checklist (≤5 min)

1. Setup from `docs/SETUP_AND_RUN.md`  
2. Show graph in `graph.py` (classify → guardrail → supervision)  
3. Walk one ticket in `outputs/results.jsonl` (`decision_log`)  
4. Show eval scores + $/100 tickets  
5. What you’d do with more time (below)  

---

## With more time

- RAG over help docs for better drafts  
- Async human queue UI + feedback → eval regression  
- Tool use (billing lookup, status page)  
- Stronger multi-annotator eval and safety checks  

---

## Harness

See [`CLAUDE.md`](CLAUDE.md) for Cursor / Claude Code conventions.
# project-agent
