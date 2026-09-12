"""ADR-004's "model gateway" — the one seam a real AI/LLM provider
integration is meant to enter through (TRD 6.1 layer order: Experience ->
Application -> Domain -> AI -> Integration -> Data -> Operations). This
file is the whole of the AI layer today, on purpose: the two decisions a
real implementation needs are both still open per
docs/open-decisions.md —

- which provider (Product Owner: "hali aniq emas" — not yet decided)
- OD-003: which data classes may never be sent to it (Product Owner:
  "keyinroq alohida belgilayman" — will decide separately later)

Building a real provider client without either answer would be exactly
the kind of unilateral guess CLAUDE.md's Master Instruction and this
project's own history (OD-002/004/005) say not to make. `NullAIPort`
below is the only implementation: no network call, no external request
of any kind — nothing a conversation contains ever leaves this process.
Wiring a real provider later means adding a new class that satisfies
`AIPort`, behind the same `doda.application.conversation_service` call
site; it does not mean touching the domain model, the API routes, or any
existing test.
"""

import typing


@typing.runtime_checkable
class AIPort(typing.Protocol):
    """`conversation_history` is the plain text of prior messages, oldest
    first — already a judgement call (full history vs. a window, vs. a
    summary) that a real provider implementation will need to revisit
    once OD-003 says what may even be included. `NullAIPort` below never
    inspects it, by design — it cannot leak content it never reads."""

    async def generate_reply(self, *, conversation_history: list[str]) -> str: ...


class NullAIPort:
    """FR-CONV-008 ("model xatosi yoki timeout'da xavfsiz degradatsiya")
    read literally, for the case where there is no model at all yet: say
    so plainly rather than fabricate a real-looking answer. Every
    conversation today gets this exact reply — it is not a per-message
    computation, so there is nothing here for
    tests/unit/test_side_effect_boundary.py to ever catch as a network
    call, now or after a refactor."""

    async def generate_reply(self, *, conversation_history: list[str]) -> str:
        del conversation_history  # intentionally unread — see class docstring
        return (
            "AI javob provayderi hali tanlanmagan (OD-003 ham hali hal "
            "qilinmagan — docs/open-decisions.md'ga qarang). Bu xabar "
            "saqlandi, lekin hech qanday tashqi modelga yuborilmadi."
        )
