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

FR-CTL-001/002ning session qismi ham qurildi: `/v1/sessions` (faol
sessiyalarni ko'rish, joriysi `is_current` bilan belgilangan) va
`DELETE /v1/sessions/{id}` (o'zining boshqa qurilmadagi sessiyasini
uzoqdan revoke qilish). "Ulangan ilova" va "memory" qismlari hali
qamrovda emas — ular mos ravishda konnektor (OD-002) va xotira
tizimi (2-bosqich, hali qurilmagan) ni talab qiladi.

**Muhim: shu ishda butun API bo'ylab ta'sir qilgan real xato topildi va
tuzatildi.** `api/dependencies.py`dagi uchta joyda (`get_request_context`,
`get_customer_request_context`, yangi `get_current_identity`) sessiyani
tasdiqlash qadami `resolve_session`ni yalang'och
`async with async_session_factory() as session:` bloki ichida chaqirardi
— `session.begin()`siz. Tajriba orqali tasdiqlandi: bunday blok chiqishda
commit qilinmagan tranzaksiyani **jimgina rollback qiladi**. Demak
`resolve_session`ning `last_seen_at` yangilanishi (FR-AUTH-006 idle
timeout'ni faollik asosida qayta tiklash mexanizmi) hech qachon
saqlanmagan — bu S2'dan beri qurilgan **barcha** endpoint orqali
ta'sirlangan (chunki hammasi shu uchta dependency funksiyadan birini
ishlatadi). Har bir joyga aniq `commit()` qo'shib tuzatdim. Tuzatish
haqiqiyligini isbotlash uchun (audit-zanjiri tuzatishida qilingandek)
o'zgarishni vaqtincha qaytarib, yangi regressiya testi (`test_sessions_api.py`)
buzuq holatda aniq muvaffaqiyatsiz bo'lishini, keyin tuzatilgan holatda
o'tishini tasdiqladim.

**CustomerRole.CUSTOMER_OWNER bo'shlig'i yopildi** — bir necha marta
"bilingan cheklov" sifatida qayd etilgan haqiqiy avtorizatsiya kamchiligi.
Yechim `get_workspace_context`ning o'zida: agar foydalanuvchi shu
workspace'ning customer'ida `customer_owner` bo'lsa, u hech qanday
`WorkspaceMembership` qatoriga ega bo'lmasa ham `WorkspaceRole.WORKSPACE_ADMIN`
sifatida rezolyutsiya qilinadi (10.2: CustomerOwner WorkspaceAdmin bilan
bir yoki undan yuqori huquqqa ega har bir qatorda). Bu bitta joyda hal
qilingani uchun barcha WORKSPACE_ADMIN tekshiruvchi funksiyalar
(`authorize_consume_approval`, `authorize_manage_workspace_members`,
`authorize_archive_workspace`, `authorize_create_task`,
`authorize_task_mutation`, hatto workspace kill switch) avtomatik to'g'ri
ishlaydi — alohida-alohida tuzatish shart bo'lmadi.

**Ishlash jarayonida ikki bosqichli tuzatish kerak bo'ldi** — bu ham
professional jarayon namunasi: birinchi urinishda har bir
`authorize_*` funksiyaga alohida `_is_customer_owner` fallback qo'shdim
(async qilib), lekin HTTP darajasidagi test buni **403 bilan rad etdi** —
sababi, `get_request_context`ning o'zi CustomerOwner uchun
`WorkspaceMembership` qatori topa olmay, avtorizatsiya funksiyasiga
yetib bormasdanoq DENY qilib qo'yardi. Shundan keyin to'g'ri yechimni —
bitta markazlashtirilgan tuzatishni — topdim va qo'lladim.

122 test, barchasi real Postgres'da.

Kod sifati infratuzilmasi (14.2-bo'lim, CI/CD gate) ham qurildi: `ruff`
(lint + format) va `mypy` (tip tekshiruvi) `pyproject.toml`'ga qo'shildi va
butun kod bazasi ularga mos qilib tozalandi (StrEnum'ga o'tish, B008
false-positive'ni FastAPI idiomasi sifatida ignore qilish, real mypy
xatosi — SQLAlchemy `tuple_()` stub cheklovi — tuzatildi). `.github/
workflows/ci.yml` qo'shildi: har push/PR'da lint+format+mypy, Alembic
migratsiya round-trip (upgrade→downgrade→upgrade, real Postgres'da), va
to'liq test suite (real Postgres+Redis service konteynerlarida) ishga
tushadi — bu round-trip mahalliy real Postgres'da ham qo'lda tekshirildi
(0008'dan 0001'gacha downgrade, keyin qaytadan upgrade, keyin butun test
suite qayta ishga tushirildi).

Ikkita arxitektura testi ham qo'shildi — ilgari faqat qo'lda tekshirilgan
ikkita invariantni endi CI o'zi kuzatadi:
- `test_domain_isolation.py` — 6.2-bo'lim "domain boshqa domainning
  implementatsiyasini import qilmaydi" qoidasini AST orqali statik
  tekshiradi (DB shart emas).
- `test_rls_coverage.py` — NFR-ISO-001/ADR-005: `customer_id` ustuni bor
  har bir jadval `FORCE ROW LEVEL SECURITY`ga ega ekanini real Postgres'da
  tekshiradi, faqat ataylab hujjatlashtirilgan ikkita istisno bilan
  (`workspace_tenant_index` — RLS bootstrap, `outbox_messages` — relay
  platform-darajali ko'rinish talab qiladi, ADR-003). Bu testni yozishda
  o'zining haqiqiy xatosi topildi va tuzatildi: birinchi versiyasi
  `Base.metadata`ga ishonardi, lekin hali import qilinmagan domenlar uchun
  bo'sh qolardi — `migrations/env.py`dagi kabi barcha domen modellarini
  aniq import qilish bilan tuzatildi. Buni isbotlash uchun
  `workspace_kill_switches`'da real vaqtda `NO FORCE ROW LEVEL SECURITY`
  qo'yib ko'rildi, test kutilganidek qizardi (`outbox_messages`'ning
  ataylab istisno ekanini ham shu jarayonda aniqladi), keyin holat
  qaytarildi va test qaytadan yashil ekani tasdiqlandi.

Bundan tashqari `list_audit_events`'ning `before_id` cursor-pagination
yo'li (11.2) hech qachon test qilinmagan bo'lib chiqdi (mypy xatosini
tuzatishda topildi) — `test_audit_query_pagination.py` bilan yopildi.

127 test, barchasi real Postgres'da.

**Kritik xavfsizlik xatosi topildi va tuzatildi — ADR-005'ning "ikkinchi
qatlami" haqiqatda ishlamas edi.** Yangi qurilgan CI birinchi marta chinakam
"fresh" (bo'sh volume'li) Postgres konteynerida test suite'ni ishga
tushirganda, `test_tenant_isolation.py` real cross-tenant data leak bilan
qizardi: bitta customer boshqa customer'larning workspace'larini ko'rdi.
Sabab — Postgres'ning rasmiy Docker image'i `POSTGRES_USER` orqali
yaratilgan rolni har doim **superuser** qilib yaratadi (bu Postgres'ning
o'z, o'zgarmas qoidasi), superuser esa `FORCE ROW LEVEL SECURITY`dan qat'i
nazar RLS'ni har doim chetlab o'tadi. Ilova `docker-compose.yml`'dagi shu
bootstrap rol (`doda`) bilan to'g'ridan-to'g'ri ulanar edi — demak har bir
jadvalda `FORCE ROW LEVEL SECURITY` yoqilgan bo'lsa ham, bu 6-bo'limda
"ikkinchi, mustaqil qatlam" deb hujjatlashtirilgan RLS himoyasi production
konfiguratsiyasida (va har qanday yangi/fresh Postgres'da) haqiqatda **hech
narsa qilmas edi** — birinchi qatlam (repository-darajasidagi customer_id
filtri) yagona haqiqiy himoya bo'lib qolgan edi. Bu mahalliy dev muhitida
hech qachon ko'rinmadi, chunki u yerdagi Postgres allaqachon boshqacha
(superuser bo'lmagan) `doda` bilan oldindan sozlangan edi — demak avvalgi
barcha "127 test real Postgres'da o'tdi" da'volari haqiqiy edi, lekin faqat
noan'anaviy, allaqachon xavfsiz mahalliy muhit tufayli, CI/production'dagi
haqiqiy konfiguratsiyaning o'zi tufayli emas.

Tuzatish (ikkita rol, bitta haqiqat manbai — `infra/postgres-init/
01-create-app-role.sql`): endi `doda` (bootstrap superuser) faqat Alembic
migratsiyalari uchun (`DODA_MIGRATION_DATABASE_URL`) ishlatiladi — CREATE
EXTENSION va DDL uchun superuser shart. Ilovaning o'zi endi ataylab
huquqi cheklangan, superuser BO'LMAGAN `doda_app` rol orqali ulanadi
(`DODA_DATABASE_URL`), `NOSUPERUSER NOBYPASSRLS` bilan yaratilgan va faqat
kerakli jadvallarga SELECT/INSERT/UPDATE/DELETE huquqi berilgan (`ALTER
DEFAULT PRIVILEGES` orqali kelajakdagi migratsiyalar yaratadigan jadvallar
uchun ham avtomatik). `docker-compose.yml` bu skriptni `docker-entrypoint-
initdb.d` orqali avtomatik bajaradi; CI'da esa alohida qadam sifatida
`psql` orqali chaqiriladi (service konteynerlar checkout'dan oldin
boshlangani uchun fayl mount qilib bo'lmaydi). `test_rls_coverage.py`ga
`test_app_connects_as_a_role_that_cannot_bypass_row_level_security`
qo'shildi — ilova ulanadigan rolning `rolsuper`/`rolbypassrls`
bo'lmasligini real Postgres'da tekshiradi, shu butun xato sinfini endi CI
har safar ushlaydi.

129 test, barchasi real Postgres'da.

FR-WKS-005'ning bilingan bo'shlig'i yopildi: "Customer'ga taklif qilish"
(yangi foydalanuvchini customer'ga a'zo qilish, rolini o'zgartirish,
chiqarish) ilgari faqat `customer_service.invite_customer_member`/
`change_customer_member_role`/`remove_customer_member` sifatida
application-layer funksiya edi — hech qanday HTTP endpoint yo'q edi
(workspace-darajasida bunday API allaqachon bor edi, `api/
workspace_admin.py`, lekin customer-darajasida yo'q edi). Endi
`api/customer_admin.py` orqali `POST/PATCH/DELETE /v1/customers/{id}/
members` mavjud, xuddi shu authz zanjiridan (`get_customer_request_context`)
foydalanadi va yangi `authorize_manage_customer_members` (10.2: faqat
CustomerOwner) bilan himoyalangan. Taklif qilinayotgan `user_id` haqiqiy
Identity User ekanini tekshiradi (aks holda hech kimga tegishli bo'lmagan
osilib qolgan a'zolik yaratilishining oldi olinadi) — `api/workspace_
admin.py`ning o'z inputi uchun qilgan xuddi shunday tekshiruvi bilan bir
xil naqsh. "Oxirgi Owner"ni pasaytirib/chiqarib bo'lmaslik invarianti
(FR-WKS-005) allaqachon `customer_service`da bor edi — bu yangi qatlam
faqat uni HTTP orqali ochadi, o'zgartirmaydi.

134 test, barchasi real Postgres'da.

FR-NTF'ning yana bir bilingan bo'shlig'i — customer-keng bildirishnoma
inbox'i — ham yopildi (tafsilot pastdagi "Bilingan cheklovlar"da,
customer-lararo global inbox'ning ataylab qurilmaganligi bilan birga).

137 test, barchasi real Postgres'da.

FR-NTF-004 (bildirishnoma turlarini sozlash) ham qurildi — tafsilot
pastdagi "Bilingan cheklovlar"da.

141 test, barchasi real Postgres'da.

**Xavfsizlik ko'rib chiqish (`security-review` skill) o'tkazildi — butun
PR diff'iga qarshi, uch bosqichli jarayon: (1) haqiqiy zaifliklarni topish
subagent'i, (2) har bir nomzod uchun alohida false-positive filtrlash
subagent'i (parallel), (3) faqat ishonch darajasi >=8 bo'lganlar
qoldirildi.** Ikkita haqiqiy xato topildi va darhol tuzatildi:

1. **Action idempotency-key workspace bo'ylab kesishishi** — `Action.
   idempotency_key` faqat `customer_id` bo'yicha unique edi, `workspace_id`
   bo'yicha emas. Bitta customer ostidagi ikkita xil workspace bir xil
   (caller tanlagan) kalitni ishlatsa, ular BITTA Action qatoriga
   to'qnashardi — `propose_action`ning idempotent-replay yo'li natijada
   boshqa workspace'ning action payload'i va (agar AWAITING_APPROVAL
   bo'lsa) uning bir martalik approval nonce'ini workspace'ga a'zo
   bo'lmagan chaqiruvchiga qaytarardi. 0010-migratsiya constraint'ni
   `(customer_id, workspace_id, idempotency_key)`ga o'zgartirdi;
   `action_service.py`ning replay-qidiruvi ham mos ravishda tuzatildi.
   Tuzatish audit-zanjiri uslubida isbotlandi: kod+DB vaqtincha eski
   holatga qaytarildi, yangi regressiya testi aynan shu leak'ni (bir xil
   action ID ikkala workspace uchun) ushlashi tasdiqlandi, keyin tuzatilgan
   holat bilan qayta tekshirildi.
2. **`parent_task_id` orqali tenant-lararo mavjudlik oracle'i** —
   `create_task` `parent_task_id`ni faqat DB FK'ga tayanib qo'yardi,
   workspace tekshiruvisiz. Buni tekshirish jarayonida muhim texnik
   haqiqat aniqlandi: cross-CUSTOMER holat aslida `FORCE ROW LEVEL
   SECURITY` tomonidan avtomatik bloklanadi (FK tekshiruvi ham superuser
   bo'lmagan egasi uchun RLS'ga bo'ysunadi — bu xuddi shu PR'dagi RLS
   bypass tuzatishining tabiiy natijasi), lekin cross-WORKSPACE-bir xil-
   customer holati bloklanmaydi (RLS faqat customer_id bo'yicha). Bu haqiqiy
   zaiflik: boshqa workspace'dagi (bir xil customer) task'ni parent qilib
   qo'yish mumkin edi, mavjud bo'lmagan UUID esa 500 (ushlanmagan
   IntegrityError) qaytarardi — 200-vs-500 orqali tenant-lararo mavjudlik
   signali. `task_service.create_task`ga `add_workspace_member`dagi kabi
   aniq workspace-ichida-qidirish tekshiruvi qo'shildi (`TaskParentNot
   FoundError` → 404). Bu ham xuddi shunday revert-test-restore bilan
   isbotlandi — muhimi, dastlabki test noto'g'ri stsenariy (ikkita butunlay
   boshqa customer) bilan yozilgan edi va kutilmaganda "muvaffaqiyatsiz"
   bo'lib chiqdi (chunki RLS uni allaqachon bloklagan edi) — shu narsa
   aynan yuqoridagi FORCE RLS haqiqatini ochib berdi va testni to'g'ri
   stsenariyga (bir xil customer, boshqa workspace) tuzatishga olib keldi.

Uchinchi nomzod (client-controlled `risk_level` R3+ approval/step-up'ni
chetlab o'tishi mumkinligi) tekshirildi va **tuzatilmadi**: dizayn
bo'shlig'i haqiqiy (server-side tool→risk-level siyosati hali yo'q), lekin
hech qanday real tashqi connector hali qurilmagani uchun (`outbox_relay.py`:
"connector hali yo'q") bugungi kunda haqiqiy tashqi ta'sir yo'q — S7'da
birinchi connector qurilishidan OLDIN bu siyosat qatlami qo'shilishi kerak,
lekin bu alohida, kelajakdagi ish sifatida qayd etildi, hozircha xato
sifatida "tuzatilmadi" (yolg'on signal emas — chinakam bo'sh joy).

145 test, barchasi real Postgres'da.

**Fundamental bo'shliq topildi va yopildi: hech qanday client "men qaysi
workspace'larga a'zoman" deb so'ray olmasdi.** Frontend/klient integratsiyasi
haqida o'ylashda aniqlandi — API'dagi HAR BIR workspace/customer-scoped
endpoint chaqiruvchidan workspace_id yoki customer_id'ni URL'da OLDINDAN
bilishni talab qiladi; login'dan keyin "menda qaysi workspace'lar bor"
degan savolga javob beradigan birorta endpoint yo'q edi. Bu shunchaki
"frontend hali yo'q" emas — bu HAR QANDAY klient (web, CLI, boshqa xizmat)
uchun asosiy, ishlatib bo'lmaydigan bo'shliq edi.

Sabab — xuddi `workspace_tenant_index`ni talab qilgan tuxum-tovuq
muammosining bir pog'ona yuqorisi: `customer_memberships`ning o'zi
`customer_id` bo'yicha RLS bilan qamalgan, shuning uchun "foydalanuvchi X
qaysi customer'larga a'zo" so'roviga customer_id'ni OLDINDAN bilmasdan
javob berib bo'lmaydi. Yechim: yangi `UserCustomerIndex` bootstrap jadvali
(0011-migratsiya) — `workspace_tenant_index` bilan bir xil, ataylab
RLS'siz, faqat `(user_id, customer_id)` xaritasi, hech qanday kontent yo'q.
`customer_service.py`ning uchta funksiyasida (`create_customer_with_owner`,
`invite_customer_member`, `remove_customer_member`) CustomerMembership
bilan BITTA tranzaksiyada yoziladi/o'chiriladi — `workspace_tenant_index`
uchun allaqachon qabul qilingan naqshning aynan takrori, yangi presedent
emas.

Yangi `GET /v1/me/workspaces` (`api/me.py`, session-scoped, `get_current_
identity` orqali — `/v1/sessions` bilan bir xil naqsh) — login'dan keyin
klient chaqira oladigan BIRINCHI endpoint: foydalanuvchi a'zo bo'lgan
HAR BIR customer bo'ylab, o'sha customer'dagi workspace'larini (nomi,
roli bilan) qaytaradi. `CustomerOwner` uchun maxsus holat ham to'g'ri
ishlaydi: `get_workspace_context`dagi kabi, hech qanday WorkspaceMembership
qatori bo'lmasa ham, CustomerOwner o'z customer'idagi BARCHA workspace'larni
(workspace_admin roli bilan) ko'radi — bu alohida testda tasdiqlangan.
Index'ning o'zi ham to'g'ri tozalanishi (`remove_customer_member`da)
alohida testda tekshirilgan.

150 test, barchasi real Postgres'da.

`GET /v1/me/workspaces`ni qurish jarayonida yana ikkita xuddi shunday
"kashfiyot" bo'shlig'i aniqlandi: workspace ichida Task yoki Action'larni
RO'YXATLASH uchun ENDPOINT UMUMAN YO'Q EDI — faqat yaratish (`POST`) va
ID bo'yicha bitta-bitta o'qish (`GET .../{id}`) bor edi. Bu, masalan, task
board yoki action inbox kabi har qanday oddiy UI ekranini butunlay
qurib bo'lmaydigan qilardi (avvalgi barcha ID'larni allaqachon bilishni
talab qiladi). `GET /v1/workspaces/{id}/tasks` va `GET /v1/workspaces/{id}/
actions` qo'shildi (`?status=` filtri va `limit` bilan) — huquq darajasi
mavjud bitta-ID endpointlar bilan bir xil (workspace a'zoligi yetarli,
egalik/actor bo'yicha cheklov yo'q, chunki `get_task`/`get_action` ham
shunday ishlaydi). 6 ta yangi test (ro'yxat to'g'ri qaytarilishi, `status`
filtri, va boshqa workspace'ning yozuvlari sizib chiqmasligi — ikkalasi
uchun ham).

156 test, barchasi real Postgres'da.

Xuddi shu "kashfiyot bo'shlig'i" naqshi yana ikki joyda topildi: workspace
va customer a'zolarini QO'SHISH/ROLINI O'ZGARTIRISH/CHIQARISH mumkin edi,
lekin joriy ro'yxatni (kim allaqachon a'zo) ko'RISH uchun endpoint yo'q
edi — a'zolarni boshqaradigan har qanday UI ekrani uchun asosiy bo'shliq.
`GET /v1/workspaces/{id}/members` va `GET /v1/customers/{id}/members`
qo'shildi. Ikkalasi ham `user_id` va `display_name`ni (Identity `User`
bilan join orqali) qaytaradi — aks holda ro'yxat faqat ma'nosiz UUID'lar
bo'lib qolardi. Workspace-darajasidagi versiya `list_my_workspaces`dagi
CustomerOwner alohida holatini ham to'g'ri hisobga oladi: hech qanday
WorkspaceMembership qatori bo'lmasa ham, CustomerOwner ro'yxatda
`membership_id: null`, `role: "workspace_admin"` bilan ko'rinadi — aks
holda workspace_admin "mening jamoamda kim bor" deb so'raganida chalg'ituvchi,
noto'liq javob olardi. Ikkalasida ham qo'shimcha rol tekshiruvi yo'q —
a'zolikning o'zi yetarli (boshqarish `authorize_manage_*_members`ga
bog'liq, ko'rish emas). 2 ta yangi test.

158 test, barchasi real Postgres'da.

Yana bitta xuddi shu naqshdagi bo'shliq: kill switch'ni engage/disengage
qilish mumkin edi, lekin u HOZIR yoqilganmi yoki yo'qmi bilish uchun
endpoint yo'q edi — buni bilishning yagona yo'li uni o'zing engage qilish
(holatni o'zgartirib) yoki action taklif qilib, bloklanishini kutish edi.
`GET /v1/workspaces/{id}/kill-switch` va `GET /v1/customers/{id}/kill-switch`
qo'shildi — `engaged` bilan birga, yoqilgan bo'lsa `reason`/`engaged_at`/
`engaged_by`ni ham qaytaradi. Workspace a'zoligi/customer a'zoligi yetarli
(qo'shimcha rol tekshiruvi yo'q) — yangi action'lar bloklanishini bilish
sezgir ma'lumot emas.

160 test, barchasi real Postgres'da.

Backend'ga endi ikkita "kashfiyot" endpoint'lar to'plami qo'shilgani va
`GET /v1/me/workspaces` haqiqatda ishlashi tufayli, S3'ning frontend
qismini (chat'siz — pastga qarang) qurish uchun endi haqiqiy to'siq
qolmadi (faqat OIDC'ning o'zi, login'ning ICHKI mexanizmi uchun kerak,
lekin frontend qobig'ining o'zi buni kutmasdan qurilishi mumkin edi).
Shuning uchun **S3'ning frontend qismi (chat'siz) shu sessiyada qurildi**:

`frontend/` — Next.js 16 (App Router) + TypeScript + Tailwind, TRD 6.3
stack'iga mos. `create-next-app` bilan boshlab, quyidagilar qo'shildi:

- `src/lib/api.ts` — backend uchun yozilgan (qo'lda, OpenAPI codegen
  hali yo'q) tipdagi client. Har bir funksiya `sessionId`ni ochiq
  parametr sifatida oladi (hech qachon o'zi storage'dan o'qimaydi).
- `src/lib/session.ts` / `useSession.ts` — session ID'ni localStorage'da
  saqlash. `useSession` `useSyncExternalStore` orqali yozilgan (oddiy
  `useEffect`+`setState` emas) — bu React'ning "effect ichida setState"
  anti-pattern'ini ESLint darajasida to'g'ri chetlab o'tadi, SSR/hydration
  mos kelmasligini oldini oladi.
- Sahifalar: `/login` (dev/test session-ID kirish, aniq ogohlantirish
  bilan — "haqiqiy OIDC emas"), `/workspaces` (`GET /v1/me/workspaces`),
  `/workspaces/[id]` (kill-switch banner, task ro'yxati+yaratish+holat
  o'zgartirish, bildirishnomalar ro'yxati+o'qildi belgilash, a'zolar
  ro'yxati — hammasi real, testlangan backend endpoint'lariga ulangan).

**Backend'da bitta zarur o'zgarish kerak bo'ldi**: CORS. Frontend
(`localhost:3000`) backend'ni (`localhost:8000`) brauzerdan to'g'ridan-
to'g'ri chaqiradi — CORS sozlanmagan bo'lsa, har qanday `fetch()`
so'rovi Authorization header to'g'ri bo'lsa ham brauzer tomonidan
jimgina bloklanardi. `config.py`ga `cors_allowed_origins` (vergul bilan
ajratilgan, hech qachon `"*"` emas — har bir so'rov session token olib
yuradi) qo'shildi, `main.py`ga `CORSMiddleware`. `tests/test_cors.py`
(3 test) buni real HTTP orqali tekshiradi: sozlangan origin ruxsat
etiladi, sozlanmagan origin **qaytarilmaydi** (wildcard emasligini
isbotlaydi), va preflight `Authorization` header'ni ruxsat beradi.

**Butun oqim real backend'ga qarshi Playwright orqali (headless Chromium,
`npm run build`/tsc emas — haqiqiy brauzer) qo'lda tasdiqlandi**: login →
workspace ro'yxati → workspace ichiga kirish → seed qilingan R3
action'dan PENDING_APPROVAL bildirishnoma ko'rinishi → yangi task
yaratish → uni IN_PROGRESS'ga o'tkazish → bildirishnomani o'qildi deb
belgilash → a'zolar ro'yxatida owner ko'rinishi — 9 bosqichning barchasi
console xatosiz o'tdi. Bu "DEMO ≠ PRODUCTION" qoidasiga mos: frontend
kodi yozilgani va tip-check/lint'dan o'tgani "isbot" emas — real HTTP
orqali, real ma'lumot bilan ishlashi ko'rsatilgan.

**Ataylab qurilmagan**: Chat (FR-CONV) va Knowledge/RAG ekranlari —
backend'da bu domainlar umuman yo'q, shuning uchun ularning UI'sini
qurish "mavjud bo'lmagan backend uchun soxta frontend" bo'lar edi.

CI'ga yangi `frontend-quality` job (ESLint + `tsc --noEmit`) qo'shilgandan
keyin real xato topildi: `src/app/layout.tsx`dagi `LayoutProps<'/'>`
(Next.js 16'ning o'z, hujjatlashtirilgan konvensiyasi,
`node_modules/next/dist/docs/`da tasdiqlangan) toza checkout'da
`Cannot find name 'LayoutProps'` bilan qizardi — bu tip faqat
`next build`/`next dev`/`next typegen` ishga tushgandan keyin generatsiya
qilinadi, mahalliy tekshiruvim esa (tasodifan) allaqachon `next dev`
ishlatilgan papkada bo'lgani uchun yolg'on o'tgan edi. `rm -rf .next
node_modules && npm ci && ...` bilan chinakam toza reproduktsiya qilib
tasdiqlandi, `frontend-quality`ga `npx next typegen` qadami (`tsc`dan
oldin) qo'shilib tuzatildi va CI'da haqiqatda yashil bo'lgani real
`get_check_runs` orqali tekshirildi (barcha 4 job: lint/format/mypy,
frontend lint+types, migration round-trip, test suite).

Keyin **Actions bo'limi ham workspace sahifasiga qo'shildi** — avval
bu "keyingi navbatdagi" ekran deb qoldirilgan edi, garchi backend
endpointi (`GET /v1/workspaces/{id}/actions`) allaqachon tayyor va
testlangan bo'lsa ham (yana bir "yozish/o'zgartirish bor, ko'rish yo'q"
naqshi). Ataylab faqat o'qish: tool_name/risk_level/status ko'rsatiladi,
propose (yangi action yaratish) va approve (tasdiqlash) formalari
qurilmadi — ikkalasi ham chinakam sabablarga ko'ra: propose formasi
hali mavjud bo'lmagan tool/connector nomlarini erkin kiritishga ruxsat
berardi (S7/OD-002'dan oldin "DEMO ≠ PRODUCTION"ni buzardi), approve
tugmasi esa umuman ishlamaydi — `Approval.nonce` (bir martalik tasdiqlash
kaliti) faqat action taklif qilingan HTTP javobida bir marta qaytariladi,
`GET .../actions` orqali qayta ko'rinmaydi (`api/schemas.py`dagi
`ApprovalOut.nonce`ning docstring'iga qarang — bu ataylab shunday, 9.2
approval invariantlarining bir qismi). Real backend'ga (native
Postgres 16+pgvector, Redis) qarshi 163 test qayta o'tkazildi, so'ng
haqiqiy seed qilingan R3 action bilan Playwright orqali brauzer'da
tasdiqlandi — "send_email / risk: R3 / AWAITING_APPROVAL" ekranda
to'g'ri ko'rinadi, konsol xatosiz.

Xuddi shu turkumdagi yana bir bo'shliq ham yopildi: `GET
/v1/workspaces/{id}/audit` (FR-AUD-002, audit viewer) allaqachon qurilgan
va testlangan edi, lekin frontend'da hech qayerda ko'rinmas edi. Workspace
sahifasiga "Audit" bo'limi qo'shildi — event_type, actor_id, occurred_at
ro'yxati, faqat o'qish (bu allaqachon o'qish-uchun-endpoint, yozish yo'q).
Customer-darajasidagi audit (`GET /v1/customers/{id}/audit`) ataylab
qo'shilmadi — bu workspace sahifasi customer_id'ni bilmaydi (faqat
workspace_id URL'da bor) va alohida customer-darajasidagi sahifa/navigatsiya
talab qiladi, bu boshqa, kattaroq ish. Xuddi Actions bo'limi kabi, real
backend'ga qarshi (163 test) va Playwright orqali brauzer'da (seed
qilingan workspace'ning "workspace.created.v1" audit yozuvi ekranda
ko'rinishi) tasdiqlandi.

Uchinchi shu turkumdagi bo'shliq: `GET .../tasks/{id}/history`
(FR-TASK-007) allaqachon qurilgan va testlangan edi, task ro'yxatida
ko'rinmas edi. Har bir task qatoriga "Tarix"/"Tarixni yashirish" toggle
tugmasi qo'shildi — bosilganda `getTaskHistory`ni chaqiradi va
`from_status → to_status (actor_id, vaqt)` ro'yxatini shu qator ostida
ochadi. Playwright'da: yangi task yaratib, uni IN_PROGRESS'ga o'tkazib,
"Tarix" bosilganda "TODO → IN_PROGRESS" yozuvi ko'rinishi va keyin
yashirilishi real backend'ga qarshi tasdiqlandi.

To'rtinchi shu turkumdagi bo'shliq: FR-CTL-001/002ning session qismi
(`GET`/`DELETE /v1/sessions`) S2'dayoq qurilgan va testlangan edi, lekin
frontend faqat login'da bir martalik tasdiqlash uchun ishlatardi — o'zining
sessiya-boshqaruv ekrani yo'q edi. Yangi `/sessions` sahifasi (workspace'lar
sahifasidagi "Sessiyalar" havolasidan) qo'shildi: foydalanuvchi darajasida
(workspace'ga bog'liq emas, `useSession`ning o'zi ishlatiladi, workspace
context kerak emas) barcha faol sessiyalar, joriysi belgilangan holda, va
boshqalarini uzoqdan yopish tugmasi. Joriy sessiyani ataylab shu tugma
bilan yopib bo'lmaydi (UX: o'zini-o'zi darhol qulflab qo'yishning oldini
olish) — buning uchun mavjud "Chiqish" bor. Ikkinchi, alohida `Session`
qatori (bir xil user_id, boshqa session_id) haqiqiy backend orqali
yaratilib, Playwright'da: (1) ikkalasi ham ro'yxatda ko'rinishi, joriysi
belgilangan holda, (2) boshqasini "Yopish" bosilgach yo'qolishi, (3) bu
UI-only emasligi — `curl -H "Authorization: Bearer <joriy>"
/v1/sessions` orqali serverning o'zi ham endi faqat bitta sessiya
qaytarishi — alohida tasdiqlandi.

Beshinchi: a'zolar bo'limiga mavjud a'zoning rolini almashtirish
(`PATCH .../members/{membership_id}`) va chiqarish (`DELETE
.../members/{membership_id}`) tugmalari qo'shildi — FR-WKS-003, S2'dayoq
qurilgan/testlangan, lekin faqat ro'yxatlash bor edi. Yangi a'zo qo'shish
(`POST .../members`) ataylab qo'shilmadi: u `customer_membership_id`ni
talab qiladi (user_id emas), buni tanlash uchun avval "shu customer'ning
a'zolari kim" degan ro'yxat kerak (`GET /v1/customers/{id}/members`) —
bu esa yana customer_id talab qiladi, xuddi customer-darajasidagi audit/
notification-preferences qurilmagan sababi bilan bir xil (workspace
sahifasi customer_id'ni bilmaydi). Rol almashtirish/chiqarish esa
allaqachon `listWorkspaceMembers`dan kelgan `membership_id`dan
foydalanadi, shuning uchun bu cheklovga duch kelmadi.

**Eslatma (bug emas, kuzatuv)**: workspace-darajasida "oxirgi
workspace_admin'ni chiqarib/pasaytirib bo'lmaydi" degan invariant yo'q
(customer-darajasidagi "oxirgi Owner" invarianti FR-WKS-005'da bor, lekin
workspace_service.change_workspace_member_role/remove_workspace_member'da
yo'q) — nazariy jihatdan bitta workspace_admin o'zini-o'zi member'ga
tushirib yoki chiqarib qo'yishi mumkin. Amalda bu kam xavfli: CustomerOwner
har doim WORKSPACE_ADMIN sifatida rezolyutsiya qilinadi (WorkspaceMembership
qatori bo'lmasa ham, yuqoriga qarang), shuning uchun customer'ning o'zi
hech qachon boshqaruvsiz qolmaydi. Bu endpoint'larning o'zi allaqachon
qurilgan/testlangan edi — men faqat frontend'ga ulab qo'ydim, yangi
invariant qo'shish minimal-diff doirasidan tashqarida (agar kerak bo'lsa,
bu alohida change request).

**Yangi `/customers/[id]` sahifasi qo'shildi — customer_id talab qilgani
uchun oldingi beshta commit'da ataylab qoldirilgan hamma narsa endi bir
joyda.** `/workspaces` ro'yxatidagi har bir qatorga customer nomi endi
alohida havola (`/customers/{customer_id}`) — `listMyWorkspaces`ning
o'zi customer_id/customer_name'ni allaqachon qaytargani uchun bu yangi
"kashfiyot" endpointi talab qilmadi, faqat mavjud ma'lumotdan foydalanish
edi. Sahifa quyidagilarni ochadi, hammasi allaqachon qurilgan/testlangan:

- **Kill switch** (FR-CTL-003, `.../kill-switch/engage|disengage`) —
  workspace sahifasidagi banner'dan farqli, bu yerda haqiqatda
  yoqish (sabab bilan)/o'chirish mumkin, faqat ko'rish emas.
- **A'zolar** (FR-WKS-005, `POST/PATCH/DELETE .../members`) — ro'yxat,
  rol almashtirish, chiqarish, VA **yangi a'zo qo'shish**. Bu oxirgisi
  workspace-darajasida ataylab qilinmagan edi (`customer_membership_id`
  kerak edi), lekin customer-darajasidagi `POST .../members`
  `user_id`ni to'g'ridan-to'g'ri qabul qiladi — xuddi shu customer_id
  cheklovi bu yerda umuman yo'q, chunki sahifaning o'zi allaqachon
  customer_id ustida turibdi. User ID hamon xom UUID input — foydalanuvchi
  qidirish/tanlash endpointi TRD'da yo'q.
- **Bildirishnoma sozlamalari** (FR-NTF-004, `GET/PUT
  .../notification-preferences[/{type}]`) — 3 turni yoqish/o'chirish.
  SECURITY_ALERT uchun tugma yo'q (backend uni hech qachon o'chirishga
  ruxsat bermaydi — `notification_service.set_notification_preference`),
  UI ham shunga mos "doim yoqilgan" deb ko'rsatadi, xato ko'rsatishga
  urinish o'rniga.
- **Bildirishnomalar** (`GET .../notifications`, workspace filtri yo'q) —
  shu customer ostidagi BARCHA workspace'lardagi bildirishnomalar bitta
  ro'yxatda.
- **Audit** (FR-AUD-002, `GET .../audit`) — customer-darajasida, workspace
  sahifasidagi audit'dan farqli (u faqat bitta workspace uchun edi).

Rol asosidagi UI-gating yo'q — boshqa sahifalar bilan bir xil naqsh:
tugma har doim ko'rsatiladi, ruxsat yo'q bo'lsa backend 403 qaytaradi.
Real backend'ga qarshi (163 test) va Playwright orqali brauzer'da to'liq
tasdiqlandi: haqiqiy ikkinchi User yaratib customer'ga auditor sifatida
taklif qilish → member'ga tushirish → chiqarish (uchtasi ham audit'da
mos `customer.member_invited/role_changed/removed.v1` yozuvlari bilan
ko'rinishi tekshirildi), FAILED_ACTION sozlamasini o'chirib/yoqib
qaytarish, SECURITY_ALERT'da tugma yo'qligi, va kill switch'ni haqiqatan
yoqib/o'chirish — barchasi konsol xatosiz.

**Frontend E2E testlari CI'ga qo'shildi — bu paytgacha "real backend'ga
qarshi Playwright orqali tasdiqlandi" degan har bir da'vo qo'lda,
scratchpad'dagi throwaway skriptlar bilan qilingan edi.** Bu haqiqiy
bo'shliq edi: hech biri repo'ga kirmagan, demak hech qanday keyingi
o'zgarish ularni qayta ishga tushirmasdi — "DEMO ≠ PRODUCTION" qoidasi
("testlarsiz modul CLOSED bo'lmaydi") aslida frontend uchun to'liq
qamrab olinmagan edi, faqat lint/tsc (kod yozilgani, ishlashi emas).

Tuzatish: `frontend/e2e/` — `@playwright/test` bilan yozilgan, ikkita
spec (`workspace.spec.ts`, `customer.spec.ts`) bu sessiyada qo'lda
tekshirilgan HAR BIR oqimni (login → workspace → task/action/
bildirishnoma/audit/tarix, va customer sahifasidagi a'zo qo'shish/rol
o'zgartirish/chiqarish/bildirishnoma sozlamalari/kill switch) qamrab
oladi. `backend/scripts/seed_e2e_demo.py` — `tests/integration/
conftest.py`dagi `seed_workspace_member` bilan bir xil dev/test seam'dan
foydalanadigan, mustaqil ishga tushiriladigan seed skripti (haqiqiy OIDC
hali yo'q, session HTTP orqali yaratib bo'lmaydi).

**Ikkita spec ATAYLAB ikkita mustaqil seed ishlatadi** (`--prefix E2E_`
va `--prefix E2E_CUSTOMER_`) — buni yozish jarayonida haqiqiy, nozik xato
ochib berdi: dastlab ikkalasi bitta seed'ni bo'lishgan edi, va
`customer.spec.ts`ning kill switch'ni yoqishi (`SECURITY_ALERT`ni
customer'ning BARCHA a'zolariga broadcast qiladi — `kill_switch_service.
engage_customer_kill_switch`) `workspace.spec.ts`ning "bildirishnomani
o'qildi deb belgilagandan keyin 0 ta belgilanmagan qoladi" degan
assertion'ini buzdi (aslida 1 ta — SECURITY_ALERT — qolib ketardi,
chunki u xuddi shu Demo User'ga, xuddi shu workspace'ning
bildirishnoma ro'yxatida ham ko'rinadi — `list_notifications_for_user`
"workspace_id berilsa, o'sha workspace YOKI customer-keng (workspace_id
NULL) bildirishnomalarni" qaytaradi, ataylab shunday hujjatlashtirilgan).
Bu ikkita spec fayl bir xil mutable seed holatini bo'lishmasligi kerak
degan haqiqiy dars edi — E2E test dizaynida keng tarqalgan xato sinfi,
shuning uchun aynan shu injiq bog'liqlikni ushlab, kelajakda takrorlanishining
oldini olish uchun `--prefix` qo'shildi.

CI'ga yangi `e2e` job qo'shildi (`.github/workflows/ci.yml`): real
Postgres+Redis service konteynerlari, backend `uvicorn` orqali fon
jarayonida (health-check `/healthz` orqali kutiladi), frontend esa
`next build && next start` orqali — ataylab `next dev` emas, production
build'ning o'zi ishlashini tekshirish uchun. Mahalliy tekshiruvda ham
xuddi shu production-build ketma-ketligi (`npm run build && npm run
start`) qo'lda takrorlandi va ikki marta ketma-ket (fresh seed bilan)
ishga tushirilib, natija barqaror ekani tasdiqlandi.

Bu ishni qilish jarayonida boshqa bir haqiqiy xato ham topildi va
tuzatildi: dastlabki spec `page.getByText("AWAITING_APPROVAL")` (strict-
mode, aniq bitta element kutadi) ishlatgan edi, lekin workspace
sahifasida endi Audit bo'limi ham bor va u yerda `action.awaiting_
approval.v1` degan audit event_type string ham ko'rinadi — Playwright'ning
`getByText` standart rejimi katta-kichik harfga sezgir emas va substring
bo'yicha moslashtiradi, shuning uchun ikkalasi ham topilib strict-mode
xatosi berdi. Bu mening avvalgi qo'lda yozilgan scratchpad skriptlarimda
hech qachon ko'rinmagan edi, chunki ular eski `page.waitForSelector("text=
...")` API'sini ishlatgan (birinchi moslikni qabul qiladi, strict emas) —
yangi, qat'iyroq `getByText().toBeVisible()` shakli buni haqiqatda
ushladi. `{ exact: true }` bilan tuzatildi.

**Yangi `e2e` CI job birinchi marta ishga tushganda haqiqatda qizardi —
xuddi shu, sessiya davomida bir necha marta takrorlangan dars: "mahalliy
qo'lda tekshirish CI'ning o'zi emas".** Sabab oddiy va aniq edi: backend
health-check qadami `GET /healthz`ni kutgan edi, lekin `main.py`
`health_router`ni `prefix="/v1"` bilan ro'yxatdan o'tkazadi — haqiqiy
yo'l `/v1/healthz`. Bu mahalliy hech qachon ko'rinmagan edi, chunki
mening barcha oldingi qo'lda tekshiruvlarim serverning tayyorligini
`curl .../docs` orqali kutgan edi (`/healthz`ning o'zi hech qachon
haqiqiy so'rov bilan chaqirilmagan edi) — CI skriptini yozishda esa
to'g'ri yo'lni tekshirmasdan `/healthz` deb taxmin qildim. Job logi buni
aynan ko'rsatdi: backend to'g'ri ishga tushgan, `/healthz`ga har bir
so'rov esa 404 qaytargan. Bitta qatorli tuzatish (`/v1/healthz`), keyin
`curl -s .../v1/healthz` bilan mahalliy alohida tasdiqlandi va butun
E2E oqimi (seed → build → start → Playwright) yana boshidan, ikkinchi
marta qo'lda takrorlanib, hali ham yashil ekani ko'rsatildi.

**Yana bir haqiqiy xato topildi va tuzatildi — Product Owner uchun
demo tayyorlash jarayonida.** Foydalanuvchiga real ishlab turgan dasturni
ko'rsatish uchun brauzer orqali sahifalarni suratga olish paytida:
authenticated sahifada haqiqiy brauzer reload (F5) qilinganda, foydalanuvchi
haqiqiy, amaldagi session'ga ega bo'lsa ham, **`/login`ga qaytarib
yuborilardi**. Sabab `useSession.ts`da: `getServerSnapshot` doim `null`
qaytarardi, shuning uchun HAR bir hard-navigation'ning birinchi client
render'ida `sessionId` vaqtincha `null` bo'lib ko'rinardi (server bilan
mos kelishi uchun majburiy) — lekin shu bitta render'dagi `useEffect`
aynan shu vaqtinchalik `null`ni "sessiya yo'q" deb qabul qilib,
`router.replace("/login")`ni darhol chaqirardi, React o'zining haqiqiy
localStorage qiymatiga tuzatish kiritishga ulgurmasdan turib. Bu S3
frontend qurilgandan beri **har bir** authenticated sahifada mavjud bo'lgan
haqiqiy production xato edi — F5 bosgan yoki to'g'ridan-to'g'ri havola
ochgan har qanday haqiqiy foydalanuvchi kutilmaganda "chiqarib
yuborilardi", garchi hech qachon avvalgi E2E testlarda ko'rinmagan edi
(ular hech qachon `page.reload()`/hard-navigation qilmagan, faqat
SPA-ichi client navigatsiyasidan foydalangan, u yerda bu race umuman
yuzaga kelmaydi).

Tuzatish: `getServerSnapshot` endi `null` o'rniga `undefined` qaytaradi —
"hali aniqlanmagan" (server/birinchi render) holatini "sessiya yo'qligi
aniq tasdiqlangan" (`null`, faqat haqiqiy `getStoredSessionId()`dan keladi)
holatidan ajratib beradi; redirect effekti faqat aniq `null`da ishlaydi,
`undefined`da hech qachon emas. Bu avvalgi tuzatishda (sessiya oxirida)
qo'llanilgan `useEffect`+alohida `hasHydrated` state yondashuvidan farqli —
o'sha yondashuv `react-hooks/set-state-in-effect` ESLint qoidasini
buzardi (xuddi `useSession`ning birinchi versiyasini yozishda ham
duch kelingan muammo), shuning uchun alohida state qo'shmasdan, faqat
sentinel qiymat farqi orqali hal qilindi.

Bu haqiqiy production xato ekanini isbotlash uchun (audit-zanjiri
tuzatishidagi kabi) avval buzuq holatga qaytarib ko'rildi — haqiqiy
`page.reload()` bilan `/login`ga qaytarilishi qayta tasdiqlandi — keyin
tuzatilgan holat bilan qayta tekshirilib, endi joyida qolishi ko'rsatildi.
Bu ikkalasi ham `next build && next start` (production build, `next dev`
emas) ustida, real backend'ga qarshi qilindi. Yangi regressiya testi
`frontend/e2e/workspace.spec.ts`ga qo'shildi ("a hard reload does not
bounce an authenticated user to /login") — xuddi shu revert-test-restore
usuli bilan CI'ning o'zi ham endi buni doimiy tekshiradi.

**Ikkita real data-integrity xato topildi va tuzatildi — kod bazasini
professional darajaga tayyorlash jarayonida, forma yuborish tugmalarini
ko'rib chiqishda.** `customer_memberships`da `(customer_id, user_id)`
bo'yicha, `workspace_memberships`da `(customer_membership_id,
workspace_id)` bo'yicha HECH QANDAY unique constraint yo'q edi —
`invite_customer_member`/`add_workspace_member` esa mavjudlikni oldindan
tekshirmasdan to'g'ridan-to'g'ri yangi qator qo'shardi. Amalda bu real
bo'shliq: customer sahifasidagi "Qo'shish" tugmasida (yoki boshqa hech
qanday formada butun ilova bo'ylab) so'rov jarayonida tugmani
o'chirib qo'yish yo'q edi — ikki marta tez ketma-ket bosilsa (yoki ikkita
admin bir vaqtda bir xil odamni taklif qilsa), bitta odam uchun IKKITA
mustaqil `CustomerMembership` qatori yaratilardi, `list_customer_members`
esa uni ikki marta ko'rsatardi — har biri alohida rol/chiqarish bilan.

Tuzatish 0010-migratsiyaning (`Action.idempotency_key` workspace bo'yicha
qamrash) xuddi shu, allaqachon isbotlangan naqshini takrorlaydi: 0012-
migratsiya ikkala jadvalga ham unique constraint qo'shdi (haqiqiy
race-safe himoya — oldindan SELECT tekshiruvi emas, chunki ikkita bir
vaqtdagi so'rov TOCTOU orqali baribir o'tib ketishi mumkin edi).
`invite_customer_member`/`add_workspace_member`ning o'zi insert'ni
`session.begin_nested()` (SAVEPOINT) ichiga oldi, natijadagi
`IntegrityError`ni tutib, aniq `DuplicateMembershipError`/
`DuplicateWorkspaceMembershipError`ga aylantiradi (`api/errors.py`da
409 `ALREADY_MEMBER` javobiga mos keladi) — xom 500 o'rniga.

Tuzatish haqiqiyligi audit-zanjiri uslubida isbotlandi: migratsiya 0011'ga
qaytarilib (constraint olib tashlanib) va kod ham eski holatga qaytarilib,
haqiqiy Postgres'ga qarshi qo'lda yozilgan repro skripti bitta foydalanuvchi
uchun ikki marta `invite_customer_member` chaqirib, natijada **2 ta**
mustaqil qator borligi tasdiqlandi — keyin ikkalasi ham tiklanib, xuddi
shu chaqiruv endi aniq `DuplicateMembershipError` bilan rad etilishi
ko'rsatildi. Ikkita yangi regressiya testi (`test_cannot_invite_the_same_
user_twice`, `test_cannot_add_the_same_workspace_member_twice`)
`test_customer_service.py`ga qo'shildi.

Bundan tashqari, frontend'ning o'zida ham (backend himoyasi endi
mavjud bo'lsa ham, halol ikki marta bosishda tushunarsiz xato ko'rsatish
o'rniga jimgina e'tiborsiz qoldirish uchun) uchta forma — task yaratish,
kill switch yoqish, a'zo taklif qilish — so'rov jarayonida submit
tugmasini o'chirib qo'yadigan holatga o'tkazildi (`creatingTask`/
`engagingKillSwitch`/`invitingMember` state'lari). 165 test, barchasi
real Postgres'da; frontend E2E suite ham (workspace + customer specs)
qayta o'tkazilib, regressiya yo'qligi tasdiqlandi.

**FR-ADM va global kill switch bo'yicha tekshiruv o'tkazildi (TRD'ning
o'zidan, xotiradan taxmin qilinmadi) — xulosa: hozircha qurilmaydi, chunki
haqiqiy arxitektura qarori talab qiladi.** TRD'ni (`docs/DODA-TRD-v2.0.docx`)
to'g'ridan-to'g'ri o'qib chiqib (3.9-bo'lim FR-ADM-001..006, 2.2-bo'lim rol
jadvali, 3.8-bo'lim FR-CTL-003) ikkita narsa aniqlandi: (1) FR-ADM aslida
admin panel (customer/workspace ro'yxati, rol-permission matritsa
tahrirlagichi, konnektor boshqaruvi, ABAC policy versiyalash, AI byudjeti,
feature flag) haqida — global kill switch bilan bog'liq emas, bu sessiyada
oldinroq qilingan taxmin noto'g'ri edi; global kill switch aslida
FR-CTL-003ning ikkinchi yarmi ("Global va workspace kill switch" — workspace
qismi allaqachon qurilgan). (2) Muhimi — 2.2-bo'lim rol jadvali Platform
Owner'ni "R5 (dual control bilan)" deb belgilaydi, ya'ni global kill switch
**ikki alohida shaxs** tasdig'ini talab qiladi (9.1: R5 — "Ikki alohida
shaxs"). Bugungi kod bazasida (`domain/security/roles.py`) `CustomerRole` va
`WorkspaceRole`dan boshqa hech qanday rol yo'q — `platform_owner` degan,
tenant'ga bog'liq bo'lmagan primitiv umuman mavjud emas, va approval
modelining o'zi ham faqat bitta approver'ni tekshiradi (9.2), ikkita
mustaqil shaxsni talab qiluvchi dual-control mexanizmi yo'q. Bitta AI agent
+ bitta Product Owner bilan ishlaydigan loyihada "ikkinchi alohida shaxs"
kim bo'lishi ham hal qilinmagan savol. Demak bu FR-CTL-003'ning global
yarmini qurish (a) yangi, tenant-scoped bo'lmagan authorization primitivini
kiritish, (b) approval modeliga dual-control semantikasini qo'shish, (c) bu
ikkinchi shaxs kim bo'lishini hal qilishni talab qiladi — bularning
barchasi OD-002/OIDC kabi Product Owner qarorini talab qiladigan haqiqiy
arxitektura qarori, "kichik xavfsiz keyingi qadam" emas. Shuning uchun
so'ralmagan holda amalga oshirilmadi (QOIDA 2: change request) — workspace
darajasidagi kill switch (allaqachon qurilgan/drill-testlangan) hozircha
yagona amalga oshirilgan qism bo'lib qoladi.

**FR-AUD-004ning ikkinchi yarmi ("Kunlik verification job; buzilishda
alert") qurildi — hash-zanjiri yozilishi (concurrency bilan) allaqachon bor
edi, lekin uni haqiqatan TEKSHIRADIGAN hech narsa yo'q edi.**
`audit_service.verify_audit_chain` har bir customer'ning audit zanjirini
yozilish tartibida (`(created_at, id)`, xuddi `list_audit_events`ning
pagination tartibi) aylanib chiqadi, har bir yozuvning hash'ini o'z
maydonlari + oldingi yozuvning saqlangan hash'idan qayta hisoblab, saqlangan
qiymat bilan solishtiradi — mos kelmasa `hash_mismatch`, zanjir bog'lanishi
uzilgan bo'lsa `prev_hash_mismatch` deb belgilaydi. Buni yozish jarayonida
haqiqiy narsa aniqlandi: `audit_events` jadvalidagi
`audit_events_no_update_delete` trigger (0001-migratsiya) UPDATE/DELETE'ni
allaqachon butunlay bloklaydi — birinchi test urinishim (ORM orqali qatorni
UPDATE qilib "tamper" simulyatsiya qilish) shu trigger tomonidan rad etildi.
Demak bu funksiya haqiqatda qaysi tahdidga qarshi himoya qilishini aniq
belgilash kerak bo'ldi: trigger faqat UPDATE/DELETE'ni to'xtatadi, INSERT'ga
tegmaydi — shuning uchun test to'g'ri stsenariyga (mavjud
`record_audit_event`ni chetlab o'tib, to'g'ridan-to'g'ri soxta hash bilan
yangi qator qo'shish — kelajakdagi xato yoki soxta tarixiy yozuv) tuzatildi,
va bu haqiqatan aniq bitta buzilgan yozuvni ko'rsatishi tasdiqlandi.

`GET /v1/customers/{id}/audit/verify` — audit viewer bilan bir xil auditoriya
(`authorize_view_customer_audit`: CustomerOwner/Auditor), chunki bu faqat
o'qish/aniqlash, hech narsani tuzatmaydi yoki yozmaydi (tekshirishning o'zi
`audit.chain_verified.v1` sifatida audit qilinadi, "audit.viewed.v1" bilan
bir xil naqsh). "Kunlik job" qismi uchun `backend/scripts/
verify_audit_chain_job.py` qo'shildi — `UserCustomerIndex` (RLS'siz
bootstrap jadval, xuddi `GET /v1/me/workspaces` ishlatgani) orqali barcha
customer'larni topib, har birini tekshiradi, buzilish topilsa stderr'ga
yozib exit code 1 bilan chiqadi (haqiqiy paging/alerting tizimi hali yo'q —
"alert" shu exit code + stderr, cron/systemd wrapper buni ushlay oladi).
Skriptni yozishda yana bitta real xato topildi: `db.get_session()` FastAPI
`Depends()` uchun mo'ljallangan yalang'och async generator, `@asynccontext
manager` bilan bezatilmagan — `async with get_session()` `TypeError` beradi;
`async_session_factory()`ning o'ziga to'g'ridan-to'g'ri murojaat qilib
tuzatildi. Tuzatilgandan keyin skript shu sessiya davomida yig'ilgan haqiqiy
~2365 ta customer'ning barchasiga qarshi ishga tushirilib, barchasi toza
(buzilish yo'q) ekani tasdiqlandi.

Frontend'ning customer sahifasiga "Zanjirni tekshirish" tugmasi qo'shildi
(Audit bo'limida) — natijani yashil ("Zanjir sog'lom — N ta yozuv
tekshirildi") yoki qizil (necha ta buzilish) banner sifatida ko'rsatadi.
Real backend'ga (169 test, barchasi real Postgres'da) va haqiqiy brauzerga
(production build, seed qilingan customer) qarshi tasdiqlandi — tugma
bosilganda haqiqiy `audit.chain_verified.v1` yozuvi hosil bo'lishi va
"Audit" ro'yxatida darhol ko'rinishi kuzatildi, konsol xatosiz.

169 test, barchasi real Postgres'da.

**NFR-SEC-002/003ning CI qismi qurildi** — "Secret scan CI'da" va
"Dependency audit" ikkalasi ham TRD'da MVP darajasidagi Must talab sifatida
yozilgan edi, lekin CI'da hech qanday bunday tekshiruv yo'q edi. Yangi
`security-scan` job (`.github/workflows/ci.yml`) uchta narsani tekshiradi:
(1) `gitleaks` (pinned binary, v8.21.2 — `gitleaks/gitleaks-action`ning
o'zi emas, chunki u GitHub Organization repo'lari uchun litsenziya kaliti
talab qiladi, CLI'ning o'zi esa sof MIT va kalit talab qilmaydi) butun repo
tarixini secret'larga tekshiradi; (2) `pip-audit` backend dependency'larini
CVE'larga tekshiradi; (3) `npm audit --audit-level=high` frontend
dependency'larini tekshiradi. Uchalasi ham hozircha toza (0 ta topilma) —
mahalliy real ishga tushirib tasdiqlandi, sintetik emas.

Buni qurishda ikkita narsa aniqlandi: (1) `pip-audit` boshida 7 ta zaiflikni
topdi — lekin bular loyihaning o'z dependency'lari emas, balki venv'dagi
eskirgan `pip`ning o'zida (versiya 24.0); `pip install --upgrade pip`ni
audit'dan oldin qo'shish bilan tuzatildi (haqiqiy tuzatish, suppress emas).
(2) Gitleaks qadamini birinchi yozishda workflow'ning global `defaults.run.
working-directory: backend`ini hisobga olmagan edim — agar step o'z
`working-directory: .`ini aniq belgilamasa, u indamay faqat `backend/`ni
skanerlaydi, `frontend/`, `.github/`, va root darajadagi fayllarni umuman
ko'rmaydi (va bu holatda ham "0 topilma" qaytargani uchun xato sezilmay
qolishi mumkin edi — "yashil" bo'lardi, lekin noto'g'ri sababdan). Qo'lda
haqiqiy `gitleaks` binary'sini yuklab, aynan shu repo tarixiga qarshi
ishga tushirib tasdiqlandi (`working-directory` tuzatilgandan keyin ham,
oldin ham "no leaks found" — repo'da haqiqatda hech narsa yo'qligi
tasdiqlandi, lekin tuzatish CI'ning to'g'ri joyni tekshirishini
kafolatlaydi).

`.github/dependabot.yml` ham qo'shildi (pip/backend, npm/frontend,
github-actions/root, haftalik) — NFR-SEC-003'ning "high <=7 kun ichida"
qismini CI o'zi o'lchay olmaydi (bu muddat kuzatish infratuzilmasi talab
qiladi, hozircha yo'q), lekin Dependabot yangilanishlarni PR sifatida
avtomatik taklif qilib, bu muddatni real qiladigan jarayonni ta'minlaydi —
qat'iy SLA hali odam/jarayon zimmasida qoladi, bu CLAUDE.md'da halol
belgilab qo'yildi (yolg'on "avtomatik enforce qilinadi" da'vosi emas).

169 test, barchasi real Postgres'da (CI job qo'shildi, mavjud test
suite'ga o'zgarish yo'q).

**NFR-MNT-001ning "ADR mavjud" qismi qurildi — va buni yozish jarayonida
TRD 19.4'dagi sakkizta Product Owner qarori (OD-001..008) hech qayerda
bitta joyda ko'rinmasligi aniqlandi, uchtasi esa hujjatdagi o'z muddatidan
allaqachon o'tib ketgani topildi.** `docs/adr/`ga TRD 6.4'dagi ADR
ro'yxatining hammasi (ADR-001..007) yozildi: beshtasi (001 modular
monolith, 002 pgvector, 003 transactional outbox, 004 model gateway, 005
RLS ikkinchi qatlam) TRD'da "Qabul qilingan" deb belgilangan, real kodga/
incident'larga (masalan ADR-005'da yuqoridagi RLS-bypass voqeasi) havola
bilan yozildi; ikkitasi (006 hosting/data residency, 007 birinchi
konnektor) TRD'ning o'zida "Ochiq" deb qolgan, shuning uchun "Open" holatda,
javob o'ylab topilmasdan yozildi.

Buni yozish OD-* ro'yxatini to'liq TRD 19.4'dan o'qishni talab qildi — va
shu jarayonda muhim narsa aniqlandi: OD-002 va OD-006 (kill switch dual-
control) allaqachon bilingan edi, lekin OD-003 (AI providerga qaysi
ma'lumot sinfi yuborilmasin), OD-005 (hosting/data residency — ADR-006
allaqachon shuni aytadi) va OD-008 (oylik AI/infra byudjeti) TRD'ning o'z
muddatidan (mos ravishda S3 oxiri, S2 boshlanishidan oldin, S2 oxiri)
allaqachon o'tib ketgan — bu bosqichlar (Safe actions, API adapterlari)
shu kod bazasida allaqachon substantially bajarilgan. Bugungi kunda bu
uchtasi haqiqiy zarar keltirmayapti, chunki ularga bog'liq ish (AI/prompt
chaqiruvlari, real infra deploy, byudjet enforcement) hali boshlanmagan —
lekin shu ish boshlanishidan OLDIN yopilishi kerak, aks holda TRD'ning o'z
ogohlantirishi bo'yicha "texnik jamoa taxmin qiladi, taxmin esa keyinchalik
qayta qurish va xavfsizlik ziddiyatiga aylanadi". `docs/open-decisions.md`
— shu sakkiztasining bittasi joyda, holati bilan (hal qilingan/ochiq/
muddatidan o'tgan) ko'rinadigan tracker. README.md'ga ikkalasiga ham
havola qo'shildi (`## Arxitektura qarorlari va ochiq savollar`).

Bu sof hujjatlashtirish — kod o'zgarmadi, 169 test o'zgarishsiz qoladi.
Aniqlikni tekshirish uchun `test_rls_coverage.py`ning o'zidan (grep
o'rniga to'g'ridan-to'g'ri o'qib) `KNOWN_RLS_EXEMPT_TABLES` ro'yxatini
oldim — dastlab ADR-003/005'ni CLAUDE.md'dagi eski ("ikkita istisno")
paragrafga tayanib yozgan edim, lekin bu eskirgan edi: `user_customer_index`
(0011-migratsiya) keyinroq uchinchi istisno sifatida qo'shilgan, CLAUDE.md
esa xronologik log bo'lgani uchun eski paragrafni orqaga qaytarib
yangilamagan. ADR'larning o'zi nuqtai-vaqt hujjat (point-in-time reference)
bo'lishi kerak, xronologik log emas — shuning uchun haqiqiy joriy holatga
(uchta istisno) tuzatildi.

**NFR-ACC-001 (WCAG 2.2 AA, "Avtomatik + qo'lda audit") uchun birinchi
avtomatik tekshiruv qo'shildi — hech qachon frontend'ga qarshi bironta
accessibility check ishga tushirilmagan edi.** `frontend/e2e/
accessibility.spec.ts` (`@axe-core/playwright`) real backend+frontend'ga
qarshi har bir haqiqiy authenticated sahifani (`/login`, `/workspaces`,
`/workspaces/[id]`, `/customers/[id]`, `/sessions`) skanerlaydi va
`serious`/`critical` darajadagi WCAG 2.0/2.1/2.2 AA buzilishlari nolga
teng bo'lishini talab qiladi — moderate/minor darajadagilar hozircha
qat'iy gate emas (haligi subyektiv/shovqinli topilmalar uchun), lekin
`serious`/`critical` "gate emas, faqat qayd etiladi" bo'lishi mumkin
emas edi, chunki bular haqiqiy, foydalanuvchiga to'sqinlik qiladigan
kamchiliklar.

Birinchi haqiqiy ishga tushirishda ikkita **real** WCAG buzilishi topildi,
sintetik emas:
1. `/customers/[id]`dagi ikkita `<select>` (yangi a'zo roli tanlash, mavjud
   a'zo rolini o'zgartirish) hech qanday accessible name'ga ega emas edi
   (`critical: select-name`) — ekran o'quvchisi foydalanuvchisi uchun bu
   ikkala boshqaruv elementi ham "nomsiz" bo'lib qolardi. `aria-label`
   qo'shib tuzatildi.
2. `/workspaces/[id]` va `/customers/[id]`dagi 7 ta joyda "ro'yxat bo'sh"
   holati `<ul>` ichida to'g'ridan-to'g'ri `<p>` sifatida render qilinardi
   (`serious: list` — `<ul>`/`<ol>` faqat `<li>`ni to'g'ridan-to'g'ri farzand
   sifatida qabul qilishi kerak). Bu yerda faqat bitta joy (bo'sh task
   ro'yxati) haqiqiy topilma sifatida ko'rindi, chunki seed qilingan
   ma'lumotda faqat shu ro'yxat bo'sh edi — lekin xuddi shu naqsh (action/
   bildirishnoma/audit/a'zo ro'yxatlarining bo'sh holati) yana olti joyda
   aynan takrorlangan edi, shuning uchun barcha ettitasi ham `<p>`dan
   `<li>`ga o'zgartirildi — faqat testda ko'ringan bittasini emas, xuddi
   shu buzuq naqshning har bir nusxasini.

Ikkalasi ham qayta build+start qilingan production frontend'ga qarshi,
haqiqiy `axe-core` skaneri bilan qayta tekshirildi (avval qizil, tuzatishdan
keyin yashil) — audit-zanjiri uslubidagi revert-test-restore emas, lekin
xuddi shunday "avval haqiqiy xato ko'rsat, keyin tuzatilganini ko'rsat"
tamoyili. Mavjud ikkita E2E spec (`workspace.spec.ts`, `customer.spec.ts`)
ham `<p>`→`<li>` o'zgarishidan keyin qayta ishga tushirilib, regressiya
yo'qligi tasdiqlandi (ularning assertion'lari `getByText` orqali, tegga
bog'liq emas). CI'ning mavjud `e2e` job'iga uchinchi mustaqil seed
(`--prefix E2E_A11Y_`) qo'shildi — xuddi ikkita mavjud spec bir xil seed'ni
bo'lishmasligi kerak degan avvalgi dars bilan bir xil ehtiyot choralari,
garchi bu spec hech qanday state'ni o'zgartirmasa ham (faqat navigatsiya +
skanerlash).

Keyingi qadam — S3'ning qolgan qismi: haqiqiy OIDC oqimi
(FR-AUTH-001, hozir `session_service.create_session` faqat dev/test
seam) — bu tashqi OIDC provayder ma'lumotlarini (client_id/secret,
issuer URL) talab qiladi, Product Owner'dan kelishi kerak. Yoki OD-002
(connector tanlovi) S6'dan oldin hal qilinishi kerak.

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
- ~~R3 approval va workspace-a'zolik boshqaruvi faqat WorkspaceRole'ni
  tekshiradi~~ — **tuzatildi**: `get_workspace_context` endi CustomerOwner'ni
  WORKSPACE_ADMIN sifatida rezolyutsiya qiladi (yuqoriga qarang).
  `CustomerContext` / `get_customer_request_context` (`api/dependencies.py`)
  hamon alohida, faqat customer-scoped endpointlar (kill switch, audit
  viewer) uchun ishlatiladi — bu ikkalasi konseptual jihatdan farqli
  (customer-scoped amal vs workspace-scoped amalda CustomerOwner huquqi).
  Bu tuzatishning o'zi ilgari faqat archive/manage-members yo'llarida real
  HTTP orqali tekshirilgan edi — R3 approval consumption (`authorize_
  consume_approval`) yo'lida hech qachon emas, garchi kod jihatdan bir xil
  `context.role` orqali ishlasa ham. "Isbotlamasdan taxmin qilma" tamoyiliga
  ko'ra `test_bare_customer_owner_can_approve_a_members_action_over_http`
  qo'shildi — WorkspaceMembership qatori yo'q customer_owner haqiqatda
  boshqa a'zoning R3 action'ini real HTTP orqali tasdiqlay olishini
  tasdiqladi.
- ~~Bildirishnomalar faqat workspace-scoped endpoint orqali ko'rinadi~~ —
  **qisman tuzatildi**: `/v1/customers/{id}/notifications` qo'shildi —
  bitta customer ostidagi BARCHA workspace'lardagi bildirishnomalarni
  bitta joydan ko'rsatadi (`list_notifications_for_user`ning o'zi allaqachon
  `workspace_id=None` bilan chaqirilganda shuni qaytarardi — yetishmagani
  faqat HTTP endpoint edi). Bu customer-scoped, "har doim faqat o'zimniki"
  bo'lgani uchun audit viewer'dan farqli — hech qanday rol cheklovisiz,
  customer a'zoligining o'zi yetarli. To'liq, chinakam CUSTOMER'LARARO
  (bir nechta customer bo'ylab) global inbox ataylab qurilmadi:
  `customer_memberships`ning o'zi RLS bilan `customer_id` bo'yicha
  qamalgan (0001), shuning uchun "foydalanuvchi qaysi customer'larga
  a'zo" degan savolning o'ziga customer_id'ni oldindan bilmasdan javob
  berib bo'lmaydi — bu xuddi `workspace_tenant_index`ning o'zi hal qilgan
  muammoning bir pog'ona yuqorisi. Buni hal qilish yangi, ataylab RLS'siz
  bootstrap jadval talab qiladi — bu haqiqiy arxitektura qarori, oddiy
  endpoint qo'shish emas, shuning uchun so'ralmagan holda amalga
  oshirilmadi (QOIDA 2: change request).
- ~~FR-NTF-004 (foydalanuvchi bildirishnoma turlarini sozlashi) qurilmagan~~
  — **tuzatildi**: 0009-migratsiya `notification_preferences` jadvalini
  qo'shdi (customer_id + recipient_id + notification_type + enabled,
  RLS bilan). `GET/PUT /v1/customers/{id}/notification-preferences[/{type}]`
  orqali har bir foydalanuvchi 4 turdan 3 tasini (PENDING_APPROVAL/
  FAILED_ACTION/COMPLETED_TASK) o'chira oladi. SECURITY_ALERT ataylab
  DB CHECK constraint bilan emas, application qatlamida (`notification_
  service.set_notification_preference` + `create_notification`ning o'zi)
  bloklanadi — "faqat shu bitta enum qiymati istisno" CHECK sifatida
  ifodalab bo'lmaydi. Qator yo'qligi = yoqilgan (yangi foydalanuvchi uchun
  hech qanday qator oldindan yaratilmaydi). Test bilan real end-to-end
  isbotlandi: FAILED_ACTION'ni o'chirib, keyin haqiqiy action'ni FAILED
  holatiga o'tkazib — bildirishnoma haqiqatda yaratilmasligi tasdiqlandi
  (sintetik chaqiruv emas, xuddi test_notifications.py'dagi kabi haqiqiy
  trigger orqali).
- Email/Telegram adapter (FR-NTF-001'ning ikkinchi yarmi) qurilmagan —
  tashqi provayder integratsiyasini talab qiladi.
- `risk_level` (Action propose qilishda) to'liq caller-supplied — `tool_name`
  qanday risk darajasiga loyiqligini aniqlaydigan server-side siyosat hali
  yo'q (9.1'ning "risk-based routing"i risk_level QIYMATIGA ishonadi, uni
  chiqarmaydi). Xavfsizlik ko'rib chiqishda topildi; bugungi kunda haqiqiy
  tashqi ta'sir yo'qligi sababli (connector hali qurilmagan) darhol xato
  emas, lekin **S7'da birinchi connector qurilishidan oldin** bu siyosat
  qatlami (tool_name → minimal risk_level xaritasi) albatta qo'shilishi
  kerak — aks holda har qanday member o'zi tanlagan tool'ni R0 deb
  e'lon qilib, approval/step-up'ni butunlay chetlab o'tishi mumkin bo'ladi.
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
- **Workspace archive/restore frontend'ga ataylab ulanmadi — UI orqali
  haqiqiy tuponga olib borardi.** `POST .../archive`/`POST .../restore`
  allaqachon qurilgan/testlangan (FR-WKS-006), lekin tekshirilganda aniq
  bo'ldi: `list_my_workspaces` (demak `GET /v1/me/workspaces`) ikki
  yo'lida ham (CustomerOwner va oddiy a'zo) arxivlangan workspace'larni
  SHARTSIZ chiqarib tashlaydi (`Workspace.archived_at.is_(None)`), va
  boshqa hech qanday endpoint arxivlangan workspace'larni ro'yxatlamaydi
  yoki ID bo'yicha bitta-bitta o'qishga imkon bermaydi. Demak: agar
  frontend'ga shunchaki "Arxivlash" tugmasi qo'shilsa, bosilgandan keyin
  o'sha workspace `/v1/me/workspaces`dan butunlay yo'qoladi va uni
  qaytarish uchun UI orqali HECH QANDAY yo'l qolmaydi — faqat workspace_id
  UUID'ni yodlab, to'g'ridan-to'g'ri API'ga (`curl`) murojaat qilish orqali.
  Bu "faqat frontend ulash" emas — backend'da "arxivlangan workspace'larni
  ko'rish" degan yangi ro'yxatlash imkoniyati (va uni qaysi sahifaga —
  customer darajasida, faqat CustomerOwner uchunmi — qo'yish haqidagi
  mahsulot qarori) kerak, bu esa shu sessiyadagi boshqa hamma narsadan
  farqli, haqiqiy arxitektura/mahsulot qarori (QOIDA 2), shuning uchun
  so'ralmagan holda amalga oshirilmadi.
