"""Pre-insert dedupe for retrieval items.

Two layers (DB + in-batch):
  1. The trends table has UniqueConstraint(source, source_id) — catches the
     same item re-fetched from the same source across runs.
  2. This module dedupes WITHIN a single orchestrator batch across sources:
     e.g. the same OpenAI post can appear in both the OpenAI RSS feed and on
     HackerNews. We catch that here before the orchestrator inserts.

Two checks per item:
  - normalized-URL hash (strip utm_*, fbclid, ref, trailing slash, lowercase host)
  - title trigram Jaccard similarity (catches paraphrased aggregator headlines)

Order matters: pass items in priority order (highest-quality source first).
Earlier items win when a near-dup is detected.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.retrieval.base import TrendItem

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
    "_hsenc", "_hsmi", "igshid",
}

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip()
    cleaned_query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in _TRACKING_PARAMS
        ]
    )
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", cleaned_query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    s = _PUNCT.sub(" ", title.lower())
    return _WS.sub(" ", s).strip()


def _trigrams(s: str) -> set[str]:
    padded = f"  {s}  "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def title_similarity(a: str, b: str) -> float:
    ta = _trigrams(normalize_title(a))
    tb = _trigrams(normalize_title(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def dedupe(
    items: list[TrendItem], *, title_threshold: float = 0.85
) -> list[TrendItem]:
    seen_url_hashes: set[str] = set()
    kept: list[TrendItem] = []
    for item in items:
        h = url_hash(item.url)
        if h in seen_url_hashes:
            continue
        if any(
            title_similarity(item.title, prev.title) >= title_threshold
            for prev in kept
        ):
            continue
        seen_url_hashes.add(h)
        kept.append(item)
    return kept
