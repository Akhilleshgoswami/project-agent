"""Small labeled eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field

from support_agent.schema import TicketResult


@dataclass
class EvalScores:
    n: int = 0
    category_correct: int = 0
    priority_correct: int = 0
    action_correct: int = 0
    per_ticket: list[dict] = field(default_factory=list)

    @property
    def category_accuracy(self) -> float:
        return self.category_correct / self.n if self.n else 0.0

    @property
    def priority_accuracy(self) -> float:
        return self.priority_correct / self.n if self.n else 0.0

    @property
    def action_accuracy(self) -> float:
        return self.action_correct / self.n if self.n else 0.0

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "category_accuracy": round(self.category_accuracy, 3),
            "priority_accuracy": round(self.priority_accuracy, 3),
            "action_accuracy": round(self.action_accuracy, 3),
            "category_correct": self.category_correct,
            "priority_correct": self.priority_correct,
            "action_correct": self.action_correct,
            "per_ticket": self.per_ticket,
        }


def score_results(results: list[TicketResult], labels: list[dict]) -> EvalScores:
    by_id = {r.ticket_id: r for r in results}
    scores = EvalScores()

    for label in labels:
        tid = label["ticket_id"]
        result = by_id.get(tid)
        if result is None:
            scores.per_ticket.append(
                {"ticket_id": tid, "error": "missing prediction"}
            )
            scores.n += 1
            continue

        cat_ok = result.category.value == label["category"]
        pri_ok = result.priority.value == label["priority"]
        act_ok = result.suggested_action.value == label["suggested_action"]

        scores.n += 1
        scores.category_correct += int(cat_ok)
        scores.priority_correct += int(pri_ok)
        scores.action_correct += int(act_ok)
        scores.per_ticket.append(
            {
                "ticket_id": tid,
                "category_ok": cat_ok,
                "priority_ok": pri_ok,
                "action_ok": act_ok,
                "predicted": {
                    "category": result.category.value,
                    "priority": result.priority.value,
                    "suggested_action": result.suggested_action.value,
                },
                "expected": {
                    "category": label["category"],
                    "priority": label["priority"],
                    "suggested_action": label["suggested_action"],
                },
            }
        )

    return scores
