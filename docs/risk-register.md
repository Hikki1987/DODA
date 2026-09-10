# Risk register — TRD 19.1 tracker

Source of truth for the ten risks TRD 19.1 names, each with a stated
likelihood/impact, a mitigation, and an owner. This file exists for the
same reason `docs/open-decisions.md` does: before this, RISK-001..010 were
never referenced anywhere in the codebase or in CLAUDE.md by ID — a
requirement-traceability audit (comparing every FR-\*/NFR-\*/UC-\*/RISK-\*/
OD-\*/ASM-\* ID in the TRD against the actual codebase) found the risk
register was the one whole requirement family with **zero** IDs ever
cited, unlike every other family which had at least partial coverage.

Status below is assessed against **actual codebase state**, not the
calendar — same convention as `docs/open-decisions.md`. A risk whose
mitigation is a later-stage deliverable (AI/model calls, memory,
connectors) is marked **dormant**, not "overdue": it cannot yet have
materialized because the work it would threaten hasn't started. A risk
already partly addressed by something built is marked **partially
mitigated** with the concrete code/process it's backed by, not just an
intention.

| ID | Risk (TRD) | Ehtimollik / Ta'sir | TRD mitigatsiyasi | Egasi | Joriy holat |
|----|------------|----------------------|---------------------|-------|-------------|
| RISK-001 | Scope kengayishi | Yuqori / Yuqori | MVP exclusion ro'yxati va change control | Product Owner | **Qisman yengillashtirilgan, amalda** — TRD 2.3's exclusion list stays inside the TRD itself (no separate tracker), but the project's own QOIDA 2 ("so'ralmagan o'zgarish — change request, bug fix emas") and the repeated "Ataylab qurilmagan" / "so'ralmagan holda amalga oshirilmadi" notes throughout CLAUDE.md are change control actually being exercised on every session, not just a policy statement. |
| RISK-002 | Haddan tashqari avtonomiya | O'rta / Kritik | Risk tier, approval, dry-run | Tech Lead | **Qisman yengillashtirilgan** — risk-tier (R0–R5) + approval/step-up mechanics are fully built, tested, and concurrency-hardened (9.1/9.2). Dry-run (FR-ACT-002 — a preview of an action's real-world effect before R3+ execution) has no dedicated implementation; the approval response happens to echo the full payload, but that was never built against or verified against this requirement. |
| RISK-003 | Memory kontaminatsiyasi | O'rta / Yuqori | Provenance, ACL, o'chirish, tasdiqlash | AI Engineer | **Dormant** — the Knowledge/memory domain (stage 2) doesn't exist yet, so this risk cannot have materialized; no mitigation exists either, since there is nothing yet to contaminate. |
| RISK-004 | Vendor lock-in | O'rta / O'rta | Model gateway va portativ sxemalar | Tech Lead | **Dormant, partially designed** — ADR-004 (model gateway) is recorded as "Accepted" in `docs/adr/`, but per that ADR's own text and CLAUDE.md's OD-003 discussion, no AI/model-calling code exists yet — the gateway is a design decision, not a built abstraction. |
| RISK-005 | Token/xarajat o'sishi | Yuqori / Yuqori | Byudjet, routing, caching, summarization | Product Owner | **Dormant, blocked on a Product Owner decision** — no AI calls exist yet, and OD-008 (monthly AI/infra budget) is logged in `docs/open-decisions.md` as open and past its stage gate; budget/routing/caching can't be designed against an unset budget. |
| RISK-006 | Xavfsizlik illyuziyasi (demo = production) | O'rta / Kritik | Live integratsiya va red-team gate'lari | QA/Security | **Best-mitigated risk in the project** — "DEMO ≠ PRODUCTION" is the codebase's first house rule (CLAUDE.md "Qat'iy qoidalar" #1): no module is CLOSED without real Postgres/Redis/HTTP/Playwright verification, and three `security-review` passes have been run against the accumulated diff. A dedicated red-team *gate* (an adversarial pass run by someone other than the builder, gating a release) doesn't formally exist — the security reviews so far are self-run by the same agent that wrote the code, which is a real difference from the TRD's "red-team gate'lari," even though the practical effect (finding and fixing real vulnerabilities before they ship) has repeatedly held up. A sharper instance of this exact risk was later found and fixed: `CustomerRole.AUDITOR` was documented as read-only in three separate places (TRD 10.2, `domain/security/roles.py` twice) and enforced in none — an auditor added to a workspace held full write authority there. Nothing about that was a demo/production difference; it was a control that existed only in prose. The lesson recorded in CLAUDE.md is the generalisable one: a documented security property with no test is not a control, and coverage measurement is what surfaced it. |
| RISK-007 | Past ishonch — foydalanuvchi actionni topshirmaydi | O'rta / Yuqori | Preview, evidence, audit, undo | Product Owner | **Qisman yengillashtirilgan** — the audit trail (FR-AUD-001/002/004) is thoroughly built; "preview" (FR-ACT-002) and "undo" (FR-CTL-005, cancel-the-last-reversible-action) both have zero implementation and were never previously tracked against these IDs. "Evidence" in the narrow sense of a single exportable action+result+hash package (FR-AUD-005) also doesn't exist yet — distinct from the existing personal-data export (`GET /v1/me/export`) and the audit chain-verify endpoint, neither of which produces a single-action evidence bundle. |
| RISK-008 | Kalit shaxsga bog'liqlik (bus factor) | Yuqori / Yuqori | ADR, hujjatlar, juftlikda ishlash | Tech Lead | **Partially addressed by design, one mitigation structurally unavailable** — ADRs and CLAUDE.md's exhaustive chronological log are real, working documentation practice. "Juftlikda ishlash" (pair programming) isn't a gap so much as inapplicable to this project's actual team shape (ASM-001: one AI coding agent + one Product Owner, no human engineering team) — already reinterpreted at the top of CLAUDE.md rather than silently ignored. |
| RISK-009 | Data residency qarorining kechikishi | Yuqori / Yuqori | OD-005 ni S2 gacha yopish | Product Owner | **Materializing exactly as the TRD predicted** — OD-005 is logged in `docs/open-decisions.md` as "Open, overdue": S2 is done, and the decision that was supposed to close before S2 started hasn't been made. Not yet causing a concrete defect only because nothing is deployed to real infrastructure yet. |
| RISK-010 | O'zbek tilida sifat pariteti past bo'lishi | O'rta / Yuqori | EVAL-LANG to'plami, model routing | AI Engineer | **Dormant** — no AI/model-routing code exists yet, so Uzbek-language quality parity cannot yet be measured or have degraded. Separately, the same traceability audit that produced this file also found **NFR-I18N-001** (externalized uz/ru/en strings, no hardcoding) was never checked: today's frontend is 100% hardcoded Uzbek with no i18n library at all — a related but distinct gap (UI string externalization vs. AI-response language quality), worth flagging together since both concern the same "O'zbek tilida sifat" theme and retrofitting either onto a larger UI later gets more expensive the longer it waits. |

## Ownership

Per TRD 19.1, most of these risks are owned by roles (Product Owner, Tech
Lead, QA/Security, AI Engineer) this project doesn't have as separate
humans — they collapse onto Hikmatullo To'rayev (Product Owner) and
whichever AI coding agent session is active (standing in for Tech
Lead/QA/AI Engineer). This file is a tracker, not an instruction to act:
a "dormant" risk should stay dormant until the domain it concerns
actually starts being built, not be preemptively mitigated against
nothing. Update the "Joriy holat" column here when a mitigation is
actually built, and cross-reference the relevant ADR/OD/CLAUDE.md entry
in the same change, matching `docs/open-decisions.md`'s convention.
