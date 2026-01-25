# Yurist Murojaat Bot

Bu Telegram bot foydalanuvchilardan yuridik murojaatlarni qabul qilish, ularni operatorlarga yo'naltirish va javob berish tizimini avtomatlashtirish uchun mo'ljallangan.

## Xususiyatlari

- 📩 Murojaatlarni qabul qilish (matn, rasm, video, hujjat).
- 👨‍💼 Operatorlar va Admin paneli.
- 📊 Statistika va Excel hisobotlar.
- 🔄 Qayta murojaat qilish tizimi.
- 🗄 PostgreSQL ma'lumotlar bazasi.

## O'rnatish

1. Repozitoriyni klonlang:
   ```bash
   git clone https://github.com/username/repo-name.git
   cd repo-name
   ```

2. Virtual muhit yarating va aktivlashtiring:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/Mac:
   source venv/bin/activate
   ```

3. Kutubxonalarni o'rnating:
   ```bash
   pip install -r requirements.txt
   ```

4. `.env` faylini yarating va sozlang:
   ```env
   BOT_TOKEN=sizning_bot_tokeningiz
   ADMIN_IDS=12345678,87654321
   GROUP_CHAT_ID=-100123456789
   DATABASE_URL=postgresql://user:password@localhost:5432/dbname
   ```

5. Botni ishga tushiring:
   ```bash
   python main.py
   ```