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
o'zgartirish/"Tarix" tugmasi bilan status o'tishlari tarixi —
`GET .../tasks/{id}/history`, FR-TASK-007), action'lar (ro'yxat —
tool_name/risk_level/status, faqat o'qish uchun), bildirishnomalar
(ro'yxat/o'qildi belgilash), a'zolar
ro'yxati, audit (`GET /v1/workspaces/{id}/audit` — event_type/actor/vaqt,
faqat o'qish, FR-AUD-002). `/sessions` (workspace'lar sahifasidagi
"Sessiyalar" havolasi) — foydalanuvchi darajasida, workspace'ga bog'liq
emas: barcha faol sessiyalarni (joriysi belgilangan holda) ko'rsatadi va
boshqa qurilmadagi sessiyani uzoqdan yopish imkonini beradi (FR-CTL-001/002,
`GET`/`DELETE /v1/sessions`). Joriy sessiyani shu sahifadan yopib
bo'lmaydi — buning uchun "Chiqish" ishlatiladi. Chat (FR-CONV) va
Knowledge/RAG (2-bosqich) qurilmagan — backend'da ham hali yo'q, shuning
uchun bu yerda ham yo'q (soxta UI qurish "DEMO ≠ PRODUCTION" qoidasini
buzardi).

Action'lar bo'limi ataylab faqat o'qish uchun: yangi action taklif qilish
(propose) formasi qurilmadi, chunki hali hech qanday haqiqiy tool/connector
yo'q (S7, OD-002) — mavjud bo'lmagan tool nomlarini erkin kiritish
imkoniyatini berish "DEMO ≠ PRODUCTION" qoidasini buzardi. Approval
(tasdiqlash) tugmasi ham qurilmadi: `nonce` (bir martalik tasdiqlash
kaliti, 9.2) faqat action taklif qilingan paytdagi HTTP javobida bir marta
qaytariladi va boshqa hech qanday joyda (jumladan shu ro'yxatlash
endpoint'ida) qayta ko'rsatilmaydi — bu ataylab shunday (backend
`ApprovalOut.nonce`ning docstring'iga qarang). Demak ro'yxatdagi
AWAITING_APPROVAL action'ni shu ekrandan tasdiqlab bo'lmaydi; buning uchun
propose+approve bitta oqim ichida (bir xil sahifa yuklanishida) qurilishi
kerak — bu alohida ish, chunki u ham propose formasini talab qiladi.
