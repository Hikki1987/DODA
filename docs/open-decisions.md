# Open decisions — Product Owner tracker

Source of truth for the eight questions TRD 19.4 requires Product Owner
sign-off on ("QAROR TALABI: Bu sakkiz savol javobsiz qolsa, texnik jamoa
taxmin qiladi..." — if these eight questions go unanswered, the technical
team guesses, and guesses turn into expensive rework and security
conflicts later). This file exists because those eight questions were
previously only mentioned scattered across CLAUDE.md prose and the TRD
itself — nowhere was there one place to see, at a glance, which are
resolved, which are still open, and which already missed their stated
deadline. An AI coding agent must not resolve any of these unilaterally;
this tracker's job is to make sure none of them get silently lost.

Status is assessed here against **actual codebase progress** (which stage
each area of work has reached), not the calendar — per CLAUDE.md, this
project reads TRD stage gates as an ordering/critical-path signal, never
a calendar commitment (no real team, one AI agent + one Product Owner).
"Overdue" below means: the stage whose *start or end* was supposed to gate
this decision has, in terms of actual work done, already been passed.

| ID | Question | Stated deadline | Blocks | Status |
|----|----------|-----------------|--------|--------|
| OD-001 | DODA faqat Hikmatullo uchunmi yoki keyinchalik SaaS bo'ladimi? | S1 oxiri | Tenant provisioning, billing dizayni | **Resolved** — multi-tenant (SaaS-shaped) from the start; see CLAUDE.md's "OD-001 — SaaS" and the Customer→Workspace→Membership architecture built since stage 0. |
| OD-002 | Birinchi real konnektor: Google Calendar, Gmail, Telegram yoki boshqa? | S5 oxiri | S6, S7 | **Open, not yet overdue** — stage S5 (Launch hardening) has not started. See ADR-007. |
| OD-003 | Qaysi ma'lumot sinflari cloud AI providerga mutlaqo yuborilmaydi? | S3 oxiri | Redaction qatlami, prompt dizayni | **Open, overdue** — S3 ("Safe actions": Task/Action/Approval/kill-switch) is substantially built and tested, but this classification decision was never made. Not yet causing real harm only because no AI/prompt-calling code exists yet (ADR-004 is unimplemented) — but it must be resolved before any Chat/Knowledge work starts sending real user content to a model provider. |
| OD-004 | O'zbek tilidagi ovoz MVP talabimi yoki keyingi bosqichmi? | S1 oxiri | Scope va jamoa rejasi | **De facto resolved, never formally logged** — TRD 2.3 already lists voice input/output under v1 OUT OF SCOPE, and no voice UI exists anywhere in `frontend/`. Recorded here so it's not mistaken for an oversight; a formal Product Owner confirmation would close it cleanly rather than leaving it as an inference from scope text. |
| OD-005 | Production hosting mamlakati va data residency talabi? | S2 boshlanishidan oldin | Butun infra | **Open, overdue** — S2 (API adapters, authz chain, full frontend shell) is done. See ADR-006. Not yet causing real harm only because nothing is deployed to real infrastructure yet (local dev + CI only) — but it determines the managed Postgres/object-storage provider, KMS/Vault region, and the redaction design that OD-003 also depends on. |
| OD-006 | R5 actionlar v1'da bloklanadimi yoki dual approval bilan ruxsatmi? | S6 oxiri | Approval dizayni | **Open, not yet overdue** — stage S6 (Expansion) has not started. This is the same gap already documented in CLAUDE.md regarding the global (platform-wide) kill switch and Platform Owner's R5 dual-control requirement (TRD 2.2): no `platform_owner` role or two-approver mechanism exists yet, and per this row, the TRD itself has not decided whether R5 is even allowed in v1 at all — building dual-control infrastructure before this is answered would risk building the wrong thing. |
| OD-007 | Retention: chat, memory, audit va fayl uchun aniq muddatlar? | S4 oxiri | Retention job, huquqiy tekshiruv | **Open, not yet overdue** — stage S4 (Operations) has not started. NFR-DATA-002 ("Retention job hisoboti") has no implementation yet; nothing to retire early against an undefined retention period. |
| OD-008 | MVP uchun oylik infra va AI token byudjeti? | S2 oxiri | Model routing, limitlar | **Open, overdue** — S2 is done. Not yet causing real harm since no AI/model-calling code exists yet (same dependency as OD-003/ADR-004), but NFR-COST-001 ("Customer/workspace/model bo'yicha byudjet va alert") cannot be designed against an unset budget. |

## What "overdue" actually means here

Three items (OD-003, OD-005, OD-008) have passed the stage gate the TRD
assigned them, purely because this project's actual build order didn't
wait for them — none of the three have caused a real defect yet, because
the work that depends on them (AI/prompt calls, real infrastructure
deployment, budget enforcement) hasn't started. They are listed as
overdue so they get closed *before* that dependent work starts, not
discovered as a blocker in the middle of it.

## Ownership

Per TRD 19.4, every one of these is explicitly a Product Owner decision —
not a technical/architecture call. This file is a tracker, not a request
to be actioned by whoever reads it next; update the Status column here
when Hikmatullo actually decides one, and update the corresponding ADR
(if one exists — ADR-006 for OD-005, ADR-007 for OD-002) from "Open" to
"Accepted" in the same change.
