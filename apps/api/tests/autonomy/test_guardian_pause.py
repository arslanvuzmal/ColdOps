"""The guardian pauses for real: the campaign, the decision row, the alert."""

from __future__ import annotations

import datetime as dt

import pytest
from coldops.activities.orchestration import _run_guardian
from coldops.db.enums import CampaignStatus
from coldops.db.models import AutonomyDecision, Campaign
from coldops.db.session import get_sessionmaker
from sqlalchemy import select, text

from tests.delivery.conftest import build_sendable

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = dt.datetime(2026, 10, 11, 12, 0, tzinfo=dt.UTC)


def outcomes(**overrides) -> dict[str, int]:
    base = {
        "sent": 400,
        "delivered": 396,
        "bounced": 2,
        "complained": 0,
        "contacted": 300,
        "replied": 6,
        "positive_replies": 3,
        "meetings_booked": 0,
    }
    base.update(overrides)
    return base


async def guard(fx, **overrides):
    return await _run_guardian(
        workspace_id=fx.workspace_id,
        campaign_id=fx.campaign_id,
        status=CampaignStatus.ACTIVE,
        configured_limit=40,
        configured_score=70,
        managed_limit=None,
        outcomes=outcomes(**overrides),
        leads_available=50,
        now=NOW,
    )


async def test_a_healthy_campaign_runs_on_its_configured_values(db_session, workspace):
    fx = await build_sendable(db_session, workspace)
    assert await guard(fx) == (40, 70, None)


async def test_a_bouncing_campaign_is_paused_recorded_and_reported(db_session, workspace):
    fx = await build_sendable(db_session, workspace)

    _limit, score, paused = await guard(fx, sent=200, delivered=180, bounced=20)

    assert paused is not None and "bounce" in paused
    assert score == 70  # the configured bar, never a tuned one
    async with get_sessionmaker()() as s:
        campaign = await s.get(Campaign, fx.campaign_id)
        decision = (
            await s.execute(
                select(AutonomyDecision).where(
                    AutonomyDecision.campaign_id == fx.campaign_id
                )
            )
        ).scalar_one()
        alerts = (
            await s.execute(
                text("SELECT count(*) FROM tasks WHERE workspace_id = :ws AND kind = :k"),
                {"ws": fx.workspace_id, "k": "deliverability_alert"},
            )
        ).scalar_one()
    assert campaign.status is CampaignStatus.PAUSED
    assert decision.actuation == "pause_campaign" and decision.applied
    assert alerts == 1
