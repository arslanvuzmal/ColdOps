"""Lead features for M3: the business's technology, and where it stands among rivals.

Programme item J ("competitors + tech"), built as the spec decided: not as
something a message says, but as inputs for the lead-propensity model (M3),
which must beat the hand-weighted score on held-out leads before it ranks a
single lead. Nothing here is ever a claim in an email.

**Technology** -- from what the crawler recorded on the business's own pages:
the website platform, and three signals of how it already spends on growth:
analytics, an advertising pixel (it pays for ads), a marketing CRM.

**Competition** -- rivals are businesses of the same industry within
:data:`RIVAL_RADIUS_KM`, from the coordinates Google Maps gave. Where this
business's rating and review count rank among them, how many there are, and
how many of them advertise. A business behind its rivals has a reason to act;
one alone in its area may have no pressure to.

**Labels** -- what happened, in M3's staged targets: contacted, seen (a person
on the evidence page), replied (a person), replied positively.

No names, addresses, domains or emails: a row is identified by lead id only.
"""

from __future__ import annotations

import csv
import dataclasses
import math
import pathlib
import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Rivals are within this distance. A local business's customers rarely
#: compare beyond it.
RIVAL_RADIUS_KM = 10.0

#: The platforms the crawler recognises, in the order a row reports the first.
PLATFORMS = ("wordpress", "shopify", "squarespace", "webflow", "wix", "nextjs")
ANALYTICS = frozenset({"google-analytics"})
AD_PIXEL = frozenset({"meta-pixel"})
MARKETING_CRM = frozenset({"hubspot"})

#: About 10 km of latitude; the grid that keeps the rival search local.
_CELL_DEG = 0.1


@dataclasses.dataclass
class LeadFeatures:
    lead_id: uuid.UUID
    industry: str
    score: int | None
    pages_crawled: int
    platform: str
    has_analytics: bool
    has_ad_pixel: bool
    has_marketing_crm: bool
    rating: float | None
    review_count: int | None
    rivals: int = 0
    rating_percentile: float | None = None
    reviews_percentile: float | None = None
    rivals_advertising_share: float | None = None
    contacted: bool = False
    seen: bool = False
    replied: bool = False
    replied_positive: bool = False
    _lat: float | None = dataclasses.field(default=None, repr=False)
    _lon: float | None = dataclasses.field(default=None, repr=False)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance; plenty precise at 10 km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _percentile(value: float | None, others: list[float]) -> float | None:
    """Share of rivals this business is ahead of (ties count half)."""
    if value is None or not others:
        return None
    below = sum(o < value for o in others)
    equal = sum(o == value for o in others)
    return round((below + equal / 2) / len(others), 4)


def platform_of(technologies: set[str]) -> str:
    for name in PLATFORMS:
        if name in technologies:
            return name
    return "unknown"


def add_rivals(rows: list[LeadFeatures]) -> None:
    """Fill the competition features, in place."""
    grid: dict[tuple[str, int, int], list[LeadFeatures]] = defaultdict(list)
    for r in rows:
        if r._lat is not None and r._lon is not None:
            grid[(r.industry, int(r._lat // _CELL_DEG), int(r._lon // _CELL_DEG))].append(
                r
            )
    for r in rows:
        if r._lat is None or r._lon is None:
            continue
        cy, cx = int(r._lat // _CELL_DEG), int(r._lon // _CELL_DEG)
        # Longitude cells shrink towards the poles; widen the search to match.
        span = max(1, math.ceil(1 / max(math.cos(math.radians(r._lat)), 0.2)))
        rivals = [
            o
            for dy in (-1, 0, 1)
            for dx in range(-span, span + 1)
            for o in grid.get((r.industry, cy + dy, cx + dx), ())
            if o is not r
            and o._lat is not None
            and o._lon is not None
            and _km(r._lat, r._lon, o._lat, o._lon) <= RIVAL_RADIUS_KM
        ]
        r.rivals = len(rivals)
        r.rating_percentile = _percentile(
            r.rating, [o.rating for o in rivals if o.rating is not None]
        )
        r.reviews_percentile = _percentile(
            float(r.review_count) if r.review_count is not None else None,
            [float(o.review_count) for o in rivals if o.review_count is not None],
        )
        crawled = [o for o in rivals if o.pages_crawled > 0]
        r.rivals_advertising_share = (
            round(sum(o.has_ad_pixel for o in crawled) / len(crawled), 4)
            if crawled
            else None
        )


async def lead_features(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[LeadFeatures]:
    """One row per lead in the workspace."""
    leads = (
        await session.execute(
            text(
                """
                SELECT l.id, o.industry, l.latest_score, o.rating, o.review_count,
                       ol.latitude, ol.longitude
                  FROM leads l
                  JOIN organizations o ON o.id = l.organization_id
                  LEFT JOIN organization_locations ol
                         ON ol.organization_id = o.id AND ol.is_primary
                 WHERE l.workspace_id = :ws
                """
            ),
            {"ws": workspace_id},
        )
    ).all()
    tech: dict[uuid.UUID, set[str]] = defaultdict(set)
    pages: dict[uuid.UUID, int] = defaultdict(int)
    for row in (
        await session.execute(
            text(
                """
                SELECT r.lead_id, p.observations -> 'technologies' AS tech
                  FROM pages p
                  JOIN crawl_runs c ON c.id = p.crawl_run_id
                  JOIN research_runs r ON r.id = c.research_run_id
                 WHERE r.workspace_id = :ws
                """
            ),
            {"ws": workspace_id},
        )
    ).all():
        pages[row.lead_id] += 1
        if isinstance(row.tech, list):
            tech[row.lead_id].update(str(t).lower() for t in row.tech)
    labels = {
        row.lead_id: row
        for row in (
            await session.execute(
                text(
                    """
                    SELECT l.id AS lead_id,
                      EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = l.id
                              AND m.sent_at IS NOT NULL) AS contacted,
                      EXISTS (SELECT 1 FROM engagement_events e WHERE e.lead_id = l.id
                              AND e.grade IN ('confirmed', 'likely')) AS seen,
                      EXISTS (SELECT 1 FROM inbound_messages i
                                JOIN reply_classifications c ON c.inbound_message_id = i.id
                               WHERE i.lead_id = l.id AND c.reply_class NOT IN
                                 ('automated', 'bounce', 'out_of_office', 'unknown'))
                        AS replied,
                      EXISTS (SELECT 1 FROM inbound_messages i
                                JOIN reply_classifications c ON c.inbound_message_id = i.id
                               WHERE i.lead_id = l.id AND c.reply_class IN
                                 ('interested', 'wants_more_info', 'wants_pricing',
                                  'wants_call')) AS replied_positive
                      FROM leads l WHERE l.workspace_id = :ws
                    """
                ),
                {"ws": workspace_id},
            )
        ).all()
    }

    rows: list[LeadFeatures] = []
    for lead in leads:
        found = tech.get(lead.id, set())
        label = labels.get(lead.id)
        rows.append(
            LeadFeatures(
                lead_id=lead.id,
                industry=str(
                    lead.industry.value
                    if hasattr(lead.industry, "value")
                    else lead.industry
                ),
                score=lead.latest_score,
                pages_crawled=pages.get(lead.id, 0),
                platform=platform_of(found),
                has_analytics=bool(found & ANALYTICS),
                has_ad_pixel=bool(found & AD_PIXEL),
                has_marketing_crm=bool(found & MARKETING_CRM),
                rating=float(lead.rating) if lead.rating is not None else None,
                review_count=lead.review_count,
                contacted=bool(label and label.contacted),
                seen=bool(label and label.seen),
                replied=bool(label and label.replied),
                replied_positive=bool(label and label.replied_positive),
                _lat=lead.latitude,
                _lon=lead.longitude,
            )
        )
    add_rivals(rows)
    return rows


COLUMNS = [f.name for f in dataclasses.fields(LeadFeatures) if not f.name.startswith("_")]


def write_csv(rows: list[LeadFeatures], path: pathlib.Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow(
                ["" if getattr(r, c) is None else getattr(r, c) for c in COLUMNS]
            )
    return len(rows)


__all__ = [
    "COLUMNS",
    "RIVAL_RADIUS_KM",
    "LeadFeatures",
    "add_rivals",
    "lead_features",
    "platform_of",
    "write_csv",
]
