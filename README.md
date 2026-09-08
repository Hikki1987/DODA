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
workspace'lardagi bildirishnomalar bitta joydan). Audit hash-zanjiri endi
concurrent yozuvlarda
ham xavfsiz (FR-AUD-004, per-customer lock); sessiya faollik-belgisi
(FR-AUTH-006 idle timeout) endi haqiqatda saqlanadi (avval jimgina
saqlanmasdi — tuzatildi).


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
infra/
  postgres-init/    # doda_app (huquqi cheklangan) rolini yaratuvchi bootstrap skript
docs/
  DODA-TRD-v2.0.docx  # authoritative talab hujjati
```
