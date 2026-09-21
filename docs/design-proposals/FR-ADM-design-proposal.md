# FR-ADM — Administrator va platforma boshqaruvi: dizayn taklifi

**Holat**: taklif hujjati, kod emas. TRD 3.9-bo'limining olti talabi
(FR-ADM-001..006) qayta ko'rib chiqilib, har biri uch toifadan biriga
ajratildi: (A) allaqachon mavjud UI/API bilan qondirilgan — faqat
ID bilan bog'lash kerak edi; (B) mavjud infratuzilmaga tayanib kichik,
xavfsiz qadam bilan yopish mumkin — shu sessiyada qurildi; (C) haqiqiy,
yangi Product Owner/arxitektura qarorini talab qiladi — bu hujjat
o'sha qarorlar uchun boshlang'ich taklif, QOIDA 2ga ko'ra o'zi
amalga oshirilmagan.

## Xulosa jadvali

| ID | Toifa | Holat |
|---|---|---|
| FR-ADM-001 | A | Mavjud UI bilan qondirilgan (pastga qarang) |
| FR-ADM-002 | C | Taklif quyida — Product Owner qarori kerak |
| FR-ADM-003 | C | Taklif quyida — Product Owner qarori kerak |
| FR-ADM-004 | C | Taklif quyida — Product Owner qarori kerak |
| FR-ADM-005 | B | **Qurildi** — `ai_budget_overrides`, `PUT/GET/DELETE /v1/customers/{id}/ai-budget-limits` |
| FR-ADM-006 | C (qisman A) | Model routing yarmi mavjud; feature flag yarmi taklif quyida |

## FR-ADM-001 — Customer/workspace ro'yxati va holati paneli

**Talab**: "Customer/workspace ro'yxati va holati paneli." **Qabul
mezoni**: "Admin faqat o'z scope'idagi obyektlarni ko'radi."

**Xulosa: allaqachon qondirilgan.** Bu talab, TRD 2.2-bo'limdagi rol
jadvaliga ko'ra, PLATFORM darajasidagi (barcha customer'lar bo'ylab)
admin panelini emas, balki CustomerOwner'ning O'Z customer'i doirasidagi
ko'rinishini nazarda tutadi deb o'qildi — buning ikkita sababi bor: (1)
bu kod bazasida `platform_owner` degan, tenant'dan yuqori primitiv
umuman mavjud emas (bu haqda CLAUDE.md'da FR-CTL-003'ning global
yarmi muhokama qilinganda alohida qayd etilgan — bu ham xuddi shunday
yangi, katta arxitektura qarori talab qiladi); (2) qabul mezonining o'zi
("faqat o'z scope'idagi") aynan CustomerOwner'ning bugungi cheklovini
tasvirlaydi — haqiqiy platform admin uchun "scope" mazmunli cheklov
bo'lmas edi (uning scope'i — butun platforma).

Bugungi `/customers/{id}` sahifasi — workspace ro'yxati (`GET
/v1/me/workspaces` orqali), arxivlangan workspace'lar (`GET
/v1/customers/{id}/workspaces/archived`), a'zolar, kill switch holati,
audit, AI provayder/byudjet sozlamalari — CustomerOwner'ga aynan O'Z
customer'i doirasida to'liq ko'rinish beradi, va RLS + aniq
`customer_id` tekshiruvlari (6.2/ADR-005) boshqa customer'ning
obyektlarini strukturaviy jihatdan ko'rsatmaydi. Yangi kod talab
qilinmadi.

## FR-ADM-002 — Rol va permission matritsasini ko'rish va tahrirlash

**Talab**: "System role permission'lari immutable; custom role
versiyalanadi."

**Xulosa: yangi Product Owner qarorini talab qiladi — qurilmadi.**
Bugungi avtorizatsiya modeli (`domain/security/roles.py`,
`application/authz_service.py`) FIKSIRLANGAN Python enum'lari
(`CustomerRole`, `WorkspaceRole`) va har bir `authorize_*` funksiyaning
o'z, qattiq yozilgan rol tekshiruvi orqali ishlaydi — bu Master
Instruction'ning o'zi ("Identity → Customer → Workspace → RBAC → Policy
→ Step-Up → Authorization zanjirini chetlab o'tma") talab qilgan
oldindan-belgilangan, tekshirilishi oson zanjir.

Bu talabni qurish uchun quyidagi savollarga Product Owner javob berishi
kerak — hech biri texnik taxmin bilan hal qilinadigan emas:
1. **Custom role'lar CustomerRole/WorkspaceRole'ning o'zini
   almashtiradimi, yoki ularning USTIGA qo'shiladigan qo'shimcha
   qatlammi?** Agar birinchisi bo'lsa, HAR BIR `authorize_*` funksiya
   (hozir ~20 ta) qattiq enum tekshiruvidan ma'lumotlar-bazasidan
   o'qiladigan permission-jadvaliga o'tishi kerak — bu authz
   zanjirining o'zini qayta yozish, minimal diff emas.
2. **Permission'lar qanday granulyarlikda ifodalanadi?** (bitta
   endpoint = bitta permission? yoki amal turi bo'yicha, masalan
   "task.create"?) Bu tanlov keyingi har bir yangi endpoint qanday
   ro'yxatga olinishini belgilaydi.
3. **"Versiyalash" nimani anglatadi amalda?** — `task_decisions`/
   `workspace_language_settings`ning append-only naqshi (har o'zgarish
   yangi qator) shu yerga ham tabiiy ko'chiriladi, lekin "eski versiyaga
   qaytarish" (rollback) qo'shimcha talab qilishi mumkin, buni ham
   Product Owner aniqlashi kerak.

**Taklif (agar/qachon boshlansa)**: yangi `domain/rbac` domeni,
`CustomRole`/`CustomRolePermission` jadvallari (RLS bilan,
append-only versiyalash — `task_decisions`ning aynan bir xil trigger
naqshi), va `authz_service.py`ga custom-role fallback (agar
foydalanuvchining CustomerRole/WorkspaceRole'i "custom" bo'lsa, DB'dan
o'qish) — lekin bu FAQAT yuqoridagi uchta savolga javob kelgandan
keyin boshlanishi kerak.

## FR-ADM-003 — Konnektor ulash, scope tanlash va uzish

**Talab**: "Scope kengaytirish qayta consent talab qiladi."

**Xulosa: yangi Product Owner qarorini talab qiladi — qurilmadi.**
Bugungi kunda bitta connector bor — Telegram (OD-002) — va u
`Settings.telegram_bot_token` orqali, operator darajasida (`.env`),
BIR MARTA sozlanadi. Hech qanday customer-darajasidagi "ulash/scope
tanlash/uzish" UI yo'q, chunki bunday oqim umuman mavjud emas — bot
tokeni platformaning o'zi ega, alohida customer'lar o'z Telegram
akkauntini "ulamaydi" (OAuth-uslubidagi consent flow emas).

Bu talabni qurish quyidagilarni talab qiladi:
1. **Umumiy, ko'p-connector consent modeli** — hozirgi Telegram
   integratsiyasi bitta, maxsus holat; "scope" tushunchasi (masalan
   "faqat xabar yuborish" vs "guruhlarni ham o'qish") hozircha
   HECH QANDAY connector uchun mavjud emas.
2. **Qaysi ikkinchi connector birinchi bo'lib shu modelni sinaydi?**
   — OD-002'ning o'zi Telegram'ni "birinchi connector" deb belgilagan,
   ikkinchisi hali Product Owner tomonidan tanlanmagan.
3. **Consent kim beradi — CustomerOwner customer nomidan, yoki har
   bir foydalanuvchi o'zi uchun?** — bu FR-ACT-006 (credential
   broker, 9.3, hali qurilmagan) bilan ham bog'liq.

**Taklif**: bu OD-002'ning o'zi kabi, keyingi real connector
tanlanganda birga hal qilinadigan qaror — spekulyativ, faqat
Telegram uchun "scope" o'ylab topish QOIDA 2'ni buzardi.

## FR-ADM-004 — Policy (ABAC) qoidalarini ko'rish va versiyalash

**Talab**: "Policy o'zgarishi audit qilinadi va rollback qilinadi."

**Xulosa: yangi Product Owner/arxitektura qarorini talab qiladi —
qurilmadi.** Bugungi avtorizatsiya modeli ABAC (Attribute-Based Access
Control) EMAS — u RBAC (Role-Based), fiksirlangan Python funksiyalari
bilan amalga oshirilgan (FR-ADM-002'da tasvirlangan). ABAC policy
mexanizmini (masalan, Open Policy Agent'ga o'xshash qoida-mexanizmi,
yoki ma'lumotlar bazasida saqlanadigan shart-asosli qoidalar) qo'shish —
"ko'rish va versiyalash" UI qurishdan OLDIN — o'zi butunlay yangi
subsystem, va bu ADR-001 (modular monolith) va Master Instruction'ning
"authz zanjirini chetlab o'tma" qoidasi bilan diqqat bilan
muvofiqlashtirilishi kerak bo'lgan arxitektura qarori: bugungi RBAC
zanjirining o'zi butun kod bazasi bo'ylab (10+ marta) xavfsizlik
ko'rib chiqishlarida tasdiqlangan; uni ABAC bilan almashtirish yoki
ustiga qo'shish yangi xavfsizlik yuzasi ochadi, buni sinchkovlik bilan
loyihalashtirmasdan boshlash xato bo'lardi.

**Taklif**: bu FR-ADM'ning eng katta, eng kech boshlanishi kerak bo'lgan
qismi — RBAC allaqachon barcha bugungi talablarni (10.2 jadvali)
qamrab olayotgan ekan, ABAC faqat RBAC yetarli bo'lmagan aniq,
haqiqiy stsenariy paydo bo'lganda (masalan "faqat ish vaqtida",
"faqat ma'lum IP diapazonidan") qurilishi kerak — bugun bunday
stsenariy yo'q.

## FR-ADM-005 — AI byudjeti va limitlarni belgilash

**Qurildi.** Bu sessiyaning asosiy kodi — `ai_budget_overrides` jadvali
(0025-migratsiya, RLS bilan), `ai_budget_service.set_customer_ai_
budget_override`/`get_customer_ai_budget_override`/`clear_customer_ai_
budget_override`, `PUT/GET/DELETE /v1/customers/{id}/ai-budget-limits`
(CustomerOwner-only yozish, CustomerOwner/Auditor o'qish —
`authorize_manage_ai_budget`/`authorize_view_ai_budget`), va customer
sahifasidagi forma. To'liq tafsilot CLAUDE.md'da.

Bu talab qanchalik "kichik xavfsiz qadam" bo'lganini ta'kidlash kerak:
enforcement (limitga yetganda bloklash) allaqachon `ai_budget_service.
reserve_budget` orqali mavjud edi — yetishmagani faqat SOZLASH
qobiliyati edi (bugungacha bitta, deployment-keng, fiksirlangan
`Settings` qiymati). Shuning uchun bu B toifasiga (mavjud infratuzilma
+ kichik yangi qatlam) to'g'ri keldi, C toifasiga emas.

## FR-ADM-006 — Feature flag va model routing sozlamasi

**Talab**: "O'zgarish darhol qo'llanadi va audit qilinadi."

**Xulosa: qisman allaqachon mavjud (model routing), qisman yangi
qaror talab qiladi (feature flag) — feature-flag qismi qurilmadi.**

**Model routing yarmi allaqachon mavjud**: `ai_preference_service`
(4 pog'onali ustuvorlik: suhbat pin > foydalanuvchi > workspace >
tizim standart) + `PUT /v1/workspaces/{id}/ai-preference` allaqachon
"model routing sozlamasi"ning aynan o'zi — workspace darajasida qaysi
provayder/model standart ishlatilishini belgilaydi, va o'zgarish
DARHOL qo'llanadi (keyingi chat burilishidan boshlab). **Bitta aniq
bo'shliq topildi**: bu o'zgarish HECH QACHON audit qilinmaydi — talab
esa aniq "audit qilinadi" deydi. Bu FR-ADM-005'ning o'zi hal qilgan
"versiyalangan-lekin-audit-qilinmagan xato bo'lardi" mulohazasining
xuddi o'zi.

**Taklif (keyingi kichik qadam, bu sessiyada QURILMADI, chunki
FR-ADM-006 o'zi "Should" darajasida va bu hujjatning maqsadi — barcha
oltitasini bir yo'la yopish emas, xaritalash)**: `ai_preference_
service.set_workspace_ai_preference`/`set_user_ai_preference`ga
`record_audit_event` chaqiruvi qo'shish, `ai_budget.override_set.v1`
naqshiga o'xshash `ai_preference.workspace_set.v1`/`ai_preference.
user_set.v1` event turlari bilan. Bu FR-ADM-006ni TO'LIQ yopmaydi
(feature flag yarmi hamon yo'q), lekin model-routing yarmini to'liq
qabul mezoniga mos qiladi.

**Feature flag yarmi yangi qaror talab qiladi**: bugungi kod bazasida
hech qanday umumiy feature-flag mexanizmi yo'q (funksiyalar
Settings orqali kompilyatsiya/deploy vaqtida yoqiladi/o'chiriladi, run-
time'da emas). Buni qurish uchun Product Owner qaysi funksiyalar
birinchi flag ostiga olinishini (hozircha hech biri so'ralmagan) va
flag'larning scope'i (customer-darajasidami, global) qaysi
bo'lishini aniqlashi kerak — bu ham spekulyativ boshlashga arzimaydi.

## Umumiy xulosa

Olti FR-ADM talabidan to'rttasi (FR-ADM-002/003/004, va FR-ADM-006ning
feature-flag yarmi) haqiqiy, yangi arxitektura yoki mahsulot qarorini
talab qiladi — bularning barchasi shu hujjatda taklif shaklida
qoldirildi, QOIDA 2ga ko'ra so'ralmasdan amalga oshirilmadi. Ikkitasi
(FR-ADM-001, model-routing yarmi FR-ADM-006) allaqachon mavjud UI/API
bilan qondirilgan edi. Bittasi (FR-ADM-005) haqiqiy, kichik,
xavfsiz qadam sifatida shu sessiyada qurildi.
