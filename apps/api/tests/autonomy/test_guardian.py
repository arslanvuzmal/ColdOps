"""Item K: the manager is a guardian now -- it pauses on a hard limit, tunes nothing."""

from __future__ import annotations

import inspect

from coldops.activities import orchestration, pipeline
from coldops.autonomy import guardian
from coldops.db.enums import CampaignStatus
from coldops.delivery.deliverability import ReputationWindow

from tests.autonomy.test_manager import window


def test_a_healthy_campaign_is_left_alone() -> None:
    assert guardian.assess(window()) is None


def test_a_bounce_rate_over_the_ceiling_pauses() -> None:
    action = guardian.assess(
        window(
            window=ReputationWindow(
                sent=200, delivered=180, hard_bounced=20, complained=0
            )
        )
    )
    assert action is not None
    assert "bounce" in " ".join(action.signals)


def test_a_complaint_over_the_ceiling_pauses() -> None:
    action = guardian.assess(
        window(
            window=ReputationWindow(sent=400, delivered=400, hard_bounced=0, complained=2)
        )
    )
    assert action is not None
    assert "complaint" in " ".join(action.signals)


def test_too_few_sends_to_judge_is_not_a_pause() -> None:
    """Below the sample floor one bounce would look catastrophic."""
    assert (
        guardian.assess(
            window(
                window=ReputationWindow(sent=8, delivered=5, hard_bounced=3, complained=0)
            )
        )
        is None
    )


def test_a_paused_campaign_is_not_paused_again() -> None:
    bad = ReputationWindow(sent=200, delivered=180, hard_bounced=20, complained=0)
    assert guardian.assess(window(status=CampaignStatus.PAUSED, window=bad)) is None


def test_the_cycle_no_longer_tunes() -> None:
    """Planted violation: put the manager's plan() or the variant promotion
    back into the campaign cycle and this fails."""
    cycle = inspect.getsource(orchestration)
    assert "promotion.decide(" not in cycle
    assert "= plan(state" not in cycle
    assert "markets.weigh(" not in cycle
    assert "managed_min_lead_score" not in cycle


def test_drafting_no_longer_reads_a_promoted_variant() -> None:
    draft = inspect.getsource(pipeline.generate_draft)
    assert "managed_promoted_variant" not in draft
