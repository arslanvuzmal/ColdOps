"""Approve all: one click, the same rules as one approval, applied to each."""

from __future__ import annotations

import pytest
from coldops.db.enums import DraftStatus, WorkspaceRole
from coldops.db.models import MessageApproval, MessageDraft
from coldops.db.session import get_sessionmaker
from coldops.policy.approval_content import CONTENT_KEY
from sqlalchemy import select

from tests.api.test_api_security import (
    auth,
    make_member,
    seed_campaign_and_draft,
    slug_of,
    token_for,
)
from tests.api.test_crm import client  # noqa: F401 -- the shared ASGI client fixture


@pytest.mark.asyncio
async def test_what_was_shown_is_approved_and_the_rest_is_named(
    client,  # noqa: F811
    db_session,
    workspace,
) -> None:
    ok = await seed_campaign_and_draft(workspace, tag="bulk-ok")
    stale = await seed_campaign_and_draft(workspace, tag="bulk-stale")
    invalid = await seed_campaign_and_draft(workspace, tag="bulk-bad")
    async with get_sessionmaker()() as s, s.begin():
        (await s.get(MessageDraft, invalid["draft_id"])).validation_passed = False
    async with get_sessionmaker()() as s:
        versions = {
            k: (await s.get(MessageDraft, ids["draft_id"])).version
            for k, ids in (("ok", ok), ("stale", stale), ("bad", invalid))
        }
    _, email = await make_member(workspace, WorkspaceRole.REVIEWER, tag="bulk")
    token = await token_for(client, email, await slug_of(workspace))

    response = await client.post(
        "/api/v1/drafts/approve-all",
        headers=auth(token),
        json={
            "drafts": [
                {"draft_id": str(ok["draft_id"]), "draft_version": versions["ok"]},
                {
                    "draft_id": str(stale["draft_id"]),
                    "draft_version": versions["stale"] + 7,
                },
                {"draft_id": str(invalid["draft_id"]), "draft_version": versions["bad"]},
            ]
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["approved"] == 1
    assert len(body["skipped"]) == 2
    async with get_sessionmaker()() as s:
        approved = await s.get(MessageDraft, ok["draft_id"])
        untouched = await s.get(MessageDraft, stale["draft_id"])
        approval = (
            await s.execute(
                select(MessageApproval).where(MessageApproval.draft_id == ok["draft_id"])
            )
        ).scalar_one()
    assert approved.status is DraftStatus.APPROVED
    assert untouched.status is not DraftStatus.APPROVED
    assert CONTENT_KEY in approval.policy_snapshot


@pytest.mark.asyncio
async def test_approve_all_needs_the_right_to_approve(
    client, db_session, workspace
) -> None:
    ids = await seed_campaign_and_draft(workspace, tag="bulk-viewer")
    _, email = await make_member(workspace, WorkspaceRole.RESEARCHER, tag="bulk-viewer")
    token = await token_for(client, email, await slug_of(workspace))
    response = await client.post(
        "/api/v1/drafts/approve-all",
        headers=auth(token),
        json={"drafts": [{"draft_id": str(ids["draft_id"]), "draft_version": 1}]},
    )
    assert response.status_code == 403
