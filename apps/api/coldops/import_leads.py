"""Load a list of businesses somebody else found, without trusting the rest of it.

    python -m coldops.import_leads FILE --campaign law_firm=<uuid> ... [--apply]

The list that prompted this (an outside scraper's "UK business leads", October
2026) named 11,518 directors at 3,145 domains, every address marked ``valid``
at 0.95. None of that was measured. The scraper built the website from the
company name -- ``https://www.<companyname>.co.uk`` -- and the address from the
director's name on that guessed domain. 2,394 of the domains do not exist.

So this takes **businesses, never addresses**. A row is a company name, its
Companies House number, a domain somebody has checked is really that company's
site, and the trade. The address comes the way every other lead's does: the
research crawl reads the firm's own pages, and invariant 6 refuses anything it
did not find there. Importing the guessed ``first.last@`` would have stored them
as PATTERN_GUESS and refused them anyway; not importing them means nothing has
to remember to refuse them.

**Nothing here authorises a send.** Leads land in ``discovered`` in campaigns
the operator names. The orchestrator works active campaigns only, so a lead in
a paused one waits there until the operator switches it on, and every draft it
eventually produces still goes through approval.

Idempotent on domain: a business the workspace already holds, or whose domain
is suppressed, is skipped, so running the same file twice adds nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from coldops.db.enums import Industry, LeadStatus
from coldops.db.models import (
    Campaign,
    Lead,
    LeadSource,
    Organization,
    OrganizationDomain,
    OrganizationLocation,
    Workspace,
)
from coldops.db.models.compliance import SuppressionEntry
from coldops.db.session import dispose_engine, get_sessionmaker
from coldops.runtime import configure_event_loop

SOURCE_KIND = "csv_import"
COMPANIES_HOUSE = "https://find-and-update.company-information.service.gov.uk/company/"


@dataclass(frozen=True, slots=True)
class ImportRow:
    """One business. Deliberately has no field for a person or an address."""

    company_name: str
    company_number: str
    domain: str
    industry: Industry
    location: str


def normalize_domain(value: str) -> str:
    domain = value.strip().lower()
    for prefix in ("https://", "http://"):
        domain = domain.removeprefix(prefix)
    return domain.split("/")[0].removeprefix("www.")


def read_rows(path: Path) -> list[ImportRow]:
    """Every row, or SystemExit naming the first one that is not a business."""
    rows: list[ImportRow] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for number, raw in enumerate(csv.DictReader(handle), start=2):
            domain = normalize_domain(raw.get("domain") or "")
            name = (raw.get("company_name") or "").strip()
            if not domain or "." not in domain or not name:
                raise SystemExit(f"line {number}: needs company_name and domain")
            try:
                industry = Industry(raw.get("industry", "").strip())
            except ValueError:
                raise SystemExit(
                    f"line {number}: unknown industry {raw.get('industry')!r}"
                ) from None
            rows.append(
                ImportRow(
                    company_name=name,
                    company_number=(raw.get("company_number") or "").strip(),
                    domain=domain,
                    industry=industry,
                    location=" ".join((raw.get("location") or "").split()),
                )
            )
    return rows


def parse_campaigns(values: list[str]) -> dict[Industry, uuid.UUID]:
    mapping: dict[Industry, uuid.UUID] = {}
    for value in values:
        industry, _, campaign_id = value.partition("=")
        try:
            mapping[Industry(industry)] = uuid.UUID(campaign_id)
        except ValueError:
            raise SystemExit(f"--campaign {value!r}: expected industry=<uuid>") from None
    return mapping


async def import_rows(
    workspace_id: uuid.UUID,
    rows: list[ImportRow],
    campaigns: dict[Industry, uuid.UUID],
    *,
    label: str,
    apply: bool,
) -> dict[str, int]:
    """Create the new businesses as discovered leads. Returns counts by outcome."""
    counts = {"added": 0, "already held": 0, "suppressed": 0, "duplicate in file": 0}
    now = dt.datetime.now(dt.UTC)
    async with get_sessionmaker()() as session, session.begin():
        for industry, campaign_id in campaigns.items():
            campaign = await session.get(Campaign, campaign_id)
            if campaign is None or campaign.workspace_id != workspace_id:
                raise SystemExit(f"campaign {campaign_id} is not in this workspace")
            if campaign.industry is not industry:
                raise SystemExit(
                    f"campaign {campaign.name!r} is {campaign.industry.value}, "
                    f"not {industry.value}"
                )
        missing = {row.industry for row in rows} - campaigns.keys()
        if missing:
            raise SystemExit(
                "no --campaign for " + ", ".join(sorted(i.value for i in missing))
            )

        domains = {row.domain for row in rows}
        held = set(
            (
                await session.execute(
                    select(Organization.canonical_domain).where(
                        Organization.workspace_id == workspace_id,
                        Organization.canonical_domain.in_(domains),
                    )
                )
            ).scalars()
        )
        suppressed = set(
            (
                await session.execute(
                    select(SuppressionEntry.normalized_value).where(
                        SuppressionEntry.workspace_id == workspace_id,
                        SuppressionEntry.scope == "domain",
                        SuppressionEntry.normalized_value.in_(domains),
                    )
                )
            ).scalars()
        )

        source_id: uuid.UUID | None = None
        seen: set[str] = set()
        for row in rows:
            if row.domain in seen:
                counts["duplicate in file"] += 1
                continue
            seen.add(row.domain)
            if row.domain in suppressed:
                counts["suppressed"] += 1
                continue
            if row.domain in held:
                counts["already held"] += 1
                continue
            counts["added"] += 1
            if not apply:
                continue

            if source_id is None:
                source = LeadSource(
                    workspace_id=workspace_id,
                    kind=SOURCE_KIND,
                    label=label[:200],
                    query_parameters={"imported_at": now.isoformat()},
                    records_returned=len(rows),
                    usage_policy={"stores": ["name", "company_number", "website"]},
                )
                session.add(source)
                await session.flush()
                source_id = source.id

            org = Organization(
                workspace_id=workspace_id,
                display_name=row.company_name[:300],
                legal_name=row.company_name[:300],
                normalized_name=row.company_name.lower().strip()[:300],
                industry=row.industry,
                canonical_domain=row.domain[:253],
                website_url=f"https://{row.domain}",
                provenance=[
                    {
                        "source": SOURCE_KIND,
                        "source_id": row.company_number or None,
                        "registry_url": (
                            COMPANIES_HOUSE + row.company_number
                            if row.company_number
                            else None
                        ),
                        "retrieved_at": now.isoformat(),
                        "fields": ["name", "company_number", "website", "address"],
                    }
                ],
            )
            session.add(org)
            await session.flush()
            session.add(
                OrganizationLocation(
                    workspace_id=workspace_id,
                    organization_id=org.id,
                    formatted_address=row.location or None,
                    country_code="GB",
                    timezone="Europe/London",
                    is_primary=True,
                )
            )
            session.add(
                OrganizationDomain(
                    workspace_id=workspace_id,
                    organization_id=org.id,
                    domain=row.domain[:253],
                    is_primary=True,
                    # Checked by whoever built the file, not by ColdOps. The
                    # research crawl confirms it, exactly as for a Places lead.
                    verified_at=None,
                )
            )
            session.add(
                Lead(
                    workspace_id=workspace_id,
                    campaign_id=campaigns[row.industry],
                    organization_id=org.id,
                    lead_source_id=source_id,
                    status=LeadStatus.DISCOVERED,
                )
            )
        if not apply:
            await session.rollback()
    return counts


async def _workspace_id(slug: str) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        found = (
            await session.execute(select(Workspace).where(Workspace.slug == slug))
        ).scalar_one_or_none()
        if found is None:
            raise SystemExit(f"workspace {slug!r} does not exist")
        return found.id


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--workspace", default="titan")
    parser.add_argument(
        "--campaign",
        action="append",
        default=[],
        metavar="INDUSTRY=UUID",
        help="which campaign each trade's leads go into; repeat per trade",
    )
    parser.add_argument("--label", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the leads; without it, print what would be added",
    )
    args = parser.parse_args()

    rows = read_rows(args.file)
    digest = hashlib.sha256(args.file.read_bytes()).hexdigest()[:12]
    workspace_id = await _workspace_id(args.workspace)
    counts = await import_rows(
        workspace_id,
        rows,
        parse_campaigns(args.campaign),
        label=args.label or f"{args.file.name} ({digest})",
        apply=args.apply,
    )

    print(f"{len(rows)} rows from {args.file.name}")
    print("applied" if args.apply else "dry run -- nothing written")
    for outcome, count in counts.items():
        print(f"  {outcome:<18} {count}")
    print("Leads are 'discovered'; no address was imported and nothing is sent.")
    await dispose_engine()
    return 0


if __name__ == "__main__":
    configure_event_loop()
    raise SystemExit(asyncio.run(main()))
