"""Render the solution file for every reply that said yes (programme item N).

Runs inside the five-minute PDF sweep. A candidate is a reply-desk draft --
the suggested answer to an inbound message -- whose message was read as
positive (interested, wants more information, wants pricing, wants a call),
still waiting on the operator, with no file rendered yet. The file is saved
under the draft's id; the outbox attaches it when, and only when, the
operator approves and sends that reply.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid

from sqlalchemy import text

from coldops.config import get_settings
from coldops.db.session import workspace_session
from coldops.intelligence import audit_pdf, case_studies, evidence_page, solution_file
from coldops.intelligence.composer import family_for
from coldops.intelligence.references import Reference
from coldops.providers.browser_client import BrowserWorkerClient

logger = logging.getLogger(__name__)

#: The reply classes that earn a plan.
POSITIVE = ("interested", "wants_more_info", "wants_pricing", "wants_call")

_CANDIDATES = text(
    """
    SELECT d.id AS draft_id, d.lead_id
      FROM message_drafts d
      JOIN reply_classifications c ON c.suggested_reply_draft_id = d.id
     WHERE d.workspace_id = :ws
       AND d.template_key LIKE 'reply:%'
       AND d.status IN ('generated', 'awaiting_approval')
       AND d.created_at > now() - interval '14 days'
       AND CAST(c.reply_class AS text) = ANY(CAST(:positive AS text[]))
     ORDER BY d.created_at
     LIMIT 10
    """
)

_PLANS = text(
    """
    SELECT o.title, s.summary, s.implementation_outline, s.estimated_effort,
           s.prerequisites
      FROM business_opportunities o
      JOIN solution_recommendations s ON s.opportunity_id = o.id
     WHERE o.workspace_id = :ws AND o.lead_id = :lead AND o.deliverable
     ORDER BY o.priority DESC, o.created_at DESC
    """
)


@dataclasses.dataclass(frozen=True)
class SolutionResult:
    rendered: int = 0
    refused: int = 0
    detail: tuple[str, ...] = ()


async def verified(references: list[Reference]) -> list[Reference]:
    """Only sources that answer today. A dead link in a plan reads as careless,
    and a source nobody can open supports nothing."""
    import httpx

    kept: list[Reference] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(
        timeout=8.0, follow_redirects=True, headers={"user-agent": "ColdOps link check"}
    ) as client:
        for ref in references:
            if ref.url in seen:
                continue
            seen.add(ref.url)
            try:
                response = await client.head(ref.url)
                if response.status_code >= 400:
                    response = await client.get(ref.url)
                if response.status_code < 400:
                    kept.append(ref)
            except httpx.HTTPError:
                continue
    return kept


async def build_for(
    workspace_id: uuid.UUID, lead_id: uuid.UUID, *, check_links: bool = True
) -> tuple[str, str | None] | None:
    """The HTML for one lead's solution file, and its business name."""
    settings = get_settings()
    async with workspace_session(workspace_id) as session:
        page = await evidence_page.load_page(session, lead_id=lead_id)
        if page is None or page.workspace_id != workspace_id or not page.findings:
            return None
        plans: list[solution_file.Plan] = []
        seen_titles: set[str] = set()
        for row in (
            await session.execute(_PLANS, {"ws": workspace_id, "lead": lead_id})
        ).all():
            if row.title in seen_titles:
                continue
            seen_titles.add(row.title)
            plans.append(
                solution_file.Plan(
                    title=row.title,
                    summary=row.summary,
                    steps=tuple(row.implementation_outline or ()),
                    effort=row.estimated_effort,
                    prerequisites=tuple(row.prerequisites or ()),
                )
            )
        industry = await session.scalar(
            text(
                "SELECT o.industry FROM leads l JOIN organizations o "
                "ON o.id = l.organization_id WHERE l.id = :lead AND l.workspace_id = :ws"
            ),
            {"ws": workspace_id, "lead": lead_id},
        )

    lead_finding = page.findings[0]
    study = case_studies.select(
        case_studies.registry(settings.case_studies_path),
        industry=str(industry) if industry else None,
        family=family_for(lead_finding.issue_type),
        issue_type=lead_finding.issue_type,
    )
    references = [r for f in page.findings for r in f.references]
    if check_links:
        references = await verified(references)
    evidence_url = (
        evidence_page.evidence_url(
            settings.evidence_base_url, lead_id, settings.evidence_secret
        )
        if settings.evidence_base_url and settings.evidence_secret
        else None
    )
    html = solution_file.build_html(
        page,
        plans=plans,
        references=references,
        case_study=study,
        evidence_url=evidence_url,
        sender_name=settings.owner_name,
        sender_site=str(settings.owner_portfolio_url).rstrip("/") or None,
    )
    return html, page.business_name


async def render_solution_files(workspace_id: uuid.UUID) -> SolutionResult:
    settings = get_settings()
    if not settings.artifact_dir:
        return SolutionResult(detail=("no artifact directory is configured",))
    async with workspace_session(workspace_id) as session:
        candidates = (
            await session.execute(
                _CANDIDATES, {"ws": workspace_id, "positive": list(POSITIVE)}
            )
        ).all()

    rendered = refused = 0
    detail: list[str] = []
    client = BrowserWorkerClient(settings)
    try:
        for draft_id, lead_id in candidates:
            path = audit_pdf.pdf_path(settings.artifact_dir, draft_id)
            if path is not None and path.exists():
                continue
            built = await build_for(workspace_id, lead_id)
            if built is None:
                continue
            html, _ = built
            outcome = await client.render_pdf(
                draft_id=draft_id,
                html=html,
                max_bytes=solution_file.MAX_SOLUTION_BYTES,
                max_pages=solution_file.MAX_SOLUTION_PAGES,
            )
            if outcome.key:
                rendered += 1
            else:
                refused += 1
                detail.append(f"{draft_id}: {outcome.refused or outcome.error}")
    finally:
        await client.aclose()
    if rendered or refused:
        logger.info(
            "solution files rendered",
            extra={"rendered": rendered, "refused": refused, "detail": detail[:5]},
        )
    return SolutionResult(rendered=rendered, refused=refused, detail=tuple(detail[:20]))


__all__ = ["POSITIVE", "SolutionResult", "build_for", "render_solution_files", "verified"]
