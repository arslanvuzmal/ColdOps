"""Programme item N: the plan a business gets after it says yes."""

from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
import uuid

import pytest
from coldops.activities import solution_file as job
from coldops.db.enums import ReplyClass
from coldops.db.models import SenderIdentity
from coldops.db.session import get_sessionmaker
from coldops.delivery.outbox_worker import OutboxWorker
from coldops.delivery.providers.mock import MockEmailProvider
from coldops.intelligence import audit_pdf
from coldops.intelligence import solution_file as sf
from coldops.intelligence.evidence_page import EvidencePage, PageFinding
from coldops.intelligence.references import Reference
from coldops.outreach import reply_desk
from sqlalchemy import update

from tests.delivery.conftest import sending_settings
from tests.outreach.test_reply_desk import _edit_and_send, _replied

MEASURED = dt.datetime(2026, 10, 10, 11, 0, tzinfo=dt.UTC)


def _page() -> EvidencePage:
    return EvidencePage(
        workspace_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        business_name="Smile Dental",
        domain="smile.example",
        findings=(
            PageFinding(
                issue_type="no_visible_phone_number",
                title="No phone number found on the crawled pages",
                page_url="https://smile.example/",
                observed_value="no tel: link across 7 pages",
                business_impact="Visitors who prefer to call cannot find how",
                recommended_solution="Add a tel: link in the header and footer",
                measured_at=MEASURED,
            ),
        ),
    )


def test_every_part_comes_from_what_was_measured_or_planned() -> None:
    html = sf.build_html(
        _page(),
        plans=[
            sf.Plan(
                title="Website conversion improvements",
                summary="Fixes to the path that loses the most high-intent visitors.",
                steps=("No phone number: add a tel: link", "Re-run the audit"),
                effort="small",
                prerequisites=("Agreement on where new enquiries should be routed",),
            )
        ],
        references=[
            Reference("MDN Web Docs", "tel: links", "https://developer.mozilla.org/")
        ],
        case_study=None,
        evidence_url="https://coldops.example/e/abc",
        sender_name="Arslan Vuzmal Lone",
        sender_site="https://arslanvuzmallone.com",
        today=dt.date(2026, 10, 12),
    )
    assert "A plan for Smile Dental" in html
    assert "No phone number found on the crawled pages" in html
    assert "Add a tel: link in the header and footer" in html
    assert html.count("<svg") == 1 and "Re-run the audit" in html
    assert "Agreement on where new enquiries should be routed" in html
    assert "https://developer.mozilla.org/" in html
    assert "The next step" in html


def test_no_plan_still_makes_an_honest_document() -> None:
    html = sf.build_html(
        _page(),
        plans=[],
        references=[],
        case_study=None,
        evidence_url=None,
        sender_name="A",
        sender_site=None,
    )
    assert "listed against each finding above" in html
    assert "<svg" not in html


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_a_reply_that_said_yes_gets_a_plan(db_session, workspace) -> None:
    _, yes = await _replied(db_session, workspace, reply_class=ReplyClass.WANTS_CALL)
    _, no = await _replied(
        db_session,
        workspace,
        reply_class=ReplyClass.NOT_INTERESTED,
        their_id="<CAF=reply-no@mail.gmail.com>",
    )
    async with get_sessionmaker()() as s:
        found = {
            r.draft_id
            for r in (
                await s.execute(
                    job._CANDIDATES, {"ws": workspace, "positive": list(job.POSITIVE)}
                )
            ).all()
        }
    assert yes in found and no not in found


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_approved_reply_carries_its_plan(
    db_session, workspace, monkeypatch
) -> None:
    fixture, draft_id = await _replied(db_session, workspace)
    await db_session.execute(
        update(SenderIdentity)
        .where(SenderIdentity.id == fixture.sender_id)
        .values(unsubscribe_url_template="https://arslanvuzmallone.com/u/{token}")
    )
    await db_session.commit()
    monkeypatch.setattr(
        reply_desk, "get_settings", lambda: sending_settings(unsubscribe_secret="s" * 32)
    )
    artifacts = pathlib.Path(tempfile.mkdtemp(prefix="coldops-plan-"))
    plan = audit_pdf.pdf_path(str(artifacts), draft_id)
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_bytes(b"%PDF-1.7 plan")
    await _edit_and_send(db_session, workspace, draft_id)

    provider = MockEmailProvider()
    results = await OutboxWorker(
        provider,
        sending_settings(artifact_dir=str(artifacts)),
        now_fn=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1),
    ).run_once()

    assert [r.outcome for r in results] == ["sent"], results
    [sent] = provider.sends
    names = [a.filename for a in sent.email.attachments]
    assert len(names) == 1 and names[0].endswith("- plan.pdf")
    assert "attached the plan" in sent.email.text_body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_reply_without_a_plan_goes_without_one(
    db_session, workspace, monkeypatch
) -> None:
    fixture, draft_id = await _replied(db_session, workspace)
    await db_session.execute(
        update(SenderIdentity)
        .where(SenderIdentity.id == fixture.sender_id)
        .values(unsubscribe_url_template="https://arslanvuzmallone.com/u/{token}")
    )
    await db_session.commit()
    monkeypatch.setattr(
        reply_desk, "get_settings", lambda: sending_settings(unsubscribe_secret="s" * 32)
    )
    await _edit_and_send(db_session, workspace, draft_id)
    provider = MockEmailProvider()
    await OutboxWorker(
        provider,
        sending_settings(artifact_dir=tempfile.mkdtemp()),
        now_fn=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1),
    ).run_once()
    [sent] = provider.sends
    assert sent.email.attachments == () or list(sent.email.attachments) == []
    assert "attached the plan" not in sent.email.text_body
