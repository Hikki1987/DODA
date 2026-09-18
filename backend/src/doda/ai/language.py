"""FR-CONV-001: "Til avtomatik aniqlanadi" — automatic language detection
for the three TRD-mandated languages (Uzbek, Russian, English).

This is a small, dependency-free word-list/script heuristic, not a real
language-identification model — adding a third-party NLP dependency for
exactly three, orthographically very distinct languages would be more
attack surface (NFR-SEC-002/003's dependency-audit scope) for no real
accuracy gain over a heuristic built on the actual linguistic facts:

- Uzbek has TWO scripts (Latin, official since 1993, and Cyrillic, still
  in real use) — so "contains Cyrillic" alone cannot mean "Russian".
  Uzbek Cyrillic uses four letters (ў, қ, ғ, ҳ) that standard Russian
  never uses; their presence is a reliable, orthographic (not
  statistical) signal that Cyrillic text is Uzbek, not Russian.
- Uzbek Latin script has its own distinctive apostrophe-based digraphs
  (o', g' — for the vowel/consonant pair not otherwise representable in
  ASCII Latin) plus a closed set of extremely common function words
  ("va", "bilan", "uchun", ...), which reliably separate it from English
  even though both use the same base alphabet.

Deliberately returns None (rather than guessing) when the signal is
ambiguous — a short or mixed message, or one with no matching markers at
all — the same "don't guess, ask/fall back" spirit as FR-CONV-004's own
acceptance criterion, even though that requirement is separate. A wrong
guess here would actively steer the model to answer in the wrong
language, which is worse than the caller falling back to no directive at
all.
"""

import re

SUPPORTED_LANGUAGES = ("UZ", "RU", "EN")

_UZBEK_CYRILLIC_ONLY_LETTERS = set("ўқғҳЎҚҒҲ")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Not linguistically exhaustive — just common enough function/greeting
# words to reliably tip a short chat message one way or the other. All
# lowercase; matching is done against a lowercased, apostrophe-normalized
# token set.
_UZBEK_LATIN_WORDS = {
    "va",
    "bu",
    "shu",
    "uchun",
    "bilan",
    "kerak",
    "salom",
    "rahmat",
    "iltimos",
    "qanday",
    "nima",
    "qachon",
    "qayerda",
    "ha",
    "yo'q",
    "yoq",
    "bor",
    "bugun",
    "ertaga",
    "kechirasiz",
    "tushunarli",
    "albatta",
    "menga",
    "sizga",
}
_ENGLISH_WORDS = {
    "the",
    "is",
    "are",
    "and",
    "you",
    "please",
    "thanks",
    "thank",
    "hello",
    "what",
    "how",
    "when",
    "where",
    "today",
    "tomorrow",
    "sorry",
    "understand",
    "sure",
    "yes",
    "no",
    "need",
    "help",
    "with",
    "for",
}

_TOKEN_RE = re.compile(r"[a-zA-Z']+")


def _normalize_apostrophes(text: str) -> str:
    # Uzbek Latin text in the wild uses several different Unicode
    # characters for the same apostrophe-like sound (U+2019 right single
    # quote, U+02BB modifier letter turned comma, U+02BC modifier letter
    # apostrophe) interchangeably with a plain ASCII "'" — normalize them
    # all to "'" before word-matching so none of these variants is missed.
    for variant in ("’", "ʻ", "ʼ"):
        text = text.replace(variant, "'")
    return text


def detect_language(text: str) -> str | None:
    """Returns "UZ"/"RU"/"EN", or None if the signal is too weak/mixed
    to call. Deterministic and pure — no network, no model call."""
    stripped = text.strip()
    if not stripped:
        return None

    if _CYRILLIC_RE.search(stripped):
        return "UZ" if any(ch in _UZBEK_CYRILLIC_ONLY_LETTERS for ch in stripped) else "RU"

    normalized = _normalize_apostrophes(stripped).lower()
    if "o'" in normalized or "g'" in normalized:
        return "UZ"

    tokens = set(_TOKEN_RE.findall(normalized))
    uzbek_score = len(tokens & _UZBEK_LATIN_WORDS)
    english_score = len(tokens & _ENGLISH_WORDS)
    if uzbek_score == 0 and english_score == 0:
        return None
    # The guard above already rules out "both zero", so reaching this
    # branch with uzbek_score >= english_score guarantees uzbek_score > 0
    # (if it were 0, english_score would have to be positive for the
    # guard to have passed, making this comparison false instead).
    if uzbek_score >= english_score:
        return "UZ"
    return "EN"


_LANGUAGE_NAMES_UZ = {"UZ": "o'zbek", "RU": "rus", "EN": "ingliz"}


def response_language_instruction(language: str | None) -> str:
    """The directive appended to a gateway call's `instructions` — empty
    string (no directive at all) when `language` is None, so an
    ambiguous/undetected turn falls back to whatever the model would
    otherwise default to, rather than forcing a guessed language."""
    if language is None:
        return ""
    return f"Har doim {_LANGUAGE_NAMES_UZ[language]} tilida javob ber."
