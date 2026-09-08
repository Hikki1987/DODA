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
qaytaradi (avval bunday "kashfiyot" endpointi umuman yo'q edi). `GET
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
service`ning dev/test seam'idan foydalanadi — bu aniq belgilangan. Chat
(FR-CONV) va Knowledge/RAG ekranlari qurilmagan, chunki backend'da ham
ular yo'q ("DEMO ≠ PRODUCTION" qoidasi: mavjud bo'lmagan backend uchun
soxta UI qurilmaydi). To'liq end-to-end oqim (login → workspace →
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

## Ishga tushirish (local dev)

```bash
docker compose up -d
cd backend
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn doda.main:app --reload
```

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
docs/
  DODA-TRD-v2.0.docx  # authoritative talab hujjati
  adr/                # Architecture Decision Records (TRD 6.4, NFR-MNT-001)
  open-decisions.md   # TRD 19.4 — Product Owner tasdig'i shart bo'lgan 8 savol, holati
```

## Arxitektura qarorlari va ochiq savollar

`docs/adr/` — TRD 6.4'dagi ADR ro'yxatining to'liq hujjatlashtirilgan
versiyasi (kontekst, qaror, oqibatlar — real kodga/incidentlarga havola
bilan). `docs/open-decisions.md` — TRD 19.4'dagi sakkizta Product Owner
qaroriga bitta joydan qarash: qaysi biri hal qilingan, qaysi biri hali
ochiq, va qaysi biri hujjatdagi muddatidan allaqachon o'tib ketgan.
