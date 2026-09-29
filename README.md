# ⚖️ Yurist Murojaat Bot — Citizen Legal Appeals & Consultation Dispatcher

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-Telegram-2CA5E0.svg?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Asyncpg-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Yurist Murojaat Bot** is an asynchronous Telegram-based citizen grievance, inquiry, and pro bono legal consultation dispatcher. Built for legal clinics and professional lawyer teams in Uzbekistan, it bridges public legal needs with licensed jurists through structured intake, automated triage, and administrative oversight.

---

## 🌟 Key Features

- **📩 Multi-Modal Citizen Intake**: Accepts citizen appeals via plain text, supporting evidentiary documents (`.pdf`, `.doc`, `.docx`), images, and archives.
- **👨‍💼 Operator & Lawyer Dispatching**: Assigns incoming inquiries to available specialist jurists with status progression tracking (`pending` ➡️ `accepted` ➡️ `closed` / `rejected`).
- **🛡️ Anti-Spam & Rate Limiting**: Built-in daily request limits, text length bounds, file size validation (up to 50 MB), and automated session timeouts.
- **📊 Reporting & Analytics**: Real-time export of daily and monthly consultation metrics into structured Excel workbooks.
- **🗄️ Robust Database Architecture**: High-concurrency PostgreSQL connection pooling with atomic state transitions and complete inquiry audit trails.

---

## 🏗️ Workflow Diagram

```
[ Citizen User ] ---> ( Telegram Bot UI ) ---> [ Ingestion & Validation ]
                                                        |
                                                        v
[ Admin / Jurist Group ] <--- [ Notification Queue ] <--+--> [ PostgreSQL DB ]
           |
           v
[ Lawyer Consultation / Response ] ---> [ Direct Citizen Delivery ]
```

---

## 🚀 Setup & Installation

### 1. Clone Repository
```bash
git clone https://github.com/mansurxongemini/yurist-murojaat-bot.git
cd yurist-murojaat-bot
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```env
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_IDS=12345678,87654321
GROUP_CHAT_ID=-100123456789
DATABASE_URL=postgresql://user:password@localhost:5432/legal_bot_db
MAX_MESSAGES_PER_SESSION=50
RATE_LIMIT_PER_DAY=3
```

### 3. Run Locally
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start Bot
python main.py
```

---

## 📜 License
Distributed under the **MIT License**.

## 👨‍💻 Author
- **Mansur Rustamov** ([@mansurxongemini](https://github.com/mansurxongemini))
- Tashkent State University of Law (TSUL)