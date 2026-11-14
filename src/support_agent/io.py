"""CSV / label loading helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from support_agent.schema import TicketInput


def load_tickets(csv_path: Path | str) -> list[TicketInput]:
    path = Path(csv_path)
    df = pd.read_csv(path)
    required = {"ticket_id", "subject", "message"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")

    tickets: list[TicketInput] = []
    for row in df.itertuples(index=False):
        tickets.append(
            TicketInput(
                ticket_id=str(row.ticket_id).strip(),
                subject=str(row.subject).strip(),
                message=str(row.message).strip(),
            )
        )
    return tickets


def load_labels(path: Path | str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("labels file must be a JSON array")
    return data
