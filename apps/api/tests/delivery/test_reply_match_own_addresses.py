"""Mail from one of our own addresses is never attached to a lead by sender.

Live, 11 Oct 2026: August's Smartlead tests were recorded as sent to an
address that later became the warm-up partner, so the sender-address fallback
attached every warm-up message from it -- 17 in two days -- to that real lead.
"""

from __future__ import annotations

import pytest
from coldops import config
from coldops.db.models import Message
from coldops.db.models.messaging import InboundMessage as InboundMessageRow
from coldops.db.session import workspace_unit_of_work
from coldops.delivery.mailbox import RawMessage
from coldops.delivery.reply_collector import ReplyCollector
from sqlalchemy import select, update

from tests.delivery.conftest import build_sendable, sending_settings
from tests.delivery.test_reply_ingest import FakeMailbox

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PARTNER = "warmup-partner@example-gmail.test"


def unthreaded(from_email: str, message_id: str) -> bytes:
    """A new conversation: no In-Reply-To, no References -- as warm-up sends."""
    return (
        f"From: Partner <{from_email}>\r\n"
        "To: sales@arslanvuzmallone.com\r\n"
        "Subject: This week\r\n"
        f"Message-ID: <{message_id}>\r\n"
        "Date: Sat, 10 Oct 2026 09:14:22 +0000\r\n"
        'Content-Type: text/plain; charset="utf-8"\r\n'
        "\r\n"
        "Fairly quiet on my end. Shout if you need anything moved.\r\n"
    ).encode()


async def _lead_of_ingested(workspace) -> object:
    async with workspace_unit_of_work(workspace) as session:
        rows = (await session.execute(select(InboundMessageRow))).scalars().all()
    return [r.lead_id for r in rows]


async def test_warm_up_mail_from_our_own_address_attaches_to_no_lead(
    db_session, workspace, monkeypatch
):
    fixture = await build_sendable(db_session, workspace, to_email=PARTNER)
    async with workspace_unit_of_work(workspace) as session:
        await session.execute(
            update(Message)
            .where(Message.id == fixture.message_id)
            .values(to_email_normalized=PARTNER)
        )
    ours = sending_settings(operator_email=PARTNER)
    monkeypatch.setattr(config, "get_settings", lambda: ours)

    mailbox = FakeMailbox(
        [RawMessage(uid="1", raw=unthreaded(PARTNER, "w1@partner.test"))]
    )
    await ReplyCollector(mailbox, mailbox_address="sales@arslanvuzmallone.com").run_once()

    assert fixture.lead_id not in await _lead_of_ingested(workspace)


async def test_a_prospect_answering_without_headers_still_matches(
    db_session, workspace, monkeypatch
):
    """The fallback exists for this, and must keep working."""
    fixture = await build_sendable(db_session, workspace)
    monkeypatch.setattr(config, "get_settings", lambda: sending_settings())

    mailbox = FakeMailbox(
        [RawMessage(uid="2", raw=unthreaded(fixture.to_email, "p1@prospect.test"))]
    )
    await ReplyCollector(mailbox, mailbox_address="sales@arslanvuzmallone.com").run_once()

    assert await _lead_of_ingested(workspace) == [fixture.lead_id]
