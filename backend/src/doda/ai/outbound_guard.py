"""OD-003's first concrete technical control: which data must never leave
this system toward a third-party AI provider. OD-003 itself (a full
classification of forbidden data *categories*) is still an open Product
Owner decision (`docs/open-decisions.md`) — but one sub-case needed no
new product decision to close, only an engineering one: a user's own
typed chat message is the one input surface this system does not control
or generate itself, and today nothing stops someone from pasting a live
API key, a private key block, or a bearer token into a chat message that
then gets forwarded verbatim to OpenAI/Gemini/Claude.

This is a deliberately narrow, high-precision pattern scan — the same
"structured, high-confidence over broad heuristics" bar already applied
to `infrastructure/telegram_client.py`'s error handling and to this
repo's own `gitleaks` CI job (NFR-SEC-002) — not a general DLP/PII
classifier. It only looks at the raw text the caller is about to send in
THIS turn (`doda.application.conversation_service.stream_message`,
before the message is even persisted); it deliberately does NOT scan
tool-call results fed back to the model (those are DODA's own,
already-authorized tenant data — task titles, audit summaries, etc. —
and no prior security review of the AI tool registry found any secret
reachable through a READ tool, so scanning them would be speculative
breadth, not a closed gap). A generic "password=..." pattern is
deliberately excluded too: without an entropy check, it would flag
ordinary conversational sentences ("parolimni unutib qo'ydim") far more
often than it would catch anything real, which is the wrong trade for a
chat product's everyday text.

A match blocks the message outright (raises `OutboundContentBlockedError`,
handled in `api/errors.py` as one clean 422) rather than silently
stripping the secret and sending the rest — the caller must see that
nothing went out, not get a response that quietly omitted part of what
they typed.
"""

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # anthropic_api_key must be checked before openai_api_key: a real
    # Anthropic key ("sk-ant-...") also matches the looser OpenAI shape
    # ("sk-" + 20+ alnum/dash chars), so whichever is checked first wins
    # the label — this order keeps the label accurate for both.
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer_token", re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._-]{20,}\b")),
]


def detect_likely_secret(content: str) -> str | None:
    """Returns the matched pattern's label (e.g. "openai_api_key") if
    `content` looks like it contains a live credential, else None. The
    label is safe to log/return to the client — it is one of the fixed
    names above, never the matched substring itself."""
    for label, pattern in _PATTERNS:
        if pattern.search(content):
            return label
    return None
