"""CLI: run triage over a CSV, or evaluate against hand labels."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from support_agent.classifier import TicketClassifier
from support_agent.cost import cost_per_100_tickets, merge_usage
from support_agent.dry_run import DryRunClassifier
from support_agent.eval import score_results
from support_agent.graph import process_ticket
from support_agent.guardrail import DryRunGuardrail, LLMGuardrail
from support_agent.io import load_labels, load_tickets
from support_agent.logging_util import (
    append_jsonl,
    clear_jsonl,
    write_summary,
    write_thread_index,
)
from support_agent.schema import (
    HumanDecisionAction,
    ReviewMode,
    TicketResult,
    UsageStats,
)
from support_agent.settings import get_settings
from support_agent.threads import (
    find_in_results_jsonl,
    load_thread_index,
    make_thread_id,
    new_run_id,
    parse_thread_id,
)


def _make_classifier(dry_run: bool):
    if dry_run:
        print("Using dry-run heuristic classifier (no LLM calls).")
        return DryRunClassifier()
    return TicketClassifier(get_settings())


def _make_guardrail(dry_run: bool):
    if dry_run:
        print("Using dry-run heuristic guardrail (LLM guardrail skipped).")
        return DryRunGuardrail(get_settings())
    print("Using LLM guardrail for allow/escalate decisions.")
    return LLMGuardrail(get_settings())


def _resolve_review_mode(args: argparse.Namespace) -> ReviewMode:
    if getattr(args, "supervision", False) and getattr(args, "hitl", False):
        raise ValueError("Use either --supervision or --hitl, not both")
    if getattr(args, "supervision", False):
        return ReviewMode.SUPERVISION
    if getattr(args, "hitl", False):
        return ReviewMode.HITL
    return ReviewMode.OFF


def _format_result_line(result: TicketResult) -> str:
    action = result.suggested_action.value
    hitl_bit = ""
    if result.human_decision:
        hitl_bit = (
            f" | review={result.human_decision.action.value}"
            f"({result.human_decision.source})"
        )
    return (
        f"    → thread={result.thread_id} | {result.category.value} | "
        f"{result.priority.value} | {action} | conf={result.confidence:.2f}{hitl_bit}"
    )


def _process_one(
    ticket,
    settings,
    classifier,
    guardrail,
    review_mode: ReviewMode,
    *,
    run_id: str,
):
    thread_id = make_thread_id(ticket.ticket_id, run_id)
    return process_ticket(
        ticket,
        settings=settings,
        classifier=classifier,
        guardrail=guardrail,
        review_mode=review_mode,
        run_id=run_id,
        thread_id=thread_id,
    )


def _run_batch(
    tickets,
    settings,
    classifier,
    guardrail,
    results_path: Path,
    *,
    review_mode: ReviewMode = ReviewMode.OFF,
    workers: int = 4,
    run_id: str | None = None,
):
    clear_jsonl(results_path)
    total = len(tickets)
    run_id = run_id or new_run_id()
    print(f"Run id: {run_id}")
    print("Each ticket gets thread_id = ticket-<id>-run-<run_id> (saved for later lookup).\n")

    if review_mode == ReviewMode.HITL:
        print("HITL: every draft reply pauses for approve / edit / reject.\n")
        workers = 1
    elif review_mode == ReviewMode.SUPERVISION:
        print(
            "Supervision (automatic): auto-approves safe high-confidence drafts; "
            f"otherwise queues for humans when confidence < {settings.auto_approve_threshold:.2f} "
            "or priority is high/critical. No keyboard prompts.\n"
        )

    workers = max(1, workers)
    if workers > 1:
        print(f"Processing {total} tickets with {workers} threads.\n")
    else:
        print(f"Processing {total} tickets sequentially.\n")

    results: list[TicketResult | None] = [None] * total
    total_usage = UsageStats()
    write_lock = threading.Lock()
    print_lock = threading.Lock()

    def _handle(index: int, ticket) -> TicketResult:
        thread_id = make_thread_id(ticket.ticket_id, run_id)
        with print_lock:
            print(
                f"[{index + 1}/{total}] start {ticket.ticket_id} "
                f"(thread={thread_id}): {ticket.subject[:50]}..."
            )
        result = _process_one(
            ticket,
            settings,
            classifier,
            guardrail,
            review_mode,
            run_id=run_id,
        )
        with write_lock:
            append_jsonl(results_path, result)
        with print_lock:
            print(f"[{index + 1}/{total}] done  {ticket.ticket_id}")
            print(_format_result_line(result))
        return result

    if workers == 1:
        for i, ticket in enumerate(tickets):
            results[i] = _handle(i, ticket)
            total_usage = merge_usage(total_usage, results[i].usage)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_handle, i, ticket): i for i, ticket in enumerate(tickets)
            }
            for future in as_completed(futures):
                i = futures[future]
                result = future.result()
                results[i] = result
                total_usage = merge_usage(total_usage, result.usage)

    ordered = [r for r in results if r is not None]
    return ordered, total_usage, run_id


def _count_decisions(results, action: HumanDecisionAction) -> int:
    return sum(
        1 for r in results if r.human_decision and r.human_decision.action == action
    )


def cmd_show(args: argparse.Namespace) -> int:
    """Print a saved thread by thread_id."""
    out_dir = Path(args.output_dir)
    results_path = Path(args.results) if args.results else out_dir / "results.jsonl"
    threads_path = Path(args.threads) if args.threads else out_dir / "threads.json"
    thread_id = args.thread_id.strip()

    row = find_in_results_jsonl(results_path, thread_id)
    if row is None and threads_path.exists():
        index = load_thread_index(threads_path)
        summary = next(
            (t for t in index.get("threads", []) if t.get("thread_id") == thread_id),
            None,
        )
        if summary is None:
            raise FileNotFoundError(
                f"No saved result for thread_id={thread_id} in {results_path} or {threads_path}"
            )
        print(json.dumps(summary, indent=2))
        print(
            f"\n(Full decision log not found in {results_path}; "
            "re-run that ticket with: support-ticket-agent rerun --thread-id ...)"
        )
        return 0

    if row is None:
        raise FileNotFoundError(
            f"No saved result for thread_id={thread_id}. Looked in {results_path}"
        )

    print(json.dumps(row, indent=2))
    return 0


def cmd_rerun(args: argparse.Namespace) -> int:
    """Re-process the ticket belonging to a thread_id (creates a new thread_id)."""
    settings = get_settings()
    thread_id = args.thread_id.strip()
    ticket_id, _old_run = parse_thread_id(thread_id)

    all_tickets = load_tickets(args.input)
    tickets = [t for t in all_tickets if t.ticket_id == ticket_id]
    if not tickets:
        raise ValueError(f"Ticket {ticket_id} from thread_id not found in {args.input}")

    out_dir = Path(args.output_dir)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "rerun_summary.json"
    threads_path = out_dir / "threads.json"

    review_mode = _resolve_review_mode(args)
    classifier = _make_classifier(args.dry_run)
    guardrail = _make_guardrail(args.dry_run)

    print(f"Re-running ticket {ticket_id} from thread {thread_id}")
    print("(A new run_id / thread_id will be created for this chat.)\n")

    run_id = new_run_id()
    new_thread = make_thread_id(ticket_id, run_id)
    result = process_ticket(
        tickets[0],
        settings=settings,
        classifier=classifier,
        guardrail=guardrail,
        review_mode=review_mode,
        run_id=run_id,
        thread_id=new_thread,
    )
    append_jsonl(results_path, result)

    existing: list[dict] = []
    if threads_path.exists():
        try:
            existing = load_thread_index(threads_path).get("threads", [])
        except (json.JSONDecodeError, FileNotFoundError, TypeError):
            existing = []
    merged = {
        "run_id": run_id,
        "threads": [
            *[t for t in existing if t.get("thread_id") != result.thread_id],
            {
                "thread_id": result.thread_id,
                "ticket_id": result.ticket_id,
                "subject": result.subject,
                "category": result.category.value,
                "suggested_action": result.suggested_action.value,
                "confidence": result.confidence,
                "rerun_of": thread_id,
            },
        ],
    }
    threads_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")

    summary = {
        "rerun_of": thread_id,
        "run_id": run_id,
        "thread_id": result.thread_id,
        "ticket_id": result.ticket_id,
        "suggested_action": result.suggested_action.value,
        "category": result.category.value,
        "usage": result.usage.model_dump(),
    }
    write_summary(summary_path, summary)

    print(_format_result_line(result))
    print(f"\nNew thread_id: {result.thread_id}")
    print(f"Appended to {results_path}")
    print(f"Updated {threads_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    tickets = load_tickets(args.input)
    if getattr(args, "thread_id", None):
        ticket_id, _ = parse_thread_id(args.thread_id.strip())
        tickets = [t for t in tickets if t.ticket_id == ticket_id]
        if not tickets:
            raise ValueError(
                f"No ticket {ticket_id} for thread_id={args.thread_id} in {args.input}"
            )
        print(f"Filtering to ticket {ticket_id} from --thread-id\n")
    if args.limit is not None:
        tickets = tickets[: args.limit]

    out_dir = Path(args.output_dir)
    results_path = out_dir / "results.jsonl"
    summary_path = out_dir / "run_summary.json"

    review_mode = _resolve_review_mode(args)
    workers = 1 if review_mode == ReviewMode.HITL else args.workers
    classifier = _make_classifier(args.dry_run)
    guardrail = _make_guardrail(args.dry_run)
    threads_path = out_dir / "threads.json"
    results, total_usage, run_id = _run_batch(
        tickets,
        settings,
        classifier,
        guardrail,
        results_path,
        review_mode=review_mode,
        workers=workers,
    )
    write_thread_index(threads_path, results, run_id=run_id)

    per_100 = cost_per_100_tickets(total_usage.estimated_cost_usd, len(results))
    summary = {
        "ticket_count": len(results),
        "run_id": run_id,
        "draft_reply_count": sum(
            1 for r in results if r.suggested_action.value == "draft_reply"
        ),
        "human_review_count": sum(
            1 for r in results if r.suggested_action.value == "human_review"
        ),
        "review_mode": review_mode.value,
        "workers": workers,
        "hitl_approved": _count_decisions(results, HumanDecisionAction.APPROVE),
        "hitl_edited": _count_decisions(results, HumanDecisionAction.EDIT),
        "hitl_rejected": _count_decisions(results, HumanDecisionAction.REJECT),
        "auto_approved": _count_decisions(results, HumanDecisionAction.AUTO_APPROVE),
        "auto_escalated": _count_decisions(results, HumanDecisionAction.AUTO_ESCALATE),
        "usage": total_usage.model_dump(),
        "estimated_cost_per_100_tickets_usd": round(per_100, 4),
        "model": "dry-run-heuristic" if args.dry_run else settings.model_name,
        "dry_run": args.dry_run,
        "confidence_threshold": settings.confidence_threshold,
        "auto_approve_threshold": settings.auto_approve_threshold,
        "results_path": str(results_path),
        "threads_path": str(threads_path),
    }
    write_summary(summary_path, summary)

    print("\n=== Run summary ===")
    print(f"Run id: {run_id}")
    print(f"Tickets: {summary['ticket_count']}")
    print(f"Workers: {workers}")
    print(f"Draft replies: {summary['draft_reply_count']}")
    print(f"Human review: {summary['human_review_count']}")
    print(f"Review mode: {review_mode.value}")
    if review_mode == ReviewMode.SUPERVISION:
        print(
            f"Supervisor auto-approved / auto-escalated: "
            f"{summary['auto_approved']} / {summary['auto_escalated']}"
        )
    elif review_mode == ReviewMode.HITL:
        print(
            f"Human approve/edit/reject: "
            f"{summary['hitl_approved']}/{summary['hitl_edited']}/{summary['hitl_rejected']}"
        )
    print(
        f"Tokens: {total_usage.total_tokens} "
        f"(prompt={total_usage.prompt_tokens}, completion={total_usage.completion_tokens})"
    )
    print(f"Estimated cost (this run): ${total_usage.estimated_cost_usd:.4f}")
    print(f"Estimated cost per 100 tickets: ${per_100:.4f}")
    print(f"Wrote {results_path}")
    print(f"Wrote {threads_path}  (thread_id lookup)")
    print(f"Wrote {summary_path}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    settings = get_settings()
    labels = load_labels(args.labels)
    label_ids = {row["ticket_id"] for row in labels}
    all_tickets = load_tickets(args.input)
    tickets = [t for t in all_tickets if t.ticket_id in label_ids]

    out_dir = Path(args.output_dir)
    results_path = out_dir / "eval_results.jsonl"
    summary_path = out_dir / "eval_summary.json"
    threads_path = out_dir / "eval_threads.json"

    classifier = _make_classifier(args.dry_run)
    guardrail = _make_guardrail(args.dry_run)
    results, total_usage, run_id = _run_batch(
        tickets,
        settings,
        classifier,
        guardrail,
        results_path,
        review_mode=ReviewMode.OFF,
        workers=args.workers,
    )
    write_thread_index(threads_path, results, run_id=run_id)
    scores = score_results(results, labels)
    per_100 = cost_per_100_tickets(total_usage.estimated_cost_usd, len(results))

    summary = {
        **scores.as_dict(),
        "run_id": run_id,
        "workers": args.workers,
        "usage": total_usage.model_dump(),
        "estimated_cost_per_100_tickets_usd": round(per_100, 4),
        "model": "dry-run-heuristic" if args.dry_run else settings.model_name,
        "dry_run": args.dry_run,
        "results_path": str(results_path),
        "threads_path": str(threads_path),
    }
    write_summary(summary_path, summary)

    print("\n=== Eval summary ===")
    print(f"Run id: {run_id}")
    print(f"N={scores.n}")
    print(f"Workers: {args.workers}")
    print(
        f"Category accuracy: {scores.category_accuracy:.1%} "
        f"({scores.category_correct}/{scores.n})"
    )
    print(
        f"Priority accuracy: {scores.priority_accuracy:.1%} "
        f"({scores.priority_correct}/{scores.n})"
    )
    print(
        f"Action accuracy:   {scores.action_accuracy:.1%} "
        f"({scores.action_correct}/{scores.n})"
    )
    print(f"Estimated cost per 100 tickets: ${per_100:.4f}")
    print(f"Wrote {results_path}")
    print(f"Wrote {threads_path}")
    print(f"Wrote {summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="support-ticket-agent",
        description="Classify, prioritize, draft or escalate support tickets.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Process tickets from a CSV")
    run_p.add_argument("--input", default="data/tickets.csv")
    run_p.add_argument("--output-dir", default="outputs")
    run_p.add_argument("--limit", type=int, default=None)
    run_p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread pool size for parallel ticket processing (forced to 1 with --hitl)",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Use offline heuristic classifier (no OpenAI calls)",
    )
    run_p.add_argument(
        "--hitl",
        action="store_true",
        help="Pause on every draft reply for human approve / edit / reject",
    )
    run_p.add_argument(
        "--supervision",
        action="store_true",
        help=(
            "Automatic supervisor: auto-approve safe high-confidence drafts, "
            "otherwise queue for humans (no interactive prompts)"
        ),
    )
    run_p.add_argument(
        "--thread-id",
        default=None,
        help="Only process the ticket referenced by this thread_id",
    )
    run_p.set_defaults(func=cmd_run)

    eval_p = sub.add_parser("eval", help="Score against hand-labeled eval set")
    eval_p.add_argument("--input", default="data/tickets.csv")
    eval_p.add_argument("--labels", default="evals/labels.json")
    eval_p.add_argument("--output-dir", default="outputs")
    eval_p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread pool size for parallel ticket processing",
    )
    eval_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Use offline heuristic classifier (no OpenAI calls)",
    )
    eval_p.set_defaults(func=cmd_eval)

    show_p = sub.add_parser("show", help="Show a saved thread by thread_id")
    show_p.add_argument("--thread-id", required=True)
    show_p.add_argument("--output-dir", default="outputs")
    show_p.add_argument("--results", default=None, help="Path to results.jsonl")
    show_p.add_argument("--threads", default=None, help="Path to threads.json")
    show_p.set_defaults(func=cmd_show)

    rerun_p = sub.add_parser(
        "rerun",
        help="Re-run the ticket for a thread_id (creates a new thread_id)",
    )
    rerun_p.add_argument("--thread-id", required=True)
    rerun_p.add_argument("--input", default="data/tickets.csv")
    rerun_p.add_argument("--output-dir", default="outputs")
    rerun_p.add_argument("--dry-run", action="store_true")
    rerun_p.add_argument("--hitl", action="store_true")
    rerun_p.add_argument("--supervision", action="store_true")
    rerun_p.set_defaults(func=cmd_rerun)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(code)
