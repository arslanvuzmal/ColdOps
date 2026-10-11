"""The dashboard's System page: is ColdOps healthy, and when may cold mail resume?

Four answers the CRM did not show, each read from where the fact lives:

* **Reactivation** -- the ``coldops reactivate`` checklist (shared module,
  :mod:`coldops.delivery.readiness`), per mailbox, with the earliest day cold
  mail could resume if every daily inbox test lands.
* **Scheduled jobs** -- every Temporal schedule for this workspace: paused or
  not, when it last ran, and when it runs next. Asked of Temporal itself; an
  unreachable Temporal is reported as such, not as an empty list.
* **Models** -- the ML registry: which version is live, which are shadowing,
  how many predictions and labels each has.
* **Personal PDFs** -- whether they are switched on, how many are rendered,
  and how many first emails actually carried one this week.

Read-only, behind the same session auth as the rest of the CRM.
"""

from __future__ import annotations

import datetime as dt
import os
import pathlib

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from coldops.api.security import Principal, require
from coldops.config import get_settings
from coldops.db.session import workspace_session

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class MailboxReadinessOut(BaseModel):
    address: str
    switched_on: bool
    inbox: int
    probes: int
    days_measured: int
    ramp_day: int
    cold_limit_today: int
    daily_limit: int
    problems: list[str]
    ready: bool


class ReadinessOut(BaseModel):
    bar: str
    mailboxes: list[MailboxReadinessOut]
    ready: int
    queued: int
    queued_stale: int
    approved: int
    approved_stale: int
    stale_days: int
    blockers: list[str]
    notes: list[str]
    earliest: dt.date | None


class ScheduleOut(BaseModel):
    name: str
    workflow: str
    note: str | None
    paused: bool
    last_run: dt.datetime | None
    next_run: dt.datetime | None


class SchedulesOut(BaseModel):
    reachable: bool
    error: str | None
    schedules: list[ScheduleOut]


class ModelOut(BaseModel):
    name: str
    version: str
    status: str
    promoted_at: dt.datetime | None
    predictions_7d: int
    predictions_total: int


class PdfsOut(BaseModel):
    enabled: bool
    rendered_total: int | None
    rendered_7d: int | None
    attached_7d: int
    first_emails_7d: int
    #: Inbox tests over the last 14 days, split by whether the probe carried
    #: the PDF -- the 9 Oct condition for attaching it at all.
    probes_with_pdf: int
    inbox_with_pdf: int
    probes_without_pdf: int
    inbox_without_pdf: int


class SystemOut(BaseModel):
    checked_at: dt.datetime
    readiness: ReadinessOut
    schedules: SchedulesOut
    models: list[ModelOut]
    labels_total: int
    pdfs: PdfsOut


async def _schedules(workspace_id: str) -> SchedulesOut:
    settings = get_settings()
    try:
        from temporalio.client import Client

        client = await Client.connect(
            settings.temporal_host, namespace=settings.temporal_namespace
        )
        out: list[ScheduleOut] = []
        async for listed in await client.list_schedules():
            if not listed.id.endswith(f"::{workspace_id}"):
                continue
            described = await client.get_schedule_handle(listed.id).describe()
            info = described.info
            recent = [a.started_at for a in info.recent_actions if a.started_at]
            out.append(
                ScheduleOut(
                    name=listed.id.split("::", 1)[0].removeprefix("coldops-"),
                    workflow=getattr(described.schedule.action, "workflow", "") or "",
                    note=described.schedule.state.note or None,
                    paused=described.schedule.state.paused,
                    last_run=max(recent) if recent else None,
                    next_run=(
                        info.next_action_times[0] if info.next_action_times else None
                    ),
                )
            )
        out.sort(key=lambda s: s.name)
        return SchedulesOut(reachable=True, error=None, schedules=out)
    except Exception as exc:  # Temporal down is an answer, not a 500
        return SchedulesOut(
            reachable=False, error=f"{type(exc).__name__}: {exc}"[:300], schedules=[]
        )


def _pdf_files(
    artifact_dir: str | None, since: dt.datetime
) -> tuple[int | None, int | None]:
    if not artifact_dir:
        return None, None
    folder = pathlib.Path(artifact_dir) / "pdfs"
    if not folder.is_dir():
        return 0, 0
    total = recent = 0
    cutoff = since.timestamp()
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".pdf"):
                total += 1
                if entry.stat().st_mtime >= cutoff:
                    recent += 1
    return total, recent


@router.get("/system", response_model=SystemOut)
async def system(
    principal: Principal = Depends(require("research:read")),
) -> SystemOut:
    from coldops.delivery import readiness

    settings = get_settings()
    now = dt.datetime.now(dt.UTC)
    week = now - dt.timedelta(days=7)
    async with workspace_session(principal.workspace_id) as session:
        r = await readiness.assess(
            session, workspace_id=principal.workspace_id, settings=settings, now=now
        )
        models = (
            await session.execute(
                text(
                    """
                    SELECT m.name, m.version, m.status, m.promoted_at,
                           count(p.id) FILTER (WHERE p.created_at >= :week) AS recent,
                           count(p.id) AS total
                      FROM ml_models m
                      LEFT JOIN ml_predictions p ON p.model_id = m.id
                     WHERE m.workspace_id = :ws
                     GROUP BY m.id
                     ORDER BY m.name, (m.status = 'active') DESC, m.created_at DESC
                    """
                ),
                {"ws": principal.workspace_id, "week": week},
            )
        ).all()
        labels = int(
            await session.scalar(
                text("SELECT count(*) FROM ml_labels WHERE workspace_id = :ws"),
                {"ws": principal.workspace_id},
            )
            or 0
        )
        firsts = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FILTER (WHERE m.one_pager_attached) AS attached,
                           count(*) AS total
                      FROM messages m
                     WHERE m.workspace_id = :ws
                       AND m.sent_at >= :week
                       AND NOT EXISTS (
                           SELECT 1 FROM messages e
                            WHERE e.workspace_id = :ws AND e.lead_id = m.lead_id
                              AND e.sent_at < m.sent_at)
                    """
                ),
                {"ws": principal.workspace_id, "week": week},
            )
        ).one()

    rendered_total, rendered_7d = _pdf_files(settings.artifact_dir, week)
    async with workspace_session(principal.workspace_id) as session:
        split = {
            bool(row.had_attachment): row
            for row in (
                await session.execute(
                    text(
                        """
                        SELECT had_attachment,
                               count(*) AS probes,
                               -- Inbox only, as the placement gate counts it.
                               count(*) FILTER (WHERE folder = 'inbox') AS inbox
                          FROM placement_checks
                         WHERE workspace_id = :ws
                           AND sent_at >= :since
                           AND folder IN ('inbox', 'promotions', 'spam', 'missing')
                         GROUP BY had_attachment
                        """
                    ),
                    {"ws": principal.workspace_id, "since": now - dt.timedelta(days=14)},
                )
            ).all()
        }
    return SystemOut(
        checked_at=now,
        readiness=ReadinessOut(
            bar=(
                f"every measured day at least {readiness.DAILY_FLOOR:.0%} inbox over "
                f"{readiness.STREAK_DAYS} days, at least {readiness.MIN_MEASURED_DAYS} "
                "days measured, domain not resting, gate clear today"
            ),
            mailboxes=[
                MailboxReadinessOut(
                    address=m.address,
                    switched_on=m.switched_on,
                    inbox=m.inbox,
                    probes=m.probes,
                    days_measured=m.days_measured,
                    ramp_day=m.ramp_day,
                    cold_limit_today=m.cold_limit_today,
                    daily_limit=m.daily_limit,
                    problems=list(m.problems),
                    ready=m.ready,
                )
                for m in r.mailboxes
            ],
            ready=r.ready,
            queued=r.queued,
            queued_stale=r.queued_stale,
            approved=r.approved,
            approved_stale=r.approved_stale,
            stale_days=readiness.STALE_DAYS,
            blockers=list(r.blockers),
            notes=list(r.notes),
            earliest=r.earliest,
        ),
        schedules=await _schedules(str(principal.workspace_id)),
        models=[
            ModelOut(
                name=m.name,
                version=m.version,
                status=m.status,
                promoted_at=m.promoted_at,
                predictions_7d=int(m.recent),
                predictions_total=int(m.total),
            )
            for m in models
        ],
        labels_total=labels,
        pdfs=PdfsOut(
            enabled=settings.audit_pdf_enabled,
            rendered_total=rendered_total,
            rendered_7d=rendered_7d,
            attached_7d=int(firsts.attached or 0),
            first_emails_7d=int(firsts.total or 0),
            probes_with_pdf=int(split[True].probes) if True in split else 0,
            inbox_with_pdf=int(split[True].inbox) if True in split else 0,
            probes_without_pdf=int(split[False].probes) if False in split else 0,
            inbox_without_pdf=int(split[False].inbox) if False in split else 0,
        ),
    )


__all__ = ["router"]
