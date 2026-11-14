"""Thread / run id helpers for referring to chats later."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

_THREAD_RE = re.compile(r"^ticket-(.+)-run-([a-f0-9]+)$", re.IGNORECASE)


def new_run_id() -> str:
    """One id per CLI batch (shared across tickets in that run)."""
    return uuid.uuid4().hex[:12]


def make_thread_id(ticket_id: str, run_id: str) -> str:
    """Stable per-ticket chat id within a run: ticket-<id>-run-<run_id>."""
    safe_ticket = ticket_id.strip().replace(" ", "-")
    return f"ticket-{safe_ticket}-run-{run_id}"


def parse_thread_id(thread_id: str) -> tuple[str, str]:
    """Return (ticket_id, run_id) from a thread id."""
    match = _THREAD_RE.match(thread_id.strip())
    if not match:
        raise ValueError(
            f"Invalid thread_id {thread_id!r}. Expected ticket-<TICKET_ID>-run-<RUN_ID>"
        )
    return match.group(1), match.group(2)


def load_thread_index(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Thread index not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_in_results_jsonl(results_path: Path, thread_id: str) -> dict | None:
    """Load the saved result object for a thread_id from results.jsonl."""
    if not results_path.exists():
        return None
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("thread_id") == thread_id:
                return row
    return None
