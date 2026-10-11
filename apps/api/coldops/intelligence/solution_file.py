"""The solution file: the plan a business gets after it says yes.

Programme item N. The original spec had an LLM write seven pages after a deep
research pass (LinkedIn, social, arXiv, GitHub). Built instead from what
ColdOps measured and planned, because three standing rules forbid the rest:
no scraping LinkedIn, no paid spend, and *never invent* -- seven pages of
model prose about somebody's business is where an invented claim gets in.

So every sentence here is something ColdOps already holds and can stand
behind: each finding as measured on the business's own site (with the
screenshot), what it costs and how it is fixed, the delivery plan research
derived for each offer (every step traced to a finding), the operator's own
project as proof, published sources that answer when checked, and the next
step. The flowchart is drawn from the plan's steps, not by a model.

It is rendered when a reply is read as positive, attached to the reply-desk
draft, and goes nowhere until the operator approves that reply.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from html import escape

from coldops.intelligence.case_studies import CaseStudy
from coldops.intelligence.evidence_page import EvidencePage, PageFinding
from coldops.intelligence.references import Reference

#: Generous for several pages with screenshots; the renderer refuses past it.
MAX_SOLUTION_BYTES = 2_500_000
MAX_SOLUTION_PAGES = 8
#: The plans the file walks through, best first.
MAX_PLANS = 3


@dataclasses.dataclass(frozen=True)
class Plan:
    title: str
    summary: str
    steps: tuple[str, ...]
    effort: str | None
    prerequisites: tuple[str, ...]


def filename(business_name: str | None) -> str:
    import re

    name = re.sub(r"[^\w .,&'-]+", " ", business_name or "").strip()
    name = re.sub(r"\s+", " ", name)[:60].strip(" .-")
    return f"{name} - plan.pdf" if name else "Plan.pdf"


def attachment_note(domain: str | None) -> str:
    where = domain or "your website"
    return (
        f"I have attached the plan for {where}: what I found, how I would fix each "
        "part, and the steps in order."
    )


def _p(text: str | None) -> str:
    return f"<p>{escape(text.strip())}</p>" if text and text.strip() else ""


def _flowchart(steps: tuple[str, ...]) -> str:
    """The plan's steps as numbered boxes joined by arrows. Inline SVG, no model."""
    width, box_h, gap = 520, 46, 22
    height = len(steps) * box_h + (len(steps) - 1) * gap
    parts = [
        f'<svg class="flow" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" xmlns="http://www.w3.org/2000/svg" role="img">'
    ]
    for i, step in enumerate(steps):
        y = i * (box_h + gap)
        label = step if len(step) <= 92 else step[:89].rstrip() + "..."
        parts.append(
            f'<rect x="1" y="{y + 1}" width="{width - 2}" height="{box_h - 2}" rx="7" '
            'fill="#eef3fa" stroke="#1f4f99" stroke-width="1"/>'
            f'<circle cx="24" cy="{y + box_h / 2}" r="12" fill="#1f4f99"/>'
            f'<text x="24" y="{y + box_h / 2 + 4}" text-anchor="middle" font-size="11" '
            f'font-weight="600" fill="#fff">{i + 1}</text>'
            f'<foreignObject x="44" y="{y + 4}" width="{width - 54}" height="{box_h - 8}">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" class="step">{escape(label)}</div>'
            "</foreignObject>"
        )
        if i < len(steps) - 1:
            ay = y + box_h
            parts.append(
                f'<path d="M{width / 2} {ay} L{width / 2} {ay + gap - 6}" stroke="#1f4f99" '
                'stroke-width="1.5"/>'
                f'<path d="M{width / 2 - 5} {ay + gap - 8} L{width / 2} {ay + gap - 1} '
                f'L{width / 2 + 5} {ay + gap - 8}" fill="none" stroke="#1f4f99" '
                'stroke-width="1.5"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _finding(f: PageFinding, index: int) -> str:
    where = (
        f'<p class="where">Seen on <span>{escape(f.page_url)}</span>, '
        f"{escape(f.measured_at.strftime('%d %B %Y').lstrip('0'))}</p>"
        if f.page_url
        else ""
    )
    return (
        f'<section class="finding"><h3>{index}. {escape(f.title)}</h3>'
        f"{_p(f.observed_value)}{where}"
        '<div class="grid">'
        f"<div><h4>What it costs you</h4>{_p(f.business_impact) or _p('Not measured.')}</div>"
        f"<div><h4>What fixes it</h4>{_p(f.recommended_solution) or _p('Not measured.')}</div>"
        "</div></section>"
    )


def build_html(
    page: EvidencePage,
    *,
    plans: list[Plan],
    references: list[Reference],
    case_study: CaseStudy | None,
    evidence_url: str | None,
    sender_name: str,
    sender_site: str | None,
    today: dt.date | None = None,
) -> str:
    """The whole document. Pure: same inputs, same file."""
    when = (today or dt.datetime.now(dt.UTC).date()).strftime("%d %B %Y").lstrip("0")
    name = escape(page.business_name)
    domain = escape(page.domain or "")

    shots = ""
    if "desktop" in page.shots:
        shots = (
            '<figure class="desk"><img data-crop="0.56" data-width="760" '
            f'src="artifact:{escape(page.shots["desktop"][0], quote=True)}" alt="">'
            "<figcaption>Your homepage, as I saw it</figcaption></figure>"
        )
    findings = "".join(_finding(f, i) for i, f in enumerate(page.findings, 1))
    plan_html = "".join(
        '<section class="plan">'
        f"<h3>{escape(p.title)}</h3>{_p(p.summary)}"
        f"{_flowchart(p.steps) if p.steps else ''}"
        '<div class="grid">'
        f"<div><h4>Size of the job</h4>{_p((p.effort or 'not estimated').capitalize())}</div>"
        "<div><h4>What I would need from you</h4>"
        + (
            "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in p.prerequisites) + "</ul>"
            if p.prerequisites
            else _p("Nothing beyond access to the site.")
        )
        + "</div></div></section>"
        for p in plans[:MAX_PLANS]
    )
    proof = ""
    if case_study is not None:
        link = f'<p class="link">{escape(case_study.url)}</p>' if case_study.url else ""
        proof = f"<section><h2>Who would do the work</h2>{_p(case_study.sentence())}{link}</section>"
    sources = ""
    if references:
        sources = (
            "<section><h2>Sources</h2><ul class='refs'>"
            + "".join(
                f"<li>{escape(r.publisher)}: {escape(r.title)}<br>"
                f'<span class="link">{escape(r.url)}</span></li>'
                for r in references
            )
            + "</ul></section>"
        )
    evidence = (
        "<p>Every measurement behind this plan, with the date it was taken: "
        f'<span class="link">{escape(evidence_url)}</span></p>'
        if evidence_url
        else ""
    )
    site = f" &middot; {escape(sender_site)}" if sender_site else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{name} - plan</title>
<style>
@page {{ size: A4; margin: 16mm 17mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font: 10.5pt/1.5 "Segoe UI", Helvetica, Arial, sans-serif; color: #1b2430; }}
header {{ border-bottom: 1.5pt solid #1f4f99; padding-bottom: 3mm; margin-bottom: 6mm; }}
h1 {{ font-size: 21pt; line-height: 1.15; margin: 0 0 1mm; letter-spacing: -0.01em; }}
.meta {{ font-size: 9pt; color: #5b6676; }}
h2 {{ font-size: 13pt; color: #1f4f99; margin: 7mm 0 3mm; break-after: avoid; }}
h3 {{ font-size: 11.5pt; margin: 0 0 1.5mm; break-after: avoid; }}
h4 {{ font-size: 8.5pt; text-transform: uppercase; letter-spacing: 0.07em; color: #5b6676;
  margin: 0 0 1mm; }}
p {{ margin: 0 0 2mm; }}
ul {{ margin: 0 0 2mm; padding-left: 5mm; }}
figure {{ margin: 0 0 4mm; }}
figure img {{ display: block; width: 150mm; border: 0.75pt solid #c9d1dc; border-radius: 2mm; }}
figcaption {{ font-size: 8pt; color: #5b6676; margin-top: 1.5mm; }}
.finding, .plan {{ border: 0.75pt solid #d5dde8; border-radius: 2.5mm; padding: 4mm 5mm;
  margin-bottom: 4mm; break-inside: avoid; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; margin-top: 2mm; }}
.where {{ font-size: 9pt; color: #5b6676; }}
.where span, .link {{ font-family: Consolas, "Courier New", monospace; font-size: 8.5pt;
  word-break: break-all; color: #1f4f99; }}
.flow {{ display: block; margin: 3mm 0; max-width: 100%; height: auto; }}
.step {{ font-size: 9.5pt; line-height: 1.3; color: #1b2430; display: flex; align-items: center;
  height: 100%; }}
.refs li {{ margin-bottom: 1.5mm; }}
.next {{ background: #eef3fa; border-radius: 2.5mm; padding: 4mm 5mm; margin-top: 6mm;
  break-inside: avoid; }}
footer {{ margin-top: 8mm; border-top: 0.75pt solid #c9d1dc; padding-top: 2.5mm;
  font-size: 8.5pt; color: #5b6676; }}
</style></head>
<body>
<header><h1>A plan for {name}</h1>
<div class="meta">{domain} &middot; {escape(when)} &middot; prepared by {escape(sender_name)}</div></header>
{shots}
<h2>What I found</h2>
<p>Each of these was measured on your own site, by visiting it as a customer would.</p>
{findings}
<h2>How I would fix it</h2>
{plan_html or _p("The fixes are the ones listed against each finding above.")}
{proof}
{sources}
<section class="next"><h2 style="margin-top:0">The next step</h2>
<p>A short call to agree which of these to start with and when. Reply to this email with a
time that suits you and I will send an invitation.</p>{evidence}</section>
<footer>{escape(sender_name)}{site}. Nothing in this plan is a guess about your business:
every finding was measured on your website, and every step traces to one of them.</footer>
</body></html>"""


__all__ = [
    "MAX_SOLUTION_BYTES",
    "MAX_SOLUTION_PAGES",
    "Plan",
    "attachment_note",
    "build_html",
    "filename",
]
