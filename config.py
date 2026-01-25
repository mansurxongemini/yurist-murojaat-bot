# config.py
import os
from typing import List
from dotenv import load_dotenv
load_dotenv()

def get_env_list(key: str, default: str = "") -> List[int]:
    """Convert comma-separated IDs to list of integers"""
    value = os.getenv(key, default)
    return [int(x.strip()) for x in value.split(",") if x.strip()]


# Telegram settings
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", 0))
ADMIN_IDS = get_env_list("ADMIN_IDS")

# Bot settings
MAX_MESSAGES_PER_SESSION = int(os.getenv("MAX_MESSAGES_PER_SESSION", 50))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", 3500))
MAX_TOPIC_LENGTH = int(os.getenv("MAX_TOPIC_LENGTH", 100))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 50))
SESSION_TIMEOUT_HOURS = int(os.getenv("SESSION_TIMEOUT_HOURS", 24))
RATE_LIMIT_PER_DAY = int(os.getenv("RATE_LIMIT_PER_DAY", 3))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
REQUIRED_CHANNEL_ID = os.getenv("REQUIRED_CHANNEL_ID", "")

# Database Pool Settings
DB_MIN_CONN = int(os.getenv("DB_MIN_CONN", 1))
DB_MAX_CONN = int(os.getenv("DB_MAX_CONN", 20))

# Branding
BOT_NAME = os.getenv("BOT_NAME", "Yurist Bot")
TEAM_NAME = os.getenv("TEAM_NAME", "Yuristlar Jamoasi")

# Validations
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN kiritilmagan!")
if not GROUP_CHAT_ID:
    raise ValueError("GROUP_CHAT_ID kiritilmagan!")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS kiritilmagan!")

# Allowed file extensions
_allowed_ext = os.getenv("ALLOWED_EXTENSIONS", ".pdf,.doc,.docx,.xls,.xlsx,.txt,.zip,.rar,.jpg,.png")
ALLOWED_FILE_EXTENSIONS = {ext.strip() for ext in _allowed_ext.split(",") if ext.strip()}

# Status mappings
STATUS_EMOJIS = {
    'pending': '⏳',
    'accepted': '✅',
    'rejected': '❌',
    'closed': '🔒'
}

STATUS_TEXTS = {
    'pending': 'Kutilmoqda',
    'accepted': 'Qabul qilindi # Tez orada javob beramiz',
    'rejected': 'Rad etildi',
    'closed': 'Javob berildi'
}