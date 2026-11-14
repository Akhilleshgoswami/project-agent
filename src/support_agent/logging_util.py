"""JSONL decision logging for triage runs."""

from __future__ import annotations

import json
from pathlib import Path

from support_agent.schema import TicketResult


def ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, result: TicketResult) -> None:
    ensure_output_dir(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")


def write_summary(path: Path, summary: dict) -> None:
    ensure_output_dir(path)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def clear_jsonl(path: Path) -> None:
    ensure_output_dir(path)
    path.write_text("", encoding="utf-8")


def write_thread_index(path: Path, results: list[TicketResult], *, run_id: str) -> None:
    """Write a lookup table: thread_id → ticket summary for later reference."""
    ensure_output_dir(path)
    index = {
        "run_id": run_id,
        "threads": [
            {
                "thread_id": r.thread_id,
                "ticket_id": r.ticket_id,
                "subject": r.subject,
                "category": r.category.value,
                "suggested_action": r.suggested_action.value,
                "confidence": r.confidence,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")
