"""Warm-up traffic, as a daily activity rather than a command somebody runs.

The module that sends and tends warm-up mail has existed since August and has
only ever been reachable from ``coldops warmup run --apply``. Nothing scheduled
it, so after the rented carrier's warm-up stopped on 24 August the domain had
none at all -- through the week it sent 492 cold messages and was filed as
spam by every probe that was read.

Returns ``skipped`` for every ordinary unconfigured state rather than raising,
for the same reason the placement activities do: a retrying activity would turn
"not set up yet" into an alert every day forever.
"""

from __future__ import annotations

import datetime as dt
import uuid

from temporalio import activity

from coldops.config import get_settings
from coldops.delivery.mailboxes import MailboxConfigError, load_mailboxes
from coldops.delivery.seeds import load_seeds
from coldops.delivery.warmup import (
    check_recipients_are_participants,
    due,
    involving_ours,
    participants_from,
    plan,
    round_pool,
    send_round,
    tend,
)
from coldops.workflows.types import WarmupRoundInput, WarmupRoundResult


@activity.defn(name="run_warmup_round")
async def run_warmup_round(request: WarmupRoundInput) -> WarmupRoundResult:
    """Send today's warm-up, then rescue, read and answer what arrived."""
    settings = get_settings()
    if not settings.warmup_enabled:
        return WarmupRoundResult(skipped="warm-up is switched off")
    if not settings.mailbox_file:
        return WarmupRoundResult(skipped="no mailbox file")
    if not settings.warmup_partner_file:
        # Not a softer "fewer signals" state: without a mailbox on another
        # provider every message stays on one server and teaches nobody
        # anything. Refusing says so; running would look like progress.
        return WarmupRoundResult(
            skipped="no warm-up partners; mail between our own mailboxes "
            "never reaches Gmail or Microsoft"
        )

    try:
        sending_registry = load_mailboxes(settings.mailbox_file)
        partner_registry = load_mailboxes(settings.warmup_partner_file)
    except MailboxConfigError as exc:
        return WarmupRoundResult(skipped=f"mailbox file unusable: {exc}")

    # The CLI's own helper, so the scheduled round and the manual one agree
    # about which day of its ramp each mailbox is on.
    from coldops.cli import _warmup_days

    days = await _warmup_days(uuid.UUID(request.workspace_id))
    sending = participants_from(sending_registry, days=days)
    partners = participants_from(partner_registry)
    seeds = {seed.address for seed in load_seeds(settings.seed_file).all()}
    pool = round_pool(sending, partners, seed_addresses=seeds)

    # Spread through the day: this runs hourly and sends only what is due by
    # now; anything already delivered is skipped, so a missed hour catches up.
    today = due(involving_ours(plan(pool), sending), dt.datetime.now(dt.UTC))
    check_recipients_are_participants(today, pool)
    timeout = float(settings.smtp_timeout_seconds)
    sent = await send_round(today, timeout_seconds=timeout)
    tended = await tend(pool, timeout_seconds=timeout)

    activity.logger.info(
        "warm-up round",
        extra={
            "sent": sent.sent,
            "failed": sent.failed,
            "rescued": tended.rescued_from_spam,
            "replied": tended.replied,
            "starred": tended.starred,
        },
    )
    try:
        await _record_by_mailbox(
            uuid.UUID(request.workspace_id),
            [sent, tended],
            ours={p.address.lower() for p in sending},
        )
    except Exception:
        activity.logger.exception("could not record warm-up per mailbox")
    return WarmupRoundResult(
        planned=len(today),
        sent=sent.sent,
        failed=sent.failed,
        rescued_from_spam=tended.rescued_from_spam,
        marked_read=tended.marked_read,
        replied=tended.replied,
        errors=tuple((sent.errors + tended.errors)[:10]),
    )


async def _record_by_mailbox(
    workspace_id: uuid.UUID, reports: list, *, ours: set[str]
) -> None:
    """Add this round's counts to today's row per mailbox, and raise an alert the
    first time a day one of our mailboxes has its warm-up mail found in spam --
    the earliest sign a mailbox is slipping, days before an inbox test shows it.
    """
    from sqlalchemy import text

    from coldops.db.session import workspace_unit_of_work
    from coldops.notify.operator import (
        NotificationKind,
        mail_notification,
        push_notification,
        record_notification,
    )

    totals: dict[str, dict[str, int]] = {}
    for report in reports:
        for address, counts in report.by_mailbox.items():
            box = totals.setdefault(
                address, {"sent": 0, "received": 0, "rescued": 0, "replied": 0}
            )
            for key, value in counts.items():
                box[key] += value
    if not totals:
        return
    today = dt.datetime.now(dt.UTC).date()
    alerts = []
    async with workspace_unit_of_work(workspace_id) as session:
        for address, c in totals.items():
            await session.execute(
                text(
                    """
                    INSERT INTO warmup_daily
                        (workspace_id, day, mailbox, sent, received, rescued, replied)
                    VALUES (:ws, :day, :mailbox, :sent, :received, :rescued, :replied)
                    ON CONFLICT (workspace_id, day, mailbox) DO UPDATE SET
                        sent = warmup_daily.sent + EXCLUDED.sent,
                        received = warmup_daily.received + EXCLUDED.received,
                        rescued = warmup_daily.rescued + EXCLUDED.rescued,
                        replied = warmup_daily.replied + EXCLUDED.replied,
                        updated_at = now()
                    """
                ),
                {"ws": workspace_id, "day": today, "mailbox": address, **c},
            )
            if c["rescued"] and address in ours:
                alert = await record_notification(
                    session,
                    workspace_id=workspace_id,
                    kind=NotificationKind.DELIVERABILITY_ALERT,
                    title=f"Warm-up mail from {address} landed in spam",
                    description=(
                        f"{c['rescued']} of its warm-up messages were found in a junk "
                        "folder today and moved back to the inbox. One is noise; the "
                        "same on following days means the mailbox is slipping."
                    ),
                    dedupe_key=f"warmup-spam:{address}:{today.isoformat()}",
                )
                if alert is not None:
                    alerts.append(alert)
    for alert in alerts:
        await mail_notification(alert)
        await push_notification(alert)


ALL_WARMUP_ACTIVITIES = [run_warmup_round]

__all__ = ["ALL_WARMUP_ACTIVITIES", "run_warmup_round"]
