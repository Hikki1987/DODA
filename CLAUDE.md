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

**ADR-003ni yozish jarayonining o'zi yangi, jiddiy bo'shliqni ochib berdi:
outbox relay hech qachon haqiqiy jarayon sifatida ishga tushmagan edi.**
ADR-001/003 "alohida worker process" haqida yozar ekanman
(`infrastructure/outbox_relay.py`), tekshirib ko'rsam —
`relay_once()` funksiyasi faqat `test_outbox_relay.py`dan chaqirilardi,
hech qachon haqiqiy, uzluksiz ishlaydigan biror jarayondan emas.
`docker-compose.yml`da ham hech qanday "worker" servisi yo'q edi (faqat
infra: postgres/redis/minio). Ya'ni: ADR'lar "worker allaqachon mavjud"
deb yozilgan bo'lsa-da (va bu texnik jihatdan `outbox_relay.py` fayli
mavjudligi ma'nosida to'g'ri edi), uni haqiqatda uzluksiz ishga
tushiradigan HECH QANDAY yo'l yo'q edi — real deploy qilinganda hech
qanday outbox xabari hech qachon Redis'ga yetkazilmagan bo'lardi.

Tuzatish: `outbox_relay.py`ga `run_forever()` (poll siklidan, bo'sh
bo'lganda `poll_interval` kutadi, lekin `stop_event`ni darhol sezadigan
qilib — oddiy `asyncio.sleep` emas, `asyncio.wait_for(stop_event.wait(),
timeout=poll_interval)`) va `main()` (SIGTERM/SIGINT'ni ro'yxatdan
o'tkazib, graceful shutdown qiladi) qo'shildi. Endi `python -m
doda.infrastructure.outbox_relay` — README.md'ga ham `uvicorn`
qatoridan keyin shu qo'shildi. `docker-compose.yml`ga alohida servis
qo'shilmadi — backend'ning o'zi ham hech qachon konteynerlashtirilmagan
(Dockerfile yo'q, README doim `uvicorn ... --reload`ni to'g'ridan-to'g'ri
host'da ishga tushirishni ko'rsatgan), shuning uchun worker ham xuddi shu
naqshga mos — bu alohida arxitektura qarori (konteynerlashtirilgan
deploy) bo'lar edi, minimal-diff doirasidan tashqarida.

Haqiqiyligi real ishga tushirib tasdiqlandi (sintetik test emas): jarayon
`python -m doda.infrastructure.outbox_relay` orqali fon jarayoni sifatida
ishga tushirildi, `outbox_relay.starting` logi ko'rindi, haqiqiy `kill
-TERM` yuborildi, `outbox_relay.stopped` logi bilan toza chiqdi, hech
qanday osilib qolgan jarayon qolmadi. 3 ta yangi test
(`test_outbox_relay.py`ga): (1) `run_forever` haqiqiy xabarni
yetkazishi VA `stop_event` o'rnatilgach darhol to'xtashi, (2) bo'sh
bo'lganda ham `stop_event`ni bir poll_interval ichida sezishi (busy-loop
qilmasdan — regressiya bo'lsa, oddiy uzoq `asyncio.sleep` timeout'ga
uchraydi), (3) `main()`ning o'zi haqiqiy `os.kill(os.getpid(),
signal.SIGTERM)` bilan chaqirilib, toza to'xtashi — real signal, mock
emas. 172 test, barchasi real Postgres+Redis'da.

**Xuddi outbox worker'da bo'lgani kabi yana bitta "ko'rinishda bor, aslida
hech narsa qilmaydi" bo'shlig'i topildi va yopildi — bu safar
observability qatlamida (6.3-bo'lim stack qarori: "OpenTelemetry,
Prometheus, structured log").** `main.py`da `FastAPIInstrumentor.
instrument_app(app)` chaqirilardi va `TracerProvider` yaratilardi —
ko'rinishida tracing "ishlagandek" edi. Lekin `TracerProvider`ga hech
qanday span processor/exporter biriktirilmagan edi: FastAPI'ning har bir
so'rovi uchun span haqiqatda yaratilardi (trace_id propagation ishlardi),
lekin keyin hech qayerga eksport qilinmasdan **jimgina yo'qolib ketardi** —
konsolga ham, hech qanday collector'ga ham emas. Bundan tashqari,
Prometheus umuman ulanmagan edi: na `prometheus-client` dependency, na
`/metrics` endpoint mavjud emas edi — 6.3'dagi stack qarorining bu yarmi
soddagina qurilmagan edi.

Tuzatish: `_configure_tracing`ga `SimpleSpanProcessor(ConsoleSpanExporter())`
qo'shildi — real OTLP collector destinatsiyasi hali tanlanmagani uchun
(bu OD-005/hosting qaroriga bog'liq) konsolga chiqarish tanlandi, bu
tracing haqiqatda ishlashini isbotlaydi, lekin kelajakda real collector
tanlanganda almashtirilishi kerak. `BatchSpanProcessor` emas
`SimpleSpanProcessor` ishlatildi — birinchisi bilan qisqa umrli jarayon
(masalan test) tugaganda fon oqimi hali flush qilayotgan bo'lib qolib,
"I/O operation on closed file" xatosini chiqarardi (buni haqiqatda
ishga tushirib topdim, keyin `SimpleSpanProcessor`ga o'tkazib tuzatdim).
Prometheus uchun `prometheus-fastapi-instrumentator` qo'shildi —
`GET /metrics` (ataylab `/v1` prefiksisiz — Prometheus scraper'lari doim
qat'iy `/metrics` yo'lini kutadi, versiyalangan kontrakt emas) standart
HTTP metrikalarni (so'rovlar soni, davomiyligi, handler/method/status
bo'yicha) chiqaradi.

Ikkalasi ham real ishga tushirib tasdiqlandi: haqiqiy uvicorn server
ishga tushirilib, `/v1/healthz`ga so'rov yuborilib, (1) konsol logida
haqiqiy span (`"name": "GET /v1/healthz"`, to'g'ri trace_id/span_id bilan)
ko'rinishi va (2) `/metrics`da `http_requests_total{handler="/v1/healthz",
method="GET",status="2xx"} 1.0` haqiqatda oshgani tasdiqlandi. 2 ta yangi
test (`test_tracing.py` — global tracer provider'ga test-only
`InMemorySpanExporter` qo'shib, haqiqiy so'rovdan keyin tugallangan span
borligini tekshiradi; `test_metrics.py` — haqiqiy so'rovdan keyin
`/metrics`da mos counter ko'rinishini tekshiradi). 174 test.

**11.2'dagi "Xato konverti" da'vosi — "har xato uchun bitta shakl" — haqiqatda
faqat ro'yxatga olingan aniq exception turlariga tegishli edi.** `api/
errors.py`ning o'z docstring'i "Every exception handler here maps a domain/
application exception to this one shape so API clients never have to
special-case response bodies" deydi, lekin kutilmagan (ro'yxatga olinmagan)
har qanday xato — masalan haqiqiy bug — FastAPI/Starlette'ning o'z standart
500 javobiga (butunlay boshqa shakl, `trace_id`/`retryable`/`field_errors`
maydonlarisiz) tushib qolardi, VA hech qanday server-side log yozuvi bilan
bog'lanmagan edi (klient xato ko'radi, lekin uni trace_id orqali server
loglaridan topib bo'lmaydi).

Tuzatish: `@app.exception_handler(Exception)` — barcha aniq handler'lardan
KEYIN emas, Starlette MRO bo'yicha eng mos handler'ni tanlagani uchun
ularni "soyalab" qo'ymaydi (aniq turlar hamon o'z handler'iga tushadi,
faqat RO'YXATGA OLINMAGAN turlar shu catch-all'ga tushadi). `structlog.
exception(...)`ni trace_id bilan chaqiradi — endi haqiqiy bug production'da
sodir bo'lsa, kliyent javobidagi trace_id orqali server logidan topsa
bo'ladi.

Buni yozish jarayonida ikkinchi, ancha nozikroq xato aniqlandi: `Exception`
uchun ro'yxatga olingan handler Starlette tomonidan avtomatik ravishda
`ServerErrorMiddleware`ga (butun ilova middleware stack'ining ENG TASHQI
qatlami) biriktiriladi — bu `TraceIdMiddleware`ning HAM tashqarisida
joylashadi. Demak bu yangi catch-all handler ishlaganda,
`TraceIdMiddleware`ning javobga `X-Trace-Id` header qo'shadigan qismi
UMUMAN ishlamaydi (chunki `call_next()` normal javob qaytarish o'rniga
xatoni qayta ko'taradi — bu Starlette'ning ataylab shunday, real ASGI
serverga (uvicorn) traceback ko'rsatish uchun mo'ljallangan xulqi). Natija:
javobning JSON tanasida `trace_id` to'g'ri bo'lardi, lekin HTTP header'ida
umuman yo'q bo'lardi — `TraceIdMiddleware`ning o'z docstring va'dasini
("har bir javobda, hatto muvaffaqiyatsiz bo'lsa ham") aynan shu bitta holat
uchun buzardi. Buni birinchi test yozishda haqiqatda ushladim (`KeyError:
'X-Trace-Id'`) — taxmin qilib emas. Tuzatish: yangi handler `X-Trace-Id`
header'ini o'zi, to'g'ridan-to'g'ri qo'yadi (`TRACE_ID_HEADER` konstantasi
`api/middleware.py`dan import qilinib), `TraceIdMiddleware`ning normal
oqimiga tayanmasdan.

Testni yozishda ham bitta amaliy g'alati holat chiqdi: `httpx`ning
`ASGITransport`i standart holatda (`raise_app_exceptions=True`) ilova
qayta ko'targan xatoni test'ning o'ziga qayta ko'taradi, garchi
`ServerErrorMiddleware` javobni allaqachon jo'natgan bo'lsa ham (bu
Starlette'ning atayin xulqi — real uvicorn buni faqat ichki log sifatida
ko'radi, klientga hali ham to'g'ri 500 javob boradi). Test `raise_app_
exceptions=False` bilan tuzatildi — bu httpx'ning test-uchun cheklovi,
tuzatishning o'zidagi xato emas.

175 test, barchasi real Postgres+Redis'da.

**NFR-OBS-001'ning o'zagi — "100% action/approval trace korrelyatsiyasi" —
haqiqatda 0% edi, garchi kod buni ataylab qurgandek ko'rinsa ham.**
`api/middleware.py`ning `TraceIdMiddleware`si o'z docstring'ida aniq
yozadi: har bir so'rov trace_id'si "shu Action'ning trace_id'i sifatida
ham ishlatilishi mumkin bo'lishi uchun" ataylab UUID shaklida saqlanadi —
bu HTTP so'rovi va uning natijasida yaratilgan domain audit trail'ini
BITTA trace_id orqali bog'lash niyatini bildiradi. Lekin haqiqiy kodni
tekshirsam, `api/actions.py`dagi `propose_and_submit_action` bu
trace_id'dan umuman FOYDALANMAS EDI — `request`ni hatto qabul ham
qilmasdan, `propose_action`ga har safar butunlay yangi, bog'liqsiz
`uuid.uuid4()` uzatardi. Natija: javobning `X-Trace-Id` header'i va shu
so'rov yaratgan Action'ning (demak uning barcha `action.*.v1` audit
yozuvlarining) `trace_id`si — ikkita mutlaqo bog'liq bo'lmagan UUID edi.
Amalda bu degani: production'da biror muammoni "shu so'rov qaysi
Action'ni yaratdi" deb HTTP trace_id orqali qidirib topib bo'lmas edi —
aynan NFR-OBS-001'ning o'z maqsadi buzilardi.

Tuzatish: `propose_and_submit_action` endi `Request`ni qabul qiladi va
`propose_action`ga `uuid.UUID(request.state.trace_id)`ni uzatadi —
`TraceIdMiddleware` allaqachon minted (yoki client'ning `X-Trace-Id`
header'idan aks ettirgan) qiymatning o'zi. Yangi test
(`test_action_trace_id_matches_the_http_requests_own_trace_id`)
ikkalasini ham tekshiradi: client `X-Trace-Id` bersa, Action'ning
trace_id'i ANIQ o'sha qiymatga teng bo'lishi; hech qanday header
berilmasa, javobning o'z `X-Trace-Id`si bilan Action'ning trace_id'i bir
xil bo'lishi. Bu Chat/Knowledge (2-bosqich) qurilganda ham naqshni
to'g'ri o'rnatib qo'yadi — kelajakdagi har qanday yangi "action yarat"
yo'li shu naqshni takrorlashi kerak, yangisini o'ylab topmasdan.

176 test, barchasi real Postgres+Redis'da.

**FR-CTL-002ning "ma'lumot eksporti" qismi qurildi — bu talabning
oxirgi, hali qamrab olinmagan yarmi edi** (sessiya revoke — bor,
konnektor uzish — OD-002'ga bog'liq, memory o'chirish — 2-bosqich hali
yo'q, eksport — endi bor). Talab matni "Eksport asinxron, kuzatiladigan
va tekshiriladigan" deydi; bugungi ma'lumot hajmi (Knowledge/RAG fayllari
yo'q, chat transkriptlari yo'q — ikkalasi ham hali qurilmagan domenlar)
uchun to'liq asinxron job-queue infratuzilmasi spekulyativ bo'lar edi,
shuning uchun v1 ataylab **sinxron** qilib qurildi — "asinxron" qismi
ochiq bo'shliq sifatida pastdagi "Bilingan cheklovlar"ga yozildi, sukut
saqlanmadi.

`application/export_service.py`dagi `export_my_data` — chaqiruvchi
foydalanuvchining o'zi a'zo bo'lgan HAR BIR customer/workspace bo'ylab
o'ziga tegishli ma'lumotni (o'zi egalik qiladigan task'lar, o'ziga
yo'naltirilgan bildirishnomalar, o'zi actor bo'lgan audit yozuvlari)
bitta javobda yig'adi — hech qachon boshqa a'zoning ma'lumoti, hatto bir
xil workspace ichida bo'lsa ham. `GET /v1/me/export` (`api/me.py`)
`/v1/me/workspaces` bilan bir xil naqsh — session-scoped, `get_current_
identity` orqali.

Buni yozish jarayonida haqiqiy xato o'zining yangi kodida topildi va
tuzatildi (commit qilinmasdan oldin, testning o'zi ushladi): birinchi
versiya customer qamrovini (`customer_ids`) `list_my_workspaces`ning
natijasidan (`memberships`) chiqarardi. Lekin `list_my_workspaces`
**workspace-shaped** — `CustomerOwner` biror customer'da bironta
arxivlanmagan `Workspace`ga ega bo'lmasa, o'sha customer uchun HECH
QANDAY yozuv qaytarmaydi (`GET /v1/me/workspaces`ning o'zi ham shunday
ishlaydi — bu allaqachon bilingan xulq). Natijada: workspace'siz
customer'ning CustomerOwner'i eksport qilsa, o'sha customer ostidagi
bildirishnomalar, audit yozuvlar VA eksportning o'z audit yozuvi
(`user.data_exported.v1`) sukut saqlab tashlab ketilardi. Bu aynan shu
stsenariyni ataylab qamrab oluvchi `test_exporting_data_is_itself_
audited` (workspace'siz customer yaratadi) bilan ushlandi — haqiqiy
xato xabari: `AssertionError: assert 'user.data_exported.v1' in
['customer.created.v1']`. Tuzatish: customer qamrovini `memberships`dan
emas, `UserCustomerIndex`dan to'g'ridan-to'g'ri so'rab olish (`GET
/v1/me/workspaces` qurilishida ishlatilgan, RLS'siz bootstrap jadval) —
"foydalanuvchi qaysi customer'larga a'zo" degan savolning haqiqiy manbai
shu, `list_my_workspaces`ning natijasi emas. Tuzatishdan keyin ikkala
test ham (workspace bilan va workspace'siz customer stsenariylari)
o'tdi.

Eksportning o'zi ham audit qilinadi (`user.data_exported.v1`, har bir
qamrab olingan customer uchun bittadan) — "audit.viewed.v1" naqshining
takrori, bu ham NFR-OBS-001 trace-korrelyatsiya darsiga rioya qiladi:
`export_my_data` chaqiruvchi HTTP so'rovining o'z `trace_id`sidan
foydalanadi (`propose_and_submit_action`da qo'llanilgan xuddi shu naqsh),
yangi bog'liqsiz `uuid4()` emas.

178 test, barchasi real Postgres'da.

**FR-WKS-006ning "Bilingan cheklovlar"da uzoq vaqt qayd etilgan bo'shlig'i
yopildi — workspace archive/restore endi frontend'ga to'liq ulandi, real
tuponsiz.** Muammo aniq edi: `POST .../archive`/`POST .../restore`
allaqachon qurilgan/testlangan edi, lekin `list_my_workspaces` (demak
`GET /v1/me/workspaces`) arxivlangan workspace'larni SHARTSIZ chiqarib
tashlaydi va hech qanday boshqa endpoint ularni ID bo'yicha ro'yxatlamaydi
— agar frontend'ga shunchaki "Arxivlash" tugmasi qo'shilsa, bosilgandan
keyin workspace butunlay yo'qolib, uni qaytarishning UI orqali HECH QANDAY
yo'li qolmasdi (faqat workspace_id UUID'ni yodlab, `curl` orqali).

Yechim ikki qismli: (1) backend'da yangi `GET /v1/customers/{id}/
workspaces/archived` (`api/customer_admin.py`, `application/workspace_
service.py`dagi `list_archived_workspaces`) — yangi `authorize_view_
archived_workspaces` (CustomerOwner-only, 10.2'da bu aniq qatorga ega
bo'lmagani uchun kill switch/audit-viewer'ning xuddi shu
restriktivligiga ergashadi) bilan himoyalangan; restore'ning o'zi
o'zgarmadi (hamon workspace_admin-scoped, bitta workspace uchun). (2)
frontend: workspace sahifasiga "Workspace'ni arxivlash" tugmasi (aniq
`window.confirm` bilan — bu haqiqiy bir tomonlama UI harakat, chunki
qaytarish endi butunlay boshqa sahifada), customer sahifasiga
"Arxivlangan workspace'lar" bo'limi ("Tiklash" tugmasi bilan, faqat
ro'yxat bo'sh bo'lmaganda ko'rinadi).

Yangi 3 ta backend testi (`test_customer_admin_api.py`): CustomerOwner
faqat arxivlangan (faol emas) workspace'larni ko'rishi, plain member 403
olishi, va boshqa customer'ning arxivlangan workspace'lari sizib
chiqmasligi. Real backend+frontend'ga qarshi (production build) yangi,
mustaqil seed (`--prefix E2E_ARCHIVE_` — xuddi ikkita mavjud spec bir xil
seed'ni bo'lishmasligi kerak degan avvalgi dars, chunki bu spec
workspace'ni haqiqatda arxivlaydi, boshqa spec'larning davom etayotgan
holatini buzgan bo'lardi) bilan to'liq oqim (arxivlash → tasdiqlash →
redirect → workspace ro'yxatidan yo'qolishi → customer sahifasida
ko'rinishi → tiklash → yana workspace ro'yxatida ko'rinishi) Playwright
orqali tasdiqlandi, konsol xatosiz. Mavjud uchta E2E spec (workspace,
customer, accessibility) ham qayta ishga tushirilib, regressiya yo'qligi
tasdiqlandi (barcha 4 spec, jami).

181 test, barchasi real Postgres'da.

**Ikkinchi `security-review` o'tkazildi — bu safar ce8d67d'dagi birinchisidan
keyingi ~26 commit'ga qarshi (GET kashfiyot endpointlari, session/customer
sahifalari, FR-CTL-002 eksport, workspace archive-listing, tracing/metrics,
catch-all exception handler).** Jarayon bir xil: (1) haqiqiy zaifliklarni
topish subagent'i, (2) topilgan nomzod uchun alohida false-positive
filtrlash subagent'i, (3) faqat ishonch darajasi >=8 bo'lganlar rasmiy
hisobotga kiritiladi. Bitta nomzod topildi — ishonch darajasi 7 (chegaradan
past) — lekin filtrlash subagent'ining o'zi tasdiqlagan haqiqat sifat
jihatidan chindan ham real edi, shuning uchun rasmiy hisobot chegarasidan
qat'i nazar tuzatildi (skill'ning shovqin-filtri hisobot uchun, muhandislik
qarori uchun emas):

`workspace_service.list_my_workspaces` — `GET /v1/me/workspaces`ning o'zagi,
login'dan keyin klient chaqiradigan BIRINCHI so'rov — ikkala filialida ham
(CustomerOwner va oddiy a'zo) `customer_id` bo'yicha hech qanday aniq SQL
predikat yo'q edi, faqat `tenant_scoped_session`ning RLS GUC'iga tayanardi.
Bu 6.2-bo'limning o'z qoidasini ("Repository qatlamida `customer_id`'siz
so'rov mavjud emas" — NFR-ISO-002) buzardi — va bu kodlar bazasida RLS'ning
jimgina ishlamay qolishi (superuser bootstrap rol voqeasi, ADR-005) allaqachon
haqiqatda sodir bo'lgan, shuning uchun bu faraziy emas. Har bir boshqa yangi
ro'yxatlash funksiyasi (`list_archived_workspaces`, `list_workspace_members`,
h.k.) aniq `customer_id`/`workspace_id` predikatiga ega, faqat shu funksiya
istisno edi. Ikkala filialga ham aniq `customer_id == customer_id` predikati
qo'shildi (`list_archived_workspaces`dagi bilan bir xil naqsh).

**Halol eslatma**: bu tuzatish uchun RLS'ni haqiqatda chetlab o'tadigan
regressiya testi yozilmadi — chunki buni isbotlash uchun test suite'ning
o'zi `FORCE ROW LEVEL SECURITY`ni vaqtincha o'chirish uchun DDL huquqiga ega
bo'lishi kerak edi, test suite esa ataylab `doda_app` (NOSUPERUSER, DDL
huquqisiz) orqali ulanadi — bu ADR-005 tuzatishining o'zi talab qilgan,
to'g'ri xavfsizlik holati, "testlash bo'shlig'i" emas. Mavjud
`test_me_api.py` (5 test) tuzatishdan keyin ham o'zgarishsiz o'tdi —
ikkinchi qatlam qo'shilishi birinchi qatlam (RLS) to'g'ri ishlayotganda
xatti-harakatni o'zgartirmaydi, bu aynan kutilgan.

181 test, barchasi real Postgres'da (xatti-harakat o'zgarmadi, faqat
ikkinchi mudofaa qatlami qo'shildi).

**NFR-PERF-001 ("P95 API read <500ms, Load test, Prometheus histogram")
birinchi marta haqiqatda o'lchandi — bu talab CI'da tekshirilmaydi
(NFR-SEC-003ning SLA qismi kabi: umumiy CI runner'lardagi vaqt shovqini
qat'iy latency assertion'ini yo qat'iyatsiz-foydasiz, yoki shovqinli/
beqaror qiladi), lekin hech qachon hech kim tomonidan real o'lchanmagan
ham edi.** `backend/scripts/load_test_api.py` — `verify_audit_chain_job.py`
bilan bir xil turkumdagi mustaqil skript (real, ishga tushirilgan
backend'ga qarshi, real Postgres bilan, real `httpx` orqali; sintetik
emas) — bir nechta asosiy o'qish endpointini (`/v1/me/workspaces`,
workspace tasks/actions/notifications/audit) bir vaqtda 20 ta parallel
so'rov bilan (200 tadan) chaqiradi va P95'ni hisoblaydi.

Birinchi ishga tushirishda haqiqiy, takrorlanuvchi topilma chiqdi: audit
ko'rish endpointlari (`GET .../audit`, ikkalasi ham — workspace va
customer darajasida) izchil ravishda 500ms P95 chegarasidan oshadi
(bir necha marta qayta ishga tushirilganda ham: 483-548ms P95),
boshqa barcha endpoint esa (ba'zan sandbox muhitining o'zi tufayli
shovqinli, lekin izchil emas) odatda chegaradan pastda qoladi. Sabab
aniq: audit ko'rish "faqat o'qish" emas — FR-AUD-002'ning o'z talabi
bo'yicha har bir ko'rish o'zi ham `audit.viewed.v1` yozuvi hosil qiladi
(`record_audit_event` orqali), bu esa FR-AUD-004'ning concurrency-xavfsiz
hash-zanjiri uchun har bir customer'ning `audit_chain_tips` qatorini
`SELECT ... FOR UPDATE` bilan qulflaydi. Natijada: bitta customer'ning
audit'ini bir vaqtda ko'rayotgan HAR BIR so'rov shu bitta qulf uchun
navbatga turadi — "o'qish" endpointi aslida bitta customer bo'yicha
serializatsiya qiladigan yozuvga aylanadi.

Bu **tuzatilmadi** — sababi aniq: qulfni olib tashlash yoki yumshatish
aynan shu sessiyada avvalroq topilgan va tuzatilgan audit-zanjiri fork
xatosini (concurrent yozuvlar bitta prev_hash'ga to'qnashishi) qayta
tiklaydi. Bu "tezlik vs to'liq tekshiriladigan audit trail" o'rtasidagi
ataylab qilingan arxitektura almashinuvi, tasodifiy xato emas — chinakam
tuzatish (masalan, o'z-audit yozuvini so'rov yo'lidan ajratib, outbox
orqali asinxron qilish) transaction-ichida-atomik kafolatni yo'qotadi va
alohida, ehtiyotkorlik bilan o'ylab chiqilishi kerak bo'lgan arxitektura
qarori — shu sababli hozircha faqat aniq, o'lchangan bo'shliq sifatida
qayd etildi (pastga qarang), tasodifiy/o'ylanmagan tuzatish qilinmadi.

Bu jarayonda bitta yolg'on izni ham tekshirib chiqdim: dastlab
`/v1/me/workspaces`ning o'zi ham bir marta 495-630ms P95 bilan
"FAIL" ko'rsatdi, DB connection pool hajmini oshirish (`pool_size=20,
max_overflow=20`) sinovdan o'tkazildi — lekin qayta-qayta ishga
tushirishda bu o'zgarish natijani izchil yaxshilamadi (ba'zida yomonroq
ham chiqdi), bu esa muammoning pool hajmi emas, sandbox muhitining o'z
shovqini ekanini ko'rsatdi. Shuning uchun bu o'zgarish tasdiqlanmagan
gipoteza sifatida qaytarib tashlandi ("isbotlamasdan taxmin qilma"
tamoyiliga ko'ra) — faqat audit endpointining izchil, takrorlanuvchi
sekinligi haqiqiy topilma sifatida qoldirildi.

181 test, barchasi real Postgres'da (kod o'zgarmadi — faqat yangi
o'lchov skripti qo'shildi).

**NFR-SCL-001ning o'z tekshiruv usuli ("Ikki instansda test") outbox
relay worker'iga qarshi birinchi marta haqiqatda qo'llanildi — va
`outbox_relay.py`ning o'z docstring'idagi da'vo ("FOR UPDATE SKIP LOCKED
lets multiple relay workers run concurrently without double-processing a
row") hech qachon haqiqiy concurrent worker'lar bilan tekshirilmagan
edi.** `test_two_concurrent_relay_workers_never_double_publish_the_same_
message` — 10 ta kutilayotgan outbox xabari yaratib, ikkita `relay_once`
chaqiruvini `asyncio.gather` orqali HAQIQIY concurrent qilib ishga
tushiradi (ketma-ket emas — har bir chaqiruvning o'z DB round-trip'lari
ikkinchisiga haqiqiy interleave imkoniyati beradi) va har bir xabar
ikkalasi orasida ANIQ bir marta (ikki marta emas, nol marta emas)
yetkazilishini tekshiradi.

Testning o'zi ma'noli ekanini isbotlash uchun (audit-zanjiri uslubidagi
revert-test-restore) `with_for_update(skip_locked=True)`ni vaqtincha
olib tashladim — test darhol, aniq kutilgan tarzda muvaffaqiyatsiz
bo'ldi (`assert 20 == 10`, ya'ni har ikkala worker ham barcha 10 ta
xabarni mustaqil ravishda oldi va IKKI MARTA nashr qildi) — bu haqiqiy
double-publish xatosi, sintetik emas. Keyin himoya qaytarilib, test
qaytadan yashil ekani tasdiqlandi. Demak: worker'ning o'zi haqiqatda
gorizontal miqyoslanadigan (ikkita nusxasi bir vaqtda ishga tushirilsa
ham xavfsiz) ekani endi CI tomonidan doimiy tekshiriladi, faqat
docstring'dagi da'vo emas.

182 test, barchasi real Postgres+Redis'da.

**UC-007/12.4ning <=60s cheklash SLA'si — endi ikkala amalga oshirilgan
kill switch qamrovida ham (workspace VA customer) haqiqatda o'lchandi,
avval faqat workspace qamrovida edi.** 12.4-bo'limning o'zi ("Cheklash
(kill switch / feature flag) — <=60 soniya qaror qabul qilingandan
keyin") qamrovga bog'liq emas — Platform Owner darajasidagi global kill
switch (hali qurilmagan, dual-control talab qiladi, yuqoriga qarang)
uchun yozilgan bo'lsa-da, xuddi shu SLA workspace va customer darajasidagi
allaqachon qurilgan/ishlayotgan kill switch'larga ham tabiiy ravishda
tegishli. `test_customer_kill_switch_blocks_every_workspace_under_it`
funksional to'g'rilikni (ikkala workspace ham bloklanadi) isbotlagan, lekin
hech qachon vaqtni o'lchamagan edi — `test_workspace_kill_switch...`ning
o'z drill'idan farqli. Yangi `test_customer_kill_switch_drill_blocks_
within_sla` xuddi shu naqshni (engage'dan blokgacha real vaqtni
`time.monotonic()` bilan o'lchash) customer qamroviga ham qo'lladi.

183 test, barchasi real Postgres'da.

**Yana bir "backend qobiliyati bor, UI yo'q" bo'shlig'i topildi va
yopildi: workspace-darajasidagi kill switch'ni ENGAGE/DISENGAGE qilish
uchun frontend'da hech qanday tugma yo'q edi — faqat customer sahifasida
bor edi.** `POST /v1/workspaces/{id}/kill-switch/engage|disengage`
allaqachon qurilgan/testlangan edi (10.2: "Kill switch" qatorida
WorkspaceAdmin = Workspace scope), lekin workspace sahifasi faqat
`GET .../kill-switch`ni chaqirib, o'qish-uchun banner ko'rsatardi. Bu
degani: CustomerOwner BO'LMAGAN, faqat workspace_admin bo'lgan
foydalanuvchi (10.2 bo'yicha bunga to'liq huquqli) o'z workspace'ining
kill switch'ini UI orqali umuman yoqib/o'chira olmasdi — customer
sahifasidagi versiya CustomerOwner-only (`authorize_engage_customer_kill_
switch`) bo'lgani uchun ularga yordam bermaydi. Xuddi shu bo'shliq
turkumi (archive/restore, notification preferences, va h.k.) yana bir
joyda takrorlangan edi.

Tuzatish: `frontend/src/lib/api.ts`ga `engageWorkspaceKillSwitch`/
`disengageWorkspaceKillSwitch` qo'shildi, workspace sahifasidagi
o'qish-uchun banner customer sahifasidagi bilan bir xil to'liq
forma/tugma juftligiga almashtirildi (sabab kiritish + "Yoqish", faol
bo'lsa "O'chirish"). Yangi, mustaqil Playwright E2E spec
(`workspace-kill-switch.spec.ts`, `--prefix E2E_KILLSWITCH_` — xuddi
avvalgi darsning takrori: bu spec workspace'ning o'z kill switch'ini
yoqadi, boshqa spec'lar bilan bir xil seed'ni bo'lishsa ularning
action-taklif qilish oqimini buzardi) — engage'dan keyin backend'ning
o'zi (`POST .../actions` to'g'ridan-to'g'ri, sahifaning o'z fetch'i
orqali emas) haqiqatda 403/`KILL_SWITCH_ENGAGED` qaytarishini,
disengage'dan keyin esa qaytadan 200 qaytarishini tasdiqlaydi — faqat
banner ko'rinishini emas. Barcha 5 E2E spec (workspace, customer,
archive, kill-switch, accessibility) birga qayta ishga tushirilib,
regressiya yo'qligi (va yangi forma WCAG buzilishi keltirmasligi)
tasdiqlandi.

**Xuddi shu naqshning eng aniq nusxasi topildi: `GET /v1/me/export`
(FR-CTL-002 ma'lumot eksporti — shu sessiyada oldinroq qurilgan) frontend'da
UMUMAN hech qayerda chaqirilmasdi.** Backend'dagi barcha endpoint
yo'llarini (`api/*.py`) frontend'ning `src/lib/api.ts`da haqiqatda
chaqirilgan yo'llar bilan to'liq ro'yxat solishtirish orqali aniqlandi —
`/v1/me/export` yagona "yozilgan, testlangan, lekin frontend'da nol
ishlatilish" endpoint bo'lib chiqdi (boshqa nomzodlar — bitta action/task'ni
ID bo'yicha o'qish, approval consume — allaqachon ataylab boshqa sabablarga
ko'ra qoldirilgan edi, yuqoriga qarang).

Tuzatish: `frontend/src/lib/api.ts`ga `MyDataExportOut`/`getMyDataExport`
qo'shildi; `/sessions` sahifasiga (FR-CTL-002ning boshqa qismi — session
revoke — allaqachon shu yerda, session-scoped, workspace/customer context
kerak emas, xuddi backend endpointining o'zi kabi) "Ma'lumotlarimni eksport
qilish" bo'limi qo'shildi — bosilganda haqiqiy JSON faylni brauzer orqali
yuklab beradi (`Blob` + vaqtinchalik `<a download>`, real Next.js sahifasida
— bu Artifact sandbox emas, yuklab olish cheklovi qo'llanilmaydi).

`workspace.spec.ts`ga yangi qadam qo'shildi: shu testning o'zida oldinroq
yaratilgan "E2E test task" haqiqatda yuklab olingan JSON faylning
`tasks` massivida borligini tekshiradi (`page.waitForEvent("download")`
orqali haqiqiy brauzer yuklab olish hodisasini ushlab, faylni o'qib) — bu
faqat tugma bosilganini emas, `GET /v1/me/export`ning haqiqiy, to'liq
round-trip natijasini isbotlaydi. Barcha 5 E2E spec (accessibility
qamrovi bilan — yangi bo'lim WCAG buzilishi keltirmadi) qayta ishga
tushirilib, regressiya yo'qligi tasdiqlandi. Backend o'zgarmadi, 183 test
o'zgarishsiz.

**Haqiqiy xavfsizlik-yo'nalishdagi xato topildi va tuzatildi: "Chiqish"
tugmasi sessiyani serverda HECH QACHON revoke qilmagan — faqat
localStorage'ni tozalagan.** `workspaces/page.tsx`ning `logOut()`
funksiyasi `clearStoredSessionId()` chaqirib `/login`ga yo'naltirardi,
lekin `DELETE /v1/sessions/{id}`ni hech qachon chaqirmasdi. Amaliy
oqibat: "Chiqish" bosilgandan keyin ham, xom session UUID
(`Authorization: Bearer <id>`) hali ham to'g'ridan-to'g'ri API
so'rovlarida ishlar edi — sessiya faqat o'zining tabiiy idle/absolute
timeout'iga yetguncha. Bu ayniqsa `/sessions` sahifasidagi mavjud
izohni noto'g'ri qilardi: "joriy sessiyani shu tugma bilan yopib
bo'lmaydi... buning uchun mavjud 'Chiqish' bor" — bu izoh "Chiqish"
haqiqatda revoke qilishini FARAZ qilgan edi, lekin tekshirilganda bu
faraz noto'g'ri chiqdi.

Backend'ning o'zi bunga tayyor edi — `DELETE /v1/sessions/{id}`
o'zining JORIY sessiyasini revoke qilishga hech qanday cheklov
qo'ymaydi (`get_current_identity` avtorizatsiyani so'rov boshida
tasdiqlaydi, keyin o'sha sessiyani revoke qiladi — joriy so'rovning
o'zi muvaffaqiyatli tugaydi, faqat KEYINGI so'rovlar rad etiladi) va
bu aniq stsenariy allaqachon `test_revoking_a_session_makes_it_
unusable`da testlangan edi (auth header'i VA maqsad sessiyasi bir xil).
Demak bu sof frontend bo'shlig'i edi.

Tuzatish: `logOut()` endi `revokeSession(sessionId, sessionId)`ni
chaqiradi (xatoni jimgina yutib — tarmoq xatosi foydalanuvchini
"chiqish"dan butunlay to'sib qo'ymasligi kerak), keyin localStorage'ni
tozalaydi. Yangi, mustaqil E2E spec (`logout.spec.ts`, `--prefix
E2E_LOGOUT_`) audit-zanjiri uslubida isbotlandi: avval tuzatishni
vaqtincha `git stash` bilan olib tashlab, qayta build qilib, test
haqiqatda kutilganidek muvaffaqiyatsiz bo'lishi ko'rsatildi (`Expected:
401, Received: 200` — "Chiqish"dan keyin ham sessiya hali ishlardi),
keyin tuzatish qaytarilib, qayta build qilinib, test yashil ekani
tasdiqlandi. Test o'zi UI orqali emas — to'g'ridan-to'g'ri backend'ga
(`page.request.get`, sahifaning o'z fetch'idan tashqarida) sessiya
haqiqatda 401/`UNAUTHENTICATED` qaytarishini tekshiradi. Barcha 6 E2E
spec birga qayta ishga tushirilib, regressiya yo'qligi tasdiqlandi.
Backend o'zgarmadi, 183 test o'zgarishsiz.

**Ikki real concurrency (race condition) xatosi topildi va tuzatildi — ikkalasi
ham haqiqiy Postgres'ga qarshi, ataylab majburlangan interleaving bilan
isbotlandi, sintetik emas.** Bu safar frontend emas, backend'ning o'z state
machine'lari: `task_service.change_task_status` va
`action_service.apply_transition` ikkalasi ham chaqiruvchi oldindan yuklab
bergan obyektning xotiradagi (potentsial eski) holatiga ishonardi — birorta
ham `SELECT ... FOR UPDATE` bilan qayta tekshirmasdan. `audit_service`ning
o'z `audit_chain_tips` qulfi (FR-AUD-004, ancha oldin tuzatilgan) bu
naqshning yagona nusxasi emas ekan — xuddi shu TOCTOU (time-of-check to
time-of-use) bo'shlig'i ikkita boshqa, ancha muhim joyda ham bor edi.

Buni qo'lda (haqiqiy ikkita mustaqil DB ulanishi/tranzaksiyasi bilan,
`asyncio.gather` orqali) reproduktsiya qilishda muhim amaliy haqiqat
aniqlandi: ikkita coroutine'ni shunchaki `asyncio.gather`ga berish odatda
haqiqiy race hosil qilmaydi — har bir so'rov juda tez (lokal DB round-trip)
bo'lgani uchun Python event loop ularni amalda ketma-ket bajarib qo'yadi.
Haqiqiy racening oldini olish uchun ikkita sessiya ham MAQSAD qatorini
(task/approval) O'QIB OLGANDAN keyin, lekin hali birontasi COMMIT
qilmagandan oldin, ikkalasini BIR VAQTDA davom ettirish kerak bo'ldi — bu
ikkita haqiqiy HTTP so'rovi bir-biridan bir necha millisekund farq bilan
kelganda sodir bo'ladigan aniq stsenariy.

1. **`change_task_status` — ikkita bir vaqtdagi so'rov bir xil task'ni
   oldinga surib, ikkalasi ham muvaffaqiyatli bo'lib, BITTA haqiqiy
   o'tishga IKKITA TaskHistory qatori yozardi.** Ikkalasi ham task'ni
   TODO holatida yuklab oladi, ikkalasi ham TODO→IN_PROGRESS'ni ruxsat
   etilgan deb topadi (o'z xotiradagi eski holatiga ko'ra), ikkalasi ham
   yozadi — yakuniy status to'g'ri (IN_PROGRESS) bo'lsa ham, tarix ikki
   marta "TODO → IN_PROGRESS" deb yolg'on guvohlik beradi.
2. **`apply_transition` (demak `consume_approval`) — bundan ancha jiddiyroq:
   BITTA bir martalik approval nonce'ini ikkita bir vaqtdagi
   `POST .../approvals/{id}/consume` so'rovi IKKALASI HAM muvaffaqiyatli
   iste'mol qila olardi.** Ikkalasi ham approval'ni PENDING holatida
   yuklaydi, 9.2'ning barcha tekshiruvlaridan (nonce mos, muddati
   o'tmagan, payload o'zgarmagan) ikkalasi ham o'tadi, ikkalasi ham
   action'ni READY'ga o'tkazadi VA har biri o'ZINING outbox xabarini
   navbatga qo'yadi. Bu 9.2'ning o'z "bir martalik nonce" invariantini
   to'g'ridan-to'g'ri buzadi — S7'da birinchi connector qurilgandan keyin
   bu haqiqiy tashqi ta'sirning (masalan email yuborish) IKKI MARTA
   bajarilishiga olib kelardi, aynan FR-ACT-004 idempotentlik butun
   mexanizmi oldini olishi kerak bo'lgan narsa.

Tuzatish ikkalasida ham `audit_chain_tips`ning aynan o'zi ishlatgan
naqsh: funksiya boshida `SELECT ... FOR UPDATE` bilan qatorni qulflab,
keyin shu qulflangan, yangilangan holatga qarab tekshirish. Bitta muhim,
amalda tajriba orqali aniqlangan SQLAlchemy nozikligi bor edi: chaqiruvchi
obyektni (`task`/`action`) session identity map'ida ALLAQACHON ushlab
turgani uchun, yalang'och `select(...).with_for_update()` xotiradagi
atributlarni YANGILAMAYDI (Postgres darajasida to'g'ri qulflaydi, lekin
Python obyekti eski qiymatni ko'rsatishda davom etadi) —
`.execution_options(populate_existing=True)` ANIQ qo'shilmasa, qulf
"ishlaydi", lekin tekshiruv hamon eski holatga asoslanib qoladi va
tuzatish sukutan ishlamaydi. Buni alohida, kichik tajriba bilan (boshqa
ulanish qatordagi qiymatni o'zgartirib commit qiladi, keyin joriy
sessiya `FOR UPDATE` bilan qayta o'qiydi) isbotlab, keyin
`populate_existing=True` bilan tuzatilganini ko'rsatib tasdiqladim.

`apply_transition`ning o'zidagi tuzatish ayniqsa qiziq: u faqat `Action`
qatorini qulflaydi, `Approval` qatorini emas — chunki `apply_transition`
HAR BIR o'tish yo'lining (validate_action, consume_approval) yagona
umumiy markazi (xuddi CustomerOwner-rezolyutsiya tuzatishidagi "bitta
markazlashtirilgan joy" naqshi). Tekshirish shuni ko'rsatdi: ikkinchi
(bloklangan, keyin ochilgan) `consume_approval` chaqiruvi `approval.status
PENDING` tekshiruvini hamon eski holat bilan o'tib ketadi — lekin
`apply_transition`ning o'z qulf+yangilash qadami endi action'ni
ALLAQACHON READY deb ko'radi va READY→READY o'tishini rad etadi,
bu esa butun tranzaksiyani (shu ichidagi `approval.status = APPROVED`
yozuvi bilan birga) rollback qiladi. Demak faqat Action'ni qulflash
Approval racening o'zini ham yopadi — alohida Approval-qulfi shart emas.

Ikkalasi ham audit-zanjiri uslubida isbotlandi: avval real, majburlangan
interleaving bilan repro skript yozib xato borligini (2 ta TaskHistory
qatori; 2 ta outbox xabari) ko'rsatdim, keyin tuzatishni qo'shib xuddi shu
skriptlar endi to'g'ri natija berishini tasdiqladim, keyin ikkala holat
uchun ham doimiy regressiya testi yozdim
(`test_task_status_concurrency.py`, `test_approval_consume_concurrency.py`
— ikkalasi ham `test_audit_chain_concurrency.py`ning "ikkita mustaqil
sessiya, majburlangan interleaving" naqshini takrorlaydi), keyin
tuzatishni vaqtincha `git stash` bilan olib tashlab ikkala yangi test
ham aynan kutilgan tarzda muvaffaqiyatsiz bo'lishini (`['ok', 'ok']` !=
`['ok', 'rejected']`) ko'rsatdim, so'ng tuzatishni qaytarib ikkalasi ham
yashil ekanini tasdiqladim. 185 test, barchasi real Postgres'da.

**Yuqoridagi ikkita concurrency tuzatishidan keyin xuddi shu TOCTOU
naqshini butun kod bazasi bo'ylab qidirishda uchinchi, kichikroq nusxasi
topildi va tuzatildi: kill switch'ni ENGAGE qilish.** `engage_workspace_
kill_switch`/`engage_customer_kill_switch` ikkalasi ham avval
`session.get(...)`ni `None` deb topib, keyin yangi qator qo'shardi —
PK'ga tayangan himoyasiz insert. Bu holatda haqiqiy "duplicate row"
xavfi yo'q (workspace_id/customer_id PRIMARY KEY, Postgres o'zi
to'qnashuvni bloklaydi), lekin ikkita admin bir vaqtda (aynan haqiqiy
incident paytida, ikkalasi ham "yoqish" tugmasini bosganda) engage qilsa,
ikkinchisi xom, ushlanmagan `IntegrityError` (500) olardi — bu esa aynan
eng yomon daqiqada tushunarsiz xato ko'rsatardi.

Bu ikkinchisidan farqli: "bir martalik nonce"ga o'xshash xavfsizlik
invarianti emas — ikkala chaqiruvchi ham bitta xohlagan natijaga
(switch engaged) erishadi, shuning uchun tuzatish `invite_customer_
member`ning "bu haqiqiy biznes xatosi" yondashuvidan farqli,
`propose_action`ning idempotent-replay semantikasiga o'xshaydi: insert'ni
`session.begin_nested()` ichiga olib, `IntegrityError`ni tutib, allaqachon
g'alaba qozongan qatorni jimgina qaytaradi — xato emas, chunki chaqiruvchi
xohlagan holat (engaged) allaqachon rost.

Xuddi avvalgi ikkita tuzatish kabi: avval real, majburlangan interleaving
bilan repro yozib xom `IntegrityError`ni ko'rsatdim, tuzatishni qo'shib
ikkalasi ham (`engaged_by` ustida kelishgan holda) muvaffaqiyatli
bo'lishini tasdiqladim, keyin `test_kill_switch_engage_concurrency.py`
(ikkalasi uchun ham — workspace va customer) yozdim, `git stash` bilan
vaqtincha olib tashlab ikkala test ham aynan kutilgan `IntegrityError`
bilan muvaffaqiyatsiz bo'lishini ko'rsatdim, keyin tuzatishni qaytarib
ikkalasi ham yashil ekanini tasdiqladim. 187 test, barchasi real
Postgres'da.

**Xuddi shu TOCTOU naqshini qidirishda to'rtinchi, bu safargisi eng
jiddiy nusxasi topildi va tuzatildi: FR-WKS-005ning "oxirgi Owner'ni
chiqarib/pasaytirib bo'lmaydi" invarianti concurrency ostida haqiqatda
buzilishi mumkin edi — natijada customer NOLTA owner bilan qolishi
mumkin edi, hech qanday API orqali tiklash yo'li yo'q holda.**
`customer_service._count_customer_owners` — `change_customer_member_role`
va `remove_customer_member`ning ikkalasi ham shu bitta funksiyaga tayanadi
— hech qanday qulflashsiz oddiy `SELECT` edi. Aynan ikkita owner (A va B)
bor customer'da A B'ni chiqarsa VA B (bir vaqtda) A'ni chiqarsa: ikkalasi
ham hali "2 owner bor" deb hisoblab tekshiruvdan o'tadi, ikkalasi ham
bajariladi — natija: 0 owner. Bu nazariy emas, qo'lda (haqiqiy ikkita
mustaqil sessiya, majburlangan interleaving) reproduktsiya qilinganda
aynan shu holat ko'rsatildi: `remaining owners: 0`.

Bu avvalgi uchtasidan (task history, approval nonce, kill switch)
farqli — bu yerda qulflanadigan BITTA tabiiy qator yo'q, chunki tekshiruv
bir nechta qatorni (customer'ning barcha owner'lari) sanaydi. Yechim:
`_count_customer_owners`ning o'z SELECT'iga `.with_for_update()`
qo'shish — bu customer'ning BARCHA owner-rol CustomerMembership
qatorlarini qulflaydi, shuning uchun ikkinchi (bloklangan, keyin
ochilgan) chaqiruv g'olib tranzaksiya o'chirgan qatorni endi ko'rmaydi va
to'g'ri "faqat 1 owner qoldi" deb sanaydi — `change_customer_member_role`
ham, `remove_customer_member` ham bitta markazlashtirilgan tuzatishdan
avtomatik foyda ko'radi, chunki ikkalasi ham shu yordamchi funksiyaga
murojaat qiladi.

Audit-zanjiri uslubida isbotlandi: avval real, majburlangan interleaving
bilan repro yozib 0 owner qolishini ko'rsatdim, tuzatishni qo'shib endi
bittasi muvaffaqiyatli, ikkinchisi `CustomerMembershipError` bilan rad
etilishini (1 owner qolib) tasdiqladim, keyin
`test_last_owner_invariant_concurrency.py` yozdim, `git stash` bilan
vaqtincha olib tashlab test aynan kutilgan tarzda (`['ok', 'ok']` emas,
`['ok', 'rejected']` kutilgan edi) muvaffaqiyatsiz bo'lishini ko'rsatdim,
keyin tuzatishni qaytarib yashil ekanini tasdiqladim. 188 test, barchasi
real Postgres'da.

**Beshinchi nusxasi — bu safar duplicate-row xavfisiz, faqat xom
`IntegrityError`ning o'zi: `set_notification_preference` (FR-NTF-004).**
`notification_preferences` jadvalida allaqachon `uq_notification_
preferences_scope` (0009-migratsiya) unique constraint mavjud edi — demak
duplicate qator xavfi yo'q, audit-zanjiri/membership holatlaridan farqli.
Lekin `set_notification_preference`ning o'zi hamon avval `session.
scalar(select(...))` bilan `None`ni tekshirib, keyin insert qilardi —
`begin_nested`/`IntegrityError` tutish yo'q edi. Ikkita bir vaqtdagi so'rov
(bitta foydalanuvchi ikkita qurilmadan bir xil turni o'zgartirsa, yoki
oddiy ikki marta bosish) bir xil (customer, recipient, type) uchun
sozlama o'rnatsa — ikkalasi ham `preference=None` ko'radi, ikkalasi ham
insert qilishga urinadi, ikkinchisi xom `IntegrityError` (500) oladi.

Bu kill switch racedan farqli bir nuance bor: u yerda ikkala chaqiruvchi
ham BIR XIL xohlagan natijaga (engaged) erishadi, shuning uchun
"g'olibni qaytarish" to'g'ri edi. Bu yerda bu "X qiymatini o'rnatish"
amali — ikkala chaqiruvchi turli qiymat xohlashi mumkin (masalan bitta
qurilma o'chirmoqchi, ikkinchisi yoqmoqchi), shuning uchun tuzatish
boshqacha: `IntegrityError`ni tutib, endi mavjud (boshqa tranzaksiya
yozgan) qatorni qayta o'qib, SHU chaqiruvchining o'z `enabled` qiymatini
unga qo'llab flush qiladi — "oxirgi yozuvchi g'olib" semantikasi, kill
switch'ning "birinchi g'olib qoladi" semantikasidan farqli, lekin bu
aynan "sozlamani o'rnatish" amali uchun to'g'ri va kutilgan xulq.

Audit-zanjiri uslubida isbotlandi: avval real, majburlangan interleaving
bilan repro yozib xom `IntegrityError`ni ko'rsatdim (duplicate qator
yo'q ekanini ham tasdiqladim — constraint allaqachon ishlayotgan edi),
tuzatishni qo'shib ikkalasi ham (har biri o'z qiymatini qaytarib)
muvaffaqiyatli bo'lishini tasdiqladim, keyin
`test_notification_preference_concurrency.py` yozdim, `git stash` bilan
vaqtincha olib tashlab test aynan kutilgan `IntegrityError` bilan
muvaffaqiyatsiz bo'lishini ko'rsatdim, keyin tuzatishni qaytarib yashil
ekanini tasdiqladim. 189 test, barchasi real Postgres'da.

**Beshta TOCTOU tuzatishidan keyin `backend/src/doda/application/`dagi
HAR BIR faylni (13 tasi) tizimli ravishda ko'rib chiqib, shu naqshning
yana bir nusxasi qolmaganini tasdiqladim — bu qidiruv endi to'liq.**
Natija: `action_service.py`, `audit_service.py` (eng birinchi, eng eski
tuzatish — naqshning o'zi shu yerdan boshlangan), `customer_service.py`,
`kill_switch_service.py`, `notification_service.py`, `task_service.py` —
oltisi ham tuzatilgan yoki allaqachon to'g'ri qulflangan edi.
`workspace_service.add_workspace_member` ham avvalgi sessiyada xuddi shu
`begin_nested`/`IntegrityError` naqshi bilan tuzatilgan edi (unique
constraint, 0012-migratsiya). Qolganlari tekshirilib, haqiqiy bo'shliq
yo'qligi tasdiqlandi: `session_service.revoke_session` ataylab idempotent
(`record.revoked_at is None` tekshiruvi — ikki marta revoke qilish xato
emas, shunchaki no-op, chunki chaqiruvchining maqsadi — "bu sessiya
ishlamasin" — allaqachon rost); `workspace_service.archive_workspace`/
`restore_workspace` oddiy boolean flip, sanash invarianti yo'q;
`change_workspace_member_role`/`remove_workspace_member`da "oxirgi
workspace_admin" invarianti ATAYLAB yo'q (yuqoridagi "Eslatma (bug
emas, kuzatuv)"ga qarang); `outbox_service.enqueue_outbox_message` har
safar mustaqil yangi qator qo'shadi, unique constraint talab qilinmaydi;
`authz_service.py`, `audit_query_service.py`, `export_service.py` hech
qanday yozuv amalini bajarmaydi (faqat o'qish/qaror).

**Uchinchi `security-review` o'tkazildi — bu safar ikkinchisidan keyingi
~10 commit'ga qarshi (beshta concurrency tuzatishi, archive-listing
frontend, observability, FR-CTL-002 eksport, "Chiqish" tuzatishi).**
Jarayon bir xil uch bosqich: (1) topish subagent'i, (2) har bir nomzod
uchun alohida false-positive filtrlash subagent'i, (3) faqat ishonch
darajasi >=8 (10 balldan) qoldiriladi. Bu safar avvalgi ikkitadan farqli
— bitta nomzod topildi va u filtrlashdan **o'tmadi** (ishonch darajasi 3):

`action_service.propose_action`ning idempotency-key replay qidiruvi
(`IntegrityError` tutilgandan keyin) `(customer_id, workspace_id,
idempotency_key)` bo'yicha moslashtiradi, `actor_id` bo'yicha emas —
demak nazariy jihatdan bir xil workspace'dagi boshqa a'zo Alice'ning
aniq `Idempotency-Key`sini bilsa/taxmin qilsa, Bob uning action
payload'ini va (agar AWAITING_APPROVAL bo'lsa) pending approval'ning bir
martalik nonce'ini qaytarib olishi mumkin edi. Filtrlash subagent'i
kodni chuqur tekshirib, bu HAQIQIY zaiflik emasligini ko'rsatdi:
(1) payload allaqachon `GET /v1/workspaces/{id}/actions`/`{id}` orqali
HAR BIR workspace a'zosiga ochiq (workspace a'zoligi yetarli, actor
tekshiruvi yo'q — bu ataylab shunday, yuqoriga qarang), shuning uchun
"payload sizib chiqishi" yangi narsa emas; (2) `Idempotency-Key`ning
yagona real generatsiya konvensiyasi `uuid.uuid4()` (frontend'da bu
endpoint uchun chaqiruvchi umuman yo'q) — Bob Alice'ning aniq kalitini
"taxmin qilishi" amalda real emas; (3) nonce'ni bilish ham hech qanday
yangi huquq bermaydi — `authorize_consume_approval` rol/self-check'ni
(WORKSPACE_ADMIN yoki action'ning o'z actor'i) nonce tekshiruvidan OLDIN
va undan MUSTAQIL bajaradi, shuning uchun oddiy a'zo nonce'ni bilsa ham
hech narsa qila olmaydi, WORKSPACE_ADMIN esa bu huquqqa roli orqali
allaqachon ega (supervisor override, ataylab shunday loyihalangan).
Demak bu "amaliy bajariladigan zaiflik" emas, balki kelajakdagi
mustahkamlash imkoniyati (replay qidiruvini `actor_id` bilan ham
cheklash) — rasmiy hisobotda "False positive" deb belgilandi.

189 test, barchasi real Postgres'da (kod o'zgarmadi — sof tekshiruv).

**Beshta concurrency tuzatishining o'zi NFR-PERF-001'ni buzmaganini
haqiqatda o'lchab tasdiqladim — taxmin qilib emas.** `load_test_api.py`
faqat o'qish endpointlarini (`/v1/me/workspaces`, audit, va h.k.)
o'lchagan edi; yangi `SELECT ... FOR UPDATE`/`begin_nested` qo'shilgan
to'rtta yozish yo'li (`change_task_status`, `engage_workspace_kill_switch`,
`set_notification_preference`, `remove_customer_member`ning owner-count
tekshiruvi) hech qachon o'lchanmagan edi — "qulf arzon, sezilarli emas"
degan taxmin shu paytgacha tasdiqlanmagan edi.

Ishlab chiqilmagan holatda (N=100, majburlangan interleaving yo'q,
oddiy ketma-ket chaqiriqlar — haqiqiy bitta foydalanuvchining holatini
aks ettiradi) to'rttasi ham 500ms NFR-PERF-001 chegarasidan ancha past:
`change_task_status` P95=2.34ms, `set_notification_preference`
P95=2.24ms, `remove_customer_member` (owner-count yo'li) P95=7.54ms,
`engage_workspace_kill_switch` P95=5.56ms — barchasida max ham 50ms'dan
past, 0 ta "spike" (>50ms). Bitta dastlabki o'lchovda `engage_workspace_
kill_switch`ning max qiymati 1.1 soniyagacha chiqdi — bu raqamni
e'tiborsiz qoldirmasdan tekshirdim: engage/disengage'ni alohida va
birga (interleaved, N=100) qayta o'lchab, bu spike takrorlanmasligini
(keyingi ikkita to'liq ishga tushirishda 0 ta spike) ko'rsatdim — demak
bu kod yo'lining o'zi emas, balki sandbox muhitining bir martalik
shovqini edi (xuddi NFR-PERF-001'ning ilgarigi `/v1/me/workspaces`
tekshiruvidagi kabi — "isbotlamasdan taxmin qilma" tamoyiliga ko'ra shu
izni oxirigacha tekshirib, keyin rad etdim, darhol yo'q deb hisoblamadim).

Kod o'zgarmadi — bu sof o'lchov, mavjud himoyalarning haqiqatda arzon
ekanini tasdiqlaydi.

Keyingi qadam — S3'ning qolgan qismi: haqiqiy OIDC oqimi
(FR-AUTH-001, hozir `session_service.create_session` faqat dev/test
seam) — bu tashqi OIDC provayder ma'lumotlarini (client_id/secret,
issuer URL) talab qiladi, Product Owner'dan kelishi kerak. Yoki OD-002
(connector tanlovi) S6'dan oldin hal qilinishi kerak.

*(Bu paragraf yozilgan vaqtda ikkalasi ham ochiq edi — xronologik
yozuv, o'zgartirilmaydi. OD-002 keyinroq shu faylning davomida
haqiqatda hal qilindi VA qurildi — Telegram, pastga qarang; OIDC
hamon ochiq, yagona qolgan blokator.)*

**Bilingan cheklovlar (keyingi ishlarda hisobga olinsin):**
- ~~Audit hash-zanjiri concurrent yozuvlarda xavfsiz emas~~ — **tuzatildi**:
  `audit_chain_tips` (0005-migratsiya) har customer uchun `SELECT ... FOR
  UPDATE` bilan lock qilinadigan tip qatori qo'shdi. Eski (buzuq) versiyaga
  qaytarib, `test_audit_chain_concurrency.py` 3 martalik urinishda ham
  aynan shu xatoni (11/12 yozuv bitta prev_hash'ga fork bo'lishi) ushlashi
  tasdiqlandi — keyin tuzatilgan versiya bilan qayta tekshirildi.
- ~~Outbox relay hozircha connector'siz — faqat Redis Stream'ga yetkazishni
  isbotlaydi~~ — **birinchi connector qurildi (Telegram, OD-002)**: pastdagi,
  session oxiridagi yozuvga qarang. Boshqa har qanday `tool_name`
  (Telegram'dan tashqari) hamon hech qanday connector tomonidan iste'mol
  qilinmaydi — bu bo'shliq faqat bitta tool uchun yopildi, umuman emas.
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
- `GET /v1/me/export` (FR-CTL-002) hozircha faqat **sinxron** — talabning
  "asinxron, kuzatiladigan" qismi ataylab v1'da qamrab olinmagan (yuqoriga
  qarang). Ma'lumot hajmi kattalashsa (Knowledge/RAG fayllari, chat
  transkriptlari qo'shilgandan keyin) real job-queue infratuzilmasi kerak
  bo'ladi — bugungi kunda buni qurish spekulyativ bo'lar edi.
- **NFR-PERF-001 audit ko'rish endpointlarida buzilgan** (`GET .../audit`,
  workspace va customer darajasida) — real yuklama testida (yuqoriga
  qarang, `backend/scripts/load_test_api.py`) izchil ravishda P95 500ms
  chegarasidan oshadi, chunki har bir ko'rish o'zi ham audit yozuvi
  hosil qiladi va bu customer bo'yicha bitta hash-zanjiri qulfini
  (`audit_chain_tips`) egallaydi — bir vaqtda ko'proq odam audit'ni
  ko'rsa, ular shu bitta qulf uchun navbatga turadi. Ataylab tuzatilmadi:
  qulfni yumshatish audit-zanjiri fork xatosini (yuqorida tuzatilgan)
  qayta ochadi; haqiqiy tuzatish (masalan, o'z-audit yozuvini so'rov
  yo'lidan asinxron ajratish) alohida arxitektura qarori talab qiladi.
- ~~`risk_level` (Action propose qilishda) to'liq caller-supplied~~ —
  **qisman tuzatildi**: `domain/action/tool_policy.py`'ning
  `TOOL_MINIMUM_RISK_LEVEL` ro'yxati va `propose_action`'ning
  `enforce_minimum_risk_level` chaqiruvi (yuqoriga qarang, OD-002 yozuvi)
  hozircha faqat ro'yxatga OLINGAN tool'lar (bugungi kunda: bitta —
  `telegram.send_message`, R3) uchun caller-supplied qiymatni minimal
  darajaga ko'taradi. Ro'yxatga kiritilMAGAN har qanday `tool_name` hamon
  to'liq caller-supplied — bu ataylab shunday (ro'yxat faqat real,
  qaror qilingan tool'lar uchun to'ldiriladi, spekulyativ keng ro'yxat
  emas), lekin degani: kelajakda qo'shiladigan har bir yangi real tool
  ham xuddi shu ro'yxatga qo'shilishi SHART, aks holda shu tool uchun
  bo'shliq ochiq qoladi.
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
- ~~Workspace archive/restore frontend'ga ataylab ulanmadi — UI orqali
  haqiqiy tuponga olib borardi~~ — **tuzatildi**: `GET /v1/customers/{id}/
  workspaces/archived` (CustomerOwner-only) qo'shildi, frontend'da
  workspace sahifasiga "Arxivlash", customer sahifasiga "Tiklash"
  ulandi (yuqoriga qarang). Mahsulot qarori (qaysi sahifa, kim ko'ra
  oladi) shu safar so'ralmasdan emas — bu safar aniq: 10.2'da bunga
  o'xshash boshqa har bir customer-keng, hech qanday roldagi qatorga ega
  bo'lmagan ko'rish (kill switch, audit) allaqachon CustomerOwner-only
  precedentini o'rnatgan edi, shuning uchun bu yangi qaror emas, mavjud
  naqshning takrori edi.

**Kod sifati ko'rib chiqish (`simplify` skill) o'tkazildi — bu safar xato
qidirish emas, shu sessiyadagi beshta concurrency-tuzatish davri
(`f156c30^...HEAD`, ~1840 qator diff) ustida reuse/simplification/
efficiency/altitude to'rt burchakdan, 4 ta parallel subagent bilan.** Har
biri diff'ning o'z burchagidan topilmalarini qaytardi, keyin dublikatlar
olib tashlanib, xavfsiz bo'lganlari to'g'ridan-to'g'ri tuzatildi:

- **Reuse**: `customer_admin.py`dagi `_to_workspace_out` funksiyasi
  `workspace_admin.py`dagi aynan bir xil funksiyaning nusxasi edi —
  import qilishga o'tkazildi, ikkinchi nusxa o'chirildi.
  `test_kill_switch_api.py`dagi ikkita joyda (mahalliy `class _Member`)
  conftest.py'da allaqachon bor `SeededMember` dataclass'ining arzimas
  qayta ixtiro qilingan nusxasi bor edi — ikkalasi ham `SeededMember`ga
  almashtirildi. Frontend'da workspace va customer sahifalarining kill
  switch formasi (state, handler, JSX) deyarli qator-baqator bir xil
  nusxa edi — yangi `frontend/src/components/KillSwitchPanel.tsx`
  komponentiga chiqarildi, ikkala sahifa ham shu komponentni chaqiradi
  (workspace sahifasida qo'shimcha `blockedNote` prop bilan, chunki u
  yerdagi matn "Yangi action'lar bloklangan" deb qo'shimcha gapni ham
  ko'rsatadi).
- **Simplification**: beshta yangi concurrency testi
  (`test_task_status_concurrency.py`, `test_approval_consume_
  concurrency.py`, `test_last_owner_invariant_concurrency.py`,
  `test_kill_switch_engage_concurrency.py`,
  `test_notification_preference_concurrency.py`) har biri "ikkita
  mustaqil tenant_scoped_session ochish, ikkalasini ham commit qilmasdan
  o'qish" degan bir xil 4 qatorli bootstrap'ni va "natijani kutish, kutilgan
  xatoda rollback+\"rejected\", aks holda commit+\"ok\"" degan bir xil
  try/except naqshini qaytarardi. `conftest.py`ga ikkita kichik yordamchi
  qo'shildi — `two_racing_sessions` (bootstrap) va `race_outcome`
  (bitta g'olib kutiladigan race uchun commit/rollback+natija) — va
  uchinchisi, `commit_and_return` (ikkalasi ham g'olib bo'ladigan race
  uchun, masalan kill switch engage yoki bildirishnoma sozlamasi
  o'rnatish). Beshta test fayli ham shu yordamchilarni ishlatishga
  o'tkazildi — assertion'lar o'zgarmadi, faqat takrorlangan scaffolding
  olib tashlandi. `test_kill_switch_engage_concurrency.py`dagi workspace
  va customer variantlari uchun ikkita deyarli bir xil test funksiyasi
  `@pytest.mark.parametrize("scope", ["workspace", "customer"])` bilan
  bitta funksiyaga birlashtirildi.
- **Altitude**: `customer_service._count_customer_owners`ning docstring'i
  o'z tuzatish texnikasini noto'g'ri ta'riflagan edi ("Same technique as
  the Task/Action/kill-switch concurrency fixes" — lekin kill switch
  aslida `begin_nested`+`IntegrityError` ishlatadi, `FOR UPDATE` emas,
  chunki u insert race, mavjud qatorni tekshirish emas) — izoh to'g'ri
  texnikaga (faqat Task/Action) aniqlashtirildi.
- **Efficiency**: ikki nomzod (Task status o'zgarishi va Approval
  consume'da bir xil qatorning ikki marta — avval qulfsiz authz uchun,
  keyin qulflab — o'qilishi; customer sahifasining arxivlangan
  workspace'lar so'rovi CustomerOwner bo'lmagan har bir ko'ruvchi uchun
  ham shartsiz chaqirilib, doim 403 qaytarishi) ataylab **tuzatilmadi** —
  ikkinchisi butun ilova bo'ylab qabul qilingan "rol asosida UI-gating
  yo'q, backend 403 qaytaradi" konventsiyasiga zid bo'lardi; birinchisi
  esa authz zanjiridagi umumiy funksiyalarni (`_get_owned_task` va hk.)
  qayta tuzishni talab qiladi — Master Instruction aniq ogohlantirgan
  zanjir, va haqiqiy foyda NFR-PERF-001'ning o'lchangan P95 (bir necha
  millisekund) yonida ahamiyatsiz. Ikkinchi, pastroq ishonchli nomzod
  (kill_switch_service'ning ikkita engage funksiyasi va notification_
  service'ning bittasi bir xil `begin_nested`/`IntegrityError`
  qayta tiklash naqshini uch xil qaytarish siyosati bilan takrorlaydi) —
  subagent'ning o'zi buni "majburan bitta abstraksiyaga solish uch xil
  semantikani haddan tashqari umumlashtirib qo'yishi mumkin" deb
  ogohlantirgani uchun ataylab **tuzatilmadi**.

Tuzatishlardan keyin: 189 test (backend, real Postgres'da) o'zgarishsiz
o'tdi; `ruff format`/`ruff check`/`mypy src` toza; frontend ESLint/
`tsc --noEmit`/production build toza; barcha 6 E2E spec (workspace,
customer, archive, kill-switch, logout, accessibility) haqiqiy backend+
frontend'ga (production build) qarshi qayta ishga tushirilib, regressiya
yo'qligi — xususan yangi `KillSwitchPanel` komponentining ikkala
sahifada ham to'g'ri ishlashi — real brauzerda tasdiqlandi.

**To'liq talab-traceability auditi o'tkazildi — QOIDA 2ning o'zi ("ID'siz
talab yo'q") birinchi marta butun TRD'ga qarshi tekshirildi, parcha-
parcha feature-bo'yicha qamrov o'rniga.** TRD'dan (`docs/DODA-TRD-
v2.0.docx`, pandoc orqali) har bir FR-\*/NFR-\*/UC-\*/RISK-\*/OD-\*/ASM-\*
ID'ni (jami 121 ta) chiqarib, har birini CLAUDE.md'ning to'liq matni va
kod bazasining haqiqiy tuzilishi bilan solishtirib chiqildi. Natija:
~68 ta **qurilgan**, ~23 ta (FR-CONV, FR-KNW, FR-ADM — butun oilalar)
**ochiq ravishda kechiktirilgan** (CLAUDE.md'da aniq "ataylab qurilmagan"
deb yozilgan), lekin **41 ta hech qayerda — na CLAUDE.md'da, na kodda —
bironta marta ham tilga olinmagan**. Bu oxirgisi kutilganidan kattaroq
bo'shliq: ayrim oilalar (FR-AUTH, FR-TASK, FR-CTL, NFR-\*) qisman qurilgan
bo'lsa-da, o'z ichidagi ba'zi ID'lari hech qachon alohida tekshirilmagan
edi.

Eng muhim **haqiqiy, tekshirilgan** topilma — FR-ACT-001/002/005/006/
007/009 (tool registry, dry-run preview, retry/circuit-breaker,
connector credential isolation, provider-receipt confirmation, cancel/
compensate oqimi): to'g'ridan-to'g'ri kodga qarab tasdiqlandi —
`ActionStatus.RUNNING/SUCCEEDED/RETRYING/COMPENSATING/COMPENSATED`
domain enum'da mavjud va `state_machine.py`da ruxsat etilgan o'tishlar
sifatida belgilangan, lekin `grep`dan tasdiqlanganidek, **hech qanday
kod yo'li hech qachon `apply_transition`ni shu besh holatning birortasi
bilan chaqirmaydi** — `propose_action`/`validate_action`/`consume_approval`
action'ni faqat DRAFT→VALIDATING→READY/AWAITING_APPROVAL/EXPIRED/
REJECTED'gacha olib boradi, undan keyin (outbox'ga navbatga qo'yilgandan
keyin) hech narsa yo'q. Bu **yangi xato emas** — "Bilingan cheklovlar"da
allaqachon "Outbox relay hozircha connector'siz — faqat Redis Stream'ga
yetkazishni isbotlaydi" deb to'g'ri qayd etilgan edi — lekin bu audit
buni aniq FR-ACT ID'lariga bog'lab, qamrovning chegarasini ilgari
qilingandan ancha aniqroq chizdi: Action'ning **bajarilishi**ning o'zi
(connector chaqirish, RUNNING/SUCCEEDED holatlariga o'tish) hali umuman
mavjud emas, faqat "navbatga qo'yish" qismi bor. Bu xuddi avvalroq qayd
etilgan `risk_level` caller-supplied bo'shlig'i (pastda, "Bilingan
cheklovlar") bilan bir xil oiladagi, undan kengroq bo'shliq — ikkalasi
ham S7'da birinchi connector qurilishidan OLDIN yopilishi kerak bo'lgan
siyosat/bajarilish qatlamlari, hozircha haqiqiy tashqi ta'sir yo'qligi
sababli zararsiz.

Ikkinchi muhim topilma: **RISK-\* (TRD 19.1, o'nta risk) — OD-\* uchun
`docs/open-decisions.md` qurilgan bo'lsa-da, risk registrining o'ziga
hech qachon mos tracker yozilmagan edi, birorta RISK ID CLAUDE.md'da
hech qachon tilga olinmagan edi.** `docs/open-decisions.md`ning aynan
bir xil formatida `docs/risk-register.md` yozildi — o'nta risk ham TRD
19.1'dan to'g'ridan-to'g'ri o'qib (subagent xulosasiga emas, hujjatning
o'ziga tayanib) olingan, har biriga haqiqiy kod bazasiga nisbatan
holat berilgan: ba'zilari (RISK-006 "xavfsizlik illyuziyasi" — "DEMO ≠
PRODUCTION" qoidasi va uch marta o'tkazilgan security-review bilan eng
yaxshi yengillashtirilgan) haqiqatda allaqachon qisman yopilgan, lekin
hech qachon ID bo'yicha bog'lanmagan edi; boshqalari (RISK-003/005/010)
hali boshlanmagan domainlarga (memory, AI/model chaqiruvlari) bog'liq
bo'lgani uchun "dormant" deb to'g'ri belgilandi, tasodifan yengillashmagan
deb emas; RISK-009 (data residency kechikishi) esa TRD aynan
bashorat qilgan tarzda materiallashayotgani ko'rsatildi — OD-005 hamon
ochiq va muddatidan o'tgan. README.md'ga havola qo'shildi.

Shu jarayonda yana bitta, alohida bo'shliq ham aniqlandi:
**NFR-I18N-001** (uz/ru/en matnlari externalized, hardcode yo'q) hech
qachon tekshirilmagan — bugungi frontend 100% hardcode qilingan o'zbek
tilida, hech qanday i18n kutubxonasi yo'q. `docs/risk-register.md`ning
RISK-010 qatoriga shu bilan bog'liq, lekin alohida eslatma sifatida
yozildi (UI matnlarini tashqariga chiqarish vs AI javoblarining til
sifati — ikki xil, lekin bog'liq masala).

**Qolgan 41 ID'ning aksariyati ataylab hech narsa qilinmadi** — ular
yoki hali qurilmagan domainlarga (Knowledge/memory, AI/chat, connector)
bog'liq (FR-TASK-002/003/005/006, FR-CTL-004, NFR-PERF-002/003,
NFR-ISO-003, NFR-PORT-001, NFR-REL-\*, NFR-DUR-001, NFR-SEC-001), yoki
yangi, alohida mahsulot qarorini talab qiladigan funksiyalar (FR-AUTH-002
MFA enrollment, FR-AUTH-007 anomalous-login alert, FR-AUTH-008 WebAuthn,
FR-AUTH-009 Service Actor credential flow, FR-WKS-007 workspace
settings, FR-CTL-005 undo, FR-AUD-003 redaction CI scanner, FR-AUD-005
evidence package) — QOIDA 2'ga ko'ra bularning har biri so'ralmagan
holda amalga oshirilmaydi, bu yerda faqat **ID bo'yicha ko'rinadigan**
qilib qo'yildi (keyingi safar kimdir "bu qurilganmi" deb so'raganda,
javob endi "tekshirilmagan" emas, aniq).

Bu sof tekshiruv+hujjatlashtirish — kod o'zgarmadi, 189 test
o'zgarishsiz qoladi.

**Traceability auditda topilgan 41 bo'shliqdan bittasi — FR-AUD-003
("Audit yozuvida secret, token, PII yoki prompt kontenti bo'lmaydi",
Must, qabul mezoni "Redaction scanner CI'da 0 topilma") — qurildi,
chunki u boshqalaridan farqli, hech qanday yangi domain yoki Product
Owner qaroriga bog'liq emas edi: bu sof statik tekshiruv, xuddi
`test_domain_isolation.py` kabi.** `tests/unit/test_audit_redaction.py`
— `record_audit_event(...)`ning barcha chaqiruv nuqtalarini (AST orqali,
DB shart emas) topib, har birining `safe_metadata=` lug'atidagi
kalitlarini bitta, qo'lda ko'rib chiqilgan ro'yxat (`ALLOWED_SAFE_
METADATA_KEYS`) bilan solishtiradi. Kelajakda kimdir audit yozuviga
`"email": user.email` yoki `"password": token` kabi yangi kalit qo'shsa,
bu test CI'da darhol qizaradi — append-only audit trail'ga (0001-
migratsiyadagi `audit_events_no_update_delete` trigger tufayli) yozilgan
narsa keyin hech qachon tuzatib bo'lmaydi, shuning uchun bu tekshiruv
yozilishdan OLDIN bo'lishi kerak.

Ro'yxatning o'zi kod bazasidagi HAR BIR mavjud chaqiruvni (audit.py,
export_service.py, action_service.py, customer_service.py, workspace_
service.py, notification_service.py, kill_switch_service.py — sakkiz
fayl, ~20 chaqiruv nuqtasi) qo'lda o'qib chiqib tuzildi, taxmin qilinmadi.
Ikkita erkin-matn maydoni (`reason` — kill switch sababi, `name` —
customer/workspace nomi) ataylab ro'yxatda qoldirildi, lekin docstring'da
aniq yozilgan: bu test ularning QIYMATINI statik tekshira olmaydi (inson
kiritgan matn ichida nazariy jihatdan sezgir narsa bo'lishi mumkin) —
bu ikkala maydonning o'zi audit uchun ma'noli bo'lishining tabiiy
narxi (masalan "nima uchun kill switch yoqildi" degan savolga javob
o'qilmaydigan bo'lsa, audit yozuvining ma'nosi yo'qoladi). Test nimani
KAFOLATLAYDI: hech qanday yangi maydon nomi ko'rib chiqilmasdan audit
yozuviga qo'shilib qolmaydi.

Testning chinakam narsani tutishi isbotlandi (audit-zanjiri uslubida):
`customer_service.py`dagi bitta chaqiruvga vaqtincha `"owner_email":
"leaked@example.com"` qo'shib test aniq shu kalitni ko'rsatib
muvaffaqiyatsiz bo'lishini tasdiqladim, qaytarib yashil ekanini
ko'rsatdim; keyin alohida, `export_service.py`dagi bitta chaqiruvni
vaqtincha o'zgaruvchiga (`safe_metadata=some_dynamic_metadata`)
almashtirib, testning "faqat literal lug'atni statik tekshira olaman"
himoya yo'lining ham ishlashini (aniq xato xabari bilan) tasdiqladim,
so'ng qaytarib yashil ekanini ko'rsatdim. 190 test, barchasi real
Postgres'da.

**Product Owner uchta haqiqiy qaror qabul qildi — birinchi marta bu
sessiyada CLAUDE.md/docs/open-decisions.md faqat kuzatib turgan
ochiq savollarga real javob keldi, taxmin qilinmadi.** Uchalasi ham
`docs/open-decisions.md`ga to'g'ridan-to'g'ri yozildi:

1. **OD-002 (birinchi konnektor) — Telegram.** `docs/adr/
   ADR-007-first-connector.md` "Open"dan "Accepted"ga o'tkazildi. Bu
   qaror avvalroq xavfsizlik ko'rib chiqishda topilgan, "birinchi
   connector'dan OLDIN qurilishi kerak" deb bir necha marta qayd
   etilgan bo'shliqni — `risk_level`ning to'liq caller-supplied
   ekanligini — endi haqiqiy, spekulyativ bo'lmagan zaruratga
   aylantirdi: aniq, real maqsadli tool nomi (`telegram.send_message`)
   paydo bo'ldi. Shuning uchun **shu sessiyada qurildi**:
   `domain/action/tool_policy.py` — `TOOL_MINIMUM_RISK_LEVEL` ro'yxati
   (hozircha faqat bitta yozuv: `telegram.send_message` → R3, xuddi
   testlarda allaqachon ishlatilgan `send_email`/`email.send`
   precedenti bilan bir xil asosda — tashqi odamga xabar yuborish
   jiddiy, qaytarib bo'lmaydigan ta'sir) va `enforce_minimum_risk_level`
   funksiyasi. `action_service.propose_action` endi chaqiruvchi
   yuborgan `risk_level`ni shu minimal darajaga ko'taradi (hech qachon
   pasaytirmaydi — R3 tool uchun R5 so'ralsa, R5 qoladi), Action qatori
   yaratilishidan OLDIN. **Ataylab FR-ACT-001ning to'liq tool
   registri EMAS** — ro'yxatga kiritilmagan `tool_name` (hozircha
   ko'pchilik, chunki haqiqiy connector'lar hali yo'q) hech qanday
   cheklovga uchramaydi, xuddi avvalgidek — faqat ro'yxatga kiritilgan,
   real qaror bilan tasdiqlangan bitta tool uchun haqiqiy minimal
   himoya qo'shildi, spekulyativ keng qamrovli o'zgarish emas.

   Tuzatish (aniqrog'i, yangi himoya qatlami) audit-zanjiri uslubida
   isbotlandi: `enforce_minimum_risk_level` chaqiruvini vaqtincha
   izohga olib, yangi integratsiya testi (`test_registered_tool_
   cannot_be_under_declared_below_its_minimum_risk`) aynan kutilgan
   tarzda muvaffaqiyatsiz bo'lishini (`assert R0 is R3` xatosi bilan)
   ko'rsatdim — sof funksiya darajasidagi testlar (`tests/unit/
   test_tool_policy.py`) shu paytda ham yashil qolishini alohida
   tasdiqladim, chunki ular `propose_action`ni emas, funksiyaning
   o'zini sinaydi. Keyin himoyani qaytarib, barchasi yashil ekanini
   ko'rsatdim. 196 test, barchasi real Postgres'da.

   Haqiqiy Telegram Bot API integratsiyasi (bot token, broker orqali
   qisqa muddatli credential — 9.3, real xabar yuborish) hali
   qurilmagan — bu haqiqiy bot token talab qiladi, uni Product Owner
   xavfsiz kanal orqali (environment variable / secrets manager,
   hech qachon chat matniga yoki repo'ga yozib emas) taqdim etishi
   kerak. Bu ADR-007'ning yangi "Status note" bo'limida aniq yozilgan.

2. **OD-004 (o'zbek tilidagi ovoz) — KERAK, avvalgi baho bekor
   qilindi.** TRD 2.3 ovozni "OUT OF SCOPE" deb ro'yxatlagan edi, va
   bu sessiyaning o'zi avvalroq buni "de facto resolved (out of
   scope)" deb baholagan edi — Product Owner endi buni aniq bekor
   qildi. Bu TRD 19.4'ning o'z mantig'iga mos: yakuniy so'z doim
   Product Owner'niki, hujjat matni emas. **Amalga oshirish hali
   BOSHLANMAGAN va yangi ochiq savol tug'diradi**: qaysi STT/TTS
   provayder (RISK-010 — "o'zbek tilida sifat pariteti past
   bo'lishi" xavfi ayni shu yerda dolzarb: ko'pchilik ovoz
   provayderlari o'zbek tilini kuchsiz qo'llab-quvvatlaydi), va
   qanday UI oqimi (odatda ovoz Chat/FR-CONV ustiga quriladi, u
   hali qurilmagan). `docs/open-decisions.md`ga to'liq yozildi —
   provayder tanlanmasdan ovoz UI'sini qurish spekulyativ bo'lardi,
   shuning uchun ataylab hali boshlanmadi (QOIDA 2: bu o'z
   navbatida yana bitta Product Owner qarorini talab qiladi).

3. **OD-001 (SaaS) — qayta tasdiqlandi, nuance bilan.** Product
   Owner aniq qildi: hozircha shaxsiy foydalanish uchun, lekin
   kelajakda boshqa odamlarga taqdim eta olish (sotish) qobiliyati
   bilan. Bu allaqachon qurilgan Customer→Workspace→Membership
   multi-tenant arxitekturaning aynan o'zi — kod o'zgarishi talab
   qilmadi, faqat `docs/open-decisions.md`dagi yozuv shu nuance bilan
   boyitildi.

**Uchta konkret kirish (Telegram bot token, STT/TTS provayder, OIDC
credential) hali kelmagani uchun keyingi bosqich (haqiqiy connector/
ovoz/OIDC) hozircha bloklangan — shuning uchun TRD'ning qolgan
tekshirilmagan NFR ID'lari (NFR-PERF-002/003, NFR-REL-001/002,
NFR-DUR-001, NFR-SEC-001, NFR-ISO-003, NFR-PORT-001) yana bir marta
ko'rib chiqildi: barchasi yoki hali qurilmagan domainlarga (Chat/
Knowledge/AI) yoki hali qabul qilinmagan OD-005 (hosting) qaroriga
bog'liq ekani tasdiqlandi — mustaqil bajarib bo'lmaydi.**

Shu tekshiruv jarayonida **NFR-SEC-001ning bir qismi — "Konfiguratsiya
skan" — haqiqiy, hech qanday infra yoki OD-005'ga bog'liq bo'lmagan
gap sifatida topildi va yopildi.** `config.py`dagi
`cors_allowed_origins` maydonining izohi har doim "hech qachon '*'
emas" degan, chunki har bir so'rov bearer session token olib yuradi —
lekin bu FAQAT izoh edi, kod darajasida HECH NARSA operatorni
`DODA_CORS_ALLOWED_ORIGINS=*` o'rnatishdan to'xtatmasdi.
`main.py`ning o'zi buni to'g'ridan-to'g'ri `CORSMiddleware(allow_origins=...,
allow_credentials=True)`ga uzatadi — bu aniq, hujjatlashtirilgan CORS
anti-pattern (wildcard + credentials). Amalda bugun buzilmagan (haqiqiy
qiymat hamon `http://localhost:3000`), lekin hech narsa buni kelajakda
xato konfiguratsiyadan saqlamas edi.

Tuzatish: `Settings.cors_allowed_origins`ga pydantic `field_validator`
qo'shildi — vergul bilan ajratilgan ro'yxatdagi HAR BIR elementni
tekshirib, birortasi (bo'sh joylar olib tashlangandan keyin) aniq `"*"`
ga teng bo'lsa, `Settings()` konstruksiyasining o'zida (ilova ishga
tushishidan oldin) `ValidationError` ko'taradi — jimgina qabul qilish
o'rniga darhol to'xtatadi. Bu birinchi `field_validator` ishlatilishi
kod bazasida (boshqa joylarda pydantic schema'lar faqat oddiy
`BaseModel`).

Audit-zanjiri uslubida isbotlandi: validator vaqtincha olib tashlanib,
yangi `tests/test_config.py`ning ikkita testi (`test_wildcard_cors_
origin_is_rejected`, `test_wildcard_mixed_with_a_real_origin_is_still_
rejected`) aynan kutilgan tarzda muvaffaqiyatsiz bo'lishi (`DID NOT
RAISE ValidationError`) ko'rsatildi — ya'ni bugungi kodda
`DODA_CORS_ALLOWED_ORIGINS=*` haqiqatda jimgina qabul qilinardi, bu
faraz emas edi. Keyin validator qaytarilib, uchala test ham (uchinchisi
— oddiy, to'g'ri qiymat rad etilmasligini tasdiqlaydi) yashil ekani
ko'rsatildi. `ruff`/`mypy` toza, 199 test (196+3), barchasi real
Postgres'da.

DB TLS/encryption-at-rest (NFR-SEC-001ning ikkinchi yarmi) ataylab
tegilmadi — bu haqiqiy managed Postgres/hosting infratuzilmasini
(OD-005) talab qiladi, real TLS ulanishisiz assertion yozish
"isbotlamasdan taxmin qilma" tamoyilini buzardi.

**Xuddi shu "izohda da'vo bor, kod darajasida tekshirilmagan" naqshini
qidirishda `session_service.list_active_sessions_for_user`ning o'z
docstring'idagi da'vosi ("listing must never itself touch
last_seen_at, or just looking at your session list would silently
keep every one of them alive forever") hech qachon boshqa (chaqiruvchining
o'zinikidan farqli) sessiya uchun test qilinmaganini topdim.**
Mavjud `test_authenticated_request_persists_the_session_activity_touch`
faqat chaqiruvchining O'Z sessiyasi auth-resolution qadamida
yangilanishini tasdiqlaydi — bu boshqa (ro'yxatda ko'ringan, lekin
so'rov qilmagan) sessiyaning `last_seen_at`'i ham chetdan
yangilanmasligini yashirib qo'yishi mumkin edi.

Yangi `test_listing_does_not_refresh_a_different_sessions_last_seen_at`
qo'shildi. Buni yozish jarayonida ikki bosqichli, o'rganarli xato
chiqdi: birinchi versiya HTTP endpoint (`GET /v1/sessions`) orqali
sinalgan edi — funksiyaga ataylab in-memory "bug" (`row.last_seen_at =
now`) kiritib ko'rganimda, test **hamon yashil qoldi**, garchi xato
haqiqatda kod ichida bo'lsa ham. Sabab: `api/sessions.py`ning
`list_my_sessions` handler'i o'z DB sessiyasini `session.begin()`siz,
hech qachon commit qilmasdan ochadi (bugungi kunda bu to'g'ri — sof
o'qish uchun yozish shart emas) — bu esa istalgan tasodifiy yozuvni
chiqishda jimgina rollback qilib, mening in-memory tekshiruv-testimni
ma'nosiz qilib qo'yardi (aynan FR-AUTH-006'ning ASL xatosi — kerakli
yozuv jimgina yo'qolgan — bilan bir xil mexanizm, faqat teskari
yo'nalishda: bu safar kerak BO'LMAGAN yozuv "tasodifan" saqlanmay
qolgani uchun test yolg'on yashil bo'lardi). Testni to'g'ri qildim:
endi `list_active_sessions_for_user`ni to'g'ridan-to'g'ri, ANIQ commit
qiluvchi sessiya bilan chaqiradi — endpoint'ning tasodifiy
commit-yo'qligi holatiga bog'liq emas. Xuddi shu in-memory bug qayta
kiritilganda test endi to'g'ri, kutilgan tarzda muvaffaqiyatsiz bo'ldi
(`assert <yangi vaqt> == <eski vaqt>`), qaytarilganda yashil.

Bu haqiqiy xato TOPILMADI — `list_active_sessions_for_user`ning o'zi
har doim to'g'ri bo'lgan (sof `SELECT`, hech qanday yozuv yo'q). Lekin
bu ish shu bilan bir xil, muhimroq narsani ochib berdi: `api/
sessions.py`ning ikkita handler'i (`list_my_sessions`,
`revoke_my_session`) hamon `api/dependencies.py`da uch joyda allaqachon
tuzatilgan eski naqshni (`async with async_session_factory()`, aniq
`session.begin()`siz) ishlatadi — `revoke_my_session` o'zi qo'lda aniq
`db.commit()` chaqirgani uchun xavfsiz, `list_my_sessions` esa yozuv
qilmagani uchun xavfsiz, lekin kelajakda kimdir shu ikkalasidan birini
kengaytirib (masalan revoke'ga yana bir yozuv qo'shib) `commit()`ni
unutsa, bu ANIQ xuddi FR-AUTH-006'ning asl xatosini takrorlaydi. Bu
o'zi alohida, kelajakdagi ehtiyotkorlik eslatmasi sifatida qayd
etildi — bugun aniq buzuqlik yo'q, shuning uchun tuzatish (masalan
`get_current_identity`dagi kabi umumiy commit-qiluvchi dependency
pattern'iga o'tkazish) so'ralmagan holda amalga oshirilmadi.

200 test, barchasi real Postgres'da.

**To'rtinchi `security-review` o'tkazildi — bu safar avvalgi uchtasidan farqli,
qisman diff emas, BUTUN PR (main'ga nisbatan barcha 186 fayl) qamrovida.**
Jarayon bir xil: (1) topish subagent'i butun kod bazasini (authz zanjiri,
session, Action/Approval state machine, kill switch, audit hash-zanjiri,
RLS/migratsiyalar, CORS/config, frontend) qayta ko'rib chiqdi, (2) faqat
haqiqiy nomzod topilsa har biri uchun alohida false-positive filtrlash
subagent'i, (3) faqat ishonch darajasi >=8 rasmiy hisobotga kiritiladi.

**Natija: 0 topilma.** Topish subagent'i bir nechta ehtimoliy nomzodni
alohida tekshirib, hech biri haqiqiy ekspluatatsiya yo'liga ega emasligini
tasdiqladi: (1) `get_workspace_context`/`get_customer_context` RLS GUC'iga
emas, aniq `CustomerMembership`/`WorkspaceMembership` join'lariga tayanadi —
demak RLS qayta ishlamay qolsa ham (ADR-005 incident'i kabi), bu authz
zanjiri o'zi mustaqil qoladi; (2) `list_tasks_for_workspace`/`list_actions_
for_workspace`/`list_workspace_members` faqat `workspace_id` bo'yicha
filtrlaydi, aniq `customer_id` predikati yo'q — bu uchinchi security-review'da
tuzatilgan `list_my_workspaces` bo'shlig'iga o'xshab ko'rinadi, lekin
`workspace_id`ning o'zi allaqachon global, taxmin qilib bo'lmaydigan noyob
kalit bo'lgani uchun cross-tenant sizib chiqish yo'q; (3) `risk_level`ning
caller-supplied ekanligi (bilingan cheklov, yuqoriga qarang) — real, lekin
hech qanday connector `READY` action'larni hali iste'mol qilmagani uchun
hozircha ekspluatatsiya qilinadigan tashqi ta'sir yo'q.

Bu safar hech qanday nomzod filtrlash bosqichiga o'tmadi (rasmiy hisobot
bo'sh) — avvalgi uchta review'dan farqli, bu safar chindan ham "toza" natija,
zo'rma-zo'raki chegara-usti (ishonch 7) topilma ham yo'q edi.

200 test, barchasi real Postgres'da (kod o'zgarmadi — sof tekshiruv).

**CI'da haqiqiy, ikki bosqichli tuzatish talab qilgan infratuzilma xatosi
topildi va yopildi — E2E job Google'ning o'z Chrome APT repo'sidagi doimiy
buzuqlik tufayli ikki marta ketma-ket muvaffaqiyatsiz bo'ldi.**
`npx playwright install --with-deps chromium` `apt-get update`ni
ishga tushiradi — bu runner image'dagi BARCHA apt manbalarni, jumladan
loyihaga umuman aloqasi yo'q, oldindan o'rnatilgan Google Chrome
repo'sini (`dl.google.com`) ham yangilaydi. Bu repo'ning mirror'i
`Packages.gz` uchun noto'g'ri hash qaytarardi ("Hash Sum mismatch").

Birinchi urinish (3 martalik retry+backoff) noto'g'ri diagnozga
asoslangan edi — "vaqtinchalik shovqin" deb taxmin qilingan edi.
Lekin retry ham muvaffaqiyatsiz bo'lgach, log'larni solishtirib
ANIQ bir xil hash qiymatlari (SHA256/SHA1/MD5) uchta urinishning
barchasida takrorlanayotganini ko'rdim — bu mirror'ning **doimiy**
buzuq holatda ekanini isbotladi, vaqtinchalik emas. Demak retry
hech qachon yordam bermas edi. To'g'ri tuzatish: loyiha Google
Chrome'ni umuman ishlatmaydi (faqat Chromium), shuning uchun
`sudo rm -f /etc/apt/sources.list.d/google-chrome*.list`ni
`playwright install`dan OLDIN qo'shib, apt bu buzuq repo'ga
umuman murojaat qilmasligini ta'minladim.

Bu ikki bosqichli jarayonning o'zi ham professional namunasi:
birinchi (noto'g'ri) tuzatish push qilinib, xuddi shu xato bilan
qayta muvaffaqiyatsiz bo'lgach, buni "yana bir flake" deb
e'tiborsiz qoldirmasdan, log'larni diqqat bilan solishtirib
haqiqiy ildiz sababni topdim. Ikkala urinish ham PR'ga ochiq
izoh sifatida hujjatlashtirildi (nima ishlamadi, nega, va nihoyat
nima ishladi) — CI'ning o'zi ham `get_job_logs` orqali tasdiqlandi,
taxmin qilinmadi.

**Product Owner haqiqiy Telegram bot tokenini xavfsiz kanal orqali
(environment variable, hech qachon chat matniga yozmasdan) taqdim etdi
— shundan keyin OD-002'ning haqiqiy connector qismi (ADR-007'ning o'z
"Status note"i "hali qurilmagan" deb belgilagan qism) qurildi.** Bu
`outbox_relay.py`ning o'z, sessiya boshidan buyon takrorlangan
da'vosini ("connector hali yo'q (S7)") birinchi marta yopadi — 176-test
atrofida topilgan FR-ACT traceability bo'shlig'i (RUNNING/SUCCEEDED/
FAILED `state_machine.py`da ruxsat etilgan o'tish sifatida bor edi,
lekin hech qanday kod yo'li ularni hech qachon chaqirmasdi) ham shu
bilan bir vaqtda yopiladi — ikkalasi ham aynan bir xil bo'shliqning
ikki tomoni edi.

`infrastructure/telegram_client.py` — minimal Bot API `sendMessage`
klienti. Xavfsizlik nozikligi: Telegram bot tokeni URL YO'LIDA
yuriladi (`/bot<token>/sendMessage`), header'da emas — demak xom
`str(exc)` yoki log'langan URL orqali token sizib chiqishi mumkin edi.
Shuning uchun har bir xato yo'li faqat `type(exc).__name__`dan
foydalanadi, hech qachon `httpx` xatosining o'z matn shaklidan emas —
bu maxsus test bilan tasdiqlangan
(`test_network_error_raises_telegram_send_error_without_leaking_the_token`,
tokenni ataylab "super-secret-token" qilib, natijadagi xato matnida
hech qachon ko'rinmasligini tekshiradi).

`infrastructure/telegram_relay.py` — outbox relay'ning
`doda:outbox:action.ready.v1` Redis Stream'idagi haqiqiy BIRINCHI
iste'molchi. Redis Streams consumer group (`XGROUP CREATE`/
`XREADGROUP`/`XACK`) orqali o'qiydi, faqat `tool_name ==
telegram.send_message` bo'lgan action'larga tegadi (boshqa har qanday
tool — hozircha hammasi — XACK qilinib, tegilmasdan qoldiriladi, bu
umumiy action executor emas). Har bir action'ni mavjud
`apply_transition` chokepoint'i orqali READY → RUNNING →
SUCCEEDED/FAILED'ga olib boradi — qulflash/audit/bildirishnoma
mantig'ini qayta yozmasdan, xuddi shu kodni qayta ishlatib.

**Ikki qatlamli idempotentlik, ikkalasi ham alohida isbotlangan**
(qayta yetkazish — consumer XACK'dan oldin qulab tushishi — nazariy
emas, Redis consumer group semantikasining o'zi): (1)
`_drive_to_running`ning aniq status tekshiruvi — READY'dan boshqa
har qanday holat "avvalgi yetkazish allaqachon bu bilan shug'ullangan"
deb toza (xatosiz, qayta yubormasdan) o'tkazib yuboriladi; (2) hatto
shu tekshiruv olib tashlansa ham, `apply_transition`ning o'z state
machine'i mustaqil ravishda SUCCEEDED→RUNNING kabi o'tishlarni rad
etadi (`InvalidActionTransition`) — demak qayta yetkazilgan yozuv
baribir `send_message`ga ikkinchi marta yetib borolmaydi, faqat
tinchroq emas (ushlanmagan xato, PEL'da ushlanib qoladi) yo'l bilan.
Bu audit-zanjiri uslubida isbotlandi: `_drive_to_running`ning aniq
tekshiruvini vaqtincha olib tashlab, kutilgan natija (jimgina ikki
marta yuborish) O'RNIGA `InvalidActionTransition` chiqishini kuzatdim
— bu ikkinchi qatlamning haqiqiy, mustaqil backstop ekanini
tasdiqladi (ADR-005'ning "ikkinchi, mustaqil qatlam" naqshining
takrori), keyin tekshiruvni qaytarib yashil ekanini ko'rsatdim.

**Halol qolgan bo'shliq (yechilmagan, aniq yozilgan)**: muvaffaqiyatli
Telegram chaqiruvi bilan shu jarayonning SUCCEEDED'ga commit qilishi
orasida qulab tushish action'ni RUNNING holatida qotirib qo'yishi
mumkin (qayta yetkazish uni RUNNING != READY deb ko'rib o'tkazib
yuboradi — qayta yuborilmaydi, lekin alohida reconciliation job'siz
SUCCEEDED'ga ham hech qachon yetmaydi). Bu haqiqiy, kelajakdagi ish
sifatida `telegram_relay.py`ning o'z docstring'ida ochiq qoldirildi —
Telegram Bot API'ning o'zida so'rov darajasidagi idempotency key yo'q,
shuning uchun buni to'g'ridan-to'g'ri yopib bo'lmaydi.

**Bu PR'ning o'z tekshiruvidagi halol chegara**: bu muhitda haqiqiy
Telegram bot token yoki chat mavjud emas, shuning uchun Telegram'ning
o'z API'siga qilingan HAQIQIY HTTP chaqiruvi hech qachon real xizmatga
qarshi ishga tushirilmagan — faqat outbox → Redis Stream → consumer →
DB holat o'tishi pipeline'i real Postgres+Redis'ga qarshi isbotlangan,
Telegram HTTP qismining o'zi test double (`httpx.MockTransport`) bilan
almashtirilgan (5 unit test — klientning o'z so'rov/javob mantig'i;
5 integration test — real Postgres+Redis'ga qarshi to'liq pipeline,
shu jumladan qayta yetkazish stsenariysi). "Real integratsiya
bajarilmagan bo'lsa PASS deb yozma" qoidasiga qat'iy rioya qilindi —
bu haqiqat har uchta yangi fayl (modul docstring, test docstring,
ADR-007'ning "Status note"i)da ochiq yozilgan, yashirilmagan.

Ishlab chiqish jarayonida ikkita amaliy xato topilib tuzatildi: (1)
`relay_once` `ensure_consumer_group`ni chaqirmasdan `XREADGROUP`ga
murojaat qilardi — birinchi test ishga tushishida `NOGROUP` xatosi
bilan darhol aniqlandi, `ensure_consumer_group`ni `relay_once`ning
o'ziga (har chaqiruvda, BUSYGROUP-toqat qiluvchi) ko'chirib tuzatildi;
(2) bu sessiyaning Redis'i butun uzoq sessiya davomida saqlanib
qolgani uchun `doda:outbox:action.ready.v1` stream'ida yuzlab eski
yozuv (`lag: 234` `XINFO GROUPS` orqali kuzatilgan) to'planib qolgan
edi — yangi urug'lantirilgan action shu backlog ORQASIDA qolib,
`relay_once`ning bitta chaqiruvi (batch=50) unga yetmasdi. Test
tomonidan qo'shilgan `_drain_until_resolved` (backlog tugagunga yoki
maqsad action READY'dan chiqquncha `relay_once`ni qayta-qayta
chaqiradi) bilan tuzatildi — `test_outbox_relay.py`ning o'zidagi
mavjud naqshning aynan takrori, yangi ixtiro emas.

`ruff`/`mypy` toza (redis-py'ning `xreadgroup` stub'lari haqiqiy
runtime shaklidan ancha bo'sh tiplangani uchun `cast()` qo'shildi).
`outbox_relay.py`ning o'z docstring'i ham yangilandi — endi "connector
hali yo'q" deb yolg'on da'vo qilmaydi, `telegram_relay.py`ga havola
beradi va boshqa tool'lar uchun bo'shliq hamon ochiqligini aniq
belgilaydi. 210 test, barchasi real Postgres+Redis'da.

Hujjatlashtirish ham yangilandi: `docs/open-decisions.md`ning OD-002
qatori va `docs/adr/ADR-007-first-connector.md`ning "Status note"
bo'limi endi connector haqiqatda qurilganini aks ettiradi (avval
"hali qurilmagan" deb yozilgan edi) — credential broker (9.3) esa
hamon qurilmagan (bugungi kunda bot tokeni to'g'ridan-to'g'ri
`Settings`dan o'qiladi, broker orqali qisqa muddatli token sifatida
emas) va bu aniq keyingi bo'shliq sifatida qayd etildi.

**Ikkita alohida "eskirgan hujjat" xatosi topildi va tuzatildi — ikkalasi
ham Telegram connector qurilishidan OLDIN, "connector hali yo'q"
degan hozirgi vaqt bayonoti sifatida yozilgan, endi noto'g'ri
bo'lib qolgan.** `domain/action/tool_policy.py`ning docstring'i "Not yet
dangerous while no connector exists" derdi — endi Telegram connector
haqiqatda `telegram.send_message` action'larini ishlatayotgani uchun bu
himoya endi preventiv emas, JONLI mitigatsiya. `frontend/README.md`
Action'lar bo'limida propose formasi qurilmaganining sababini "hali
hech qanday haqiqiy tool/connector yo'q" deb ko'rsatardi — haqiqiy sabab
tarraqroq: forma tool nomini erkin matn sifatida qabul qiladi, va
ko'pchilik tool nomlari (Telegram'dan tashqari) hamon connector'ga ega
emas. Ikkalasi ham to'g'ri sababga (jonli mitigatsiya / tor "erkin matn"
muammosi) yangilandi. README.md'ning o'zi ham yangilandi (200→210 test,
connector haqiqatda qurilgani, halol chegara bilan). Kod xulqi
o'zgarmadi — sof hujjat aniqligi, `ruff`/`mypy`/210 test bilan
tasdiqlandi.

**FR-ACT/telegram_relay.py'ning o'z docstring'ida ochiq qoldirilgan
"Action RUNNING holatida qotib qolishi mumkin" bo'shlig'ining
KUZATISH (observability) yarmi yopildi — YECHISH yarmi emas.**
`backend/scripts/find_stuck_running_actions.py` —
`verify_audit_chain_job.py` bilan bir xil turkumdagi mustaqil skript
(`UserCustomerIndex` orqali customer'larni topib, har birini
tekshiradi, buzilish/bo'shliq topilsa stderr + exit code 1 — "alert" shu
oqim). Har bir hozir RUNNING holatidagi Action uchun o'zining
`action.running.v1` audit yozuvi (`apply_transition` RUNNING'ga
o'tganda yozadigan) topiladi; agar shu yozuvning `occurred_at`'i
belgilangan chegaradan (standart 15 daqiqa) eski bo'lsa — STUCK deb
belgilanadi.

**Ataylab YECHILMAYDI**: qaysi qotib qolgan Action'ni qanday
tiklash (Telegram'ga xabar haqiqatda yuborilganmi yoki yo'qmi — Bot
API'da so'rov darajasidagi idempotency key yo'qligi sababli buni
ishonchli bilib bo'lmaydi) — bu haqiqiy arxitektura qarori, monitoring
skripti qaror qabul qilishi kerak bo'lgan narsa emas. Skript faqat
bo'shliqni KO'RINADIGAN qiladi, uni yopmaydi.

Bu skript uchun (boshqa mustaqil skriptlar — `verify_audit_chain_job.py`,
`load_test_api.py` — kabi) pytest test yozilmadi, xuddi shu ikkalasi
kabi qo'lda, real Postgres'ga qarshi tekshirildi (kod bazasidagi
o'rnatilgan konventsiya — bu skriptlar hech qachon pytest orqali emas,
qo'lda ishga tushirib tasdiqlanadi). Tekshiruv: haqiqiy `telegram.send_
message` action'ini to'liq propose→validate→approve→consume oqimi
orqali READY'ga, keyin `telegram_relay._drive_to_running` orqali
RUNNING'ga (hech qachon SUCCEEDED/FAILED'ga hal qilmasdan — aynan
"crash o'rtada" stsenariysi) haqiqiy Postgres'da yaratildi. Standart
15-daqiqalik chegara bilan bu YANGI action "running_ok" deb to'g'ri
belgilandi (exit 0); `threshold=0` bilan esa aynan shu action haqiqiy
`occurred_at`/yosh (`age`) bilan STUCK deb belgilandi (exit 1) — ikkala
holat ham skriptning o'zi (import qilingan `main()` funksiyasi orqali)
haqiqiy ishga tushirilib, keyin standalone `python scripts/find_stuck_
running_actions.py` orqali ham qayta tasdiqlandi.

Bu skriptni yozish/tekshirish jarayonida haqiqiy amaliy xato o'zida
topildi va tuzatildi (commit qilinmasdan oldin): birinchi tekshiruv
urinishi `customer_id = uuid.uuid4()`ni to'g'ridan-to'g'ri, hech qanday
`UserCustomerIndex` qatorisiz ishlatgan edi — skript hech narsa
topmadi (customer discovery bo'sh qaytardi), ikkala threshold bilan ham
exit 0 berdi, garchi RUNNING action haqiqatda mavjud bo'lsa ham. Bu
skriptning o'zidagi xato emas — `verify_audit_chain_job.py` bilan bir
xil, to'g'ri customer-discovery konventsiyasini ishlatgani (haqiqiy
customer'lar doim `UserCustomerIndex`da bo'ladi, `customer_service`
orqali yaratilgani uchun) aniqlandi; tekshiruv skriptining o'zi
tuzatilib (customer_id'ni `UserCustomerIndex`ga ham yozib), keyin
to'g'ri natija berdi. `infrastructure/telegram_relay.py`ning o'z
docstring'iga ham yangi skriptga havola qo'shildi.

210 test, barchasi real Postgres+Redis'da (yangi skript uchun pytest
test yo'q, o'rnatilgan konventsiyaga ko'ra — yuqoriga qarang).

**Test qamrovi (coverage) bu loyihada hech qachon o'lchanmagan edi — birinchi
marta o'lchandi, va o'lchashning o'zi uchta narsani ochib berdi: bitta haqiqiy
qamrov bo'shlig'i va ikkita test-infratuzilma nuqsoni (ikkalasi ham xatoni
ko'rsatish o'rniga YASHIRADI).**

**Coverage konfiguratsiyasi bu kod bazasi uchun majburiy, "sozlash" emas.**
`concurrency = ["thread", "greenlet"]`siz coverage SQLAlchemy'ning greenlet
ko'prigi va async so'rov yo'li orqali bajarilgan kodni ko'rmaydi — natijada
HAR BIR FastAPI route handler'ining tanasi "bajarilmagan" deb ko'rinadi.
O'lchangan: `api/tasks.py` aynan shu qatorlarni haqiqatda ishlatadigan
testlar bilan **72%** deb ko'rsatildi, shu sozlama bilan esa **97%** —
~25 punktlik xato, va aynan xavfli yo'nalishda: yo'q bo'lgan bo'shliqlarni
o'ylab chiqaradi, HAQIQIY bo'shliqlarni esa "bu shunchaki artifakt-da"
deb kechirishga asos beradi. `pyproject.toml`ga `pytest-cov` (dev) va
`[tool.coverage.run]` qo'shildi. **CI gate sifatida ataylab ulanmadi** —
chegara (threshold) tanlash siyosat qarori, o'lchovni tuzatish emas
(QOIDA 2).

**Haqiqiy bo'shliq**: `infrastructure/telegram_relay.py` — 73%, holbuki
uning egizagi `outbox_relay.py` — 98%. Sabab aniq: `outbox_relay`da
worker-lifecycle testlari bor (`run_forever`, `main()`ning SIGTERM'da
to'xtashi), men Telegram connector'ini yozganda esa shu naqshni
takrorlamaganman. Beshta test qo'shildi: `run_forever` haqiqiy action'ni
SUCCEEDED'ga olib borishi va `stop_event`da darhol to'xtashi; `main()`ning
real SIGTERM bilan toza chiqishi; malformed payload (chat_id/text yo'q)
→ FAILED, Telegram'ga umuman murojaat qilmasdan; bo'sh (idle) yo'l —
`relay_once` 0 qaytarishi; va `relay_once`ning o'z izohidagi, hech qachon
tekshirilmagan da'vo — "xato bergan entry PEL'da qoladi, jimgina
ACK qilinmaydi". Oxirgisi audit-zanjiri uslubida isbotlandi: kodga
vaqtincha "xato bergan entry'ni ham XACK qil" regressiyasi kiritilib,
test aynan kutilgan xabar bilan (`assert 0 == 1 — a failed entry must
stay in the PEL`) qizardi, keyin qaytarilib yashil ekani ko'rsatildi.
`telegram_relay.py` endi **98%** — egizagi bilan bir darajada; umumiy
qamrov **98%**.

**Nuqson 1 — `db_available` fixture'i toza "skip" va'da qilib, uni
bajarmasdi.** U faqat SQLAlchemy'ning `OperationalError`ini tutardi, lekin
eng keng tarqalgan holat (portda hech narsa tinglamayapti) asyncpg'dan
to'g'ridan-to'g'ri yalang'och `ConnectionRefusedError` sifatida keladi —
SQLAlchemy uni o'rashga ulgurmaydi. Bu haqiqatda kuzatildi (faraz emas):
shu sessiya davomida mahalliy Postgres qulab tushdi va bitta ishga
tushirish fixture'ning o'z maqsadi bo'lgan 128 ta "Postgres'ni ishga
tushiring" skip'i O'RNIGA 128 ta bir xil traceback berdi. Endi `OSError`
ham tutiladi — Postgres'ni haqiqatan to'xtatib tekshirildi: **128 xato →
133 toza skip**. CI'da bu xavfli emas: workflow'ning postgres/redis
service konteynerlari health-check bilan, shuning uchun o'lik DB bilan
pytest umuman boshlanmaydi (ya'ni "hammasi skip bo'lib, CI yashil"
stsenariysi mumkin emas).

**Nuqson 2 — worker-entrypoint testlari o'z jarayoniga signal yuboradi.**
Ikkala worker'ning `main()`i SIGTERM handler'ini `finally`da olib
tashlaydi. Demak `main()` allaqachon chiqib ketgan bo'lsa, testning
`os.kill(os.getpid(), SIGTERM)`i Python'ning STANDART handler'iga tushadi
va pytest jarayonini butunlay o'ldiradi: xato yo'q, chiqish yo'q, ishga
tushirish shunchaki yo'qoladi. Bu yangi Telegram testini Redis
o'chirilgan holda ishga tushirganda topildi (jarayon indamay o'ldi).
Tuzatish ikkala joyda ham — yangi testda VA u ko'chirilgan eski
`test_outbox_relay.py`dagi testda (bir xil nuqson, ikkala nusxa ham;
"buzuq naqshning har bir nusxasini tuzat" tamoyili, `<p>`→`<li>`
holatidagi kabi): umumiy `assert_worker_still_running_before_signaling`
yordamchisi `main()`ni chiqishga majbur qilgan haqiqiy xatoni qayta
ko'taradi (signal yuborilishidan OLDIN), va ikkala test endi
`redis_client` fixture'ini ham oladi — shuning uchun Redis o'chirilganda
ular boshqa har bir Redis-ga bog'liq test kabi toza skip bo'ladi.

**Yo'l-yo'lakay o'zimning kiritgan xatom topildi va tuzatildi**: yangi PEL
testi stream'ga ataylab buzuq entry XADD qiladi, lekin `XACK` faqat
pending ro'yxatini tozalaydi, stream'ning O'ZIDAN o'chirmaydi — natijada
u `test_outbox_relay`ni zaharladi (u stream'ning har bir entry'sini
aylanib, `fields["aggregate_id"]`ni indekslaydi). Fayl yolg'iz
ishga tushirilganda 10 test o'tdi, TO'LIQ suite esa `KeyError` bilan
qizardi — aynan shuning uchun har doim to'liq suite ishga tushiriladi.
Endi `finally` blokida `XDEL` ham qiladi; to'liq suite ketma-ket ikki
marta ishga tushirilib, stream'da hech qanday qoldiq qolmagani
tasdiqlandi (`malformed: 0 of 1001`). Bu E2E spec'larning alohida seed
ishlatishi bilan bir xil dars — umumiy mutable holatni ortda qoldirma.

`.gitignore`ga `.coverage`/`htmlcov/` qo'shildi (yangi artefakt, repo'ga
tushmasligi kerak). 215 test (210 + 5), `ruff`/`mypy` toza, barchasi
real Postgres+Redis'da.

**Eslatma — sandbox muhiti haqida, kod haqida emas**: shu ish davomida
mahalliy Postgres ham, Redis ham qulab tushdi (xotira yetarli edi —
OOM emas, ehtimol sandbox darajasidagi reclaim). Ikkalasi ham qo'lda
qayta ishga tushirildi (`pg_ctlcluster 16 main start` "stale pid file"
bilan — ya'ni toza to'xtamagan, qulagan) va butun suite qayta yashil
ekani tasdiqlandi. Bu kod bazasidagi muammo emas, lekin yuqoridagi
1-nuqsonni aynan shu voqea ochib berdi — o'lik DB bilan suite'ning
xatti-harakati endi to'g'ri (toza skip).

**Coverage o'lchovi darhol o'z qiymatini ko'rsatdi: u ko'rsatgan uchta
qoplanmagan qator FR-AUTH-005/006ning — sessiya muddati tugashini
MAJBURLASH qismining — umuman test qilinmaganini ochib berdi.**
`session_service.resolve_session`dagi ikkita shart:

    if now > record.expires_at:                   # FR-AUTH-005, absolut 12h
    if now - record.last_seen_at > IDLE_TIMEOUT:  # FR-AUTH-006, idle 30m

Ikkala talab ham CLAUDE.md, README.md va shu PR'ning o'z tavsifida
"qurilgan" deb yozilgan ("idle (30m) + absolute (12h) timeout"), lekin
hech qachon bironta test ularni bosib o'tmagan. Mavjud yagona
FR-AUTH-006 testi `last_seen_at`ni YANGILASHni tekshiradi — aynan
teskari yarmi; butun suite'dagi yagona "muddat tugashi" testi esa
Approval uchun (9.2), bu boshqa talab.

**Taxmin qilinmadi, isbotlandi**: ikkala tekshiruvni ham
`resolve_session`dan butunlay o'chirib tashlaganda FAQAT shu ikkita
yangi test qizaradi — qolgan 216 test yashil qoladi. Ya'ni shu paytgacha
sessiya muddati majburlashni butunlay olib tashlash to'liq yashil suite
bergan bo'lardi — xavfsizlikka tegishli talab uchun.

Muddat tugashi kutish bilan emas, timestamp'larni o'tmishga yozish bilan
simulyatsiya qilinadi (12h/30m'dan keyingi haqiqiy holat), va har bir
test IKKINCHI timestamp'ni xavfsiz qiymatga qotiradi — shuning uchun
aniq bitta filial izolyatsiya qilinadi: absolut test `last_seen_at`ni
yangi qoldiradi, idle test `expires_at`ni kelajakda qoldiradi. Ikkalasi
ham real HTTP orqali tekshiradi, demak butun authz zanjirining rad
etishini qamrab oladi, faqat servis funksiyasini emas. `IDLE_TIMEOUT`
test ichida qayta yozilmasdan, sinalayotgan moduldan import qilinadi —
konstantani o'zgartirish testni jimgina ma'nosiz qilib qo'ymasligi uchun.

Uchinchi test — noma'lum sessiya UUID'si: `test_missing_session_is_
rejected` (tasks API) umuman `Authorization` header yubormaydi, shuning
uchun bearer parser uni `resolve_session`ga yetib bormasdan rad etadi —
to'g'ri shakldagi, lekin mavjud bo'lmagan UUID test qilinmagan edi.
O'zimning birinchi qoralamamdagi xato ham tuzatildi: testlar
`{"error": {"code": ...}}` kutgan edi, `api/errors.py`ning enveloper'i
esa tekis (`["code"]`) — buni mavjud 401 testi allaqachon ko'rsatib
turgan edi. `session_service.py`: 92% → **100%**. 218 test.

**Sandbox konteyneri qayta ishga tushirilishi uchun SessionStart hook
qo'shildi — bu shu sessiyada UCH MARTA takrorlangan real muammo edi.**
Remote konteynerda systemd yo'q va u qayta ishga tushiriladi (`uptime`
"up 1 min" ko'rsatdi), shuning uchun Postgres ham, Redis ham
to'xtab qoladi — garchi ularning data directory'si saqlanib qolsa ham.
Bu har qanday repo'da bezovta qiladi, lekin bu loyihada ayniqsa:
QOIDA 1 ("DEMO ≠ PRODUCTION") bo'yicha hech narsa real Postgres(+Redis)
da ishlatilmaguncha tasdiqlangan hisoblanmaydi. Har uchala holatda ham
natija bir xil edi: butun suite yo xato bilan to'xtadi, yo (yuqoridagi
`db_available` tuzatishidan keyin) 130+ skip berdi, va tiklanish qo'lda
`pg_ctlcluster`/`redis-server` chaqirishdan iborat bo'ldi.

`.claude/hooks/session-start.sh` (+ `.claude/settings.json`): ikkala
servisni ishga tushiradi, cluster hech qachon provision qilinmagan
bo'lsa rol/baza/extension'larni yaratadi, migratsiyalarni qo'llaydi,
`doda_app` grant skriptini qayta ishlatadi, backend+frontend
dependency'larini o'rnatadi. Tartib CI bilan bir xil: avval
migratsiyalar (jadvallarni yaratadi), keyin rol skripti (mavjud
jadvallarga huquq beradi).

Muhim nuance: hook `doda`ni NOSUPERUSER holda qoldiradi va
extension'larni `postgres` yaratadi — `CREATE EXTENSION` superuser
talab qiladigan yagona qadam, ADR-005 esa ilova rolining `FORCE ROW
LEVEL SECURITY`ni chetlab o'tolmasligiga tayanadi (aynan shu xato
CLAUDE.md'da yuqorida hujjatlashtirilgan). Ya'ni hook o'zi qulaylik
uchun xavfsizlik qatlamini buzmaydi.

Hook **faqat remote**da ishlaydi (`CLAUDE_CODE_REMOTE` tekshiruvi),
shuning uchun mahalliy mashinadagi `docker compose up -d` oqimiga
tegmaydi. Ataylab **sinxron**: Postgres ko'tarilishidan oldin boshlangan
sessiya aynan shu tuzatilayotgan muammoni qaytadan topadi. Bundan
tashqari `CLAUDE_ENV_FILE` orqali backend venv'ini PATH'ga qo'shadi —
shu sessiyada har bir buyruqda `source .venv/bin/activate` yozish
kerak bo'lgan holat ham shu bilan yopiladi.

Tekshiruv sintetik emas: ikkala servis ham haqiqatan to'xtatilib
(qayta ishga tushirilgan konteynerni simulyatsiya qilib) hook
ishlatildi — ikkalasini ham qaytarib, exit code 0 bilan tugadi; sog'lom
servislarga qarshi qayta ishlatilganda esa toza no-op. Keyin linter,
`mypy` va testlar FAQAT hook eksport qiladigan PATH bilan (qo'lda venv
aktivlashtirmasdan) ishlatildi — 218 test yashil.

**Haqiqiy avtorizatsiya xatosi topildi va tuzatildi — `CustomerRole.AUDITOR`
("faqat o'qish", 10.2) workspace ichida TO'LIQ yozish huquqiga ega edi.**
Coverage o'lchovining qoldiq qoplanmagan qatorlarini ko'rib chiqishda
aniqlandi: `authz_service.py`ning `authorize_propose_action`/
`authorize_create_task` DENY filiallari (113, 140-qatorlar) hech qachon
bajarilmagan. Sababini tekshirganda ma'lum bo'ldi — ular bugungi kunda
strukturaviy jihatdan **yetib bo'lmas**: `WorkspaceRole`da faqat ikki
qiymat bor (`MEMBER`, `WORKSPACE_ADMIN`) va ikkalasi ham ruxsat etilgan
to'plamda. Bu o'z-o'zidan xato emas (izohning o'zi "kelajakdagi uchinchi
rol omission orqali o'tib ketmasligi uchun ataylab aniq tekshiruv" deb
yozadi) — lekin savol tug'dirdi: unda Auditor aslida NIMA bilan
to'xtatiladi?

Javob: hech narsa bilan. `get_workspace_context`ning join'i
`CustomerMembership.role`ni O'QIYDI, lekin uni `_customer_role` deb
tashlab yuborardi — demak `auditor` customer-roliga ega foydalanuvchi
biror workspace'ga a'zo qilinsa, u shu workspace'da to'laqonli
`WorkspaceRole.MEMBER` (yoki `workspace_admin` berilgan bo'lsa —
WORKSPACE_ADMIN) sifatida rezolyutsiya qilinardi. Bu butun kod bazasida
`AUDITOR` tekshiriladigan yagona joy `authorize_view_customer_audit`
bo'lgani uchun (grep bilan tasdiqlandi) — workspace-scoped HAR BIR
`authorize_*` faqat `WorkspaceRole`ga qaraydi — natija: auditor task
yaratishi, action taklif qilishi (R3 `telegram.send_message` ham, AAL2
bilan o'zini-o'zi tasdiqlab!) va workspace kill switch'ini yoqishi
mumkin edi. Bu `domain/security/roles.py`ning o'z da'vosiga
("CustomerRole.AUDITOR has no WorkspaceRole counterpart by design
(auditors are read-only, 2.2)"... "Auditor never can") va 10.2
matritsasining Auditor qatoriga to'g'ridan-to'g'ri zid.

Stsenariy faraziy emas, aynan CustomerOwner tabiiy ravishda qiladigan
ish: tashqi compliance tekshiruvchisiga `auditor` roli beriladi (faqat
o'qish uchun), keyin "shu workspace'ni ko'rsin" deb workspace'ga
qo'shiladi — va owner auditor'ning read-only holati saqlanadi deb
kutadi, aslida esa u jimgina to'liq yozish huquqini oladi.

Avval uchta test yozib xato haqiqiyligi isbotlandi (real HTTP orqali,
uchalasi ham **200** qaytardi: task yaratish, action taklif qilish,
kill switch yoqish). Keyin ADR-005'ning "ikkita mustaqil qatlam"
naqshi bo'yicha tuzatildi:
1. **Majburlash (markazlashtirilgan)** — `get_workspace_context` endi
   allaqachon qo'lidagi `customer_role`dan foydalanadi: auditor bo'lsa
   DENY (10.1 fail-closed). CustomerOwner tuzatishidagi kabi bitta
   joyda hal qilingani uchun barcha `authorize_*` avtomatik to'g'ri
   ishlaydi.
2. **Oldini olish (manbada)** — `add_workspace_member` auditor
   CustomerMembership'ga workspace roli berishni rad etadi (409
   `MEMBERSHIP_INVALID`), shuning uchun a'zolar ro'yxatida "rol
   berilgan"dek ko'rinadigan, aslida huquqsiz qator umuman
   yaratilmaydi.

**Ikkala qatlam ham mustaqil zarur ekani alohida-alohida isbotlandi**
(revert-test-restore): faqat 1-qatlam bilan — uchta majburlash testi
o'tadi, lekin auditor'ni qo'shish hamon 200 qaytaradi (huquqsiz qator
yaratiladi); faqat 2-qatlam bilan — qo'shish rad etiladi, lekin boshqa
yo'l bilan yozilgan qator hamon to'liq yozish huquqini beradi. Eng
muhimi 1-qatlam PASAYTIRISH yo'lini ham qamraydi:
`change_customer_member_role` orqali oddiy a'zo keyinchalik auditor'ga
tushirilsa, u workspace yozish huquqini DARHOL yo'qotadi —
`WorkspaceMembership` qatorini tozalash shart emas (qaytib ko'tarilsa,
huquq ham qaytadi). 2-qatlam buni hech qachon ushlay olmasdi.

**Ataylab nomlangan oqibat**: auditor endi workspace-scoped O'QISHga
ham ega emas. Buni berish uchun haqiqiy, yangi read-only
`WorkspaceRole` va 10.2'ning har bir qatori bo'yicha qaror kerak — bu
change request (QOIDA 2), shu yerda taxmin qilinadigan narsa emas.
Auditor'ning 10.2'da hujjatlashtirilgan huquqi (customer-keng audit
ko'rish, `GET /v1/customers/{id}/audit`) `get_customer_context` orqali
ishlaydi va tegilmadi — tasdiqlangan: butun suite o'zgarishsiz o'tdi.

To'rtinchi test `WorkspaceMembershipError`ning HTTP konverti (409
`MEMBERSHIP_INVALID`) ustidan ham birinchi qoplamani beradi — bu
exception ilgari faqat servis darajasida test qilingan edi.
`conftest.py`ning `seed_workspace_member`iga `customer_role` parametri
qo'shildi (mavjud `workspace_role` bilan bir xil shakl).

222 test, barchasi real Postgres'da.

**Coverage o'lchovi yana uchta haqiqiy bo'shliqni ko'rsatdi (ikkisi test
qamrovi, bittasi test-infratuzilmaning o'zida) — va uchinchisi shu
sessiyada bir necha marta takrorlangan darsning yangi nusxasi bo'lib
chiqdi: umumiy mutable holat.**

1. **`?trace_id=` va `?event_type=` audit filtrlari hech qachon
   bajarilmagan** (`audit_query_service.py` 39/41-qatorlar). Bu
   NFR-OBS-001 uchun muhim: trace-korrelyatsiyaning YOZISH yarmi
   allaqachon testlangan edi (Action HTTP so'rovning o'z trace_id'sini
   oladi), lekin O'QISH yarmi — operator aslida ishlatadigan "shu
   trace_id bilan nima bo'lgan" so'rovi — umuman tekshirilmagan edi,
   ya'ni korrelyatsiya faqat yarim isbotlangan edi. Ikkita test
   qo'shildi (`test_audit_api.py`), ikkalasi ham filtrni o'chirib
   ko'rish bilan tasdiqlandi: `trace_id` filtri o'chirilganda test
   boshqa so'rovning yozuvlarini ko'rib qizaradi, `event_type`
   o'chirilganda esa to'rtta qo'shimcha turni ko'rib qizaradi — ya'ni
   ikkalasi ham haqiqatda filtrlashni tekshiradi, shunchaki "200
   qaytdi"ni emas.
2. **`set_notification_preference`ning YANGILASH filiali hech qachon
   bajarilmagan** (116-117-qatorlar) — har bir mavjud test sozlamani
   faqat BIRINCHI marta yaratardi. Ya'ni frontend taklif qiladigan
   haqiqiy toggle (o'chir → qayta yoq) backend darajasida test
   qilinmagan edi. Yangi test qo'shildi: o'chirib, qayta yoqib, keyin
   HAQIQIY trigger (task'ni DONE'ga o'tkazish) orqali bildirishnoma
   qaytadan kelishini tasdiqlaydi — "qator enabled deb yozilgan, lekin
   `create_notification` hamon to'sib turadi" holatini ham qamrab
   oladi.
3. **Bitta-ID endpointlaridagi per-record tenancy tekshiruvlari
   (`record is None or record.<scope>_id != ctx...`) hech birida
   qoplama yo'q edi** — `api/tasks.py:72`, `api/notifications.py:160`,
   `api/workspace_admin.py:104`, `api/customer_admin.py:96`. Muhim
   nuance (xuddi `parent_task_id` tuzatishidagi kabi): cross-CUSTOMER
   holat allaqachon RLS tomonidan bloklanadi (qator ko'rinmaydi, `is
   None` filiali ishlaydi), lekin RLS faqat `customer_id` bo'yicha —
   BITTA customer ichidagi ikki workspace orasida yagona himoya aynan
   shu aniq `!= workspace_id` solishtiruvi. Yangi
   `test_cross_workspace_record_access.py` (4 test) shu holatni
   qamraydi: qo'shni workspace'ning task'ini o'qish (404) va uning
   statusini o'zgartirish (404 + task haqiqatda TODO'da qolishi),
   qo'shni workspace'ning a'zoligini PATCH/DELETE qilish (404), va
   bitta workspace ICHIDA boshqa a'zoning bildirishnomasini o'qildi
   deb belgilash (404 — `recipient_id` tekshiruvi). Oxirgisi ataylab
   ikkala foydalanuvchini ham BIR XIL workspace'ga a'zo qiladi, aks
   holda authz zanjiri so'rovni per-record tekshiruvga yetib
   bormasdanoq rad etardi va test noto'g'ri qatlamni isbotlagan
   bo'lardi.

**Shu yangi testlar uchta test-infratuzilma xatosini ochib berdi —
uchalasi ham bir xil sinf: `relay_once` outbox'ni PLATFORM-KENG
o'qiydi (`outbox_messages` ataylab RLS'dan ozod, ADR-003), demak u
boshqa HAR QANDAY test qoldirgan pending qatorlarni ham oladi.** Yangi
testlar (action taklif qiladigan) bir nechta pending qator qoldirdi va
uchta relay testi shu tufayli qizardi. "Flake" deb o'tkazib
yuborilmadi — uchalasi ham qo'lda, ataylab pending qator yaratadigan
skript bilan aniq reproduktsiya qilindi:
- `test_two_concurrent_relay_workers...` — `assert sum(counts) == 10`
  global hisobga tayanadi: 3 ta qoldiq qator bilan `assert 13 == 10`
  bo'lib qizardi.
- `test_relay_once_returns_zero_when_nothing_new_is_pending`
  (telegram) — bitta `relay_once` bilan "drain" qilardi, lekin u bir
  martada ko'pi bilan 50 yozuv oladi: 60 yozuvli backlog bilan
  `assert 10 == 0` bo'lib qizardi.
- `test_relay_publishes_ready_action_to_its_event_stream` — 120
  yozuvli backlog bilan o'zining action'i birinchi batch'dan
  tashqarida qolib qizardi.

Uchalasi ham bitta naqsh bilan tuzatildi — bitta chaqiruv emas, SIKL
bilan to'liq drain (`test_outbox_relay.py`da umumiy
`_relay_until_drained` yordamchisiga chiqarildi, telegram faylida
mahalliy `while` sikli). Bu E2E spec'larning alohida seed ishlatishi
va PEL probe yozuvining `XDEL` qilinishi bilan bir xil dars: umumiy
mutable holat ustida aniq son bo'yicha assertion qilma. Tuzatish
haqiqiyligi: butun suite ketma-ket ikki marta, har safar ataylab 150
ta pending outbox qatori yaratilgandan KEYIN ishga tushirilib, yashil
ekani tasdiqlandi (keyin backlog'siz uchinchi marta ham).

229 test, barchasi real Postgres+Redis'da.

**Auditor tuzatishining davomi — ro'yxat va ruxsat bir-biriga mos kelishi
kerak.** `get_workspace_context` auditor'ni DENY qilgandan keyin yangi
nomuvofiqlik paydo bo'ldi: `list_my_workspaces` (demak `GET
/v1/me/workspaces`) workspace'larni to'g'ridan-to'g'ri
`WorkspaceMembership` orqali ro'yxatlaydi, `get_workspace_context` orqali
emas — demak **pasaytirish** yo'lida (oddiy a'zo keyinchalik auditor'ga
o'tkazilsa, `WorkspaceMembership` qatori joyida qoladi) klient
ro'yxatda workspace'ni ko'rardi, lekin uni ochishga har bir urinish 403
qaytarardi. `add_workspace_member` yangi bunday juftlikni yaratishga
yo'l qo'ymaydi, lekin pasaytirish qoldirgan qatorni u hech qachon
ushlay olmaydi — shuning uchun bu aniq, alohida `continue` bilan
o'tkazib yuborilishi kerak edi, "bunday qator yo'q" deb taxmin qilish
bilan emas.

Bu ishda **o'zimning birinchi testim bo'sh (vacuous) ekani topildi va
tuzatildi** — tuzatishni vaqtincha olib tashlaganda test baribir
yashil qoldi. Sababi muhim va o'rganarli: `conftest.py`ning
`seed_workspace_member`i Customer/CustomerMembership qatorlarini
to'g'ridan-to'g'ri yozadi, `customer_service` orqali emas — demak
`UserCustomerIndex`ga hech narsa yozilmaydi, `list_my_workspaces` esa
aynan shu bootstrap jadvaldan boshlaydi. Ya'ni shu seed bilan
yaratilgan HAR QANDAY foydalanuvchi uchun `/v1/me/workspaces` baribir
`[]` qaytaradi, roli qanday bo'lishidan qat'i nazar. Test haqiqiy
stsenariyga qayta yozildi: `create_customer_with_owner` +
`invite_customer_member` + `add_workspace_member` orqali haqiqiy
a'zo yaratiladi, ro'yxatda ko'rinishi tasdiqlanadi, keyin
`change_customer_member_role` bilan auditor'ga pasaytiriladi va
ro'yxat bo'shab qolishi (VA workspace'ning haqiqatda 403 bilan
yopilishi — faqat yashirilmasligi) tekshiriladi. Endi tuzatishni olib
tashlaganda test aynan kutilgan tarzda qizaradi.

**Halol qolgan cheklov (bu o'zgarish keltirgan emas, lekin endi
ko'rinadigan)**: auditor uchun `GET /v1/me/workspaces` bo'sh bo'lgani
uchun frontend'da uning o'z huquqiga (customer-keng audit ko'rish,
`/customers/{id}`) navigatsiya havolasi yo'q — workspace'lar ro'yxati
customer nomini faqat workspace qatori orqali ko'rsatadi. Bu
bo'shliq auditor'ning workspace a'zoligi BO'LMAGAN holatida ham
avvaldan mavjud edi (endpoint workspace-shaped), shuning uchun yangi
emas; to'g'ri yechim `export_service` duch kelgan xuddi shu masalaning
yechimi bo'ladi — customer qamrovini `UserCustomerIndex`dan olish —
lekin bu endpoint shaklini o'zgartiradi (yangi "customers" o'lchovi),
ya'ni change request (QOIDA 2), shu yerda jimgina qilinadigan narsa
emas.

230 test, barchasi real Postgres'da.

**Coverage 98% → 99% (10 qator qoldi) — va bu raund uchta haqiqiy narsani
ochdi: ikkita hech qachon ishlatilmagan filtr, bitta hech qachon
chaqirilmagan endpoint, va bitta haqiqiy o'lik kod.** Hammasi testlar
(kod xulqi o'zgarmadi), bitta o'chirishdan tashqari:

- **`GET /v1/workspaces/{id}/actions/{action_id}` da bironta test yo'q
  edi — baxtli yo'li ham.** Endi ikkala yarmi ham bor: o'z workspace'idan
  o'qilishi, qo'shni workspace'dan 404.
- **`POST .../approvals/{id}/consume`ning IKKINCHI tekshiruvi
  (`action.workspace_id != ctx...`) — 9.2'ning bir martalik nonce'ini
  himoya qiladigan qator — test qilinmagan edi.** Bu ayniqsa muhim,
  chunki Approval qatorining O'ZI `customer_id` tekshiruvidan o'tadi
  (bir xil customer!), demak qo'shni workspace'ning approval'ini
  sarflashdan to'sadigan yagona narsa aynan shu ikkinchi tekshiruv.
  Isbotlandi: tekshiruv olib tashlanganda AAL2 sessiyali workspace A
  admini workspace B ning approval'ini **haqiqatda 200 bilan sarflab
  yubordi**. Test ataylab A'ga AAL2 beradi — aks holda step-up
  tekshiruvi birinchi ishga tushib, assertion noto'g'ri sababdan
  o'tgan bo'lardi (bu birinchi urinishda aynan shunday bo'ldi: 403
  qaytdi, ya'ni step-up ushladi, workspace guard emas).
- **`?unread_only=true`** (ikkala bildirishnoma ro'yxatida ham bor)
  hech qachon bajarilmagan edi — filtrni no-op qilib ko'rish bilan
  test haqiqatda filtrlashni tekshirishi tasdiqlandi.
- **Hujjatlashtirilgan xato konvertlari birinchi marta HTTP orqali
  tekshirildi**: 409 `ALREADY_MEMBER` (customer va workspace
  darajasidagi duplikat a'zolik — CLAUDE.md bu mappingni ancha oldin
  da'vo qilgan, lekin u hech qachon ishga tushmagan edi), 409
  `APPROVAL_INVALID`ning "allaqachon sarflangan" yarmi (avval faqat
  "nonce mos kelmadi" yarmi qamrab olingan edi — 9.2 uchun muhimi
  aynan birinchisi), `MEMBERSHIP_INVALID` (auditor tuzatishi bilan).
- **Umumiy input chegaralari** (`test_request_edge_cases.py`): buzuq
  bearer token (401, 500 emas), noma'lum workspace id (403 DENY — 404
  emas, 10.1: mavjudlikni oshkor qilmaslik), UUID bo'lmagan
  `X-Trace-Id` (almashtiriladi, rad etilmaydi — `TraceIdMiddleware`ning
  o'z va'dasi).

**O'lik kod o'chirildi**: `db.get_session()` — butun kod bazasida
**bironta chaqiruvchisi yo'q** (grep bilan tasdiqlandi). Bundan
tashqari u allaqachon bir marta tuzoq bo'lgan (shu faylda yuqorida
yozilgan: `@asynccontextmanager` bezagisiz bo'lgani uchun `async with
get_session()` `TypeError` beradi) VA u kod bazasidagi yagona
tenant-scoped BO'LMAGAN sessiya yordamchisi edi — ya'ni mavjudligining
o'zi NFR-ISO-002'ni chetlab o'tishga taklif qilardi. O'chirildi,
`ruff`/`mypy`/242 test bilan tasdiqlandi.

**Qolgan 10 qator ataylab qoldirildi, har biri aniq sababi bilan** —
"qamrovni 100% qilish" uchun sun'iy test yozilmadi:
- `authz_service.py` 135/162 — `authorize_propose_action`/
  `authorize_create_task`ning DENY filiallari bugun **strukturaviy
  jihatdan yetib bo'lmas**: `WorkspaceRole`da faqat ikki qiymat bor va
  ikkalasi ham ruxsat etilgan. Ataylab shunday yozilgan (izohi: uchinchi
  rol qo'shilsa omission orqali o'tib ketmasligi uchun).
- `errors.py:80` (`InvalidActionTransition`) va `action_service.py:234`
  (`request_approval` AWAITING_APPROVAL bo'lmagan action uchun) — ikkalasi
  ham ichki invariant, HTTP chaqiruvchisi bu holatni yarata olmaydi.
- `workspace_service.py:68` (cross-customer CustomerMembership) — HTTP
  orqali yetib bo'lmaydi, chunki boshqa customer'ning qatori
  tenant-scoped sessiyada RLS tufayli umuman ko'rinmaydi (404 avval
  qaytadi). Ya'ni bu qator RLS allaqachon to'sadigan holat uchun
  ikkinchi himoya qatlami — o'z maqsadini bajarib, hech qachon
  ishlamasligi to'g'ri.
- `export_service.py:75` (bir workspace ikki marta chiqmasligi uchun
  dedupe) — 0012-migratsiyaning unique constraint'i
  `(customer_membership_id, workspace_id)`ni kafolatlaganidan keyin bu
  amalda erishilmas bo'lib qoldi. O'chirilmadi (constraint'dan
  mustaqil, arzon himoya), lekin shu yerda qayd etildi.
- `audit_service.py:124` — `prev_hash_mismatch` (zanjir bog'lanishi
  uzilishi). `hash_mismatch` yarmi testlangan; buni qamrash uchun
  ataylab soxta zanjir halqasi yasash kerak.
- Relay fayllarining `if __name__ == "__main__"` qatorlari va
  `telegram_relay.py:90` (BUSYGROUP bo'lmagan Redis xatosini qayta
  ko'tarish).

242 test, barchasi real Postgres+Redis'da, qamrov 99%.

**`GET /v1/me/customers` qurildi — auditor tuzatishi ochib bergan
navigatsiya bo'shlig'ini yopadi, va u bo'shliq auditor'dan kengroq edi.**
Yuqoridagi yozuvda bu "change request" deb qoldirilgan edi, chunki
`/v1/me/workspaces`ning SHAKLINI o'zgartirish kerak deb hisoblagandim.
Qaytib ko'rib chiqqanda aniqlandi: shaklni o'zgartirish shart emas —
kerak bo'lgani `/v1/me/workspaces` bilan yonma-yon turadigan yangi,
buzmaydigan (non-breaking) customer-scoped juftlik, aynan
`export_service`ning o'zi allaqachon qo'llagan naqsh bilan
(`UserCustomerIndex`dan customer qamrovini olish). Shuning uchun
endpoint shakli o'zgarmaydi, hech qanday mavjud klient buzilmaydi, va
bu endi "mahsulot qarori" emas, mavjud naqshning takrori.

Bo'shliq faqat auditor haqida emas: `list_my_workspaces`
**workspace-shaped** bo'lgani uchun (a) workspace'i yo'q (yoki hammasi
arxivlangan) customer'ning CustomerOwner'i ham, (b) hech qanday
workspace roliga ega bo'lmagan har qanday a'zo ham hech narsa
ko'rmaydi — holbuki ikkalasi ham customer-darajasidagi endpointlarni
(FR-AUD-002 audit ko'rish, FR-NTF-004 sozlamalar, FR-CTL-003 kill
switch, FR-WKS-006 arxivlangan workspace'larni tiklash) chaqirishga
to'liq huquqli. Bu aynan `export_service.export_my_data` yozilganda
topilgan va u yerda mahalliy tarzda chetlab o'tilgan muammoning
o'zi — endi HTTP orqali umumiy tarzda yopildi, har bir chaqiruvchi
uni qaytadan kashf qilmasligi uchun.

`customer_service.list_my_customers` (+ `MyCustomerEntry`) —
`list_my_workspaces` bilan bir xil tuzilma: RLS'siz bootstrap
index'dan customer'lar, keyin har biri uchun tenant-scoped sessiyada
aniq `customer_id` predikati bilan nom+rol. Eskirgan index qatori
(bo'lmasligi kerak, lekin index — mirror, authority emas) a'zolik
sifatida qaytarilmasdan o'tkazib yuboriladi. 3 ta yangi test
(`test_me_api.py`): workspace'i yo'q customer'ning owner'i ko'rinishi,
auditor o'z ROLI bilan ko'rinishi (workspace roli emas), va
customer'dan chiqarilgan foydalanuvchiga endi ko'rinmasligi
(`remove_customer_member`ning index tozalashiga bog'liq).

Frontend: `/workspaces` sahifasiga "Customer'larim" bo'limi qo'shildi
(faqat bo'sh bo'lmaganda ko'rsatiladi), har bir qator
`/customers/{id}`ga havola + rol belgisi.

**Bu o'zgarish mavjud E2E spec'ini HAQIQATDA buzdi va shu suite
tomonidan ushlandi** — `customer.spec.ts` customer sahifasiga
`page.getByText("Demo Customer").click()` bilan o'tardi, endi esa bu
nom ikki joyda (workspace qatorining customer havolasi va yangi
bo'lim) ko'rinadi, demak strict-mode ambiguity. Bu aynan
CLAUDE.md'da allaqachon yozilgan `getByText("AWAITING_APPROVAL")`
darsining takrori. Spec yangi bo'limga scope qilib tuzatildi — bu
bir vaqtda semantik jihatdan ham to'g'ri yo'l, chunki workspace
roliga ega bo'lmagan foydalanuvchi uchun yuqoridagi qator umuman
mavjud emas.

Tekshiruv: 245 test real Postgres'da; `ruff`/`mypy` toza; frontend
ESLint/`tsc`/production build toza; barcha 6 E2E spec haqiqiy
backend+frontend'ga (`next build && next start`) qarshi qayta ishga
tushirildi va yashil — jumladan accessibility skaneri, ya'ni yangi
bo'lim hech qanday serious/critical WCAG buzilishi keltirmadi.

**Auditor oqimi HAQIQIY brauzerda, haqiqiy auditor sessiyasi bilan tekshirildi
— va bu bitta haqiqiy qoldiq nuqsonni topdi.** Yangi `GET /v1/me/customers`
auditor'ga yo'l berdi, lekin customer sahifasining o'z sarlavhasi (`h1`)
customer nomini `listMyWorkspaces`dan izlardi — aynan shu foydalanuvchi
uchun bo'sh ro'yxat, demak sahifa o'zini shunchaki "Customer" deb
nomlardi. `listMyCustomers`ga o'tkazildi (sahifa allaqachon customer_id
ustida turgani uchun boshqa hech narsa o'zgarmadi).

Brauzer tekshiruvida yana ikkita narsa aniqlandi, ikkalasi ham **kod
xatosi emas**, lekin yozib qo'yishga arziydi:
1. Mening birinchi tekshiruv skriptim sarlavhani "Customer" deb ko'rdi
   va audit ro'yxatini bo'sh deb topdi — bu skriptning o'z poygasi edi
   (bosgandan keyin darhol o'qidi, fetch tugamasdan). Network trace
   bilan tekshirilganda HAR BIR so'rov 200 qaytargani va sarlavha
   haqiqatda "Demo Customer" bo'lgani ko'rsatildi. "Isbotlamasdan taxmin
   qilma" — xulosani skriptning birinchi natijasiga tayanib chiqarmaslik.
2. `127.0.0.1:3000` orqali kirganda login umuman ishlamadi — sababi
   CORS: backend'ning ruxsat ro'yxati aniq (`http://localhost:3000`) va
   ataylab wildcard EMAS (har bir so'rov bearer token olib yuradi). Bu
   himoyaning haqiqatda ishlayotganining tasdiqi, nosozlik emas.

Auditor uchun sahifada bitta 403 bor (`.../workspaces/archived`,
CustomerOwner-only) — sahifa uni jimgina yutadi, bu butun ilova bo'ylab
qabul qilingan "rol asosida UI-gating yo'q, backend 403 qaytaradi"
konventsiyasining o'zi (`simplify` ko'rib chiqishi aynan shu chaqiruvni
"tuzatmaslik" deb qaror qilgan edi). Yangi spec shuning uchun console'ni
"403 dan boshqa hech qanday xato yo'q" deb tekshiradi, ko'r-ko'rona
"nol xato" deb emas.

Yangi `e2e/auditor.spec.ts` (o'z seed prefiksi bilan, `E2E_AUDITOR_`) shu
oqimni doimiy qiladi: auditor kira oladi, workspace ro'yxati BO'SH
(`a[href^='/workspaces/']` = 0), "Customer'larim" bo'limida customer'i
roli bilan ko'rinadi, customer sahifasi TO'G'RI nom bilan ochiladi va
unda audit ro'yxati bor, VA workspace'ning o'zi backend darajasida
(sahifa fetch'i orqali emas, to'g'ridan-to'g'ri) 403/`DENY` qaytaradi.
`seed_e2e_demo.py` endi har bir seed'da haqiqiy auditor a'zo + sessiya
ham yaratadi (`*_AUDITOR_SESSION_ID`), ataylab `WorkspaceMembership`siz
— `add_workspace_member` endi bunday juftlikni rad etadi.

Barcha 7 E2E spec (workspace, customer, archive, kill-switch, logout,
accessibility, auditor) real backend+frontend'ga (production build)
qarshi yashil; CI'ning seed qadamiga yangi prefiks qo'shildi.
