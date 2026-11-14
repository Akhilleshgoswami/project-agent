# CLAUDE.md — Support Ticket Agent

## Project

Python package that triages support tickets with LangGraph + OpenAI structured output.

## Setup / run

Full guide: [`docs/SETUP_AND_RUN.md`](docs/SETUP_AND_RUN.md)

```bash
uv sync
cp .env.example .env   # set OPENAI_API_KEY
uv run pytest
uv run support-ticket-agent run --input data/tickets.csv
uv run support-ticket-agent eval --labels evals/labels.json
uv run support-ticket-agent run --dry-run
uv run support-ticket-agent run --dry-run --hitl --limit 5
uv run support-ticket-agent run --dry-run --supervision
uv run ruff check src tests
```

Requires `.env` with `OPENAI_API_KEY` for live LLM runs (see `.env.example`). Use `--dry-run` offline.

Review modes:
- `--supervision`: fully automatic — auto-approve safe drafts, else auto-escalate to human queue (no prompts)
- `--hitl`: interactive pause on every draft (`approve` / `edit` / `reject`)
- Policy-escalated tickets never get a send-ready draft

## Conventions

- Package code lives in `src/support_agent/`. CLI entrypoint: `support_ticket_agent:main`.
- Prefer Pydantic models in `schema.py` for anything that crosses LLM or file boundaries.
- Escalation policy is **code** in `rules.py`, not only prompt text — keep money/security/access there.
- Decision logs must explain *why* (classify → policy → draft/escalate).
- Do not commit `.env` or raw `outputs/*.jsonl` with customer data.
- Eval labels are hand-authored in `evals/labels.json`; primary metric is category accuracy.

## Architecture reminder

```text
CSV → LangGraph(classify → LLM guardrail → auto_approve|auto_escalate|HITL|finalize) → JSONL
```

Guardrail: `support_agent/guardrail.py` (`LLMGuardrail` live, `DryRunGuardrail` offline).

When changing prompts, re-run `eval` and note accuracy deltas in the README cost/eval section.

## Cursor / agent notes

- Time box: prefer clear choices over polish.
- If the API key is missing, unit tests for rules/cost/eval/io still must pass offline.
- Never auto-send drafts to customers in this prototype — draft text is an artifact only.
