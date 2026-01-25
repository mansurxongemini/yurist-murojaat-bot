# utils.py
import logging
import os
from typing import Tuple, Optional
from telegram import User, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from config import ALLOWED_FILE_EXTENSIONS

logger = logging.getLogger(__name__)

class BotError(Exception):
    """Base bot exception"""
    pass


class RateLimitError(BotError):
    """Rate limit exceeded"""
    pass


def get_user_contact_text(user: User) -> str:
    """Get user contact info (privacy-safe)"""
    contact = f"👤 <b>Ism:</b> {user.first_name} {user.last_name or ''}\n"
    contact += f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
    
    if user.username:
        contact += f"🔹 <b>Username:</b> @{user.username}\n"
        contact += f"💬 <b>Chat:</b> t.me/{user.username}"
    else:
        contact += f"⚠️ <b>Username:</b> Yo'q\n"
        contact += f"💬 <b>Direct:</b> tg://user?id={user.id}"
    
    return contact


def extract_message_data(message) -> Tuple[Optional[str], Optional[str], str, Optional[int], Optional[str]]:
    """Extract file_id, text, type, size, and extension from message"""
    text = message.text or message.caption
    file_extension = None
    
    if message.photo:
        return message.photo[-1].file_id, text, "photo", message.photo[-1].file_size, None
    elif message.video:
        ext = os.path.splitext(message.video.file_name)[1].lower() if message.video.file_name else None
        return message.video.file_id, text, "video", message.video.file_size, ext
    elif message.voice:
        return message.voice.file_id, text, "voice", message.voice.file_size, None
    elif message.document:
        ext = os.path.splitext(message.document.file_name)[1].lower() if message.document.file_name else None
        return message.document.file_id, text, "document", message.document.file_size, ext
    else:
        return None, text, "text", None, None


def validate_file_extension(ext: Optional[str]) -> bool:
    """Validate file extension"""
    if not ext:
        return True
    return ext in ALLOWED_FILE_EXTENSIONS



def setup_logging(log_file: str = "bot.log", level: str = "INFO"):
    """Logging sozlash - FAQAT konsolga chiqarish uchun"""
    import logging
    
    class EmojiFilter(logging.Filter):
        def __init__(self, remove_emojis=True):
            super().__init__()
            self.remove_emojis = remove_emojis
            self.emojis = ['🚀', '✅', '❌', '⚠️', '📊', '📋', '👤', '📝', '⏰', '🤖', '👨‍💻', '📩', '📭', '⏳', '🔒', '📌', '🆔', '📅', '⭐', '▶️', '🗑️', '📨', '🎬', '🔧', '📁', '🔍', '👁️']
        
        def filter(self, record):
            if self.remove_emojis:
                msg = str(record.msg)
                for emoji in self.emojis:
                    msg = msg.replace(emoji, '')
                record.msg = msg
            return True

    # Loggerni tozalash (eski handlerlarni o'chirish)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.addFilter(EmojiFilter(remove_emojis=False))
        elif isinstance(handler, logging.StreamHandler):
            handler.addFilter(EmojiFilter(remove_emojis=True))


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    from config import ADMIN_IDS
    return user_id in ADMIN_IDS


def rate_limit(func):
    """Decorator for rate limiting"""
    from functools import wraps
    from database import check_rate_limit, get_setting
    from config import RATE_LIMIT_PER_DAY
    
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        
        # Get dynamic limit
        dynamic_limit = get_setting("rate_limit_per_day")
        limit = int(dynamic_limit) if dynamic_limit else RATE_LIMIT_PER_DAY
        
        allowed, remaining = check_rate_limit(user.id, limit)
        
        if not allowed:
            await update.message.reply_text(
                f"⚠️ Sizning kunlik limitingiz ({limit} ta murojaat) tugagan!\n"
                "Ertaga qayta urinib ko'ring.",
                reply_markup=context.bot_data.get('main_keyboard')
            )
            return
        
        return await func(update, context, *args, **kwargs)
    return wrapper


async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Foydalanuvchi kanalga obuna bo'lganligini tekshirish"""
    from database import get_setting
    channel_id = get_setting("required_channel_id")
    
    if not channel_id:
        return True
        
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except BadRequest:
        return True
    except Exception as e:
        logger.error(f"Membership check error: {e}")
        return True


def subscription_required(func):
    """Decorator: Kanalga obuna bo'lishni talab qilish"""
    from functools import wraps
    from database import get_setting
    
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)
            
        if is_admin(user.id):
            return await func(update, context, *args, **kwargs)
            
        if await check_membership(user.id, context):
            return await func(update, context, *args, **kwargs)
            
        channel_id = get_setting("required_channel_id")
        keyboard = [
            [InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subscription")]
        ]
        
        msg = f"⚠️ <b>Botdan foydalanish uchun kanalimizga obuna bo'ling!</b>\n\nKanal: {channel_id}"
        
        if update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    return wrapper


def check_ban(func):
    """Decorator: Check if user is banned"""
    from functools import wraps
    from database import is_user_blocked
    
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user and is_user_blocked(user.id):
            if update.callback_query:
                await update.callback_query.answer("🚫 Siz botdan bloklangansiz!", show_alert=True)
            elif update.message:
                await update.message.reply_text("🚫 <b>Siz botdan bloklangansiz!</b>", parse_mode='HTML')
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ==================== TRANSLATIONS ====================
TRANSLATIONS = {
    'uz': {
        'main_new_case': "📩 Yangi murojaat",
        'main_my_cases': "📋 Mening murojaatlarim",
        'main_stats': "📊 Mening statistikam",
        'main_templates': "📄 Ariza shablonlari",
        'main_booking': "📅 Qabulga yozilish",
        'main_faq': "❓ FAQ",
        'main_info': "ℹ️ Bot haqida",
        'main_lang': "🌐 Tilni o'zgartirish",
        'main_offers': "💡 Takliflar",
        'placeholder': "Tanlang...",
        'welcome': "👋 Assalomu alaykum!\n\n<b>🤖 {bot_name} ga xush kelibsiz!</b>\n\n✅ Biz sizga yuridik maslahat beramiz.",
        'lang_select': "🇺🇿 Iltimos, tilni tanlang:\n🇷🇺 Пожалуйста, выберите язык:",
        'lang_set': "✅ Til o'zgartirildi: O'zbek tili",
        'bot_info_text': "ℹ️ <b>Bot Haqida</b>\n\nBu bot orqali siz yuridik yordam olishingiz mumkin.\n\n1. 📩 Yangi murojaat tugmasini bosing.\n2. Mavzuni yozing.\n3. Muammoni batafsil tushuntiring.",
        'cancelled': "❌ Bekor qilindi.",
    },
    'ru': {
        'main_new_case': "📩 Новое обращение",
        'main_my_cases': "📋 Мои обращения",
        'main_stats': "📊 Моя статистика",
        'main_templates': "📄 Шаблоны заявлений",
        'main_booking': "📅 Запись на прием",
        'main_faq': "❓ FAQ",
        'main_info': "ℹ️ О боте",
        'main_lang': "🌐 Изменить язык",
        'main_offers': "💡 Предложения",
        'placeholder': "Выберите...",
        'welcome': "👋 Здравствуйте!\n\n<b>🤖 Добро пожаловать в {bot_name}!</b>\n\n✅ Мы предоставим вам юридическую консультацию.",
        'lang_select': "🇺🇿 Iltimos, tilni tanlang:\n🇷🇺 Пожалуйста, выберите язык:",
        'lang_set': "✅ Язык изменен: Русский",
        'bot_info_text': "ℹ️ <b>О боте</b>\n\nЧерез этот бот вы можете получить юридическую помощь.\n\n1. Нажмите 📩 Новое обращение.\n2. Напишите тему.\n3. Подробно опишите проблему.",
        'cancelled': "❌ Отменено.",
    }
}

def get_text(key: str, user_id: int = None, lang: str = None, **kwargs) -> str:
    """Tarjima matnini olish"""
    from database import get_user_language
    
    if not lang and user_id:
        lang = get_user_language(user_id)
    
    if not lang:
        lang = 'uz'
        
    texts = TRANSLATIONS.get(lang, TRANSLATIONS['uz'])
    text = texts.get(key, key)
    
    if kwargs:
        return text.format(**kwargs)
    return text