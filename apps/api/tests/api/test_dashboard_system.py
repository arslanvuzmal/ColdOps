"""The System page: reactivation readiness, jobs, models, personal PDFs."""

from __future__ import annotations

import pytest
from coldops.api import system as system_api
from coldops.db.enums import WorkspaceRole

from tests.api.test_api_security import auth, make_member, slug_of, token_for
from tests.api.test_crm import client  # noqa: F401 -- the shared ASGI client fixture
from tests.delivery.conftest import build_sendable


async def _token(client, workspace) -> str:  # noqa: F811
    _, email = await make_member(workspace, WorkspaceRole.RESEARCHER, tag="sys")
    return await token_for(client, email, await slug_of(workspace))


@pytest.mark.asyncio
async def test_the_system_page_answers_every_section(
    client,  # noqa: F811
    db_session,
    workspace,
    monkeypatch,
):  # noqa: F811, RUF100
    await build_sendable(db_session, workspace)

    async def no_temporal(_workspace_id):
        return system_api.SchedulesOut(
            reachable=False, error="ConnectionRefused: test", schedules=[]
        )

    monkeypatch.setattr(system_api, "_schedules", no_temporal)
    token = await _token(client, workspace)

    response = await client.get("/api/v1/dashboard/system", headers=auth(token))

    assert response.status_code == 200, response.text
    body = response.json()
    readiness = body["readiness"]
    assert len(readiness["mailboxes"]) == 1
    [mailbox] = readiness["mailboxes"]
    # No placement readings at all: not ready, and it says why.
    assert mailbox["ready"] is False
    assert any("days measured" in p for p in mailbox["problems"])
    assert readiness["queued"] == 1
    assert body["schedules"]["reachable"] is False
    assert body["models"] == []
    assert body["pdfs"]["first_emails_7d"] == 0
    assert body["healing"]["container_log_available"] is False
    assert body["healing"]["repaired_7d"] == 0


@pytest.mark.asyncio
async def test_the_system_page_needs_a_session(client):  # noqa: F811
    response = await client.get("/api/v1/dashboard/system")
    assert response.status_code == 401


def test_the_container_doctors_log_is_read() -> None:
    import pathlib
    import tempfile

    folder = pathlib.Path(tempfile.mkdtemp(prefix="coldops-heal-"))
    log = folder / "heal.log"
    log.write_text(
        '{"at":"2026-10-11T19:48:15Z","container":"deploy-api-1","action":"restarted",'
        '"reason":"health check failing"}\n'
        "not json at all\n"
        '{"at":"2026-10-11T19:48:25Z","container":"deploy-api-1","action":"gave_up",'
        '"reason":"needs a person"}\n',
        encoding="utf-8",
    )
    repairs = system_api._container_repairs(str(log))
    assert [r.action for r in repairs] == ["restarted", "gave_up"]
    assert repairs[0].what == "container deploy-api-1"
    assert system_api._container_repairs(str(folder / "missing.log")) is None
    assert system_api._container_repairs(None) is None
