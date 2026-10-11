"""Half of each round's inbox tests carry the PDF, so its effect is measured.

The 9 Oct 2026 decision to attach a personal PDF to first emails came with a
condition: measure placement with and without it. Until 11 Oct every probe
went without one (``had_attachment`` always false), so the comparison the
decision rested on did not exist.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import uuid

import pytest
from coldops.db.models import Campaign
from coldops.db.session import get_sessionmaker
from coldops.delivery import placement_probe
from coldops.delivery.placement_probe import plan_round, sample_pdf, send_round
from coldops.delivery.providers.base import Attachment, SendResult
from sqlalchemy import update

from .test_placement_probe import DAY, MAILBOXES, SEEDS


def test_without_a_pdf_nothing_is_marked() -> None:
    planned = plan_round(MAILBOXES, SEEDS, now=DAY)
    assert not any(p.attach for p in planned)


def test_with_a_pdf_each_round_has_both_kinds() -> None:
    planned = plan_round(MAILBOXES, SEEDS, now=DAY, with_attachment=True)
    marks = [p.attach for p in planned]
    assert any(marks) and not all(marks)


def test_every_mailbox_is_read_both_ways_across_two_days() -> None:
    today = {
        p.from_email: p.attach
        for p in plan_round(MAILBOXES, SEEDS, now=DAY, with_attachment=True)
    }
    tomorrow = {
        p.from_email: p.attach
        for p in plan_round(
            MAILBOXES, SEEDS, now=DAY + dt.timedelta(days=1), with_attachment=True
        )
    }
    assert all(today[m] != tomorrow[m] for m in today)


@pytest.mark.asyncio
async def test_the_marked_probes_go_out_with_it_and_only_they(monkeypatch) -> None:
    sent: list = []

    class Recorder:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def send(self, email):
            sent.append(email)
            return SendResult(accepted=True)

    monkeypatch.setattr(placement_probe, "SmtpPoolProvider", Recorder)
    planned = plan_round(MAILBOXES, SEEDS, now=DAY, with_attachment=True)
    pdf = Attachment(filename="website-check.pdf", content=b"%PDF-1.7 test")

    await send_round(object(), planned, timeout_seconds=5, now=DAY, attachment=pdf)

    by_token = {p.probe_token: p.attach for p in planned}
    for email in sent:
        token = email.idempotency_key.removeprefix("placement:")
        assert bool(email.attachments) == by_token[token]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_the_operators_own_pdf_is_ever_carried(db_session, sendable) -> None:
    """A prospect's screenshot and findings never leave their own email."""
    from coldops.intelligence import audit_pdf

    folder = pathlib.Path(tempfile.mkdtemp(prefix="coldops-pdfs-"))
    path = audit_pdf.pdf_path(str(folder), sendable.draft_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7 prospect")

    async with get_sessionmaker()() as s:
        found = await sample_pdf(
            s, workspace_id=sendable.workspace_id, artifact_dir=str(folder)
        )
    assert found is None, "a prospect's PDF was offered to a probe"

    async with get_sessionmaker()() as s, s.begin():
        await s.execute(
            update(Campaign)
            .where(Campaign.id == sendable.campaign_id)
            .values(slug=f"coldops-e2e-test-{uuid.uuid4().hex[:4]}")
        )
    async with get_sessionmaker()() as s:
        found = await sample_pdf(
            s, workspace_id=sendable.workspace_id, artifact_dir=str(folder)
        )
    assert found is not None and found.content == b"%PDF-1.7 prospect"
