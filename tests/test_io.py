from pathlib import Path

from support_agent.io import load_labels, load_tickets


def test_load_tickets():
    tickets = load_tickets(Path("data/tickets.csv"))
    assert len(tickets) == 30
    assert tickets[0].ticket_id == "T001"
    assert tickets[0].subject
    assert tickets[0].message


def test_load_labels():
    labels = load_labels(Path("evals/labels.json"))
    assert len(labels) == 10
    assert {row["ticket_id"] for row in labels} <= {f"T{i:03d}" for i in range(1, 31)}
