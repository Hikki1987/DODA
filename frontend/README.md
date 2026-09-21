# DODA — Web frontend

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

## Kirish: Google OIDC yoki dev/test seam

`/login` ikkala yo'lni ham taklif qiladi. **Google orqali kirish**
tugmasi backend'ning `GET /v1/auth/google/login` → `/callback` oqimiga
(FR-AUTH-001, haqiqiy login — `../CLAUDE.md`ga qarang) redirect qiladi;
ishlashi uchun backend'da `DODA_GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`/
`_REDIRECT_URI` sozlangan bo'lishi kerak (`backend/.env.example`),
bo'lmasa `/v1/auth/google/login` 503 `OIDC_NOT_CONFIGURED` qaytaradi.

Pastdagi forma esa hamon mavjud: haqiqiy parol emas, `session_service.
create_session` orqali to'g'ridan-to'g'ri yaratilgan xom session UUID'ni
kutadi — Google login sozlanmagan muhitda (yoki tezkor local tekshiruvda)
ishlatiladi. Test session yaratish uchun backend'da:

```python
from doda.db import tenant_scoped_session
from doda.application.session_service import create_session
from doda.domain.identity.models import AuthStrength
# ... User/Customer/Workspace allaqachon mavjud bo'lishi kerak
session = await create_session(db, user_id=..., auth_strength=AuthStrength.AAL2)
print(session.id)  # shu UUID'ni login sahifasiga kiriting
```

## End-to-end testlar (Playwright)

Bu sessiyagacha har bir frontend tekshiruvi qo'lda, scratchpad'dagi
throwaway skriptlar bilan qilingan edi — hech biri repo'ga kirmagan va
hech qanday keyingi o'zgarish ularni qayta ishga tushirmagan. `e2e/`
buni haqiqiy, commit qilingan, CI'da ishlaydigan test suite'ga
aylantiradi ("DEMO ≠ PRODUCTION" qoidasi: qo'lda bir marta tekshirilgan
narsa keyingi o'zgarishlar uni buzmasligini kafolatlamaydi).

```bash
# Terminal 1 — backend (real Postgres+Redis kerak, docker compose up -d)
cd backend && uvicorn doda.main:app --reload

# Terminal 2 — frontend
cd frontend && npm run dev

# Terminal 3 — demo ma'lumot urug'lash va testlarni ishga tushirish
cd backend
python scripts/seed_e2e_demo.py --prefix E2E_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_CUSTOMER_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_A11Y_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_ARCHIVE_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_KILLSWITCH_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_LOGOUT_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_AUDITOR_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_AUTHCALLBACK_ >> /tmp/e2e.env
python scripts/seed_e2e_demo.py --prefix E2E_CHAT_ >> /tmp/e2e.env
cd ../frontend
set -a && source /tmp/e2e.env && set +a
npm run e2e
```

Har bir spec o'z mustaqil `--prefix`i bilan urug'lanadi — bu boshida
ikkita spec uchun aniqlangan naqsh edi (`customer.spec.ts`ning customer-
keng kill switch'ni yoqishi SECURITY_ALERT bildirishnomasini customer'ning
BARCHA a'zolariga yuboradi, bu `workspace.spec.ts`ning bildirishnoma-sonini
tekshiruvchi assertion'ini buzardi — `e2e/customer.spec.ts` ichidagi izohga
qarang), keyingi har bir yangi spec ham xuddi shu ehtiyot chorasini
takrorladi. Hozir 9 ta mustaqil spec bor: `workspace.spec.ts`,
`customer.spec.ts`, `workspace-archive.spec.ts`, `workspace-kill-switch.spec.ts`,
`logout.spec.ts`, `accessibility.spec.ts` (`@axe-core/playwright` — har bir
sahifada WCAG 2.2 AA `serious`/`critical` buzilishlarning nolga teng
bo'lishini talab qiladi), `auditor.spec.ts` (`CustomerRole.AUDITOR` —
workspace ro'yxati bo'sh, `/v1/me/customers` orqali customer'ga kirish,
audit ko'rish, va workspace'ning o'zi backend darajasida 403 qaytarishi —
CLAUDE.md'dagi auditor-avtorizatsiya tuzatishining doimiy regressiya
testi), `auth-callback.spec.ts` (FR-AUTH-001 — `/auth/callback`ning
`session_id` query-param handoff'i: haqiqiy, yoqilgan, va yo'q/noto'g'ri
session_id holatlari; real Google OAuth consent screen'ini emas, faqat
bu frontend/backend mexanizmini isbotlaydi), va `chat.spec.ts` (FR-CONV —
suhbat yaratish/xabar yuborish/real `NullModelGateway` javobi, cancel
mid-stream, qidiruv, provayder/til pin qilish, customer sahifasidagi AI
provayder yoqish/o'chirish/fallback sozlamalari). `backend/scripts/
seed_e2e_demo.py` xuddi `tests/integration/conftest.py`dagi `seed_
workspace_member` bilan bir xil dev/test seam'dan foydalanadi — haqiqiy
OIDC endi bor (yuqoriga qarang), lekin headless seed uchun hamon
foydasiz, chunki u haqiqiy Google hisobi/consent screen talab qiladi.

CI (`.github/workflows/ci.yml`ning `e2e` job'i) xuddi shu ketma-ketlikni
avtomatik bajaradi: real Postgres+Redis, backend `uvicorn` orqali,
frontend `next build && next start` orqali (dev server emas — production
build'ning o'zi ishlashini tekshiradi), barcha 9 ta mustaqil seed, va
`npx playwright test`.

## Qamrov

Login (dev seam) → `/v1/me/workspaces` orqali workspace tanlash (va
`/v1/me/customers` orqali customer tanlash — "Customer'larim" bo'limi, shu
ikkisi alohida, chunki workspace roliga ega bo'lmagan a'zo uchun birinchi
ro'yxat bo'sh qoladi) →
workspace ichida: kill-switch (haqiqatda yoqish/sabab bilan/o'chirish —
`KillSwitchPanel` komponenti, customer sahifasi bilan bir xil, faqat
birida qo'shimcha "Yangi action'lar bloklangan" matni bor), workspace'ni
arxivlash tugmasi (`window.confirm` bilan — qaytarish endi faqat customer
sahifasidan, pastga qarang), task'lar (ro'yxat/yaratish — muddat bilan/
holat o'zgartirish/"Tarix" tugmasi bilan status o'tishlari tarixi —
`GET .../tasks/{id}/history`, FR-TASK-007/"Qarorlar" toggle bilan
variant/tradeoff/qaror/sabab yozish va versiyalangan tarixini ko'rish,
FR-TASK-003/"Eslatmalar" toggle bilan reminder so'rash-tasdiqlash-bekor
qilish oqimi, FR-TASK-005 — va kunlik/haftalik "Reja" paneli, muddati
yaqin/o'tgan tasklarni alohida ko'rsatadi, FR-TASK-002), action'lar
(ro'yxat — tool_name/risk_level/status/inson-o'qiy oladigan preview matni,
FR-ACT-002, va READY/RUNNING holatidagi action'lar uchun "Bekor qilish"
tugmasi, FR-ACT-009/FR-CTL-005 — boshqa har qanday holatda tugma yo'q),
bildirishnomalar (ro'yxat/o'qildi belgilash), a'zolar (ro'yxat + mavjud
a'zoning rolini almashtirish/chiqarish, FR-WKS-003 — yangi a'zo qo'shish
bu yerda yo'q, pastga qarang), audit (`GET /v1/workspaces/{id}/audit` —
event_type/actor/vaqt, `?trace_id=` filtri bilan — har bir yozuvning
o'z trace_id'siga bosilganda shu qiymat bilan filtrlanadi, NFR-OBS-001,
faqat o'qish, FR-AUD-002). Alohida `/workspaces/[id]/chat` sahifasi
(FR-CONV — Chat/AI yordamchi, uchta real provayder: OpenAI/Gemini/
Claude, bitta gateway ortida, ADR-008/ADR-009): suhbatlar ro'yxati +
yaratish, suhbat tarixini qidirish (FR-CONV-006), xabar yuborish (SSE
streaming, "Bekor qilish" tugmasi bilan cancel-mid-stream, FR-CONV-002),
suhbat-darajasidagi provayder/model pin va til pin (o'zbek/rus/ingliz
avtomatik aniqlanadi, aniq pin ustunlik qiladi, FR-CONV-001), workspace
standart provayderi va standart tili (WorkspaceAdmin-only yozish, FR-
WKS-007). `/sessions` (workspace'lar sahifasidagi
"Sessiyalar" havolasi) — foydalanuvchi darajasida, workspace'ga bog'liq
emas: barcha faol sessiyalarni (joriysi belgilangan holda) ko'rsatadi va
boshqa qurilmadagi sessiyani uzoqdan yopish imkonini beradi (FR-CTL-001/002,
`GET`/`DELETE /v1/sessions`) — "Chiqish" endi shu sessiyani haqiqatda
serverda revoke qiladi (avval faqat localStorage'ni tozalardi, haqiqiy
xato edi, tuzatildi); shu sahifada "Ma'lumotlarimni eksport qilish"
(`GET /v1/me/export`, FR-CTL-002) tugmasi ham bor — JSON faylni haqiqiy
brauzer yuklab olish orqali beradi. Joriy sessiyani shu sahifadan
tugma bilan yopib bo'lmaydi — buning uchun "Chiqish" ishlatiladi.
Knowledge/RAG (2-bosqich) hamon qurilmagan — backend'da ham hali yo'q,
shuning uchun bu yerda ham yo'q (soxta UI qurish "DEMO ≠ PRODUCTION"
qoidasini buzardi).

Action'lar bo'limida yangi action taklif qilish (propose) formasi hamon
qurilmagan. OD-002 (Telegram) endi bitta real connector
(`telegram.send_message`) qurilgan bo'lsa-da, propose formasi tool
nomini erkin matn sifatida kiritishga ruxsat beradi — foydalanuvchi hali
mavjud bo'lmagan (yoki noto'g'ri yozilgan) tool nomini kiritishi mumkin
bo'lardi, bu "DEMO ≠ PRODUCTION" qoidasini buzardi. Approval
(tasdiqlash) tugmasi ham qurilmagan: `nonce` (bir martalik tasdiqlash
kaliti, 9.2) faqat action taklif qilingan paytdagi HTTP javobida bir marta
qaytariladi va boshqa hech qanday joyda (jumladan shu ro'yxatlash
endpoint'ida) qayta ko'rsatilmaydi — bu ataylab shunday (backend
`ApprovalOut.nonce`ning docstring'iga qarang). Demak ro'yxatdagi
AWAITING_APPROVAL action'ni shu ekrandan tasdiqlab bo'lmaydi; buning uchun
propose+approve bitta oqim ichida (bir xil sahifa yuklanishida) qurilishi
kerak — bu alohida ish, chunki u ham propose formasini talab qiladi.
Bekor qilish (cancel) esa propose formasidan mustaqil bo'lgani uchun
allaqachon qurilgan (yuqoriga qarang) — nonce yoki propose input talab
qilmaydi.

Workspace a'zolar bo'limidagi "yangi a'zo qo'shish" ham ataylab yo'q:
`POST .../members` `customer_membership_id`ni talab qiladi (user_id emas)
— buni tanlash uchun avval customer'ning a'zolari ro'yxati kerak bo'ladi,
bu esa customer_id talab qiladi (workspace sahifasida yo'q). Rol
almashtirish va chiqarish esa allaqachon ro'yxatlangan a'zoning
`membership_id`sidan foydalanadi, shuning uchun bu cheklovga duch
kelmaydi.

## `/customers/[id]` — customer-darajasidagi sahifa

Workspace'lar ro'yxatidagi customer nomiga bosilganda ochiladi
(`/workspaces` sahifasidagi har bir qatorda). Workspace sahifasi
customer_id'ni bilmagani uchun ilgari qurib bo'lmagan customer-darajasidagi
hamma narsa endi shu yerda:

- **Kill switch**: holat + yoqish (sabab bilan)/o'chirish tugmalari
  (FR-CTL-003, `.../kill-switch/engage|disengage`) — xuddi workspace
  sahifasidagi bilan bir xil `KillSwitchPanel` komponenti, faqat
  customer-darajasidagi API'ga ulangan.
- **A'zolar**: ro'yxat + **yangi a'zo qo'shish** (User ID + rol), rol
  almashtirish, chiqarish (FR-WKS-005, `POST/PATCH/DELETE .../members`).
  Workspace-darajasidan farqli, bu yerda "qo'shish" mumkin — customer-level
  `POST` `user_id`ni to'g'ridan-to'g'ri qabul qiladi
  (`customer_membership_id` emas), shuning uchun oldindan boshqa ro'yxat
  kerak emas. User ID hamon xom UUID sifatida kiritiladi — foydalanuvchi
  qidirish/tanlash endpointi hali yo'q.
- **Bildirishnoma sozlamalari**: 4 turdan 3 tasini yoqish/o'chirish
  (FR-NTF-004). SECURITY_ALERT uchun tugma yo'q — backend uni hech qachon
  o'chirishga ruxsat bermaydi (`NotificationPreferenceError`), shuning
  uchun UI ham "doim yoqilgan" deb ko'rsatadi, urinib xato ko'rsatish
  o'rniga.
- **Bildirishnomalar**: shu customer ostidagi BARCHA workspace'lardagi
  bildirishnomalar bitta ro'yxatda (`GET .../notifications`,
  `workspace_id` filtri yo'q).
- **Audit**: customer-darajasidagi audit (`GET .../audit`, FR-AUD-002) —
  CustomerOwner/Auditor uchun butun customer, workspace sahifasidagi
  audit esa faqat o'sha bitta workspace uchun edi. `?trace_id=` filtri
  (NFR-OBS-001, workspace sahifasidagi bilan bir xil naqsh). "Zanjirni
  tekshirish" tugmasi ham bor (`GET .../audit/verify`, FR-AUD-004) —
  natijani yashil ("Zanjir sog'lom") yoki qizil (buzilish soni) banner
  sifatida ko'rsatadi; tekshirishning o'zi ham audit qilinadi
  (`audit.chain_verified.v1`). Trace_id filtri qo'llanilganda "Evidence
  eksport" tugmasi ham ko'rinadi (`GET .../audit/evidence-package`,
  FR-AUD-005) — shu trace'ning barcha yozuvlari + har birining o'z-o'ziga
  moslik tekshiruvi + butun zanjir tekshiruvi natijasini JSON fayl
  sifatida yuklab beradi.
- **AI provayderlar**: har uch provayder (OPENAI/GEMINI/CLAUDE)ning
  sozlangan/yoqilgan/tekshirilgan holati, "Ulanishni tekshirish"
  tugmasi, yoqish/o'chirish. Shu bo'limda: "Avtomatik fallback" (standart
  o'chirilgan, ADR-009), "Mening AI afzalligim" (foydalanuvchi-darajasidagi
  provayder tanlovi, chat sahifasidagi suhbat/workspace pin'laridan
  ustunlik zanjirining bir pog'onasi), va oylik AI byudjeti banneri
  (`GET .../ai-budget`, OD-008/NFR-COST-001 — soft cap'dan oshganda
  amber ogohlantirish bilan).
- **Arxivlangan workspace'lar**: ro'yxat + "Tiklash" tugmasi
  (`GET .../workspaces/archived`, FR-WKS-006, CustomerOwner-only) — faqat
  ro'yxat bo'sh bo'lmaganda ko'rinadi. Workspace sahifasidagi "Arxivlash"
  tugmasidan keyingi yagona qaytarish yo'li shu — arxivlash bir tomonlama
  UI harakat (workspace arxivlangandan keyin o'sha sahifaga kira
  bo'lmaydi).

Rol asosidagi tugmalarni (masalan faqat CustomerOwner qila oladigan
amallar) client tomonda yashirish yo'q — boshqa sahifalar bilan bir xil
naqsh: tugma har doim ko'rsatiladi, ruxsat yo'q bo'lsa backend 403
qaytaradi va xato xabari ko'rsatiladi.
