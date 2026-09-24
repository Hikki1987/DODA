"""NFR-DATA-001b/c — TRD 13.2's five-tier data classification (C1-C5),
applied to the one thing this codebase actually sends to an external AI
provider today: the user's own typed chat message
(`doda.application.conversation_service.stream_message`).

Like `doda.ai.outbound_guard`, this is a deliberately narrow,
high-precision pattern scan — not a general DLP/PII classifier. It only
answers "does this look like it contains one of TRD 13.2's own worked
examples for a class" (finansiy raqam, IBAN, tibbiy/huquqiy atama,
kontakt ma'lumoti), never a broad heuristic that would flag ordinary
conversational text. C5 ("Sirlar — token, kalit, credential") is
deliberately not a value this function can return: that class is
already blocked outright, before this module ever runs, by
`outbound_guard.detect_likely_secret` — by the time content reaches
`classify_outbound_content`, it has already been proven not to look like
a live credential.

C1 ("Ochiq") is also never returned automatically — this function has no
way to know a message was meant to be public, so the safe default for
anything that doesn't match a more specific class is C2 ("Ichki"), not
C1. Under-classifying (calling C3/C4 content C2) is the failure mode
this narrow scan cannot fully close, same honestly-documented limitation
`outbound_guard` already carries for secrets.
"""

import enum
import re


class DataClassification(enum.StrEnum):
    """TRD 13.2's classes actually reachable from this scan — see module
    docstring for why C1 and C5 are excluded."""

    C2_INTERNAL = "C2"
    C3_PERSONAL = "C3"
    C4_SENSITIVE = "C4"


_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+\d{9,15}|0\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})(?!\d)")

_IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_CARD_NUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

# TRD 13.2's own worked examples for C4 ("Moliya, sog'liq, huquqiy
# hujjatlar") — a small, curated, unambiguous list in the project's three
# languages, the same "narrow beats broad" bar `outbound_guard` applies to
# secrets. Deliberately excludes generic words like "shifoxona"/"hospital"
# (mentioning a place is not the same as disclosing someone's own health
# data) — see module docstring.
_SENSITIVE_KEYWORDS = (
    "diagnoz",
    "diagnosis",
    "диагноз",
    "kasallik tarixi",
    "medical record",
    "история болезни",
    "retsept",
    "prescription",
    "рецепт",
    "sud ishi",
    "jinoyat ishi",
    "criminal record",
    "уголовное дело",
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _looks_like_card_number(content: str) -> bool:
    for match in _CARD_NUMBER_PATTERN.finditer(content):
        digits = re.sub(r"[ -]", "", match.group())
        if _luhn_valid(digits):
            return True
    return False


def classify_outbound_content(content: str) -> DataClassification:
    """Classifies `content` (the user's own message text, already proven
    by `outbound_guard.detect_likely_secret` to not be a C5 credential)
    into the highest-sensitivity TRD 13.2 class it matches. Checked in
    order C4 -> C3 -> default C2, so content matching both a C4 and a C3
    pattern (e.g. a card number next to an email) is never
    under-classified as C3."""
    lowered = content.lower()
    if (
        _IBAN_PATTERN.search(content)
        or _looks_like_card_number(content)
        or any(keyword in lowered for keyword in _SENSITIVE_KEYWORDS)
    ):
        return DataClassification.C4_SENSITIVE
    if _EMAIL_PATTERN.search(content) or _PHONE_PATTERN.search(content):
        return DataClassification.C3_PERSONAL
    return DataClassification.C2_INTERNAL
