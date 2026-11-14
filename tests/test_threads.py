from pathlib import Path

from support_agent.cli import _run_batch
from support_agent.dry_run import DryRunClassifier
from support_agent.guardrail import DryRunGuardrail
from support_agent.io import load_tickets
from support_agent.schema import ReviewMode
from support_agent.settings import Settings
from support_agent.threads import make_thread_id


def test_threaded_batch_preserves_order_and_thread_ids(tmp_path: Path):
    tickets = load_tickets("data/tickets.csv")[:8]
    settings = Settings(openai_api_key="", confidence_threshold=0.75)
    results_path = tmp_path / "results.jsonl"

    results, _usage, _run_id = _run_batch(
        tickets,
        settings,
        DryRunClassifier(),
        DryRunGuardrail(settings),
        results_path,
        review_mode=ReviewMode.SUPERVISION,
        workers=4,
        run_id="testrun01",
    )

    assert len(results) == 8
    assert [r.ticket_id for r in results] == [t.ticket_id for t in tickets]
    assert all(r.run_id == "testrun01" for r in results)
    assert results[0].thread_id == make_thread_id(tickets[0].ticket_id, "testrun01")
    assert results_path.exists()
    lines = results_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 8


def test_make_thread_id_format():
    assert make_thread_id("T004", "abc123") == "ticket-T004-run-abc123"
