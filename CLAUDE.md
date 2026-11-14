# CLAUDE.md — Support Ticket Agent

Guidance for Claude Code / Cursor when working in this repo.

## What this project is

A take-home **support ticket triage agent**:

- Reads tickets from CSV (`subject` + `message`)
- Classifies: `bug` | `billing` | `feature_request` | `question` | `other`
- Assigns priority + short reason
- Drafts replies only for safe/simple questions (and praise)
- Escalates anything uncertain or sensitive
- Logs decisions + rough LLM cost
- Ships a 10-ticket hand-labeled eval

Human operators should only handle escalated / auto-escalated tickets — not every draft.

Full human setup guide: [`docs/SETUP_AND_RUN.md`](docs/SETUP_AND_RUN.md)  
Design notes / deliverable narrative: [`README.md`](README.md)

---

## Stack

| Piece | Choice |
| --- | --- |
| Runtime | Python 3.15+, `uv` |
| Orchestration | LangGraph |
| LLM | OpenAI `gpt-4o-mini` via LangChain structured output |
| Config | `.env` + `pydantic-settings` |
| Package | `src/support_agent/` |
| CLI | `support-ticket-agent` → `support_agent.cli:main` |

---

## Architecture (do not flatten into one mega-prompt)

```text
CSV
  → classify (LLM structured TicketAnalysis)
  → guardrail (LLM allow_draft | escalate + risk flags)
  → review gate
        ├─ --supervision: auto_approve | auto_escalate  (no keyboard)
        ├─ --hitl: interrupt → approve | edit | reject
        └─ off: keep guardrail outcome
  → finalize + JSONL log (thread_id, decision_log, usage)
```

Each ticket chat gets:

```text
thread_id = ticket-<TICKET_ID>-run-<RUN_ID>
```

Saved in `outputs/results.jsonl` and `outputs/threads.json` for later lookup.

---

## Commands (use these)

```bash
# Setup
uv sync
cp .env.example .env          # set OPENAI_API_KEY with model.request access

# Offline (no LLM) — prefer for quick tests
uv run support-ticket-agent run --dry-run --supervision
uv run support-ticket-agent eval --dry-run

# Live LLM
uv run support-ticket-agent run --supervision
uv run support-ticket-agent run --supervision --workers 8
uv run support-ticket-agent eval

# Interactive HITL (single-threaded)
uv run support-ticket-agent run --hitl --limit 5

# Thread lookup / re-run
uv run support-ticket-agent show --thread-id ticket-T004-run-<RUN_ID>
uv run support-ticket-agent rerun --thread-id ticket-T004-run-<RUN_ID> --dry-run --supervision
uv run support-ticket-agent run --thread-id ticket-T004-run-<RUN_ID> --dry-run --supervision

# Quality
uv run pytest
uv run ruff check src tests
```

**Never combine** `--hitl` and `--supervision`.

---

## Review modes

| Mode | Behavior |
| --- | --- |
| *(default)* | Classify + guardrail only |
| `--supervision` | Automatic: high-confidence safe drafts → `auto_approve`; else → `auto_escalate` to human queue. **No prompts.** |
| `--hitl` | Pause on every remaining draft for `a` / `e` / `r`. Forces `--workers 1`. |
| `--dry-run` | Heuristic classifier + heuristic guardrail (no OpenAI) |

Thresholds (`.env`):

- `CONFIDENCE_THRESHOLD` (default 0.75) — below → escalate
- `AUTO_APPROVE_THRESHOLD` (default 0.90) — supervision auto-approve floor

---

## Key files

```text
src/support_agent/
  schema.py         # Pydantic models / enums — source of truth for I/O shapes
  prompts.py        # CLASSIFICATION_PROMPT + GUARDRAIL_PROMPT
  classifier.py     # LLM triage
  guardrail.py      # LLMGuardrail + DryRunGuardrail + apply_guardrail_verdict
  rules.py          # Deterministic heuristics (used by DryRunGuardrail)
  supervision.py    # needs_human_supervision()
  hitl.py           # apply_human_decision + interactive prompt
  graph.py          # LangGraph nodes + process_ticket(thread_id=...)
  threads.py        # run_id / thread_id helpers + lookup
  cli.py            # run | eval | show | rerun
  dry_run.py        # Offline classifier
  cost.py / eval.py / io.py / logging_util.py / settings.py

data/tickets.csv           # 30 synthetic tickets
evals/labels.json          # 10 hand labels (primary metric: category)
outputs/                   # results.jsonl, threads.json, summaries (gitignored)
docs/SETUP_AND_RUN.md
```

---

## Coding conventions

1. **Structured I/O only** — anything crossing LLM or JSONL boundaries uses models in `schema.py`.
2. **Keep the graph stages separate** — do not merge classify + guardrail into one prompt without a strong reason; the dual-call is intentional for the take-home story.
3. **Safety over recall** — when unsure, escalate. Money / phishing / legal / ownership / cancellations must not become send-ready drafts.
4. **Drafts are artifacts, not sends** — this prototype never emails customers.
5. **Decision logs must explain why** — every path should leave `classify` → `guardrail` → (`supervision`|`hitl`) → `finalize` breadcrumbs.
6. **Thread ids on every result** — `thread_id` + `run_id` required on `TicketResult`.
7. **Offline tests must pass without an API key** — use `DryRunClassifier` / `DryRunGuardrail` in unit tests.
8. **Do not commit secrets** — `.env` is gitignored; never print full API keys (mask if logging).
9. **CLI via `uv run support-ticket-agent …`** from repo root after `uv sync`.
10. After prompt / guardrail changes, run `eval` (dry-run at minimum) and update README eval/cost notes if numbers change.

---

## Safety / product rules (always)

Escalate (no send-ready auto-reply) when involving:

- Refunds, duplicate charges, billing disputes
- Phishing / credentials / security
- Legal / compliance
- Account lock, ownership transfer, subscription cancellation that changes state
- Bugs / outages needing engineering
- Feature requests (acknowledge via human queue, don’t invent roadmap promises)
- Low confidence or empty/unsafe drafts

Allow drafts only for clear FAQ-style **questions** (and pure praise).

---

## Outputs to know

| File | Purpose |
| --- | --- |
| `outputs/results.jsonl` | Full per-ticket result + `decision_log` + usage |
| `outputs/threads.json` | `thread_id` → ticket lookup |
| `outputs/run_summary.json` | Counts, workers, `$ / 100 tickets` |
| `outputs/eval_summary.json` | Category / priority / action accuracy |

---

## Common pitfalls

| Symptom | Likely cause |
| --- | --- |
| Tokens always `0` | You passed `--dry-run` |
| `401 Missing scopes: model.request` | API key lacks model permission — not an env-load bug |
| Settings look empty | Use project-root `.env`; `settings.py` resolves path from package location |
| HITL + threads broken UX | `--hitl` must stay single-worker |
| `ModuleNotFoundError` | Run with `uv run` from repo root after `uv sync` |

---

## How to change things safely

| Goal | Touch |
| --- | --- |
| Better classification | `prompts.py` (`CLASSIFICATION_PROMPT`) + re-eval |
| Stricter allow/deny | `prompts.py` (`GUARDRAIL_PROMPT`) and/or `guardrail.py` |
| Supervision aggressiveness | `AUTO_APPROVE_THRESHOLD` / `supervision.py` |
| Offline behavior | `dry_run.py` + `DryRunGuardrail` |
| New CLI behavior | `cli.py` + tests under `tests/` |
| Cost formula | `settings.py` prices + `cost.py` |

---

## Agent working style for this take-home

- Prefer **clear choices** over polish; keep the 4-hour spirit.
- Prefer extending the LangGraph path over bolting on unrelated frameworks.
- Add/adjust **unit tests** for rules, supervision, threads, eval — no live API required.
- Keep README / SETUP docs in sync when CLI flags or pipeline stages change.
