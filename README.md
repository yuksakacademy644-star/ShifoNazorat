# 🏥 ShifoNazorat - Telegram Web App / Mini App Tizimi

Ushbu loyiha klinikadagi bemorlar bazasini yuritish, xizmat ko'rsatish sifatini nazorat qilish va norozi mijozlar haqida adminlarni ogohlantirish uchun yaratilgan. Tizim to'liq **Telegram Web App (Mini App)** formatida ishlaydi — ya'ni bot ichida sayt ko'rinishida ochiladi!

---

## 🛠 Texnologik Stack
*   **Backend (Server & API):** FastAPI (Uvicorn) va Python.
*   **Database:** SQLite.
*   **Frontend (Veb-interfeys):** HTML5, Vanilla CSS3 (Glassmorphism & Dark Mode) va JavaScript (Telegram WebApp SDK).
*   **Bot API:** `python-telegram-bot` (asinxron rejimda uvicorn lifespan orqali ishlaydi).

---

## 📂 Loyiha Tuzilishi

*   `bot.py` — Telegram botni va FastAPI serverni bir vaqtda ishga tushiruvchi asosiy fayl.
*   `web_server.py` — Web App uchun barcha API endpointlarni (bemor qo'shish, ro'yxat, statistika, baholash va sozlamalar) belgilaydi.
*   `database.py` — SQLite ma'lumotlar bazasi va til sozlamalarini boshqarish.
*   `utils.py` — Telefon raqamlarini normallashtirish yordamchisi.
*   `static/` — Web App veb-sayt resurslari:
    *   `index.html` — Bosh sahifa (Admin Paneli, Bemor Portali va Mehmon sahifasi).
    *   `style.css` — Zamonaviy dark-mode dizayn, progress barlar, switchlar va yulduzli baholash tugmalari.
    *   `app.js` — Telegram foydalanuvchisini aniqlash va API bilan bog'lanish mantiqi.
*   `.env` — Bot tokeni, Admin ID'lari, Guruh ID'si va Web App manzili.

---

## 🚀 O'rnatish va Ishga Tushirish

### 1. Kutubxonalarni yuklab olish:
Terminalda quyidagi buyruqni bajaring:
```bash
pip install -r requirements.txt
```

### 2. Sozlamalarni kiritish (`.env` fayli):
Loyiha papkasidagi `.env` faylini oching va quyidagilarni sozlang:
*   `BOT_TOKEN` — Bot tokeni (avtomatik kiritilgan).
*   `ADMIN_IDS` — Administratorlarning Telegram ID'si (vergul bilan ajratilgan).
*   `ADMIN_GROUP_ID` — Guruh ID'si (alertlar yuborish uchun).
*   `WEBAPP_URL` — Web App manzili. Mahalliy test qilish uchun `http://localhost:8000` qoldiring. Telegram ichida ochish uchun ngrok HTTPS manzilini yozing.

> [!TIP]
> **Admin ID-ni aniqlash:**
> Agar botda hali hech qanday admin sozlanmagan bo'lsa, siz botga kirib `/start` tugmasini bossangiz, bot sizning shaxsiy Telegram ID'ingizni ko'rsatadi. Uni `.env` fayliga qo'shing va botni qayta ishga tushiring.

### 3. Botni ishga tushirish:
```bash
python bot.py
```
Ushbu buyruq orqali **FastAPI web server** (port 8000 da) va **Telegram Bot** birgalikda bitta terminalda ishga tushadi!

---

## 📱 Botdan foydalanish va stsenariylar

### 1. Tilni tanlash va Ro'yxatdan o'tish (Patient Flow):
1. Foydalanuvchi botni boshlaganda, bot unga til tanlash tugmalarini ko'rsatadi: `🇺🇿 O'zbekcha` yoki `🇷🇺 Русский`.
2. Til tanlangandan so'ng, bot uning chat_id'sini tilga moslab bazaga saqlaydi va telefon raqamini ulashni so'raydi (`📱 Telefon raqamni yuborish`).
3. Raqam yuborilgach, bot shaxsni tasdiqlaydi va unga `🏥 ShifoNazorat` tugmasini taqdim etadi.

### 2. Bemor Portali (Xizmatni baholash):
*   Agar oddiy bemor `🏥 ShifoNazorat` tugmasini bossa, bot ichida veb-sayt ochiladi.
*   Saytda uning **oxirgi tashrif buyurgan shifokori** va **tashrif sanasi** ko'rsatiladi.
*   Agarda bemor hali xizmatni baholamagan bo'lsa, unga **1 dan 5 gacha yulduzli interaktiv baholash** taqdim etiladi.
*   Baholagandan so'ng:
    *   **4 yoki 5 ball** bersa — *"Katta rahmat! Kelgusi tashrifingiz uchun sizga 5% chegirma... Promokod: SHIFO5"* yozuvi ko'rsatiladi.
    *   **1, 2 yoki 3 ball** bersa — *"Fikringiz qabul qilindi. Tez orada bog'lanamiz"* yozuvi ko'rsatiladi va administratorlar guruhiga zudlik bilan norozilik ogohlantirishi yuboriladi.

### 3. Administrator Boshqaruv Paneli (Admin Dashboard):
Agarda `.env` faylida admin sifatida kiritilgan foydalanuvchi `🏥 Web App Dashboard` tugmasini bossa, u to'liq boshqaruv paneliga kiradi:
1.  **📊 Statistika tab-i:** Klinikadagi umumiy bemorlar soni, faol bemorlar, norozi bemorlar soni, o'rtacha xizmat bahosi va reyting progress-bari dinamik ravishda yangilanadi.
2.  **➕ Qo'shish tab-i:** Saytning o'zida yangi bemor ismini, telefonini, shifokorini va tashrif sanasini kiritib qo'shish imkoniyati (bugungi sanani tanlash uchun qulay "Bugun" tugmasi bor).
3.  **📋 Bemorlar tab-i:** Baza ro'yxati chiqadi. Tepada **Live Search** bor — ism yoki shifokor nomini yozishingiz bilan ro'yxat shu zahoti filtrlanadi.
    *   *Testlash uchun qulaylik:* Agar bemor botga ulangan bo'lsa, uning ostida `✉️ Eslatma yuborish` tugmasi chiqadi. Uni bossangiz, bemorning Telegramiga baholash xabari **shu zahoti** yuboriladi.
4.  **⚙️ Sozlamalar tab-i:** Sayt orqali avtomatik xabarlarni yoqish/o'chirish va **Test rejimi**ni (kutilish vaqtini 1 daqiqa qilish) yoqish/o'chirish switchlari mavjud.
