"""May cold mail be switched back on? One answer, for the CLI and the dashboard.

Cold mail stops in two places: every mailbox switched off (``is_active``), and
the placement gate resting the domain after spam readings. Switching mailboxes
back on is the one act that restarts it, and on 10 Oct 2026 the end-to-end
test showed what that act would have released: ten auto-approved pitches
queued a week or two earlier, and a ramp that read five mailboxes new to
Google Workspace as warm since August. This is the checklist in front of it.

The bar is the operator's (3 Oct): **at least 80% inbox on the placement
probes, every measured day for 14 days**, the domain not resting, and today's
gate verdict clear -- per mailbox. Read-only: nothing here changes anything.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from coldops.config import Settings

#: The operator's reactivation bar.
STREAK_DAYS = 14
DAILY_FLOOR = 0.80
#: A probe round can be missed; this many measured days in the window is the
#: least that still counts as two weeks of evidence.
MIN_MEASURED_DAYS = 10
#: Queued or approved longer ago than this should not go out on reactivation:
#: the findings behind it are that old, and so is the decision to send it.
STALE_DAYS = 7


@dataclasses.dataclass(frozen=True)
class MailboxReadiness:
    address: str
    switched_on: bool
    inbox: int
    probes: int
    days_measured: int
    ramp_day: int
    cold_limit_today: int
    daily_limit: int
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


@dataclasses.dataclass(frozen=True)
class Readiness:
    checked_at: dt.datetime
    mailboxes: tuple[MailboxReadiness, ...]
    queued: int
    queued_stale: int
    approved: int
    approved_stale: int
    blockers: tuple[str, ...]
    notes: tuple[str, ...]
    #: The earliest day every measured mailbox could meet the bar, if each
    #: daily round from now on lands in the inbox. None when something other
    #: than time is in the way (a bad day, a resting domain, authentication).
    earliest: dt.date | None

    @property
    def ready(self) -> int:
        return sum(m.ready for m in self.mailboxes)


async def assess(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    settings: Settings,
    now: dt.datetime,
) -> Readiness:
    from coldops.db.models import SenderIdentity, Workspace
    from coldops.db.models.identity import SENDER_INACTIVE
    from coldops.delivery import deliverability, placement_gate
    from coldops.delivery.outbox_worker import _ramp_start

    workspace = await session.get(Workspace, workspace_id)
    senders = list(
        (
            await session.execute(
                select(SenderIdentity)
                .where(SenderIdentity.workspace_id == workspace_id)
                .order_by(SenderIdentity.from_email)
            )
        )
        .scalars()
        .all()
    )
    # Only mailboxes still in some campaign's pool are candidates to send; a
    # retired one (arslan@, 10 Oct) is reported by nothing here.
    pooled = {
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT DISTINCT sender_identity_id FROM campaign_senders "
                    "WHERE workspace_id = :ws"
                ),
                {"ws": workspace_id},
            )
        ).all()
    }
    senders = [s for s in senders if s.id in pooled or s.is_active]
    readings = await placement_gate.load_readings(
        session,
        workspace_id=workspace_id,
        domains={placement_gate.domain_of(s.from_email) for s in senders},
        now=now,
    )
    first_sends = {
        r.sender_identity_id: r.first
        for r in (
            await session.execute(
                text(
                    "SELECT sender_identity_id, min(sent_at) AS first FROM messages "
                    "WHERE workspace_id = :ws AND sent_at IS NOT NULL "
                    "GROUP BY sender_identity_id"
                ),
                {"ws": workspace_id},
            )
        ).all()
    }
    cutoff = now - dt.timedelta(days=STALE_DAYS)
    queue = (
        await session.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE created_at < :cutoff) AS stale,
                       count(*) AS total
                  FROM outbox_messages
                 WHERE workspace_id = :ws
                   AND status IN ('pending', 'deferred', 'leased')
                """
            ),
            {"ws": workspace_id, "cutoff": cutoff},
        )
    ).one()
    approved = (
        await session.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE d.created_at < :cutoff) AS stale,
                       count(*) AS total
                  FROM message_drafts d
                 WHERE d.workspace_id = :ws
                   AND d.status = 'approved'
                   AND NOT EXISTS (SELECT 1 FROM outbox_messages o
                                    WHERE o.draft_id = d.id)
                """
            ),
            {"ws": workspace_id, "cutoff": cutoff},
        )
    ).one()

    since = (now - dt.timedelta(days=STREAK_DAYS)).date()
    daily: dict[str, dict[dt.date, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    for r in readings:
        day = r.sent_at.astimezone(dt.UTC).date()
        if day >= since:
            cell = daily[r.from_email.lower()][day]
            cell[0] += int(r.reached)
            cell[1] += 1

    out: list[MailboxReadiness] = []
    only_time = True
    for s in senders:
        address = s.from_email.lower()
        days = daily.get(address, {})
        bad = sorted(d for d, (hit, n) in days.items() if hit / n < DAILY_FLOOR)
        verdict = placement_gate.assess(address, readings, now=now)
        start = _ramp_start(first_sends.get(s.id), s.warmup_started_at)
        limit = deliverability.warmup_limit(
            first_send_at=start, now=now, target=s.daily_send_limit
        )
        problems: list[str] = []
        if len(days) < MIN_MEASURED_DAYS:
            problems.append(f"{len(days)} of {MIN_MEASURED_DAYS} days measured so far")
        if bad:
            only_time = False
            problems.append(
                "under the bar on " + ", ".join(f"{d:%d %b}" for d in bad[-3:])
            )
        if not verdict.may_send:
            if verdict.code != placement_gate.UNMEASURED:
                only_time = False
            problems.append(verdict.detail)
        auth = [e for e in s.authorization_errors() if e != SENDER_INACTIVE]
        if auth:
            only_time = False
        problems.extend(auth)
        out.append(
            MailboxReadiness(
                address=address,
                switched_on=s.is_active,
                inbox=sum(h for h, _ in days.values()),
                probes=sum(n for _, n in days.values()),
                days_measured=len(days),
                ramp_day=deliverability.warmup_day(start, now),
                cold_limit_today=limit if limit is not None else s.daily_send_limit,
                daily_limit=s.daily_send_limit,
                problems=tuple(problems),
            )
        )

    earliest: dt.date | None = None
    if out and only_time:
        short = max(MIN_MEASURED_DAYS - m.days_measured for m in out)
        # Today's round counts if it has not run yet; be conservative and
        # count from tomorrow.
        earliest = now.date() + dt.timedelta(days=max(short, 0))

    blockers: list[str] = []
    if not settings.production_sending_enabled:
        blockers.append("COLDOPS_PRODUCTION_SENDING_ENABLED is off")
    if workspace is not None and not workspace.sending_authorized:
        blockers.append("the workspace is not authorized to send")
    if not settings.placement_gate_enabled:
        blockers.append("the placement gate is off; it must stay on for cold mail")
    notes: list[str] = []
    if settings.test_recipients:
        notes.append(
            "COLDOPS_TEST_RECIPIENTS is still set "
            f"({', '.join(settings.test_recipients)}); remove it when testing is done"
        )

    return Readiness(
        checked_at=now,
        mailboxes=tuple(out),
        queued=int(queue.total),
        queued_stale=int(queue.stale),
        approved=int(approved.total),
        approved_stale=int(approved.stale),
        blockers=tuple(blockers),
        notes=tuple(notes),
        earliest=earliest,
    )


__all__ = [
    "DAILY_FLOOR",
    "MIN_MEASURED_DAYS",
    "STALE_DAYS",
    "STREAK_DAYS",
    "MailboxReadiness",
    "Readiness",
    "assess",
]
