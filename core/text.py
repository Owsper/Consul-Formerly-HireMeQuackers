"""Text normalisation and matching helpers shared across services."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9+#. ]+")

STOPWORDS = {
    "a", "an", "and", "the", "with", "for", "of", "in", "on", "to", "at", "by",
    "or", "as", "is", "are", "be", "from", "your", "our", "you", "we", "will",
    "experience", "work", "working", "job", "role", "team", "including", "etc",
}

# Canonical spellings for skills that are commonly written differently.
SKILL_ALIASES = {
    "python3": "python",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "node": "node.js",
    "nodejs": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "postgres": "postgresql",
    "postgre": "postgresql",
    "k8s": "kubernetes",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "llm": "large language models",
    "llms": "large language models",
    "aws": "amazon web services",
    "gcp": "google cloud platform",
    "ci/cd": "ci cd",
    "rest api": "rest apis",
    "restful apis": "rest apis",
    "restful": "rest apis",
}


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    text = strip_accents(text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("’", "'")
    return normalize_whitespace(text)


def slugify(text: str, max_length: int = 80) -> str:
    text = strip_accents(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_length].strip("-")


def canonical_skill(skill: str) -> str:
    key = normalize_text(skill).strip(" .,;:")
    key = re.sub(r"\s+", " ", key)
    return SKILL_ALIASES.get(key, key)


def skill_tokens(skills: list[str]) -> set[str]:
    return {canonical_skill(s) for s in skills if normalize_text(s)}


def text_contains_skill(text: str, skill: str) -> bool:
    """Word-boundary-ish containment that understands multiword skills."""
    haystack = normalize_text(text)
    needle = canonical_skill(skill)
    if not needle:
        return False
    if needle in haystack:
        # Guard against substring matches like "ai" inside "maintain" for short tokens
        if len(needle) > 3 or " " in needle:
            return True
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return False


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def keyword_set(text: str) -> set[str]:
    tokens = _NON_WORD_RE.sub(" ", normalize_text(text)).split()
    return {t for t in tokens if len(t) > 2 and t not in STOPWORDS}


def coverage(required: list[str], candidate_text: str) -> tuple[list[str], list[str]]:
    """Return (matched, missing) skills against a block of candidate text."""
    matched, missing = [], []
    for skill in required:
        (matched if text_contains_skill(candidate_text, skill) else missing).append(skill)
    return matched, missing


def truncate(text: str, limit: int) -> str:
    text = normalize_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def initials(name: str) -> str:
    parts = [p for p in normalize_whitespace(name).split() if p]
    return "".join(p[0].upper() for p in parts[:3]) or "CV"


def filename_stem(*parts: str) -> str:
    joined = "_".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", joined).strip("_")[:120]
