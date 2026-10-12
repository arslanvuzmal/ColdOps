"""Warm-up per mailbox: recorded every round, and spam raises an alert once a day."""

from __future__ import annotations

import pytest
from coldops.activities.warmup import _record_by_mailbox
from coldops.db.session import get_sessionmaker
from coldops.delivery.warmup import WarmupReport
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SALES = "sales@arslanvuzmallone.com"


def _report(**counts) -> WarmupReport:
    r = WarmupReport()
    for key, n in counts.items():
        r.count(SALES, key, n)
    return r


async def _row(workspace):
    async with get_sessionmaker()() as s:
        return (
            await s.execute(
                text(
                    "SELECT sent, received, rescued, replied FROM warmup_daily "
                    "WHERE workspace_id = :ws AND mailbox = :m"
                ),
                {"ws": workspace, "m": SALES},
            )
        ).one()


async def _alerts(workspace) -> int:
    async with get_sessionmaker()() as s:
        return int(
            await s.scalar(
                text(
                    "SELECT count(*) FROM tasks WHERE workspace_id = :ws "
                    "AND kind = 'deliverability_alert'"
                ),
                {"ws": workspace},
            )
        )


async def test_each_round_adds_to_the_days_row(db_session, workspace) -> None:
    await _record_by_mailbox(workspace, [_report(sent=2, replied=1)], ours={SALES})
    await _record_by_mailbox(workspace, [_report(sent=3, received=4)], ours={SALES})
    row = await _row(workspace)
    assert (row.sent, row.received, row.rescued, row.replied) == (5, 4, 0, 1)
    assert await _alerts(workspace) == 0


async def test_spam_raises_one_alert_a_day(db_session, workspace) -> None:
    await _record_by_mailbox(workspace, [_report(rescued=1)], ours={SALES})
    await _record_by_mailbox(workspace, [_report(rescued=2)], ours={SALES})
    assert (await _row(workspace)).rescued == 3
    assert await _alerts(workspace) == 1


async def test_a_partners_spam_is_recorded_but_not_alerted(db_session, workspace) -> None:
    await _record_by_mailbox(workspace, [_report(rescued=1)], ours=set())
    assert (await _row(workspace)).rescued == 1
    assert await _alerts(workspace) == 0
