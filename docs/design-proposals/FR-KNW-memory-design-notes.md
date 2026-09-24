# FR-KNW-002..009 va FR-CTL-004 (Knowledge/RAG pipeline + Memory): dizayn eslatmalari

**Holat**: taklif/eslatma hujjati, kod emas. TRD'ning to'liq talab-ID
sweep'ida FR-KNW-003..009 hech qayerda (kod ham, CLAUDE.md ham) ID
bo'yicha keltirilmagani aniqlandi — faqat FR-KNW-001'ning o'z commit
xabarida "FR-KNW-002 dan boshlab... barchasi qurilmadi" deb JAMOAVIY
zikr qilingan edi. QOIDA 2 ("ID'siz talab yo'q") buni to'liq
qondirmaydi — bu hujjat har bir ID'ni alohida, TRD'ning o'z matniga
(3.5-bo'lim va 8-bo'lim, `docs/DODA-TRD-v2.0.docx`) qarab baholaydi.

## Xulosa jadvali

| ID | Toifa | Holat |
|---|---|---|
| FR-KNW-001 | — | **Qurildi** (avvalgi sessiyada) — fayl ingest, tur/hajm/malware validatsiyasi |
| FR-KNW-002 | C | Haqiqiy embedding chaqiruvi kerak — bloklangan |
| FR-KNW-003 | C | FR-KNW-002'ning ustiga quriladi — bloklangan |
| FR-KNW-004 | C | FR-KNW-002/003'ning ustiga quriladi — bloklangan |
| FR-KNW-005 | C | FR-KNW-002'ning "indeks"i mavjud emas — bloklangan |
| FR-KNW-006 | C | FR-KNW-002/003'ning ustiga quriladi — bloklangan |
| FR-KNW-007 / FR-CTL-004 | C (qisman A) | "Preference" xotira turi allaqachon boshqa ID'lar ostida qurilgan; qolgan to'rt turi (Working/Episodic/Semantic/Sensitive) yangi PO qarori kerak |
| FR-KNW-008 | C | FR-KNW-002'ning ustiga quriladi — bloklangan |
| FR-KNW-009 | C | FR-KNW-002'ning ustiga quriladi — bloklangan |

Toifalar FR-ADM design-proposal hujjatining o'zi bilan bir xil: (A)
allaqachon mavjud, faqat ID bilan bog'lash kerak edi; (B) mavjud
infratuzilma bilan kichik xavfsiz qadam; (C) yangi Product Owner/
arxitektura qarorini yoki hali qurilmagan tashqi bog'liqlikni talab
qiladi.

## Nega FR-KNW-002..006/008/009 hammasi bitta blokerga bog'liq

TRD 3.5-bo'limining o'zi buni zanjir sifatida yozadi: **002 (parsing→
chunking→embedding→indexing)** — bu zanjirning eng old bo'g'ini, va
qolgan oltitasining HAR BIRI unga tayanadi:
- **003** (gibrid retrieval: metadata+keyword+vector+reranking) — 002
  yaratgan vektor indeksisiz "vector" qismi umuman mavjud emas.
- **004** (citation-required rejim, groundedness eval) — 003'ning
  retrieval natijasisiz "manba"ning o'zi yo'q.
- **005** (o'chirish so'rovi indeks/blob/cache/derived artifactlarga
  tarqaladi) — 002 yaratadigan "indeks" hali mavjud emas, tarqatiladigan
  narsa yo'q.
- **006** (manba topilmasa ochiq aytish) — 003/004'ning retrieval+
  citation natijasisiz "topilmadi" holatini ham simulyatsiya qilib
  bo'lmaydi (haqiqiy emas, soxta bo'lardi).
- **008** (katta fayl uchun asinxron ingest+progress) — 002'ning o'z
  sinxron/asinxron ingest jarayonining kengaytmasi, 002'siz mustaqil
  ma'no yo'q.
- **009** (hujjat versiyalanishi, eskirgan versiya retrieval'dan
  chiqarilishi) — versiyalash DB darajasida qurilishi mumkin edi, lekin
  "retrieval'dan chiqarish" 003'ning o'z retrieval mexanizmini talab
  qiladi — mustaqil qurish keyin 003 qurilganda qayta ishlashga
  majbur qilardi.

**002'ning o'zi nega bloklangan**: real, ishlaydigan embedding
chaqiruvi kerak (OpenAI/Gemini/Claude'ning embeddings endpoint'i yoki
alohida embedding provayder). Bu muhitning tarmoq siyosati uchala AI
provayderning ham haqiqiy API'siga chiqishni bloklaydi (ADR-008/
ADR-009'ning o'z "honest limitation" bo'limlarida allaqachon
hujjatlashtirilgan, xuddi shu cheklov) — demak embedding chaqiruvini
qurish "tekshirib bo'lmaydigan kod yozish" bo'lardi, QOIDA 1'ning o'zi
buni taqiqlaydi. Bundan tashqari, pgvector uchun DB sxemasi (chunk
jadvali, embedding ustuni, indeks turi — HNSW/IVFFlat) va chunking
strategiyasi (fixed-size vs semantic) haqiqiy Product Owner/texnik
qarorini talab qiladi — bular ham hali so'ralmagan.

## FR-KNW-007 / FR-CTL-004 — Memory: qisman allaqachon qurilgan

**Talab (TRD 8-bo'lim)**: beshta memory turi — Working (joriy chat
konteksti), **Preference** (til, format, ism, uslub — "foydalanuvchiga
ko'rinadi va tahrirlanadi"), Episodic (oldingi task natijasi),
Semantic (tasdiqlangan fakt/knowledge), Sensitive (sog'liq/moliya/
sirlar — "default o'chiq, explicit consent"). FR-CTL-004'ning qabul
mezoni: "Sensitive memory default o'chiq; yoqish explicit consent
talab qiladi."

**Preference turi — allaqachon, boshqa ID'lar ostida, mustaqil
qurilgan**: TRD'ning o'z misoli ("til, format, ism, uslub") aynan
mos keladigan narsalar bu kod bazasida allaqachon bor —
`Conversation.pinned_language`/`WorkspaceLanguageSetting` (FR-CONV-001/
FR-WKS-007), `UserAIPreference`/`WorkspaceAIPreference` (FR-ADM-006) —
barchasi "foydalanuvchiga ko'rinadi va tahrirlanadi" (GET/PUT/DELETE
endpoint'lari, frontend forma) va "provenance" (audit event — FR-ADM-006
tuzatishidan keyin) talabini qondiradi. Bu qurilganda "memory" atamasi
ishlatilmagan edi — TRD 8-bo'limining o'zi buni keyinroq o'qib
solishtirilganda aynan shu qatlamning bir qismi ekani ma'lum bo'ldi.

**Working/Episodic/Semantic/Sensitive — yangi Product Owner qarorini
talab qiladi, qurilmadi**:
1. **Working** (joriy chatdagi vaqtinchalik kontekst) — bu allaqachon
   `conversation_service.stream_message`ning o'z `history`si (suhbat
   davomidagi xabarlar) orqali AMALDA mavjud, lekin TRD uni alohida
   "memory" sifatida nomlab, retention/consent siyosatiga bog'laydi —
   buni alohida ID sifatida "qurish" kerakmi, yoki mavjud suhbat
   tarixining o'zi yetarlimi, Product Owner hal qilishi kerak savol.
2. **Episodic** ("oldingi task natijasi", "relevance + consent" bilan
   yoziladi) — bu FR-KNW-002/003'ning retrieval mexanizmiga tayanadi
   (task natijasini keyingi suhbatda "eslash" degani — semantik qidiruv
   kerak), demak shu blokerning o'zi bilan bog'liq.
3. **Semantic** ("tasdiqlangan fakt yoki knowledge", versiyalangan) —
   xuddi Episodic kabi, FR-KNW-002/003'ga bog'liq.
4. **Sensitive** (default o'chiq, explicit consent, "secretlar
   butunlay chiqarib tashlanadi") — bu OD-003'ning kengaytmasi bo'lar
   edi (`doda.ai.outbound_guard`/`doda.ai.data_classification`
   allaqachon C4/C5'ni bloklaydi, lekin bu YO'QLIKKA majburlaydi, uni
   "consent bilan yoqish mumkin memory" qilib saqlash butunlay boshqa,
   ancha xavfliroq xususiyat — qanday shifrlanadi, kim ko'ra oladi,
   qachon o'chiriladi — hammasi yangi qaror).

8.1-bo'limning "Memory write gate" (7 bosqichli ketma-ket tekshiruv:
scope→sensitivity→consent→dedup→provenance→retention→encryption) va
8.2'ning "Retrieval ACL" (filter-before-vector) — ikkalasi ham FR-KNW-
002/003 mavjud bo'lmasa amalga oshirib bo'lmaydigan mexanizmlar,
shuning uchun bu ham asosiy blokerning bir qismi.

**Taklif (agar/qachon boshlansa)**: FR-KNW-002 (embedding+chunking
pipeline) qurilishi bilan bir vaqtda, Working/Episodic/Semantic uchun
`domain/memory` yangi domeni — 8.1'ning gate'ini bitta, markazlashtirilgan
`write_memory_candidate(...)` funksiyasi sifatida (kelajakda 8.1'ning
yetti bosqichini alohida-alohida qo'shish o'rniga, boshidanoq to'liq
zanjir bilan). Sensitive turi esa alohida, keyinroq Product Owner
qaroridan keyin — bu eng yuqori xavfli, eng kech boshlanishi kerak
qism.

## Umumiy xulosa

To'qqizta FR-KNW ID'idan bittasi (001) qurilgan; oltitasi (002/003/004/
005/006/008/009) bitta umumiy blokerga (real embedding chaqiruvi + DB
sxema qarori) bog'liq va shu bloker yechilmaguncha ketma-ket
qurilmaydi. FR-KNW-007/FR-CTL-004 (memory) — beshta turdan bittasi
(Preference) allaqachon boshqa ID'lar ostida qondirilgan, qolgan
to'rttasi ham yuqoridagi bloker bilan (Episodic/Semantic) yoki yangi,
alohida Product Owner qaroriga (Sensitive consent modeli) bog'liq.
