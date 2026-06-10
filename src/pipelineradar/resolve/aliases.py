"""Hardcoded alias map and normalisation helpers for entity resolution.

All values in DRUG_ALIASES and COMPANY_ALIASES are lowercase canonical names.
Lookups must normalise the input with `normalise` / `normalise_company` first.
"""

from __future__ import annotations

import re

# raw lowercase alias → lowercase canonical name
DRUG_ALIASES: dict[str, str] = {
    "keytruda": "pembrolizumab",
    "mk-3475": "pembrolizumab",
    "lambrolizumab": "pembrolizumab",
    "sch 900475": "pembrolizumab",
    "opdivo": "nivolumab",
    "bms-936558": "nivolumab",
    "ono-4538": "nivolumab",
    "mdx1106": "nivolumab",
}

COMPANY_ALIASES: dict[str, str] = {
    "msd": "merck sharp & dohme",
    "merck": "merck sharp & dohme",
    "merck & co": "merck sharp & dohme",
    "merck and co": "merck sharp & dohme",
    "merck sharp and dohme": "merck sharp & dohme",
    "merck sharp dohme": "merck sharp & dohme",
    "bms": "bristol myers squibb",
    "bristol-myers squibb": "bristol myers squibb",
    "bristol myers squibb company": "bristol myers squibb",
}

# Stripped in order — longest first to avoid partial matches
_COMPANY_SUFFIXES: tuple[str, ...] = (
    " incorporated",
    " corporation",
    " limited",
    " company",
    " & co",
    " and co",
    " gmbh",
    " llc",
    " plc",
    " inc",
    " ltd",
    " corp",
    " co",
)

_PUNCT_RE = re.compile(r"[^\w\s&/\-]")
_SPACE_RE = re.compile(r"\s+")


def normalise(name: str) -> str:
    """Lowercase, strip non-alphanumeric punctuation, collapse whitespace."""
    s = name.lower()
    s = _PUNCT_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def normalise_company(name: str) -> str:
    """Normalise then strip common corporate-form suffixes."""
    s = normalise(name)
    for suffix in _COMPANY_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break
    return s


def apply_alias(normalised: str, kind: str) -> str:
    """Return the canonical name for a known alias, or the input unchanged."""
    if kind == "drug":
        return DRUG_ALIASES.get(normalised, normalised)
    if kind == "company":
        return COMPANY_ALIASES.get(normalised, normalised)
    return normalised
