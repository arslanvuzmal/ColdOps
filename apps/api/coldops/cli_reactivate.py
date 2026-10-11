"""``coldops reactivate`` -- may cold mail be switched back on, and what would go out?

    coldops reactivate --workspace titan

Read-only: it reports and changes nothing. The checklist itself lives in
:mod:`coldops.delivery.readiness`, shared with the dashboard's System page so
the two can never disagree.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from sqlalchemy import select

from coldops.config import get_settings


async def _run(args: argparse.Namespace) -> int:
    from coldops.db.models import Workspace
    from coldops.db.session import get_sessionmaker
    from coldops.delivery import readiness

    async with get_sessionmaker()() as session:
        ws_id = (
            await session.execute(
                select(Workspace.id).where(Workspace.slug == args.workspace)
            )
        ).scalar_one_or_none()
        if ws_id is None:
            print(f"no workspace with slug {args.workspace!r}")
            return 1
        r = await readiness.assess(
            session,
            workspace_id=ws_id,
            settings=get_settings(),
            now=dt.datetime.now(dt.UTC),
        )

    print(f"Reactivation check for {args.workspace}, {r.checked_at:%Y-%m-%d %H:%M} UTC")
    print(
        f"Bar: every measured day >= {readiness.DAILY_FLOOR:.0%} inbox over "
        f"{readiness.STREAK_DAYS} days, at least {readiness.MIN_MEASURED_DAYS} days "
        "measured, domain not resting, gate clear."
    )
    print()
    for m in r.mailboxes:
        share = f"{m.inbox}/{m.probes} inbox" if m.probes else "no readings"
        print(
            f"  {m.address:<36} {'on ' if m.switched_on else 'off'}  {share:<14} "
            f"ramp day {m.ramp_day}, cold limit today {m.cold_limit_today} of {m.daily_limit}"
        )
        for p in m.problems:
            print(f"      not yet: {p}")
        if m.ready:
            print("      READY")
    print()
    print(
        "Would go out the moment mail is switched on "
        f"(stale = over {readiness.STALE_DAYS} days old):"
    )
    print(f"  queued emails       {r.queued:>4}   stale {r.queued_stale}")
    print(f"  approved, unqueued  {r.approved:>4}   stale {r.approved_stale}")
    print()
    for b in r.blockers:
        print(f"  not yet: {b}")
    for n in r.notes:
        print(f"  note: {n}")
    if r.earliest is not None:
        print(
            f"  earliest, if every daily round lands in the inbox: {r.earliest:%a %d %b}"
        )
    print()
    print(f"{r.ready} of {len(r.mailboxes)} mailboxes meet the bar. Nothing was changed.")
    return 0


def add_reactivate_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = sub.add_parser(
        "reactivate",
        help="read-only checklist: may cold mail be switched back on, what would go out",
    )
    parser.add_argument("--workspace", default="titan")
    parser.set_defaults(func=cmd_reactivate)


def cmd_reactivate(args: argparse.Namespace) -> int:
    from coldops.db.session import dispose_engine
    from coldops.runtime import configure_event_loop

    async def run() -> int:
        try:
            return await _run(args)
        finally:
            await dispose_engine()

    configure_event_loop()
    return asyncio.run(run())


__all__ = ["add_reactivate_parser", "cmd_reactivate"]
