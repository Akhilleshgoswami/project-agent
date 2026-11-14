from enum import Enum

from pydantic import BaseModel, Field


class TicketCategory(str, Enum):
    BUG = "bug"
    BILLING = "billing"
    FEATURE_REQUEST = "feature_request"
    QUESTION = "question"
    OTHER = "other"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SuggestedAction(str, Enum):
    DRAFT_REPLY = "draft_reply"
    HUMAN_REVIEW = "human_review"


class GuardrailDecision(str, Enum):
    ALLOW_DRAFT = "allow_draft"
    ESCALATE = "escalate"


class HumanDecisionAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    AUTO_APPROVE = "auto_approve"
    AUTO_ESCALATE = "auto_escalate"


class ReviewMode(str, Enum):
    """How drafts are reviewed before finalize."""

    OFF = "off"  # no review gate
    HITL = "hitl"  # interactive: every draft pauses for a human
    SUPERVISION = "supervision"  # non-interactive: supervisor auto-approves or auto-escalates


class TicketInput(BaseModel):
    ticket_id: str
    subject: str
    message: str


class TicketAnalysis(BaseModel):
    """Structured LLM output for a single ticket."""

    category: TicketCategory
    priority: Priority
    priority_reason: str = Field(description="Short reason for the priority")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in classification")
    suggested_action: SuggestedAction
    action_reason: str = Field(description="Why this action was chosen")
    reply_draft: str | None = Field(
        default=None,
        description="Customer-facing reply draft; only for simple questions",
    )
    human_review_reason: str | None = Field(
        default=None,
        description="Why a human should review; required when escalating",
    )


class GuardrailVerdict(BaseModel):
    """LLM guardrail decision on whether a draft reply is safe to keep."""

    decision: GuardrailDecision
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(
        default_factory=list,
        description="e.g. refund, phishing, account_access, legal, low_confidence, wrong_category",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Guardrail confidence in its decision")


class HumanDecision(BaseModel):
    action: HumanDecisionAction
    edited_draft: str | None = None
    note: str | None = None
    source: str = "human"  # human | supervision


class DecisionLogEntry(BaseModel):
    step: str
    detail: str


class UsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class TicketResult(BaseModel):
    ticket_id: str
    thread_id: str = Field(
        description="LangGraph / chat thread id — use this to refer to the run later"
    )
    run_id: str = Field(description="Batch run id shared by all tickets in one CLI invocation")
    subject: str
    category: TicketCategory
    priority: Priority
    priority_reason: str
    confidence: float
    suggested_action: SuggestedAction
    action_reason: str
    reply_draft: str | None = None
    human_review_reason: str | None = None
    human_decision: HumanDecision | None = None
    decision_log: list[DecisionLogEntry] = Field(default_factory=list)
    usage: UsageStats = Field(default_factory=UsageStats)
