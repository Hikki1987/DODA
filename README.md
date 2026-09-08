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

Real backend'ga (native Postgres 16 + pgvector, Redis, `doda_app`
huquqi cheklangan rol) qarshi to'liq qayta tekshirildi: 163 test (avvalgi
150'dan ko'p — bu orada boshqa ishlar ham qo'shilgan edi), so'ng haqiqiy
seed qilingan R3 action bilan Playwright orqali browser'da — action
"send_email / risk: R3 / AWAITING_APPROVAL" va audit'da
"workspace.created.v1" ekranda to'g'ri ko'rinishi tasdiqlandi, konsol
xatosiz.

## Ishga tushirish (local dev)

```bash
docker compose up -d
cd backend
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn doda.main:app --reload
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

CI (`.github/workflows/ci.yml`): har push/PR'da lint+format+mypy, Alembic
migratsiya round-trip (upgrade→downgrade→upgrade, real Postgres'da), va
to'liq test suite (real Postgres+Redis'da) ishga tushadi.

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
  tests/
frontend/
  src/
    app/            # Next.js App Router sahifalari (login, workspaces, workspace/[id])
    lib/            # api.ts (backend client), session.ts, useSession.ts
infra/
  postgres-init/    # doda_app (huquqi cheklangan) rolini yaratuvchi bootstrap skript
docs/
  DODA-TRD-v2.0.docx  # authoritative talab hujjati
```
