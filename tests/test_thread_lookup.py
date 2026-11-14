import json
from pathlib import Path

from support_agent.threads import find_in_results_jsonl, parse_thread_id


def test_parse_thread_id():
    ticket_id, run_id = parse_thread_id("ticket-T004-run-f7370974f598")
    assert ticket_id == "T004"
    assert run_id == "f7370974f598"


def test_find_in_results_jsonl(tmp_path: Path):
    path = tmp_path / "results.jsonl"
    path.write_text(
        json.dumps({"thread_id": "ticket-T001-run-abc", "ticket_id": "T001"})
        + "\n"
        + json.dumps({"thread_id": "ticket-T004-run-abc", "ticket_id": "T004"})
        + "\n",
        encoding="utf-8",
    )
    row = find_in_results_jsonl(path, "ticket-T004-run-abc")
    assert row is not None
    assert row["ticket_id"] == "T004"
    assert find_in_results_jsonl(path, "missing") is None
