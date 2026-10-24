"""Exact-quote checking: does this quote really appear in the document, and on which page?

Matching ignores case, spacing, curly vs straight quotes and dash styles, but not words.
An ellipsis (...) lets a quote skip text, as long as the parts appear in order on one page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.knowledge.ingest import Document

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " "})


def normalise(s: str) -> str:
    s = s.translate(_TRANS).lower()
    s = re.sub(r"[*_`#>]", " ", s)          # markdown symbols
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .,;:\"'")


@dataclass
class QuoteResult:
    found: bool
    page: Optional[int]          # page where it was actually found
    page_matches_claim: bool


def _in_text(parts: list[str], text: str) -> bool:
    pos = 0
    for part in parts:
        j = text.find(part, pos)
        if j == -1:
            return False
        pos = j + len(part)
    return True


def find_quote(doc: Document, quote: str, claimed_page: Optional[int] = None) -> QuoteResult:
    if not quote or len(normalise(quote)) < 4:
        return QuoteResult(False, None, False)
    parts = [normalise(p) for p in re.split(r"\.\.\.|…", quote) if normalise(p)]
    pages = sorted(doc.pages, key=lambda p: (p.number != claimed_page, p.number))
    for p in pages:
        if _in_text(parts, normalise(p.text)):
            return QuoteResult(True, p.number, p.number == claimed_page)
    return QuoteResult(False, None, False)
