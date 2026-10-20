"""Importing an outside list takes businesses, never the addresses it came with."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from coldops.db.enums import CampaignStatus, Industry, LeadStatus
from coldops.db.models import Campaign, ContactChannel, Lead, Organization
from coldops.db.models.compliance import SuppressionEntry
from coldops.db.session import get_sessionmaker
from coldops.import_leads import import_rows, normalize_domain, read_rows
from sqlalchemy import func, select

HEADER = "company_name,company_number,domain,industry,location,published_emails\n"


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "leads.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_the_domain_is_reduced_to_the_registrable_host() -> None:
    assert normalize_domain("https://www.Example.co.uk/contact") == "example.co.uk"


def test_an_unknown_trade_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    path = write(tmp_path, "Acme Ltd,123,acme.co.uk,plumbers,London,\n")

    with pytest.raises(SystemExit, match="unknown industry"):
        read_rows(path)


async def _campaign(workspace_id: uuid.UUID, industry: Industry) -> uuid.UUID:
    async with get_sessionmaker()() as session, session.begin():
        campaign = Campaign(
            workspace_id=workspace_id,
            name=f"Import {industry.value}",
            slug=f"import-{industry.value}-{uuid.uuid4().hex[:6]}",
            status=CampaignStatus.PAUSED,
            industry=industry,
            target_country_code="GB",
        )
        session.add(campaign)
        await session.flush()
        return campaign.id


@pytest.mark.asyncio
async def test_businesses_land_as_discovered_with_no_address(
    workspace, tmp_path: Path
) -> None:
    law = await _campaign(workspace, Industry.LAW_FIRM)
    rows = read_rows(
        write(
            tmp_path,
            "Abc Solicitors Ltd,01234567,www.abcsolicitors.example,law_firm,Leeds,"
            "info@abcsolicitors.example\n"
            "Abc Solicitors Ltd,01234567,abcsolicitors.example,law_firm,Leeds,\n"
            "Gone Ltd,07654321,gone.example,law_firm,York,\n",
        )
    )
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            SuppressionEntry(
                workspace_id=workspace,
                scope="domain",
                normalized_value="gone.example",
                reason="unsubscribe",
                source="test",
                suppressed_at=dt.datetime.now(dt.UTC),
            )
        )

    dry = await import_rows(
        workspace, rows, {Industry.LAW_FIRM: law}, label="t", apply=False
    )
    assert dry == {
        "added": 1,
        "already held": 0,
        "suppressed": 1,
        "duplicate in file": 1,
    }

    first = await import_rows(
        workspace, rows, {Industry.LAW_FIRM: law}, label="t", apply=True
    )
    again = await import_rows(
        workspace, rows, {Industry.LAW_FIRM: law}, label="t", apply=True
    )
    assert first["added"] == 1
    assert again["added"] == 0 and again["already held"] == 1

    async with get_sessionmaker()() as session:
        lead = (
            await session.execute(select(Lead).where(Lead.workspace_id == workspace))
        ).scalar_one()
        org = await session.get(Organization, lead.organization_id)
        channels = await session.scalar(
            select(func.count())
            .select_from(ContactChannel)
            .where(ContactChannel.workspace_id == workspace)
        )
    assert lead.status is LeadStatus.DISCOVERED
    assert lead.campaign_id == law
    assert org.canonical_domain == "abcsolicitors.example"
    assert org.provenance[0]["source_id"] == "01234567"
    # The address in the file is not taken: the crawl finds the firm's own.
    assert channels == 0


@pytest.mark.asyncio
async def test_a_campaign_of_another_trade_is_refused(workspace, tmp_path: Path) -> None:
    dentists = await _campaign(workspace, Industry.DENTIST)
    rows = read_rows(write(tmp_path, "Abc Ltd,1,abc.example,law_firm,Leeds,\n"))

    with pytest.raises(SystemExit, match="is dentist"):
        await import_rows(
            workspace, rows, {Industry.LAW_FIRM: dentists}, label="t", apply=True
        )
