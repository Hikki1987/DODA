# DODA — loyiha konteksti (AI coding agent uchun)

Bu fayl har bir Claude Code sessiyasi uchun majburiy kontekst. To'liq talab
authoritative manba: `docs/DODA-TRD-v2.0.docx` (Texnik Topshiriq, hujjat kodi
DODA-TRD-002, v2.0). Bu yerda faqat kundalik ishlash uchun zarur xulosa bor.

## Loyiha nima

DODA — foydalanuvchining maqsadlari, hujjatlari, bizneslari va ruxsat berilgan
raqamli servislar bilan ishlaydigan shaxsiy AI operatsion tizimi (chat + task
planning + knowledge/RAG + tasdiqli tashqi actionlar + audit).

Ochiq qarorlar hal qilindi:
- **OD-001 — SaaS**: DODA boshidanoq to'liq multi-tenant arxitektura sifatida
  quriladi (Customer → Workspace → Membership), single-tenant emas.
- **Jamoa**: real inson jamoasi yo'q — loyihani to'liq AI coding agent quradi,
  Product Owner Hikmatullo To'rayev. Hujjatdagi 17/18-bo'lim (4.5–5 FTE,
  kalendar sprintlar) shunga ko'ra **rejalashtirish uchun emas**, faqat ish
  tartibi ketma-ketligi (kritik yo'l) sifatida o'qiladi.

## Qat'iy qoidalar (hujjat 0.4-bo'lim)

1. **DEMO ≠ PRODUCTION** — unit/integration/security/migration/acceptance
   testlarsiz modul CLOSED bo'lmaydi.
2. **ID'siz talab yo'q** — har o'zgarish FR-*/NFR-* ID'ga bog'lanadi.
3. **Model authoritative emas** — AI chiqishi hech qachon avtorizatsiya yoki
   xavfsizlik bo'yicha yakuniy manba emas; deterministik gate tasdiqlaydi.

## Master Instruction (20-bo'lim, qisqartirilmaydi)

Domain chegaralari, public kontraktlar, migratsiya tarixi va testlarni buzma.
Har taskda avval qabul mezonlari va threat case'larni yoz. Identity → Customer
→ Workspace → RBAC → Policy → Step-Up → Authorization zanjirini chetlab
o'tma. Tenant-scoped lookupda customer_id majburiy. Model chiqishini ishonchli
deb qabul qilma; typed validation va deterministik avtorizatsiya ishlat.
Tashqi side effect approval, idempotency, outbox, audit va verifikatsiyasiz
bajarilmasin. Secret, token, xom credential, PII yoki prompt kontentini log
yoki auditga yozma. Minimal diff qil; aloqasiz kodni o'zgartirma. Real
integratsiya bajarilmagan bo'lsa PASS deb yozma.

## Arxitektura (6-bo'lim)

Modular monolith + alohida worker (mikroservis emas — ADR-001). Qatlamlar:
Experience → Application → Domain → AI → Integration → Data → Operations.
Domain boshqa domainning implementatsiyasini import qilmaydi — faqat
ID/reference kontrakti yoki application port orqali.

Stack (6.3): Python 3.12 + FastAPI + Pydantic; PostgreSQL 16+ + pgvector;
SQLAlchemy 2 async + Alembic; Redis; Next.js + TypeScript; S3-mos object
storage; OIDC/OAuth 2.1; OpenTelemetry/Prometheus.

Dependency qoidalari (6.2, CI'da tekshiriladi):
- Repository qatlamida `customer_id`'siz so'rov mavjud emas (global ID
  lookup yo'q — NFR-ISO-002).
- AI qatlami authoritative avtorizatsiya qarorini chiqarmaydi.
- Connector domain credentialini ko'rmaydi — broker orqali qisqa muddatli
  token.
- Har tashqi side effect outbox + idempotency orqali o'tadi.
- PostgreSQL transaction-local customer context + majburiy RLS (ADR-005) —
  bu tenant izolyatsiyaning ikkinchi qatlami, repository scoping bilan bir
  qatorda, biri o'rniga emas.

## Talab ID prefikslari (0.2-bo'lim)

FR-AUTH (identity/sessiya), FR-WKS (customer/workspace), FR-CONV (chat),
FR-TASK (task/reja), FR-KNW (fayl/knowledge/xotira), FR-ACT (tool/action),
FR-NTF (bildirishnoma), FR-CTL (foydalanuvchi nazorati), FR-ADM (admin),
FR-AUD (audit), NFR-* (11-bo'lim), UC-* (use case), RISK-*, OD-*, ASM-*.

## Bosqichlar (17.1-bo'lim, kalendar muddatsiz o'qiladi)

0 Foundation → 1 Product shell → 2 Knowledge → 3 Safe actions → 4 Operations
→ 5 Launch hardening → 6 Expansion. Kritik yo'l: outbox/idempotency →
approval → connector → E2E.

**Holat**: 0-Foundation yakunlandi (config, RLS bilan DB, Identity/Customer/
Workspace/Audit skeleti — hujjatdagi "Bajarilgan" belgisi bu kod bazasiga
tegishli emas edi, endi haqiqatda shunday). S1 (17.2-bo'lim: outbox +
idempotency asosi, Task/Action/Approval skeleti) yakunlandi va real
Postgres+Redis'da tekshirildi: state machine (4.2), risk-based approval
routing (9.1), approval invariantlari — payload-hash bog'lanish, bir martalik
nonce, muddat (9.2), idempotentlik (FR-ACT-004) va transactional outbox
(FR-ACT-008, ADR-003) barchasi ishlaydi va testlangan.

S2 (17.2: "API application adapterlari") ham yakunlandi va real HTTP orqali
tekshirildi (67 test): 10-bo'limdagi authoritative zanjir — Session →
[tenant bootstrap] → Workspace Membership → RBAC → Step-Up — endi kod
bazasida haqiqatda mavjud va HTTP endpointlar shu zanjir orqali ochilgan
(`api/actions.py`, `api/dependencies.py`). FR-AUTH-004 (step-up) ham qisman
qamrab olindi: R3 approval `AuthStrength.AAL2` talab qiladi, aks holda
STEP_UP_REQUIRED qaytadi.

S1'da qarzda qolgan qism yopildi: Task domeni faqat model sifatida qolgan
edi (application service va API yo'q edi). Endi `application/task_service.py`
(FR-TASK-001/004/007: create, status transition, history) va
`api/tasks.py` mavjud — xuddi shu authz zanjiridan foydalanadi (owner yoki
workspace_admin state'ni o'zgartira oladi).

FR-WKS (customer/workspace boshqaruvi) ham endi to'liq: `customer_service.py`
(Customer yaratish + a'zolik — "oxirgi Owner chiqarib/pasaytirib bo'lmaydi"
invarianti bilan, FR-WKS-005) va `workspace_service.py` kengaytirildi
(workspace a'zoligi qo'shish/rol o'zgartirish/chiqarish, arxivlash/tiklash —
FR-WKS-003/005/006). Customer yaratish ataylab public API orqali ochilmagan
— 2.3-bo'lim "self-serve public signup"ni v1 uchun OUT OF SCOPE deb
belgilagan; bu faqat operator/test tooling uchun.

94 test, barchasi real Postgres'da. Bu bosqichda 3 ta real xato topib
tuzatildi: (1) audit hash-zanjiri concurrency fork'i (yuqorida), (2)
`restore_workspace` endpointi arxivlangan workspace'ga kira olmasdi, chunki
`get_workspace_context` arxivlangan workspace'ni har doim DENY qilardi —
`allow_archived` parametri va alohida dependency bilan tuzatildi, (3)
`create_customer_with_owner` o'zi ichida yangi tasodifiy `customer_id`
generatsiya qilib, chaqiruvchi ochgan `tenant_scoped_session`ning ID'siga
mos kelmasdi — RLS insert'ni rad etardi.

FR-CTL-003 (kill switch, release-blocker — 15.2) ham qurildi: workspace
darajasi (`workspace_admin`) va customer darajasi (`customer_owner`), 10.2
permission-matritsasining "Kill switch" qatoriga mos. Tekshirish nuqtasi —
`kill_switch_service.assert_not_killed` — `action_service.propose_action`
boshida chaqiriladi, shuning uchun faol kill switch hech qanday yangi
Action qatori yaratilishiga yo'l qo'ymaydi (hatto DRAFT holatida ham).
"Drill" testi ham bor: engage'dan blokgacha o'tgan real vaqtni o'lchab,
≤60s SLA'ni tasdiqlaydi (12.4/UC-007). Global (platform-wide) qamrov
qurilmagan — bu Platform Owner + R5 dual-control infratuzilmasini talab
qiladi (FR-ADM, hali yo'q); 10.2 jadvalining o'zida ham "global" ustuni
yo'q, faqat workspace/customer bor.

FR-AUD-002 (audit viewer) ham qurildi, 10.2 permission-matritsasining
"Audit ko'rish" qatoriga aynan mos ikkita endpoint bilan:
`/v1/workspaces/{id}/audit` (Member = "o'z amallarini", WorkspaceAdmin =
butun workspace) va `/v1/customers/{id}/audit` (CustomerOwner/Auditor =
butun customer — Auditor'ning kill switch kabi yozuv amallariga kira
olmasligi ham alohida testda tasdiqlangan). Buning uchun `AuditEvent`ga
`workspace_id` ustuni qo'shildi (0007-migratsiya, nullable — customer-only
hodisalar uchun) — avval bu JSON ichida ko'milgan bo'lib, WorkspaceAdmin
filtri uchun indekslanadigan, to'g'ri ustun yo'q edi. "Eksport audit
qilinadi" mezoni ham qamrab olindi: har bir audit ko'rish so'rovi o'zi
ham `audit.viewed.v1` yozuvi qoldiradi (kim, qaysi filtr, nechta natija —
ko'rilgan yozuvlarning mazmuni emas).

FR-NTF (in-app bildirishnoma) ham qurildi — faqat in-app qismi
(FR-NTF-001: "email/Telegram keyingi adapter", hali qamrovda emas).
`notification_service.py` va to'rtala majburiy tur (FR-NTF-002) haqiqiy
trigger nuqtalaridan ishga tushadi, sun'iy yozilmagan:
PENDING_APPROVAL/FAILED_ACTION — `action_service.apply_transition`ning
o'zida (har qanday kod yo'li shu holatlarga olib borsa ham ishlaydi);
COMPLETED_TASK — `task_service.change_task_status`da (task egasi
bildirishnoma oladi, hatto workspace_admin uni yopgan bo'lsa ham);
SECURITY_ALERT — kill switch ishga tushganda **workspace yoki customer'ning
barcha a'zolariga** broadcast qilinadi (FR-NTF-004: "Security alert'ni
o'chirib bo'lmaydi" ruhiga mos — hamma darhol xabardor bo'ladi).
FR-NTF-003 ("sezgir kontent bo'lmaydi") schema darajasida ta'minlangan —
`Notification`da erkin matn maydoni umuman yo'q, faqat reference +
tor safe_metadata; test har bir tur uchun ruxsat etilgan kalitlar
ro'yxatidan tashqariga chiqmasligini va action payload'i (masalan email
manzili) sizib chiqmasligini tekshiradi.

Testlashda 1 ta real xato topildi: bildirishnomalarni ro'yxatlash avval
Python darajasida workspace bo'yicha filtrlanardi (DB'dan olingandan
keyin) — bu ko'p workspace'ga a'zo foydalanuvchi uchun `limit` bilan
noto'g'ri sahifalashga (haqiqiy natijalar yo'qolishiga) olib kelishi
mumkin edi. SQL darajasidagi filtrga o'tkazib tuzatildi.

111 test, barchasi real Postgres'da.

Keyingi qadam — S3 (17.2): Web product shell (login, workspace, chat, task)
— bu yerda FR-AUTH-001'ning haqiqiy OIDC oqimi qurilishi kerak (hozir
`session_service.create_session` faqat dev/test seam) va bu tashqi OIDC
provayder ma'lumotlarini (client_id/secret, issuer URL) talab qiladi —
Product Owner'dan kelishi kerak. Yoki OD-002 (connector tanlovi) S6'dan
oldin hal qilinishi kerak.

**Bilingan cheklovlar (keyingi ishlarda hisobga olinsin):**
- ~~Audit hash-zanjiri concurrent yozuvlarda xavfsiz emas~~ — **tuzatildi**:
  `audit_chain_tips` (0005-migratsiya) har customer uchun `SELECT ... FOR
  UPDATE` bilan lock qilinadigan tip qatori qo'shdi. Eski (buzuq) versiyaga
  qaytarib, `test_audit_chain_concurrency.py` 3 martalik urinishda ham
  aynan shu xatoni (11/12 yozuv bitta prev_hash'ga fork bo'lishi) ushlashi
  tasdiqlandi — keyin tuzatilgan versiya bilan qayta tekshirildi.
- Outbox relay hozircha connector'siz — faqat Redis Stream'ga yetkazishni
  isbotlaydi. Haqiqiy tashqi effekt (S7, birinchi konnektor) connector'ning
  o'zi ham idempotent bo'lishini talab qiladi.
- `pytest` `asyncio_default_fixture_loop_scope = "session"` talab qiladi —
  `doda.db`dagi global `engine` bitta event loop'ga bog'lanadi; buni servis
  darajasida (masalan har-request engine) hal qilish keyingi bosqichda
  ko'rib chiqilishi mumkin.
- `Authorization: Bearer <session-id>` — imzosiz xom session UUID, haqiqiy
  JWT/OIDC token emas (FR-AUTH-001 S3 ishi). Session jadvali va uning
  idle/absolute timeout, revoke mantig'i haqiqiy; faqat "session qanday
  tug'iladi" bosqichi hali stand-in.
- R3 approver siyosati va workspace-a'zolik boshqaruvi faqat `WorkspaceRole`ni
  tekshiradi (`member` / `workspace_admin`); `CustomerRole.CUSTOMER_OWNER`
  ham 10.2 bo'yicha bu amallarni bajara olishi kerak. `CustomerContext` /
  `get_customer_request_context` (`api/dependencies.py`) endi ikkita joyda
  ishlatilmoqda (kill switch, audit viewer) va customer-darajasidagi rolni
  to'g'ri aniqlaydi — bu boshqa joylardagi shu cheklovni yopish uchun ham
  qayta ishlatilishi mumkin, lekin R3 approval va workspace-a'zolik
  boshqaruvi ataylab o'zgartirilmadi (bu alohida, so'ralmagan o'zgarish
  bo'lardi).
- "Customer'ga taklif qilish" (yangi foydalanuvchini customer'ga a'zo
  qilish) uchun HTTP endpoint yo'q — `customer_service.invite_customer_member`
  faqat application-layer funksiya.
- Bildirishnomalar workspace-scoped endpoint orqali ko'rinadi
  (`/v1/workspaces/{id}/notifications`), chunki butun API shu naqshda
  qurilgan. Haqiqiy "barcha workspace'lardagi bildirishnomalarim" inbox'i
  session-scoped (workspace'siz) yangi endpoint talab qiladi —
  qurilmagan.
- FR-NTF-004 (foydalanuvchi bildirishnoma turlarini sozlashi, Should
  darajali) qurilmagan — hozircha barcha bildirishnoma turlari doim
  yetkaziladi (bu "Security alert o'chirib bo'lmaydi" qismini avtomatik
  qanoatlantiradi, lekin boshqa uch turni o'chirish imkoniyati yo'q).
- Email/Telegram adapter (FR-NTF-001'ning ikkinchi yarmi) qurilmagan —
  tashqi provayder integratsiyasini talab qiladi.
- `workspace_tenant_index` jadvali — RLS'ning "tuxum-tovuq" muammosini hal
  qilish uchun ataylab RLS'siz qoldirilgan bootstrap jadval (faqat
  workspace_id→customer_id xaritasi, kontent yo'q). Faqat
  `workspace_service.create_workspace` orqali, Workspace bilan bitta
  tranzaksiyada yoziladi — hech qachon boshqa joydan yozilmasin.
- Task uchun 4.2-bo'limdagidek rasmiy state machine jadvali TRD'da yo'q —
  `task_service.ALLOWED_TASK_TRANSITIONS` faqat oldinga siljish/bekor
  qilishni ruxsat beradi, orqaga qaytish (masalan DONE → IN_PROGRESS,
  "qayta ochish") ataylab qo'llab-quvvatlanmaydi. Kerak bo'lsa bu change
  request (QOIDA 2), bug fix emas.
