"""Markdown brief renderer.

render_brief(grounded_brief, run_id) -> str

Produces a professional markdown document and writes it to
output/brief_{run_id}.md relative to the project root.
Unverified claims are visually prominent so a human reviewer cannot miss them.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from pipelineradar.schemas import Brief, GroundedBrief

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_OUTPUT_DIR = Path("output")


def render_brief(grounded: GroundedBrief, run_id: str) -> str:
    """Render a GroundedBrief to markdown and write to output/."""
    md = _build_markdown(grounded, run_id)
    _write_file(md, run_id)
    return md


def brief_to_db_model(grounded: GroundedBrief, markdown: str, run_id: str) -> Brief:
    """Convert a GroundedBrief + rendered markdown into a Brief for DB persistence."""
    from uuid import UUID

    all_citations = [
        {"item_id": cit.item_id, "label": cit.label, "url": cit.url}
        for section in grounded.sections
        for claim in section.claims
        for cit in claim.citations
    ]
    return Brief(
        run_id=UUID(run_id),
        therapeutic_area=grounded.therapeutic_area,
        body_md=markdown,
        citations=all_citations,
    )


# ── private ────────────────────────────────────────────────────────────────────


def _build_markdown(grounded: GroundedBrief, run_id: str) -> str:
    ts = grounded.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "# PipelineRadar Intelligence Brief",
        f"**Therapeutic Area:** {grounded.therapeutic_area}  ",
        f"**Generated:** {ts}  ",
        f"**Run ID:** {run_id}",
        "",
        "---",
        "",
    ]

    # First pass: assign footnote numbers and collect source lines
    footnote_index: dict[str, int] = {}  # item_id → footnote number
    source_lines: list[str] = []
    counter = 1

    for section in grounded.sections:
        for claim in section.claims:
            for cit in claim.citations:
                if cit.item_id not in footnote_index:
                    footnote_index[cit.item_id] = counter
                    source_lines.append(f"[{counter}] [{cit.label}]({cit.url})")
                    counter += 1

    # Second pass: render sections with footnote references
    for section in grounded.sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        for claim in section.claims:
            refs = " ".join(
                f"[{footnote_index[cit.item_id]}]"
                for cit in claim.citations
                if cit.item_id in footnote_index
            )
            suffix = f" {refs}" if refs else ""
            lines.append(f"- {claim.text}{suffix}")
            if claim.unverified:
                lines.append("  > ⚠ UNVERIFIED — review before distributing")
        lines.append("")

    lines += [
        "---",
        "",
        "### Sources",
        "",
    ]
    lines.extend(source_lines)

    return "\n".join(lines)


def _write_file(markdown: str, run_id: str) -> None:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    path = _OUTPUT_DIR / f"brief_{run_id}.md"
    path.write_text(markdown, encoding="utf-8")
    log.info("markdown.written", path=str(path))
