"""Prompt templates for the brief synthesizer.

These are the only functions allowed to construct LLM prompts. Keeping them
here makes prompt iteration fast without touching agent logic.
"""

from __future__ import annotations

from pipelineradar.schemas import Item

_SYSTEM = (
    "You are a life-sciences intelligence analyst. "
    "Write only from the provided items. "
    "Every claim must cite at least one item_id from the list. "
    "Do not infer, extrapolate, or mention anything not present in the items. "
    "Respond with ONLY a JSON object — no preamble, no markdown fences."
)

_ITEM_MAX_SUMMARY = 250  # chars; keeps prompt size predictable

_RESPONSE_SCHEMA = """{
  "sections": [
    {
      "heading": "Clinical Trials",
      "claims": [
        {
          "text": "One sentence stating one fact.",
          "source_item_ids": ["<exact UUID from item list>"],
          "confidence": 0.95
        }
      ]
    }
  ]
}"""


def build_synthesis_prompt(items: list[Item], therapeutic_area: str) -> tuple[str, str]:
    """Return (system, user) prompt strings for BriefDraft synthesis.

    Items are serialised as a numbered list so the LLM can reference them
    by their UUID in source_item_ids.
    """
    lines: list[str] = []
    for i, item in enumerate(items, 1):
        summary = item.summary[:_ITEM_MAX_SUMMARY]
        if len(item.summary) > _ITEM_MAX_SUMMARY:
            summary += "…"
        pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "unknown"
        lines.append(
            f"Item {i}: id={item.id}\n"
            f"  source={item.source} | type={item.item_type}\n"
            f"  title={item.title}\n"
            f"  summary={summary}\n"
            f"  url={item.url}\n"
            f"  published={pub}"
        )

    item_block = "\n\n".join(lines)

    user = (
        f"You are analysing {len(items)} intelligence items for the "
        f"'{therapeutic_area}' therapeutic area.\n\n"
        f"Items:\n{item_block}\n\n"
        "Write a structured intelligence brief.\n\n"
        "Rules:\n"
        "1. Group claims under these headings (omit a heading if no content):\n"
        '   "Clinical Trials", "Regulatory Approvals", "Literature"\n'
        "2. Each claim: ONE sentence, ONE fact, grounded in the items above.\n"
        "3. Write at most 5 claims per section (pick the most significant).\n"
        "4. source_item_ids: use ONLY the exact UUID strings shown as 'id=' above.\n"
        "   Do NOT use item numbers — use UUIDs.\n"
        "5. confidence: your estimate of factual accuracy, 0.0 to 1.0.\n\n"
        f"Return ONLY valid JSON matching this schema exactly:\n{_RESPONSE_SCHEMA}"
    )

    return _SYSTEM, user
