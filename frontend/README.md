# DODA — Web frontend (S3 shell)

Next.js + TypeScript, per TRD 6.3. Talks directly to the backend
(`../backend`) over HTTP — see `src/lib/api.ts` for the client and
`../CLAUDE.md` for the full backend context.

## Ishga tushirish

```bash
cd backend && uvicorn doda.main:app --reload   # backend, alohida terminalda
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

`http://localhost:3000` ochiladi.

## Dev/test kirish (haqiqiy OIDC hali yo'q)

Login sahifasi haqiqiy parol emas, `session_service.create_session` orqali
yaratilgan xom session UUID'ni kutadi — bu FR-AUTH-001'ning S3 bosqichidagi
bilingan cheklovi (`../CLAUDE.md`ga qarang). Test session yaratish uchun
backend'da:

```python
from doda.db import tenant_scoped_session
from doda.application.session_service import create_session
from doda.domain.identity.models import AuthStrength
# ... User/Customer/Workspace allaqachon mavjud bo'lishi kerak
session = await create_session(db, user_id=..., auth_strength=AuthStrength.AAL2)
print(session.id)  # shu UUID'ni login sahifasiga kiriting
```

## Qamrov

Login (dev seam) → `/v1/me/workspaces` orqali workspace tanlash →
workspace ichida: kill-switch holati, task'lar (ro'yxat/yaratish/holat
o'zgartirish), bildirishnomalar (ro'yxat/o'qildi belgilash), a'zolar
ro'yxati. Chat (FR-CONV) va Knowledge/RAG (2-bosqich) qurilmagan — backend'da
ham hali yo'q, shuning uchun bu yerda ham yo'q (soxta UI qurish "DEMO ≠
PRODUCTION" qoidasini buzardi).
