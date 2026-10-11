"""The guardian: what is left of the campaign manager, and all it may do.

Programme item K (decided 9 Oct 2026). The manager used to *tune*: it raised
a campaign's lead-score bar when it degraded, promoted a winning message
variant from fixed A/B splits, and weighted the shared sending budget towards
the markets that had done best. Those are learning decisions, and they belong
to the trained models (M3 lead propensity, M4 message policy), which may only
rank, hold back or suggest -- and only after beating the rule they replace on
held-out data, with the operator's approval. Until a model earns a job, the
operator's configured values stand.

What stays is the guardian, and it has one decision: **pause a campaign whose
reputation has crossed a hard limit** -- the same ``BLOCK`` severity the send
gate itself refuses on (bounce or complaint rate over its ceiling, on a sample
large enough to mean it). It never resumes one; that is the operator's call.
Repair (stranded drafts, abandoned runs, schedule healing) and reporting (the
daily and weekly reports, every action written to ``autonomy_decisions``) are
done by the jobs that already do them.

Pure: no session, no I/O. The orchestration activity applies it.
"""

from __future__ import annotations

from dataclasses import dataclass

from coldops.autonomy.health import CampaignWindow
from coldops.db.enums import CampaignStatus

#: The actuation the guardian records in ``autonomy_decisions``.
PAUSE = "pause_campaign"


@dataclass(frozen=True, slots=True)
class GuardianAction:
    """Pause this campaign, and the sentence that says why."""

    reason: str
    signals: tuple[str, ...]


def assess(window: CampaignWindow) -> GuardianAction | None:
    """Pause an active campaign on a hard reputation limit; otherwise nothing."""
    from coldops.delivery.deliverability import Severity, check_reputation

    if window.status is not CampaignStatus.ACTIVE:
        return None
    blocking = [
        s for s in check_reputation(window.window) if s.severity is Severity.BLOCK
    ]
    if not blocking:
        return None
    return GuardianAction(
        reason="; ".join(s.detail for s in blocking),
        signals=tuple(s.code for s in blocking),
    )


__all__ = ["PAUSE", "GuardianAction", "assess"]
