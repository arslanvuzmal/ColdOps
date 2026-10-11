"""Item J: technology and competition, as M3 features -- never as claims."""

from __future__ import annotations

import csv
import pathlib
import tempfile
import uuid

import pytest
from coldops.ml import lead_features as lf


def row(industry: str, lat: float, lon: float, *, rating=None, reviews=None, pixel=False):
    return lf.LeadFeatures(
        lead_id=uuid.uuid4(),
        industry=industry,
        score=None,
        pages_crawled=3,
        platform="wordpress",
        has_analytics=False,
        has_ad_pixel=pixel,
        has_marketing_crm=False,
        rating=rating,
        review_count=reviews,
        _lat=lat,
        _lon=lon,
    )


def test_rivals_are_same_industry_and_nearby() -> None:
    # London: 0.05 deg of latitude is about 5.6 km, 0.5 deg about 56 km.
    me = row("dentist", 51.50, -0.12, rating=4.0, reviews=50)
    near = row("dentist", 51.55, -0.12, rating=4.8, reviews=300, pixel=True)
    near2 = row("dentist", 51.48, -0.10, rating=3.5, reviews=10)
    far = row("dentist", 52.00, -0.12, rating=5.0, reviews=900)
    other_trade = row("law_firm", 51.50, -0.12, rating=4.9, reviews=900)
    rows = [me, near, near2, far, other_trade]

    lf.add_rivals(rows)

    assert me.rivals == 2
    assert me.rating_percentile == 0.5  # ahead of 3.5, behind 4.8
    assert me.reviews_percentile == 0.5
    assert me.rivals_advertising_share == 0.5
    assert other_trade.rivals == 0 and other_trade.rating_percentile is None


def test_a_business_without_coordinates_has_no_rivals() -> None:
    lonely = row("dentist", 51.5, -0.1)
    lonely._lat = None
    lf.add_rivals([lonely, row("dentist", 51.5, -0.1)])
    assert lonely.rivals == 0


def test_the_platform_is_the_first_recognised_one() -> None:
    assert lf.platform_of({"google-analytics", "wordpress"}) == "wordpress"
    assert lf.platform_of({"meta-pixel"}) == "unknown"


def test_no_personal_data_is_exported() -> None:
    """Identified by lead id only: no name, address, domain or email."""
    forbidden = {"name", "email", "domain", "address", "phone", "website", "url"}
    assert not any(part in col for col in lf.COLUMNS for part in forbidden)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_export_runs_on_real_rows(db_session, workspace) -> None:
    from coldops.db.session import get_sessionmaker

    from tests.delivery.conftest import build_sendable

    sendable = await build_sendable(db_session, workspace)

    async with get_sessionmaker()() as s:
        rows = await lf.lead_features(s, workspace_id=sendable.workspace_id)
    [only] = rows
    assert only.lead_id == sendable.lead_id
    assert only.contacted is False and only.replied is False

    path = pathlib.Path(tempfile.mkdtemp(prefix="coldops-feat-")) / "lead-features.csv"
    assert lf.write_csv(rows, path) == 1
    with path.open(encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == lf.COLUMNS
