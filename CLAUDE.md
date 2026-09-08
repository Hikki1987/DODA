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
