# DODA

Shaxsiy AI operatsion tizimi (Personal AI Operating System). To'liq talab va
arxitektura: [`docs/DODA-TRD-v2.0.docx`](docs/DODA-TRD-v2.0.docx)
(DODA-TRD-002, v2.0). Coding agent uchun kundalik kontekst: [`CLAUDE.md`](CLAUDE.md).

## Holat

Bosqich **0 — Foundation** yakunlandi: config, DB (PostgreSQL + pgvector,
RLS tenant izolyatsiyasi bilan), Redis, object storage, Identity/Customer/
Workspace/Audit domen skeleti.

Bosqich **1 — S1** (17.2-bo'lim) yakunlandi: Task/Action/Approval domen
skeleti, action execution state machine (4.2), risk-based approval routing
(9.1), approval invariantlari (9.2), idempotentlik (FR-ACT-004) va
transactional outbox (FR-ACT-008, ADR-003) — Redis Stream'ga relay bilan.

Bosqich **S2** yakunlandi: 10-bo'limdagi authoritative authz zanjiri
(Session → Workspace Membership → RBAC → Step-Up) va shu zanjir orqali
himoyalangan HTTP API (`/v1/workspaces/{id}/actions`, `.../approvals/{id}/consume`,
`.../tasks`, `.../tasks/{id}/status`, `.../tasks/{id}/history`,
`.../members`, `.../archive`, `.../restore`, `.../kill-switch/engage`,
`.../kill-switch/disengage`, `.../audit`, `.../notifications`,
`/v1/sessions`, va customer-darajasida `/v1/customers/{id}/kill-switch/...`,
`/v1/customers/{id}/audit`, `/v1/customers/{id}/members` (invite/rol
o'zgartirish/chiqarish, faqat CustomerOwner — FR-WKS-005),
`/v1/customers/{id}/notifications` (customer ostidagi barcha
workspace'lardagi bildirishnomalar bitta joydan),
`/v1/customers/{id}/notification-preferences[/{type}]` (FR-NTF-004:
SECURITY_ALERT'dan tashqari har bir turni yoqish/o'chirish), va
session-scoped `/v1/me/workspaces` — login'dan keyin klient chaqiradigan
birinchi endpoint, foydalanuvchi a'zo bo'lgan barcha customer/workspace'larni
qaytaradi (avval bunday "kashfiyot" endpointi umuman yo'q edi). Uning
customer-scoped juftligi `GET /v1/me/customers` ham bor — `/v1/me/workspaces`
workspace-shaped bo'lgani uchun workspace'i yo'q customer'ni (yoki hech
qanday workspace roliga ega bo'lmagan a'zoni, masalan auditor'ni) umuman
ko'rsatmaydi, shuning uchun customer-darajasidagi endpointlarga (audit
ko'rish, bildirishnoma sozlamalari, kill switch, arxivlangan workspace'lar)
yetib borish uchun alohida kerak. `GET
/v1/workspaces/{id}/tasks` va `.../actions` (ro'yxatlash, `?status=` filtri
bilan) ham qo'shildi — avval faqat yaratish va ID bo'yicha o'qish bor edi.
`GET /v1/workspaces/{id}/members` va `GET /v1/customers/{id}/members`
(joriy a'zolar ro'yxati — display_name bilan; avval faqat qo'shish/
o'zgartirish/chiqarish bor edi, ko'rish yo'q edi),
`GET .../kill-switch` (joriy holatni ko'rish — avval faqat engage/disengage
bor edi). Audit hash-zanjiri endi concurrent yozuvlarda
ham xavfsiz (FR-AUD-004, per-customer lock); sessiya faollik-belgisi
(FR-AUTH-006 idle timeout) endi haqiqatda saqlanadi (avval jimgina
saqlanmasdi — tuzatildi).

Butun PR ustida xavfsizlik ko'rib chiqish o'tkazildi (tafsilot CLAUDE.md'da):
ikkita haqiqiy tenant-izolyatsiya xatosi topildi va tuzatildi — Action
idempotency-key workspace bo'ylab kesishishi (bir xil customer ostidagi
ikkita workspace bir xil kalitni ishlatsa, biri ikkinchisining action
payload'i va approval nonce'ini ko'rar edi) va `parent_task_id` orqali
tenant-lararo mavjudlik oracle'i.

Bosqich **S3 (qisman)** boshlandi: `frontend/` — Next.js + TypeScript web
qobig'i (login, workspace tanlash, task/bildirishnoma/a'zolar/kill-switch
ekranlari), backend'ning real, testlangan endpointlariga ulangan. Haqiqiy
OIDC hali yo'q (FR-AUTH-001), shuning uchun login sahifasi `session_
service`ning dev/test seam'idan foydalanadi — bu aniq belgilangan. Knowledge/RAG ekrani hamon qurilmagan, chunki backend'da ham u yo'q
("DEMO ≠ PRODUCTION" qoidasi: mavjud bo'lmagan backend uchun soxta UI
qurilmaydi). Chat (FR-CONV) uchun bu holat keyinroq o'zgardi — pastga
qarang: backend to'liq qurildi va endi frontend chat UI'si ham bor
(`/workspaces/[id]/chat`). To'liq end-to-end oqim (login → workspace →
bildirishnoma → task yaratish/holat o'zgartirish → o'qildi belgilash →
a'zolar) real backend'ga qarshi Playwright orqali browser'da qo'lda
tasdiqlandi, faqat `npm run build` bilan emas.

Workspace sahifasiga Action'lar bo'limi ham qo'shildi (`GET
/v1/workspaces/{id}/actions` — allaqachon qurilgan va testlangan
endpoint edi, lekin frontend'da hech qayerda ko'rsatilmagan edi). Ataylab
faqat o'qish uchun (tafsilot `frontend/README.md`da): propose/approve
formalari hali yo'q, chunki (1) haqiqiy tool/connector yo'q, (2) approval
nonce'i faqat propose javobida bir marta qaytariladi, ro'yxatlashda emas.
Xuddi shu naqshda audit ko'rinishi ham qo'shildi (`GET
/v1/workspaces/{id}/audit`, FR-AUD-002 — allaqachon qurilgan/testlangan,
frontend'da ko'rinmas edi): workspace sahifasiga event_type/actor/vaqt
ro'yxati.

A'zolar ro'yxatiga mavjud a'zoning rolini almashtirish (member ↔
workspace_admin) va uni workspace'dan chiqarish tugmalari qo'shildi
(`PATCH`/`DELETE /v1/workspaces/{id}/members/{membership_id}` —
FR-WKS-003, allaqachon qurilgan/testlangan). Yangi a'zo qo'shish
qo'shilmadi (tafsilot `frontend/README.md`da — `customer_membership_id`
tanlash uchun customer_id kerak, workspace sahifasida yo'q).

Yangi `/customers/[id]` sahifasi qo'shildi — `/workspaces` ro'yxatidagi
customer nomiga bosilganda ochiladi. Bu workspace_id o'rniga customer_id
talab qiladigan hamma narsani (audit, bildirishnoma sozlamalari, customer
darajasidagi kill switch, va — workspace-darajasidan farqli — a'zo
**qo'shish** ham) bir joyga jamladi (tafsilot `frontend/README.md`da).

Task ro'yxatidagi har bir qatorga "Tarix" tugmasi qo'shildi —
`GET .../tasks/{id}/history` (FR-TASK-007) endi frontend'da ham ko'rinadi,
bosilganda status o'tishlarini (`from → to`, kim, qachon) ko'rsatadi.

`/sessions` sahifasi ham qo'shildi (`GET`/`DELETE /v1/sessions` —
FR-CTL-001/002, allaqachon qurilgan/testlangan): foydalanuvchi darajasidagi
(workspace'ga bog'liq emas) faol sessiyalar ro'yxati, joriysi belgilangan
holda, va boshqa qurilmadagi sessiyani uzoqdan yopish tugmasi.

Real backend'ga (native Postgres 16 + pgvector, Redis, `doda_app`
huquqi cheklangan rol) qarshi to'liq qayta tekshirildi: 163 test (avvalgi
150'dan ko'p — bu orada boshqa ishlar ham qo'shilgan edi), so'ng haqiqiy
seed qilingan R3 action bilan Playwright orqali browser'da — action
"send_email / risk: R3 / AWAITING_APPROVAL", audit'da
"workspace.created.v1", va ikkita sessiyadan birini uzoqdan yopib
(server tomonda `GET /v1/sessions` orqali haqiqatda yo'qolgani `curl`
bilan alohida tasdiqlangan) faqat joriysi qolishi, real ikkinchi
a'zoni workspace'ga qo'shib, uni workspace_admin'ga ko'tarib, keyin
chiqarib, va yangi `/customers/[id]` sahifasida real a'zo qo'shib/rolini
o'zgartirib/chiqarib, bildirishnoma sozlamasini o'chirib/yoqib, kill
switch'ni yoqib/o'chirib, hammasi audit'da to'g'ri ko'rinishini
tasdiqlab — barchasi ekranda to'g'ri ko'rinishi tasdiqlandi, konsol
xatosiz.

Shu paytgacha yuqoridagi barcha Playwright tekshiruvlari qo'lda, throwaway
scratchpad skriptlar bilan qilingan edi — hech biri repo'ga kirmagan,
hech qanday kelajakdagi o'zgarish ularni qayta ishga tushirmagan bo'lardi.
Bu haqiqiy bo'shliq edi: "DEMO ≠ PRODUCTION" qoidasi testlarsiz modul
CLOSED bo'lishini taqiqlaydi, lekin frontend'ning o'z acceptance testi
umuman yo'q edi. Endi `frontend/e2e/` (Playwright, `@playwright/test`)
va `backend/scripts/seed_e2e_demo.py` bor — real Postgres+Redis+backend+
frontend (production build) ustida ishlaydigan, commit qilingan, CI'da
avtomatik ishga tushadigan ikkita spec (`workspace.spec.ts`,
`customer.spec.ts`), bugungacha qo'lda tekshirilgan HAR BIR oqimni
qamrab oladi. Tafsilot `frontend/README.md`da.

Bosqich **S3/S4 davomida** (163 testdan beri) yana bir qator ish
qilindi — to'liq tafsilot CLAUDE.md'da, bu yerda faqat xulosa: workspace
archive/restore va workspace-darajasidagi kill switch engage/disengage
frontend'ga ulandi (avval faqat customer sahifasida bor edi);
`GET /v1/me/export` (FR-CTL-002) `/sessions` sahifasiga ulandi; "Chiqish"
tugmasi haqiqatda serverda sessiyani revoke qilmasligi (faqat
localStorage'ni tozalashi) aniqlanib tuzatildi. To'rt ta yangi, mustaqil
E2E spec qo'shildi (archive, workspace-kill-switch, logout, accessibility
— jami 6 ta), shu jumladan `@axe-core/playwright` orqali WCAG 2.2 AA
avtomatik tekshiruvi (2 ta real buzilish topilib tuzatildi). Observability
qatlami haqiqatda ishlaydigan qilindi — tracing avval jimgina yo'qolib
ketardi, endi eksport qilinadi; Prometheus `/metrics` qo'shildi;
action↔HTTP trace_id korrelyatsiyasi (NFR-OBS-001) 0%'dan 100%'ga
tuzatildi.

Butun `application/` qatlami bo'ylab tizimli TOCTOU (check-then-act race
condition) qidiruvi o'tkazildi — 5 ta haqiqiy concurrency xatosi topildi
va tuzatildi (task status/approval nonce ikki marta bajarilishi, kill
switch engage race'i, customer "oxirgi Owner" invarianti nolga tushib
qolishi mumkinligi, bildirishnoma sozlamasi race'i), har biri real
Postgres'ga qarshi majburlangan interleaving bilan isbotlangan. Yana
ikkita `security-review` o'tkazildi (jami 3 ta) — real xatolar topilib
tuzatilgan (workspace bo'ylab Action idempotency-key kesishishi,
`parent_task_id` orqali tenant-lararo mavjudlik oracle'i — birinchi
o'tkazishda). Butun TRD bo'yicha talab-traceability auditi o'tkazildi
(121 ID, `docs/risk-register.md`ning kelib chiqishi) va FR-AUD-003
(audit yozuvlarida sezgir kontent bo'lmasligini statik tekshiradigan
CI redaction scanner) qurildi.

Keyinroq Product Owner uchta haqiqiy qaror qabul qildi (`docs/
open-decisions.md`): **OD-002 (birinchi konnektor) — Telegram**
(shu bilan `domain/action/tool_policy.py` — `tool_name` → minimal
`risk_level` siyosati — qurildi, `telegram.send_message` uchun R3);
**OD-004 (o'zbek tilidagi ovoz) — kerak** (STT/TTS provayder tanlovi
hali ochiq); **OD-001 (SaaS) qayta tasdiqlandi** (shaxsiy foydalanish +
kelajakda boshqalarga taqdim etish). To'rtinchi `security-review` ham
o'tkazildi — bu safar butun PR diff'iga (barcha 186 fayl) qarshi, 0
topilma bilan. `config.py`ga CORS wildcard'ni rad etuvchi pydantic
validator (NFR-SEC-001) qo'shildi, va CI'da haqiqiy infratuzilma xatosi
(Google'ning o'z Chrome apt repo'sidagi doimiy buzilish E2E job'ini
ikki marta qulatgan edi) diagnostika qilinib to'g'ri tuzatildi
(apt manbani butunlay chetlab o'tish, vaqtinchalik retry emas).

Product Owner Telegram bot tokenini xavfsiz kanal (environment
variable) orqali taqdim etgach, **OD-002'ning haqiqiy connector qismi
qurildi**: `infrastructure/telegram_client.py` (Bot API `sendMessage`
klienti, token URL yo'lida yurilgani uchun hech qanday xato yo'lida
sizib chiqmaydi) va `infrastructure/telegram_relay.py` (outbox
relay'ning Redis Stream'idagi `action.ready.v1` xabarlarini o'qib,
`telegram.send_message` action'larini `apply_transition` orqali
READY→RUNNING→SUCCEEDED/FAILED'gacha olib boradigan, ikki qatlamli
idempotentlikka ega consumer). Bu `outbox_relay.py`ning "connector hali
yo'q" degan eski holatini birinchi marta yopadi. Halol chegara: bu
muhitda haqiqiy Telegram bot token/chat mavjud emas, shuning uchun
Telegram'ning o'z API'siga haqiqiy HTTP chaqiruvi hech qachon real
xizmatga qarshi ishga tushirilmagan — faqat outbox→Stream→consumer→DB
pipeline'i real Postgres+Redis'ga qarshi isbotlangan, Telegram HTTP
qismi test double bilan. Credential broker (9.3) hamon qurilmagan —
bot tokeni hozircha to'g'ridan-to'g'ri `Settings`dan o'qiladi.

**210 test, barchasi real Postgres(+Redis)'da; 6 E2E spec, barchasi CI'da
avtomatik; 4 marta security-review o'tkazilgan.**

Shu nuqtadan keyin (to'liq tafsilot `CLAUDE.md`da): test qamrovi birinchi
marta o'lchandi (99%, `concurrency = ["thread","greenlet"]` sozlamasi
majburiy — aks holda FastAPI handler'lari yolg'on "qoplanmagan" ko'rinadi)
va o'lchov o'zi bir nechta haqiqiy bo'shliqni ochdi, eng muhimi —
**`CustomerRole.AUDITOR` workspace ichida to'liq yozish huquqiga ega edi**,
garchi 10.2 va kod izohlari uni uch joyda "faqat o'qish" deb
hujjatlashtirsa ham. Ikkita mustaqil qatlam bilan tuzatildi
(`get_workspace_context`da markazlashtirilgan DENY + `add_workspace_member`da
manbada oldini olish), har ikkalasi alohida zarur ekani isbotlandi.
Shu tuzatish navigatsiya bo'shlig'ini ochdi (`GET /v1/me/workspaces`
workspace-shaped bo'lgani uchun auditor/workspace'siz customer owner'i
hech narsa ko'rmaydi) — `GET /v1/me/customers` bilan yopildi, frontend'da
"Customer'larim" bo'limi va auditor'ning butun oqimini real brauzerda,
haqiqiy auditor sessiyasi bilan tasdiqlaydigan `e2e/auditor.spec.ts` bilan.

Bundan tashqari 6.2-bo'limning "har tashqi side effect outbox orqali
o'tadi" qoidasi, audit jurnalining append-only trigger'i, bootstrap
(RLS'siz) jadvallarning yozish-ro'yxati va approval nonce'ining bir
martalik ko'rsatilishi — avval faqat matnda bo'lgan to'rtta xavfsizlik
xususiyati endi CI tomonidan statik/integration test bilan majburlanadi.

Shundan keyin `Settings`ning har bir xom credential olib yuruvchi maydoni
(`database_url`, `migration_database_url`, `telegram_bot_token`,
`redis_url`) pydantic `SecretStr`ga o'tkazildi — "hech qachon loglanmasin"
endi faqat izoh emas, `repr()`/`str()`ning o'zi orqali majburlangan
struktura; har biri revert-test-restore uslubida (xom qiymat vaqtincha
qaytarilib, test aynan kutilgan tarzda qizarishi ko'rsatilib) isbotlangan.

**255 test, barchasi real Postgres(+Redis)'da; 7 E2E spec; 99% o'lchangan
qamrov; CustomerRole.AUDITOR xatosi tuzatilgan.**

**FR-AUTH-001 — haqiqiy Google OIDC login qurildi**, `session_service`ning
dev/test seam'ini almashtirmasdan, uning ustiga: `GET /v1/auth/google/
login` (state cookie o'rnatadi, Google'ga redirect qiladi) va `GET
/v1/auth/google/callback` (state'ni tekshiradi, kodni access token'ga
almashtiradi, Google'ning `userinfo` endpoint'idan subject+ism oladi,
`get_or_create_user` orqali User'ni topadi/yaratadi, haqiqiy Session
yaratadi, frontend'ning `/auth/callback?session_id=...`iga redirect
qiladi). JWT/JWKS tekshiruvi ataylab yo'q — Google'ning `userinfo`
endpoint'i access token'ni o'zi serverda tasdiqlaydi, bu Google'ning o'z
hujjatlashtirilgan alternativi. `application/oidc_login_service.py` —
kod bazasida birinchi marta application qatlami infrastructure qatlamiga
to'g'ridan-to'g'ri murojaat qiladi (`test_side_effect_boundary.py`ga shu
sabab bilan hujjatlashtirilgan istisno qo'shildi): login redirect outbox/
relay zanjiriga sig'maydi — brauzer aynan shu HTTP javobini kutib turgan,
orqasida asinxron worker yo'q.

Frontend: `/login`ga "Google orqali kirish" tugmasi (dev/test session-ID
formasi bilan yonma-yon, ikkalasi ham ishlaydi), yangi `/auth/callback`
sahifasi (`session_id` query param'ni o'qiydi, tekshiradi, saqlaydi,
`/workspaces`ga yo'naltiradi). Buni qurishda haqiqiy WCAG regressiyasi
topildi va tuzatildi: yangi "yoki" ajratuvchisi `text-gray-400` bilan
kontrast nisbati 2.6:1 edi (kerak — 4.5:1) — `axe-core` birinchi haqiqiy
ishga tushirishda aniq shu elementni ko'rsatdi, `text-gray-600`ga
o'tkazib tuzatildi, qayta tekshirilib 0 topilma tasdiqlandi.

Uchta haqiqiy credential (Telegram bot tokeni, Google Client ID/Secret)
Product Owner tomonidan xavfsiz taqdim etildi va faqat `.env`ga yozildi —
chatga, kodga yoki commitga hech qachon chiqmagan. **Halol chegara**: bu
muhitning tarmoq siyosati Google'ning API'siga chiqish so'rovlarini
bloklaydi, shuning uchun haqiqiy token exchange/userinfo chaqiruvi bu
yerda real Google'ga qarshi ishga tushirilmagan — faqat bitta haqiqiy
tashqi tarmoq bosqichi (`httpx.MockTransport`) test double bilan
almashtirilgan, qolgan butun zanjir (state cookie, get_or_create_user,
Session yaratish, redirect) real Postgres'ga qarshi HTTP orqali
tasdiqlangan. Frontend tomoni (callback sahifasining query-param
handoff'i) real backend+brauzer'ga qarshi Playwright orqali (`e2e/
auth-callback.spec.ts`, o'z seed prefiksi bilan) tasdiqlandi.

279 test, barchasi real Postgres(+Redis)'da; 8 E2E spec.

**Birinchi marta production deployment infratuzilmasi yozildi** —
`backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.prod.yml`,
`deploy/Caddyfile` (avtomatik HTTPS). Domen (`natsecurity.uz`) Product
Owner tomonidan tasdiqlangan haqiqiy domen; server esa ataylab
nol-boshidan ("serverni o'zing yaratgin"). **Halol chegara**: bu
muhitning tarmoq siyosati Docker Hub'ga chiqishni bloklaydi — `docker
build` haqiqiy ishga tushirilmagan, faqat `docker compose config` orqali
YAML to'g'riligi tasdiqlangan. `deploy/README.md`da aniq yozilgan: real
server provisioning/DNS — bu agent bajara olmaydigan, inson (yoki
kredensial) kerak bo'ladigan qadam.

**FR-CONV (Chat) backend'i to'liq qurildi — uch provayderli AI
integratsiyasi bilan (ADR-008: OpenAI, standart; ADR-009: Google Gemini
va Anthropic Claude, Product Owner'ning aniq, qamrovni kengaytiruvchi
ko'rsatmasi bilan).** `doda.ai.port.ModelGateway` — bitta provayderdan
mustaqil Protocol (`stream_chat`, streaming events: text/tool-call/
structured-output/completion/error); `doda.ai.factory.get_gateway` har
bir provayder uchun mustaqil ravishda haqiqiy adapter
(`infrastructure/{openai,gemini,claude}_gateway.py`) yoki, kalit
sozlanmagan bo'lsa, `NullModelGateway`ni tanlaydi — **bitta provayderning
sozlanmaganligi hech qachon boshqa provayderga almashtirilmaydi**
(testlangan). `doda.application.conversation_service.stream_message` —
har bir suhbat burilishining markazi: foydalanuvchi xabarini saqlash →
provayder/model tanlovini hal qilish (`ai_preference_service`: suhbat
pin > foydalanuvchi standart > workspace standart > tizim standart,
to'rt darajali, hech qachon aralashtirmaydi) → butun burilish uchun
eng yomon holat byudjetini oldindan zahira qilish (`ai_budget_service`,
`SELECT ... FOR UPDATE` bilan qulflangan oylik ledger — besh marta
isbotlangan concurrency-xavfsiz naqsh) → gateway bilan, tool-call
davrlarini boshqarib (READ vositalar darhol bajariladi; WRITE vositalar
HECH QACHON to'g'ridan-to'g'ri bajarilmaydi, mavjud Action/Approval
zanjiri orqali o'tadi va burilishni aniq, model yaratmagan status xabari
bilan tugatadi) → byudjetni haqiqiy sarfga moslashtirish (har qanday
kutilmagan xatoda ham — `except Exception:` bilan umumlashtirilgan, aks
holda qulab tushish "hech qachon ozod qilinmaydigan" zahirani qoldirardi).

`POST /v1/workspaces/{id}/conversations/{id}/messages` — SSE (`text/
event-stream`) orqali javob beradi. Ikki xil xato yo'li ataylab farqli:
birinchi bayt OLDIN (byudjet tugashi, DEEP narx chegarasi, birinchi
davrdagi provayder xatosi) — oddiy HTTP 4xx/5xx (headerlar hali
yuborilmagan); birinchi bayt KEYIN (masalan ikkinchi tool-call davrida
provayder xatosi) — bitta yakuniy `event: error` SSE freymi, keyin
generator toza tugaydi (aks holda tranzaksiya rollback bo'lib, allaqachon
mijozga yuborilgan xabarlar tarixi yo'qolardi). Ikkalasi ham real
HTTP/SSE orqali, skriptlashtirilgan fake gateway bilan (haqiqiy provayder
xatosini soxtalashtirib) tasdiqlandi — audit-zanjiri uslubida: himoya
vaqtincha olib tashlanib, test aniq kutilgan tarzda buzilishi, keyin
qaytarilib yashil ekani ko'rsatildi.

**Shu ishni yozish jarayonida haqiqiy xato topildi va tuzatildi**:
`ai_tools.propose_write_tool_action` retry holatida (bir xil
idempotency-key bilan ikkinchi chaqiruv) `submit_action_for_execution`ni
SHARTSIZ qayta chaqirardi — allaqachon `AWAITING_APPROVAL`ga o'tgan
action uchun bu `InvalidActionTransition` bilan qulardi. `api/
actions.py`ning allaqachon to'g'ri qilgan `created`-tekshiruvi bilan bir
xil naqshga o'tkazib tuzatildi. Bu xato hech qachon ishlatilmagan
edi — yangi `test_a_retried_write_tool_call_collapses_onto_the_same_
action_not_a_duplicate` uni birinchi marta yozilganida DARHOL ushladi.

**Provayder sozlamalari admin API'si va opt-in fallback ham qurildi**
(`api/ai_settings.py`, `ai_provider_settings_service.py`) —
"configured" (server darajasidagi kalit) / "enabled" (CustomerOwner
o'chirib qo'ymagani) / "verified working" (haqiqiy test-connection
natijasi) uchta alohida fakt, `GET /v1/customers/{id}/ai-providers` +
`PUT .../enabled` + `POST .../test-connection`; shuningdek ilgari
hech qanday HTTP yo'li bo'lmagan `set_user_ai_preference`/
`set_workspace_ai_preference` endi `GET/PUT/DELETE .../me/ai-preference`
va `.../workspaces/{id}/ai-preference` orqali ochildi. Fallback
(`CustomerAIFallbackSetting`, standart O'CHIRILGAN) faqat uchta
vaqtinchalik xato turida (`ModelTimeoutError`/`ModelRateLimitedError`/
`ModelProviderError`), faqat round 0da hali hech narsa ishlab
chiqarilmagan bo'lsa, bitta urinish — byudjet/ruxsat rad etishlarini
hech qachon chetlab o'ta olmaydi (strukturaviy jihatdan ularga
yetolmaydi, alohida tekshiruv emas).

**Bu ishni qurish jarayonida haqiqiy, jiddiy xato topildi va tuzatildi —
har bir MUVAFFAQIYATLI suhbat burilishi cheksiz tsiklga tushib qolardi.**
Fallback uchun round-tsiklni `while True:`ga o'rashda, muvaffaqiyatli
yakunlanishni belgilaydigan `break` xato joyga (`for/else`ning faqat
`else` qismi ichiga) qo'yilgan edi — oddiy, muvaffaqiyatli yakunlanish
yo'li (erta `break` bilan) `else`ni umuman chaqirmaydi, demak
`while True:` hech qachon to'xtamay qolardi. To'liq test suite'ni ishga
tushirishda DARHOL aniqlandi (99% CPU, progress'siz ~2+ daqiqa) — bu
aynan "har safar to'liq suite'ni ishga tushir" intizomining nima uchun
shart ekanini ko'rsatadi: yolg'iz birlik testlari buni hech qachon
ko'rsatmagan bo'lardi. Shu jarayonda ikkita boshqa haqiqiy xato ham
topildi: `ai_tools.propose_write_tool_action`ning retry yo'li
(idempotent replay'da `submit_action_for_execution`ni shartsiz qayta
chaqirib, `InvalidActionTransition` bilan qulardi) va
`AIProviderVerification.last_verified_at`da `DateTime(timezone=True)`
yo'qligi (real `asyncpg.DataError`). To'liq tafsilot: `CLAUDE.md`.

**Halol, ataylab ochiq qoldirilgan qismlar** (QOIDA 2): provayder
model-darajasidagi capability override (hozir faqat provider darajasida).
**Eng muhim ochiq xavf** —
`docs/open-decisions.md`ning OD-003 qatori: qaysi ma'lumot sinflari AI
provayderga yuborilmasin degan qaror hamon OCHIQ, va endi DOLZARB — real
API kalit ulangan zahoti, foydalanuvchi chatga yozgan har qanday matn
filtrlashsiz tashqi provayderga ketadi. `backend/scripts/
run_ai_eval_suite.py` — 11 ta o'zbek tilidagi vazifa bilan eval harness
(real orkestratsiya orqali, `NullModelGateway`dan tashqari hech qachon
bu muhitda real provayderga qarshi ishlatilmagan — tarmoq siyosati
bloklaydi).

353 test, barchasi real Postgres(+Redis)'da; ADR-008/ADR-009 yozildi.

**Frontend chat UI va AI provayder sozlamalari qurildi — backend'ning
to'liq multi-provider zanjiri (yuqoriga qarang) endi haqiqiy brauzer
orqali ham ishlatiladi.** Yangi `/workspaces/[id]/chat` sahifasi:
suhbatlar ro'yxati + yangi suhbat yaratish, xabar yuborish (backend'ning
SSE oqimini brauzerning o'z `fetch()` + `ReadableStream`'i orqali o'qib,
matnni real vaqtda ko'rsatadi — `EventSource` ishlatilmadi, chunki u
faqat GET so'rovlarni qo'llab-quvvatlaydi, bu yerda esa POST kerak),
rejim tanlovi (FAST/STANDARD/DEEP), suhbatning o'z provayder/model
pin'ini o'rnatish, va workspace darajasidagi standart provayder/model
tanlovi. Xatolarning ikki yo'li (module docstring'da hujjatlashtirilgan
oqim bo'yicha) frontend'da ham aynan shunday ishlaydi: birinchi bayt
oldingi xato oddiy `ApiError` (masalan byudjet tugashi), birinchi
baytdan keyingi xato esa bitta `event: error` SSE freymi sifatida
ko'rsatiladi, oqim esa toza tugaydi.

Yangi `/customers/[id]` bo'limi — "AI provayderlar": har uch provayder
(OPENAI/GEMINI/CLAUDE) uchun sozlangan/yoqilgan/tekshirilgan holatini
ko'rsatadi, "Ulanishni tekshirish" tugmasi haqiqiy (garchi bu muhitda
kalitsiz bo'lsa ham halol) `test_provider_connection` chaqiruvini
ishga tushiradi, yoqish/o'chirish tugmasi bor. Shu yerga "Avtomatik
fallback" (standart — o'chirilgan, ADR-009) va "Mening AI afzalligim"
(4 pog'onali tanlov zanjirining foydalanuvchi darajasi) ham qo'shildi —
ikkalasi ham allaqachon qurilgan/testlangan backend endpointlariga
ulanadi, boshqa customer-darajasidagi bo'limlar (kill switch, audit)
bilan bir xil "customer_id sahifaning o'zida bor" mantig'iga ergashib.

Boshqa har bir sahifadagi kabi, bu yerda ham rol asosida UI-gating yo'q
— tugmalar har doim ko'rsatiladi, ruxsat yo'q bo'lsa backend javob
qaytaradi (masalan workspace AI afzalligini o'zgartirish faqat
`WorkspaceAdmin`/`CustomerOwner`ga ruxsat, oddiy a'zo yozishga urinsa
403 oladi, lekin forma baribir ko'rinadi).

Real backend'ga (353 test o'zgarishsiz) va haqiqiy brauzerga (production
build, `next build && next start`) qarshi Playwright orqali tasdiqlandi:
yangi `frontend/e2e/chat.spec.ts` (o'z mustaqil seed'i — `E2E_CHAT_`,
chunki bu spec customer-keng AI sozlamalarini (enable/disable, fallback)
o'zgartiradi, boshqa spec'larning seed'i bilan bo'lishilsa ularga
ta'sir qilardi) ikkita oqimni qamraydi: (1) yangi suhbat yaratish, xabar
yuborish, real `NullModelGateway`ning halol "AI javob provayderi hali
tanlanmagan yoki sozlanmagan" javobini olish (bu matn frontend'da
qattiq yozilmagan — backend'ning o'zidan real HTTP orqali kelgan), va
suhbat provayderini pin qilish, to'g'ridan-to'g'ri backend so'rovi bilan
tasdiqlangan; (2) provayder yoqish/o'chirish, ulanishni tekshirish,
fallback yoqish, va "mening AI afzalligim"ni o'rnatish — har biri
sahifaning o'z fetch'idan tashqari to'g'ridan-to'g'ri backend so'rovi
bilan ham tasdiqlangan (masalan fallback yoqilgani `GET .../ai-fallback`
orqali). Barcha 12 E2E spec (10 mavjud + 2 yangi) birga qayta ishga
tushirilib, konsol xatosiz va accessibility (`serious`/`critical` WCAG)
regressiyasiz ekani tasdiqlandi.

## Ishga tushirish (local dev)

```bash
docker compose up -d
cd backend
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn doda.main:app --reload
```

Claude Code on the web (remote sessiya) uchun bu qadamlar
`.claude/hooks/session-start.sh` (SessionStart hook) orqali avtomatik
bajariladi — u Postgres/Redis'ni ishga tushiradi, migratsiyalarni
qo'llaydi, `doda_app` rolini ta'minlaydi va dependency'larni o'rnatadi.
Hook **faqat remote muhitda** ishlaydi (`CLAUDE_CODE_REMOTE` tekshiruvi),
shuning uchun mahalliy mashinangizdagi yuqoridagi `docker compose`
oqimiga umuman tegmaydi. Sababi: remote konteyner qayta ishga
tushirilganda (systemd yo'q) Postgres ham, Redis ham to'xtab qoladi —
bu esa "barchasi real Postgres'da" qoidasiga tayangan butun test
suite'ni ishga tushirib bo'lmaydigan holatga olib keladi.

Outbox relay worker (ADR-001/003 — a separate process from the API; polls
`outbox_messages` and publishes to Redis Streams, so no proposed R0-R2
action or approved R3+ action actually gets delivered without this
running too):

```bash
cd backend
python -m doda.infrastructure.outbox_relay
```

Test:

```bash
cd backend
pytest                          # unit testlar (infra shart emas)
pytest tests/integration        # RLS/live-DB testlari (docker compose up talab qiladi)
```

Kod sifati (14.2-bo'lim, CI'da ham majburiy):

```bash
cd backend
ruff check .                    # lint
ruff format --check .           # format
mypy src/doda                   # tiplar
```

CI (`.github/workflows/ci.yml`): har push/PR'da lint+format+mypy, frontend
lint+types, Alembic migratsiya round-trip (upgrade→downgrade→upgrade, real
Postgres'da), to'liq backend test suite (real Postgres+Redis'da), va
end-to-end Playwright suite (real Postgres+Redis+backend+frontend
production build ustida) ishga tushadi.

Frontend (backend allaqachon ishga tushirilgan bo'lishi kerak):

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

`http://localhost:3000` — tafsilot `frontend/README.md`da.

### Ikki xil DB roli — nega

`docker compose up`, birinchi marta ishga tushganda, `infra/postgres-init/`
skriptini avtomatik bajaradi va ikkinchi, huquqi cheklangan `doda_app`
rolini yaratadi. `DODA_DATABASE_URL` (ilovaning o'zi ishlatadigan) shu
rolga, `DODA_MIGRATION_DATABASE_URL` (faqat Alembic) esa bootstrap
superuser'ga (`doda`) ishora qiladi — bittasi emas, ataylab ikkitasi.

Sababi: Postgres'ning rasmiy Docker image'i `POSTGRES_USER` orqali
yaratilgan rolni har doim **superuser** qilib yaratadi, superuser esa
`FORCE ROW LEVEL SECURITY`dan qat'i nazar RLS'ni har doim chetlab o'tadi —
bu Postgres'ning o'zining qat'iy qoidasi, sozlash masalasi emas. Agar ilova
to'g'ridan-to'g'ri shu bootstrap rol bilan ulansa, ADR-005'dagi "ikkinchi
qatlam" (RLS) haqiqatda hech narsa qilmaydi, garchi har bir jadvalda
`FORCE ROW LEVEL SECURITY` yoqilgan bo'lsa ham. Bu aynan shunday sodir
bo'lganini birinchi marta haqiqiy, yangi (fresh) Postgres konteynerida
ishlagan CI o'zi topdi (`test_tenant_isolation.py` bitta tenant boshqa
tenant'ning workspace'larini ko'rib qoldi) — mahalliy dev muhitida
yashiringan edi, chunki u yerdagi Postgres allaqachon boshqacha (superuser
bo'lmagan) `doda` bilan sozlangan edi. Tuzatish: `test_rls_coverage.py`ga
ilovaning o'zi ulanadigan rol haqiqatda superuser/BYPASSRLS emasligini
tekshiradigan test qo'shildi — shu sinf xatoni endi CI har safar ushlaydi.

## Struktura

```
backend/
  src/doda/
    domain/        # Identity, Customer, Workspace, Audit (modular monolith, 6-bo'lim)
    api/            # Experience qatlami (FastAPI routerlar)
    config.py, db.py, main.py
  migrations/       # Alembic
  scripts/          # seed_e2e_demo.py — frontend E2E suite uchun demo ma'lumot
  tests/
frontend/
  src/
    app/            # Next.js App Router sahifalari (login, workspaces, workspace/[id], customers/[id])
    lib/            # api.ts (backend client), session.ts, useSession.ts
  e2e/              # Playwright — real backend+frontend'ga qarshi, CI'da ishlaydi
infra/
  postgres-init/    # doda_app (huquqi cheklangan) rolini yaratuvchi bootstrap skript
deploy/
  Caddyfile         # reverse proxy + avtomatik HTTPS (production, haqiqiy VPS uchun)
  README.md         # real serverga joylashtirish qadamlari (bepul Render MVP + VPS yo'li)
docker-compose.prod.yml  # postgres/redis/migrate/backend/relay workers/frontend/caddy
.env.prod.example   # docker-compose.prod.yml uchun shablon (haqiqiy .env.prod gitignored)
render.yaml         # Render.com Blueprint — bepul MVP deploy (Redis'siz, VPS kelmaguncha)
docs/
  DODA-TRD-v2.0.docx  # authoritative talab hujjati
  adr/                # Architecture Decision Records (TRD 6.4, NFR-MNT-001)
  open-decisions.md   # TRD 19.4 — Product Owner tasdig'i shart bo'lgan 8 savol, holati
  risk-register.md    # TRD 19.1 — o'nta riskning har biri, haqiqiy kod bazasiga nisbatan holati
```

## Arxitektura qarorlari va ochiq savollar

`docs/adr/` — TRD 6.4'dagi ADR ro'yxatining to'liq hujjatlashtirilgan
versiyasi (kontekst, qaror, oqibatlar — real kodga/incidentlarga havola
bilan). `docs/open-decisions.md` — TRD 19.4'dagi sakkizta Product Owner
qaroriga bitta joydan qarash: qaysi biri hal qilingan, qaysi biri hali
ochiq, va qaysi biri hujjatdagi muddatidan allaqachon o'tib ketgan.
`docs/risk-register.md` — TRD 19.1'dagi o'nta riskning har biri qanday
yengillashtirilgani (yoki hali dormant/yengillashtirilmagan ekani),
haqiqiy kod bazasiga nisbatan baholangan.
