"""Text normalisation and matching helpers shared across services."""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

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


# Prose clean-up applied to every generated CV before it is written out. Word
# swaps only where the plain word stays grammatical and keeps the meaning.
_HUMAN_WORD_SWAPS = {
    "utilise": "use", "utilises": "uses", "utilised": "used", "utilising": "using",
    "utilize": "use", "utilizes": "uses", "utilized": "used", "utilizing": "using",
    "leverage": "use", "leverages": "uses", "leveraged": "used", "leveraging": "using",
    "spearheaded": "led", "spearheads": "leads", "spearheading": "leading",
    "passionate about": "interested in",
    "cutting-edge": "modern",
    "seamlessly": "cleanly",
}
_HUMAN_PHRASE_SWAPS = {
    "in order to": "to",
    "prior to": "before",
    "due to the fact that": "because",
    "at this point in time": "now",
    "on a daily basis": "daily",
    "in a timely manner": "on time",
    "make use of": "use",
    "a wide range of": "many",
    "a variety of": "several",
}
_HUMAN_SWAP_RE = re.compile(
    r"\b(" + "|".join(
        re.escape(term) for term in
        sorted({*_HUMAN_WORD_SWAPS, *_HUMAN_PHRASE_SWAPS}, key=len, reverse=True)
    ) + r")\b",
    re.IGNORECASE,
)
_HUMAN_SWAPS = {**_HUMAN_WORD_SWAPS, **_HUMAN_PHRASE_SWAPS}

# Adjectives that carry no information; dropped together with their article.
_HUMAN_FILLER_RE = re.compile(
    r"\b(a|an|the)\s+(?:passionate|dynamic|results-driven|detail-oriented|highly motivated)\b"
    r"(?:\s*[,;])?\s*",
    re.IGNORECASE,
)


def _match_case(replacement: str, original: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def humanise_text(text: str) -> str:
    """Rewrite machine-written prose the way a person would type it.

    Removes em dashes and smart quotes, turns numeric en dashes into hyphens,
    replaces the usual CV marketing words with plain ones and tidies spacing.
    Facts, names, dates and numbers are never changed.
    """
    if not text:
        return ""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"(?<=\d)\u2013(?=\d)", "-", text)   # 2023–2025 -> 2023-2025
    text = text.replace("\u2014", " - ").replace("\u2013", " - ")
    text = re.sub(r"\s*-{2,}\s*", " - ", text)
    text = _HUMAN_SWAP_RE.sub(
        lambda m: _match_case(_HUMAN_SWAPS[m.group(0).lower()], m.group(0)), text)
    for _ in range(3):  # "a passionate, dynamic developer" needs two passes
        text, dropped = _HUMAN_FILLER_RE.subn(lambda m: m.group(1) + " ", text)
        if not dropped:
            break
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]%])", r"\1", text)
    return normalize_whitespace(text)


def _decode_sequence(text: str) -> list[Any] | None:
    """Return a list embedded in a JSON/Python-notation string, if any."""
    if len(text) < 2 or text[0] not in "[(" or text[-1] not in ")]":
        return None
    for loader in (ast.literal_eval, json.loads):
        try:
            parsed = loader(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, (list, tuple)):
            return list(parsed)
    return None


def _strip_serialization_wrappers(text: str) -> str:
    """Remove brackets and quotes left behind by a previous CSV round-trip."""
    text = text.strip()
    for _ in range(10):
        before = text
        # Escaped quotes from repeated repr/JSON round-trips serve no purpose
        # inside a skill name; normal punctuation such as C# and CI/CD stays.
        text = text.replace("\\", "").strip()
        # Only unwrap brackets that look like a serialized container, so real
        # values such as "React (hooks)" and "(ISC)²" keep their brackets.
        if len(text) >= 3 and text[0] == "[" and text[-1] == "]" and text[1] in "\"'[":
            text = text[1:-1].strip()
        elif len(text) >= 3 and text[0] == "(" and text[-1] == ")" and text[1] in "\"'(":
            text = text[1:-1].strip()
        if len(text) >= 2 and text[0] in "[(" and text[1] in "\"'":
            text = text[1:].strip()
        if len(text) >= 2 and text[-1] in "])" and text[-2] in "\"'":
            text = text[:-1].strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        if text == before:
            break
    return text.strip()


def normalize_string_list(value: Any) -> list[str]:
    """Turn a list field into clean strings, healing legacy serialized values.

    Older profile data can contain values such as ``"['Python', 'SQL']"`` or
    nested variants after a list was rendered into a comma-separated editor and
    read back. Real skill punctuation such as ``C#``, ``C++``, ``.NET`` and
    ``CI/CD`` is preserved.
    """
    result: list[str] = []

    def visit(item: Any, depth: int = 0) -> None:
        if item is None or depth > 12:
            return
        if isinstance(item, str):
            text = item.strip()
            if not text:
                return
            decoded = _decode_sequence(text)
            if decoded is not None:
                for nested in decoded:
                    visit(nested, depth + 1)
                return
            for part in re.split(r"[,;\n]", text):
                cleaned = _strip_serialization_wrappers(part)
                if not cleaned:
                    continue
                nested = _decode_sequence(cleaned)
                if nested is not None:
                    for value in nested:
                        visit(value, depth + 1)
                else:
                    result.append(normalize_whitespace(cleaned))
            return
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested, depth + 1)
            return
        result.append(normalize_whitespace(str(item)))

    visit(value)
    return [item for item in result if item]


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


# Words that mark a skill group as not (yet) demonstrated. They are matched
# against group names and explicit proficiency values, never against individual
# skill names.
LEARNING_MARKERS = (
    "currently learning", "learning", "in progress", "in-progress", "beginner",
    "familiar", "getting started", "to learn", "studying", "training", "novice",
)
INTEREST_MARKERS = (
    "interest", "interests", "aspiring", "exploring", "curious", "want to learn",
)
SKILL_STATUSES = ("demonstrated", "learning", "interest")


def skill_group_status(name: str, proficiency: str = "") -> str:
    """Classify a skill group as demonstrated, learning or interest.

    An explicit value wins. Otherwise a group name such as "Currently learning"
    or "Professional interests" is honoured, so a candidate learning C or C++
    is never scored as if those languages were demonstrated.
    """
    explicit = normalize_text(proficiency)
    if explicit in SKILL_STATUSES:
        return explicit
    label = normalize_text(name)
    if any(marker in label for marker in LEARNING_MARKERS):
        return "learning"
    if any(marker in label for marker in INTEREST_MARKERS):
        return "interest"
    return "demonstrated"


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


# A heading that starts a block belonging to the site, not to the advert:
# neighbouring postings, talent pools, share widgets. Everything from such a
# line onwards is dropped before skill extraction, so "Other open roles: Go,
# Rust, PHP" can never turn into requirements of the job the user pasted.
LISTING_END_RE = re.compile(
    r"^(?:(?:other|further|similar|related|more|additional)\s+(?:open\s+)?"
    r"(?:roles?|jobs?|openings?|vacanc(?:y|ies)|positions?)\b|"
    r"view\s+all\s+(?:jobs?|roles?|openings?)\b|"
    r"all\s+(?:open\s+)?(?:jobs?|roles?|positions?)\s+(?:at|in)\b|"
    r"share\s+(?:this\s+)?(?:job|role|posting)\b|talent\s+pool\b|"
    r"weitere\s+(?:stellen|jobs|stellenangebote|positionen)\b|"
    r"ähnliche\s+(?:stellen|jobs|stellenangebote|positionen)\b|"
    r"andere\s+(?:stellen|jobs|stellenangebote)\b|"
    r"alle\s+(?:offenen\s+)?(?:stellen|jobs|stellenangebote)\b|"
    r"autres\s+(?:offres|postes)\b|offres\s+similaires\b|"
    r"otras\s+ofertas\b|ofertas\s+similares\b)",
    re.I,
)


def strip_listing_boilerplate(text: str) -> str:
    """Cut a scraped job text at the first related-postings/footer block."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        cleaned = re.sub(r"^[#*\-\s]+", "", line).strip(" :").strip()
        is_bullet = bool(re.match(r"^\s*(?:[-\u2022*\u00b7\u2013]|\d+[.)])\s+", line))
        if (cleaned and not is_bullet and len(cleaned) <= 80
                and LISTING_END_RE.match(cleaned)):
            break
        kept.append(line)
    return "\n".join(kept).strip()


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
