# handlers.py
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, User
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import Forbidden, BadRequest
from functools import wraps

import asyncio
from config import *
from database import *
from utils import *
import re
import io
import openpyxl
import json

logger = logging.getLogger(__name__)


# State constants
BROADCAST_WAITING = 1
SUGGESTION_WAITING = 2
ADMIN_ADD_OP_NAME, ADMIN_ADD_OP_GENDER, ADMIN_ADD_OP_ID, RE_APPEAL_COLLECTING, ADMIN_SET_CHANNEL, ADMIN_SET_WELCOME, ADMIN_BAN_ID, ADMIN_SET_LIMIT = range(20, 28)
FAQ_QUESTION, FAQ_ANSWER = range(30, 32)
ADMIN_ADD_TEMPLATE_FILE, ADMIN_ADD_TEMPLATE_NAME = range(40, 42)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/broadcast komandasi - 1-qadam"""
    user = update.effective_user
    
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ Siz admin emassiz!")
        return ConversationHandler.END
    
    if not context.args:
        await update.message.reply_text(
            "📢 <b>Broadcast yuborish:</b>\n\n"
            "Foydalanish: <code>/broadcast matn</code>",
            parse_mode='HTML'
        )
        return ConversationHandler.END
    
    # Xabarni saqlash (context.user_data emas, context.chat_data ishlatamiz)
    context.chat_data['broadcast_text'] = " ".join(context.args)
    
    keyboard = [["✅ Ha, yuborish", "❌ Yo'q, bekor qilish"]]
    await update.message.reply_text(
        f"📢 <b>Broadcast tekshirish:</b>\n\n{context.chat_data['broadcast_text']}\n\nYuborilsinmi?",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    
    return BROADCAST_WAITING


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiqlash tugmasi bosilganda - 2-qadam"""
    users = get_all_users()
    
    if not users:
        await update.message.reply_text("❌ Hech qanday foydalanuvchi topilmadi!")
        return ConversationHandler.END
    
    msg = await update.message.reply_text(f"⏳ {len(users)} ta foydalanuvchiga yuborilmoqda...")
    
    success, failed = 0, 0
    
    for idx, user_id in enumerate(users):
        try:
            await context.bot.send_message(
                user_id,
                f"📢 <b>Botdan yangilik:</b>\n\n{context.chat_data['broadcast_text']}",
                parse_mode='HTML'
            )
            success += 1
            
            # Progress har 10 ta foydalanuvchidan keyin
            if idx % 10 == 0:
                percent = (idx / len(users)) * 100
                await msg.edit_text(f"⏳ Yuborilmoqda... {percent:.1f}%")
            
            # Tezlikni oshirish (1000 user uchun 500s emas, 50s ketadi)
            await asyncio.sleep(0.05)
            
        except Exception as e:
            failed += 1
            logger.error(f"User {user_id} ga xato: {e}")
    
    await msg.edit_text(
        f"✅ <b>Yakunlandi!</b>\n\n✅ Muvaffaqiyatli: {success}\n❌ Bloklangan: {failed}",
        parse_mode='HTML'
    )
    
    await update.message.reply_text("📢 Broadcast yakunlandi!", reply_markup=MAIN_KEYBOARD)
    
    # Tozalash
    context.chat_data.clear()
    return ConversationHandler.END


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bekor qilish tugmasi bosilganda"""
    await update.message.reply_text("❌ Broadcast bekor qilindi.", reply_markup=MAIN_KEYBOARD)
    context.chat_data.clear()
    return ConversationHandler.END


# Keyboard definitions
def get_main_keyboard(lang: str = 'uz') -> ReplyKeyboardMarkup:
    """Asosiy menyu klaviaturasi (Tilga moslashgan)"""
    t = TRANSLATIONS.get(lang, TRANSLATIONS['uz'])
    return ReplyKeyboardMarkup(
        [[t['main_new_case'], t['main_my_cases']],
         [t['main_booking'], t['main_templates']],
         [t['main_faq'], t['main_info']],
         [t['main_offers'], t['main_lang']]],
        resize_keyboard=True, input_field_placeholder=t.get('placeholder', "Tanlang...")
    )

SESSION_KEYBOARD = ReplyKeyboardMarkup(
    [["✅ Murojaatni yuborish"],
     ],
    resize_keyboard=True, input_field_placeholder="Yoki xabar yuboring..."
)

PREVIEW_KEYBOARD = ReplyKeyboardMarkup(
    [["✅ Yana xabar yozish"],
     ["📝 Boshqatdan yozish", "❌ Bekor qilish"]],
    resize_keyboard=True, input_field_placeholder="Tasdiqlash yoki tahrirlash..."
)

def get_approval_keyboard(case_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Qabul qilish", callback_data=f"approve_{case_number}"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"reject_{case_number}")],
        [InlineKeyboardButton("👤 Biriktirish", callback_data=f"assign_{case_number}")]
    ])

def get_re_appeal_keyboard(case_number: int) -> InlineKeyboardMarkup:
    """Qayta murojaat uchun klaviatura (Biriktirish tugmasisiz)"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Qabul qilish", callback_data=f"approve_{case_number}"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"reject_{case_number}")
    ]])

# ==================== Conversation States ====================
TOPIC, COLLECTING = range(2)


# ==================== Command Handlers ====================
# handlers.py faylida start funksiyasini almashtirish:

@check_ban
@subscription_required
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Tilni tekshirish
    lang = get_user_language(user.id)
    if not lang:
        await show_language_selection(update, context)
        return
    
    context.user_data.clear()
    
    # Bazadan matnni olish
    welcome_text = get_setting("welcome_message")
    
    if not welcome_text:
        welcome_text = get_text('welcome', lang=lang, bot_name=BOT_NAME)
    
    # Callback orqali kelgan bo'lsa (masalan til tanlash yoki obuna tekshirish)
    # Eski xabarni o'chiramiz va yangisini yuboramiz (ReplyKeyboard uchun)
    if update.callback_query:
        try:
            await update.callback_query.delete_message()
        except Exception:
            pass

    # Xabar yuborish (barcha holatlar uchun universal)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=welcome_text,
        parse_mode='HTML',
        reply_markup=get_main_keyboard(lang)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    user = update.effective_user
    
    if cancel_session(user.id):
        lang = get_user_language(user.id)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=get_text('cancelled', lang=lang),
            reply_markup=get_main_keyboard(lang)
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Bekor qilish uchun aktiv murojaat topilmadi.",
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
    
    context.user_data.clear()
    return ConversationHandler.END


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check case status by number"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text("⚠️ Iltimos, murojaat raqamini kiriting: /status 123")
        return
    
    try:
        case_number = int(context.args[0])
        case = get_case_status(case_number, user.id)
        
        if not case:
            await update.message.reply_text("⚠️ Sizning bunday murojaatingiz topilmadi!")
            return
        
        status_emoji = STATUS_EMOJIS.get(case['status'], '📝')
        status_text = STATUS_TEXTS.get(case['status'], 'Noma\'lum')
        
        await update.message.reply_text(
            f"📋 <b>Murojaat #{case['case_number']}</b>\n\n"
            f"📌 <b>Mavzu:</b> {case['topic'] or '—'}\n"
            f"📊 <b>Holat:</b> {status_emoji} {status_text}\n"
            f"📅 <b>Yaratilgan:</b> {case['created_at'][:16]}",
            parse_mode='HTML',
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
    except ValueError:
        await update.message.reply_text("⚠️ Noto'g'ri raqam formati!")


# ==================== Message Handlers ====================
@check_ban
@subscription_required
@rate_limit
async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new case session"""
    user = update.effective_user
    
    # Maintenance check (Texnik tanaffus tekshiruvi)
    if get_setting("maintenance_mode") == "on" and not is_admin(user.id):
        await update.message.reply_text(
            "⚠️ <b>Texnik Tanaffus</b>\n\n"
            "Botda hozirda profilaktika ishlari olib borilmoqda.\n"
            "Iltimos, birozdan so'ng urinib ko'ring.",
            parse_mode='HTML'
        )
        return

    # Clear any existing session
    context.user_data.clear()
    cancel_session(user.id)
    
    session_id = create_session(user.id)
    context.user_data['session_id'] = session_id
    context.user_data['awaiting_topic'] = True
    
    logger.info(f"User {user.id} started new session {session_id}")
    
    await update.message.reply_text(
        "✅ Yangi murojaat yaratildi.\n\n"
        "✍️ Iltimos, murojaatingizning *qisqacha mavzu nomini* yuboring:\n\n"
        "🔹 *Namuna*: Oilaviy Nizo\n"
        "🔹 *Namuna*: To'lov qaytarilmasligi, Tuhmat",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )


async def collect_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Collect messages for session"""
    user = update.effective_user
    message = update.message
    
    # Check if waiting for topic
    if context.user_data.get('awaiting_topic'):
        topic = message.text
        
        if not topic:
            await message.reply_text("⚠️ Iltimos, matnli mavzu nomini yuboring.")
            return
        
        if len(topic) > MAX_TOPIC_LENGTH:
            await message.reply_text(f"⚠️ Mavzu nomi {MAX_TOPIC_LENGTH} belgidan oshmasin! Sizniki: {len(topic)}")
            return
        
        session_id = context.user_data['session_id']
        update_session_topic(session_id, topic)
        context.user_data['awaiting_topic'] = False
        
        logger.info(f"User {user.id} set topic: {topic}")
        
        await message.reply_text(
            f"✅ Mavzu qabul qilindi: <b>{topic}</b>\n\n"
            "Endi murojaatingizning to'liq matnini yuboring:\n"
            "• Matn • Rasm • Video • Ovozli xabar • Fayl\n\n"
            "Barcha xabarlarni yuborgach, ✅Murojaatni yuborish tugmasini bosing.",
            parse_mode='HTML',
            reply_markup=SESSION_KEYBOARD
        )
        return
    
    # Check active session
    session_data = get_active_session(user.id)
    if not session_data:
        await message.reply_text(
            "⚠️ Aktiv murojaat topilmadi. \"📩 Yangi murojaat\" bosing.",
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
        return
    
    session_id = session_data['session_id']
    update_session_activity(session_id)
    
    messages = get_session_messages(session_id)
    if len(messages) >= MAX_MESSAGES_PER_SESSION:
        await message.reply_text(f"⚠️ Maksimum {MAX_MESSAGES_PER_SESSION} ta xabar!")
        return
    
    # Extract message data
    text = message.text or message.caption
    if text and len(text) > MAX_TEXT_LENGTH:
        await message.reply_text(f"⚠️ Matn {MAX_TEXT_LENGTH} belgidan oshmasin! Sizniki: {len(text)}")
        return
    
    file_id, msg_text, msg_type, file_size, file_ext = extract_message_data(message)
    
    if file_size and file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await message.reply_text(
            f"⚠️ Fayl hajmi {MAX_FILE_SIZE_MB}MB dan oshmasin!\n"
            f"Sizning faylingiz: {file_size / 1024 / 1024:.1f}MB"
        )
        return
    
    if file_ext and not validate_file_extension(file_ext):
        await message.reply_text(
            f"⚠️ Bu fayl turi (.{file_ext}) ruxsat etilmagan!\n"
            f"Ruxsat etilgan: {', '.join(ALLOWED_FILE_EXTENSIONS)}"
        )
        return
    
    try:
        add_session_message(session_id, msg_type, msg_text, file_id, file_size)
        await message.reply_text("🕔 Shu yetarlimi? Agar to'liq yozib bo'lmagan bo'lsangiz yozishni davom ettiiring.", reply_markup=SESSION_KEYBOARD)
    except Exception as e:
        logger.error(f"Failed to add message: {e}", exc_info=True)
        await message.reply_text("⚠️ Xabarni saqlashda xatolik.", reply_markup=SESSION_KEYBOARD)


async def preview_case(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview current session"""
    user = update.effective_user
    
    if context.user_data.get('awaiting_topic'):
        await update.message.reply_text("⚠️ Avval mavzu nomini yuboring!")
        return
    
    session_data = get_active_session(user.id)
    if not session_data:
        await update.message.reply_text("⚠️ Aktiv murojaat topilmadi.", reply_markup=get_main_keyboard(get_user_language(user.id)))
        return
    
    messages = get_session_messages(session_data['session_id'])
    if not messages:
        await update.message.reply_text("⚠️ Murojaat bo'sh! Xabar yuboring.", reply_markup=SESSION_KEYBOARD)
        return
    
    text_parts = [msg['text'] for msg in messages if msg['type'] == 'text' and msg['text']]
    combined_text = "\n\n".join(text_parts) or "—"
    topic_display = session_data['topic'] or "—"
    
    preview = (
        f"👁️ <b>Murojaatni tekshiring:</b>\n\n"
        f"📌 <b>Mavzu:</b> {topic_display}\n\n"
        f"📝 <b>Matn:</b>\n{combined_text[:1000]}{'...' if len(combined_text) > 1000 else ''}\n\n"
        f"📦 Xabarlar soni: {len(messages)}\n"
        f"✅ Tasdiqlaysizmi?"
    )
    
    await update.message.reply_text(preview, parse_mode='HTML', reply_markup=PREVIEW_KEYBOARD)


async def confirm_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and submit case"""
    user = update.effective_user
    
    if context.user_data.get('awaiting_topic'):
        await update.message.reply_text("⚠️ Avval mavzu nomini yuboring!")
        return
    
    session_data = get_active_session(user.id)
    if not session_data:
        await update.message.reply_text("⚠️ Aktiv murojaat topilmadi.", reply_markup=get_main_keyboard(get_user_language(user.id)))
        return
    
    messages = get_session_messages(session_data['session_id'])
    if not messages:
        await update.message.reply_text("⚠️ Murojaat bo'sh!", reply_markup=SESSION_KEYBOARD)
        return
    
    text_parts = [msg['text'] for msg in messages if msg['type'] == 'text' and msg['text']]
    combined_text = "\n\n".join(text_parts) or "—"
    topic = session_data['topic']
    
    # Create case
    case_id, case_number, _ = create_case(session_data['session_id'], user.id, topic, combined_text)
    
    # Prepare group message
    group_text = (
        f"📋 <b>Murojaat #{case_number}</b>\n\n"
        f"📌 <b>Mavzu:</b> {topic or '—'}\n"
        f"{get_user_contact_text(user)}\n\n"
        f"📝 <b>Matn:</b>\n{combined_text}\n\n"
        f"⏰ <b>Yuborildi:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    
    try:
        # Send main message
        sent_msg = await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=group_text,
            parse_mode='HTML',
            reply_markup=get_approval_keyboard(case_number)
        )
        
        update_case_group_msg_id(case_id, sent_msg.message_id)
        
        # Send media messages
        media_msg_ids = []
        for i, msg in enumerate(messages):
            if not msg['file_id']:
                continue
            
            try:
                caption = f"📎 Fayl #{i+1}"
                if msg['type'] == 'photo':
                    media_msg = await context.bot.send_photo(GROUP_CHAT_ID, photo=msg['file_id'], caption=caption)
                elif msg['type'] == 'video':
                    media_msg = await context.bot.send_video(GROUP_CHAT_ID, video=msg['file_id'], caption=caption)
                elif msg['type'] == 'voice':
                    media_msg = await context.bot.send_voice(GROUP_CHAT_ID, voice=msg['file_id'], caption=caption)
                elif msg['type'] == 'document':
                    media_msg = await context.bot.send_document(GROUP_CHAT_ID, document=msg['file_id'], caption=caption)
                else:
                    continue
                
                media_msg_ids.append(media_msg.message_id)
                
            except Exception as e:
                logger.error(f"Media send error: {e}")
                error_msg = await context.bot.send_message(GROUP_CHAT_ID, f"⚠️ Fayl yuborishda xatolik: {e}")
                media_msg_ids.append(error_msg.message_id)
        
        # Map media messages
        for msg_id in media_msg_ids:
            add_media_message_map(msg_id, case_id)
        
        # Clear user data
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ Murojaatingiz muvaffaqiyatli yuborildi!\n"
            f"🆔 Murojaat raqami: <b>#{case_number}</b>\n\n"
            f"24-72 soat ichida ko'rib chiqib javob beramiz.",
            parse_mode='HTML',
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
        
        logger.info(f"✅ Murojaat #{case_number} submitted by user {user.id}")
        
    except Exception as e:
        logger.error(f"Failed to submit case: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Murojaatni yuborishda xatolik.", reply_markup=SESSION_KEYBOARD)


@check_ban
@subscription_required
async def list_my_cases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's cases"""
    user = update.effective_user
    await show_user_cases_page(update, context, user.id, page=1, status_filter='all')

async def show_user_cases_page(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, page: int, status_filter: str = 'all'):
    limit = 5
    offset = (page - 1) * limit
    
    cases = get_user_cases(user_id, limit, offset, status_filter)
    total_count = count_user_cases(user_id, status_filter)
    total_pages = (total_count + limit - 1) // limit

    # Filter buttons
    filter_row = [
        InlineKeyboardButton(f"{'✅ ' if status_filter == 'all' else ''}Barchasi", callback_data="mycases_filter_all"),
        InlineKeyboardButton(f"{'✅ ' if status_filter == 'open' else ''}Ochiq", callback_data="mycases_filter_open"),
        InlineKeyboardButton(f"{'✅ ' if status_filter == 'closed' else ''}Yopilgan", callback_data="mycases_filter_closed"),
    ]

    if not cases:
        text = "📭 Sizda hozircha murojaatlar topilmadi."
        keyboard = [filter_row]
        if update.callback_query:
             await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
             await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    text = f"📋 <b>Sizning murojaatlaringiz ({total_count} ta):</b>\n\n"
    keyboard = [filter_row]
    row = []
    
    for i, case in enumerate(cases):
        emoji = STATUS_EMOJIS.get(case['status'], '📝')
        status = STATUS_TEXTS.get(case['status'], 'Noma\'lum')
        topic = case['topic'] or "—"
        date = str(case['created_at'])[:16] if case['created_at'] else "—"
        
        text += f"{emoji} <b>{topic}</b>\n🆔: #{case['case_number']} | {date}\n📊 Holat: {status}\n\n"
        
        # Tugma qo'shish
        row.append(InlineKeyboardButton(f"📝 #{case['case_number']} ga yozish", callback_data=f"reply_case_{case['case_number']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    # Pagination buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"mycases_page_{page-1}_{status_filter}"))
    
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"mycases_page_{page+1}_{status_filter}"))
        
    if nav_row:
        keyboard.append(nav_row)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def my_cases_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    page = int(parts[2])
    status_filter = parts[3] if len(parts) > 3 else 'all'
    await show_user_cases_page(update, context, query.from_user.id, page, status_filter)

async def my_cases_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status_filter = query.data.split("_")[2]
    await show_user_cases_page(update, context, query.from_user.id, 1, status_filter)

@check_ban
@subscription_required
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user = update.effective_user
    stats = get_user_stats(user.id)
    
    if stats['total_cases'] == 0:
        await update.message.reply_text(
            "📊 <b>Sizning statistikangiz:</b>\n\n📭 Hozircha murojaatlar yo'q\n📩 \"Yangi murojaat\" tugmasini bosing!",
            parse_mode='HTML',
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
        return
    
    text = (
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"📦 Umumiy: <b>{stats['total_cases']}</b>\n"
        f"⏳ Kutilmoqda: <b>{stats['pending_cases']}</b>\n"
        f"✅ Qabul qilingan: <b>{stats['accepted_cases']}</b>\n"
        f"❌ Rad etilgan: <b>{stats['rejected_cases']}</b>\n"
        f"🔒 Yopilgan: <b>{stats['closed_cases']}</b>\n\n"
    )
    
    if stats['last_case_at']:
        text += f"🕐 Oxirgi murojaat: {str(stats['last_case_at'])[:16]}"
    else:
        text += "🕐 Oxirgi murojaat: —"
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_keyboard(get_user_language(user.id)))


# handlers.py faylida bot_info funksiyasini almashtiring:

@check_ban
@subscription_required
async def bot_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot haqida ma'lumotni chiqarish"""
    user = update.effective_user
    logger.info(f"User {user.id} requested bot info")
    lang = get_user_language(user.id)
    
    info_text = get_text('bot_info_text', lang=lang)
    
    await update.message.reply_text(
        info_text,
        parse_mode='HTML',
        reply_markup=get_main_keyboard(lang)
    )





# ==================== Admin Handlers ====================
async def admin_approve_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approve/reject callback"""
    query = update.callback_query
    await query.answer()
    
    # Check admin
    if not is_admin(query.from_user.id):
        await query.answer("⚠️ Siz admin emassiz!")
        return
    
    try:
        action, case_number = query.data.split("_")
        case_number = int(case_number)
    except ValueError:
        await query.answer("Noto'g'ri format!")
        return
    
    case = get_case_by_message_id(query.message.message_id)
    if not case:
        await query.answer("Murojaat topilmadi!")
        return
    
    case_id = case['case_id']
    user_id = case['user_id']
    topic = case['topic']
    
    # Check if user blocked bot
    try:
        await context.bot.get_chat_member(user_id, user_id)
    except (Forbidden, BadRequest):
        logger.error(f"User {user_id} blocked bot")
        await query.answer("Foydalanuvchi botni bloklagan!")
        update_case_status(case_id, 'rejected')
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ <b>Foydalanuvchi botni bloklagan!</b>",
            parse_mode='HTML'
        )
        return
    
    if action == "approve":
        update_case_status(case_id, 'accepted')
        
        try:
            topic_text = f'"{topic}"' if topic else "Mavzusiz"
            await context.bot.send_message(
                user_id,
                f'✅ Sizning {topic_text} murojaatingiz qabul qilindi.\n'
                f'🆔 Murojaat raqami: #{case_number}\n\n'
                f'72 soat ichida javob beramiz.',
                parse_mode='HTML',
                reply_markup=get_main_keyboard(get_user_language(user_id))
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        # Xabar matnini olish (formatlash bilan)
        current_text = query.message.text_html
        status_suffix = "\n\n✅ <b>Qabul qilindi!</b>"
        new_text = current_text + status_suffix if status_suffix not in current_text else current_text

        await query.edit_message_text(
            text=new_text,
            parse_mode='HTML',
            reply_markup=get_approval_keyboard(case_number)
        )
        
    elif action == "reject":
        update_case_status(case_id, 'rejected')
        
        await query.edit_message_text(
            text=query.message.text + "\n\n❌ <b>Rad etildi!</b>",
            parse_mode='HTML'
        )
        
        try:
            await context.bot.send_message(
                user_id,
                "❌ Sizning murojaatingiz ko'rib chiqish uchun yetarli emas.\n"
                "Iltimos, qayta urinib ko'ring yoki ma'lumotni to'ldiring.",
                reply_markup=get_main_keyboard(get_user_language(user_id))
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")



@check_ban
@subscription_required
async def search_cases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi murojaatlarini qidirish"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "🔍 <b>Qidirish:</b>\n\n"
            "Foydalanish: <code>/search kalitso'z</code>\n\n"
            "Namuna: <code>/search hisob</code>",
            parse_mode='HTML'
        )
        return
    
    query = " ".join(context.args)
    
    if len(query) < 3:
        await update.message.reply_text("⚠️ Kamida 3 ta belgi kiriting!")
        return
    
    results = search_user_cases(user.id, query)
    
    if not results:
        await update.message.reply_text(
            f"❌ '{query}' boʻyicha hech narsa topilmadi.",
            reply_markup=get_main_keyboard(get_user_language(user.id))
        )
        return
    
    text = f"🔍 <b>'{query}' boʻyicha natijalar:</b>\n\n"
    
    for case in results:
        emoji = STATUS_EMOJIS.get(case['status'], '📝')
        status = STATUS_TEXTS.get(case['status'], 'Noma\'lum')
        topic = case['topic'] or "—"
        date = case['created_at'][:16]
        
        text += f"{emoji} <b>{topic}</b>\n🆔: #{case['case_number']} | {date}\n📊 {status}\n\n"
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=get_main_keyboard(get_user_language(user.id)))

# ===================================================================
# ADMIN PANEL & OPERATORS
# ===================================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel entry point"""
    if not is_admin(update.effective_user.id): return
    
    keyboard = [
        [InlineKeyboardButton("👥 Operatorlar", callback_data="admin_operators")],
        [InlineKeyboardButton("👨‍💼 Operator Statistikasi", callback_data="admin_op_stats_view")],
        [InlineKeyboardButton(" Bloklanganlar", callback_data="admin_blocked")],
        [InlineKeyboardButton("❓ FAQ Sozlamalari", callback_data="admin_faq")],
        [InlineKeyboardButton("📄 Shablonlar", callback_data="admin_templates")],
        [InlineKeyboardButton("📅 Qabul Vaqtlari", callback_data="admin_booking")],
        [InlineKeyboardButton("� Majburiy Obuna", callback_data="admin_channel")],
        [InlineKeyboardButton("📝 Welcome Matni", callback_data="admin_welcome")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_info")],
        [InlineKeyboardButton("⚙️ Tizim Sozlamalari", callback_data="admin_system")],
        [InlineKeyboardButton("📊 Statistika (Excel)", callback_data="admin_stats_export")],
        [InlineKeyboardButton("❌ Yopish", callback_data="admin_close")]
    ]
    
    if update.message:
        await update.message.reply_text(
            "⚙️ <b>Admin Panel</b>\nBo'limni tanlang:", 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode='HTML'
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚙️ <b>Admin Panel</b>\nBo'limni tanlang:", 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode='HTML'
        )

async def admin_operations_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel navigation and Operator assignment"""
    query = update.callback_query
    
    # Check admin
    if not is_admin(query.from_user.id):
        await query.answer("⚠️ Siz admin emassiz!", show_alert=True)
        return

    data = query.data
    
    # --- Admin Panel Navigation ---
    if data == "admin_close":
        await query.message.delete()
        return

    elif data == "admin_back":
        keyboard = [
            [InlineKeyboardButton("👥 Operatorlar", callback_data="admin_operators")],
            [InlineKeyboardButton("👨‍💼 Operator Statistikasi", callback_data="admin_op_stats_view")],
            [InlineKeyboardButton("� Bloklanganlar", callback_data="admin_blocked")],
            [InlineKeyboardButton("❓ FAQ Sozlamalari", callback_data="admin_faq")],
            [InlineKeyboardButton("📄 Shablonlar", callback_data="admin_templates")],
            [InlineKeyboardButton("📅 Qabul Vaqtlari", callback_data="admin_booking")],
            [InlineKeyboardButton("📢 Majburiy Obuna", callback_data="admin_channel")],
            [InlineKeyboardButton("📝 Welcome Matni", callback_data="admin_welcome")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_info")],
            [InlineKeyboardButton("📊 Statistika (Excel)", callback_data="admin_stats_export")],
            [InlineKeyboardButton("❌ Yopish", callback_data="admin_close")]
        ]
        await query.edit_message_text(
            "⚙️ <b>Admin Panel</b>\nBo'limni tanlang:", 
            reply_markup=InlineKeyboardMarkup(keyboard), 
            parse_mode='HTML'
        )
        return

    elif data == "admin_operators":
        await show_operators_menu(query)
        return
    
    elif data == "admin_op_stats_view":
        await show_operator_stats(query)
        return
    
    elif data == "admin_blocked":
        await admin_blocked_menu(query)
        return

    elif data == "admin_faq":
        await admin_faq_menu(query)
        return
        
    elif data == "admin_templates":
        await admin_templates_menu(query)
        return

    elif data == "admin_booking":
        await admin_booking_menu(query)
        return
        
    elif data == "add_slots_tomorrow":
        await admin_add_slots_callback(update, context)
        return

    elif data == "admin_channel":
        await admin_channel_menu(query)
        return

    elif data == "admin_welcome":
        await admin_welcome_menu(query)
        return

    elif data.startswith("unblock_"):
        user_id = int(data.split("_")[1])
        unblock_user(user_id)
        await query.answer("✅ Foydalanuvchi blokdan chiqarildi")
        await admin_blocked_menu(query)
        return

    elif data == "reset_welcome":
        set_setting("welcome_message", "")
        await query.answer("✅ Default holatga qaytarildi")
        await admin_welcome_menu(query)
        return

    elif data == "del_channel_confirm":
        set_setting("required_channel_id", "")
        await query.answer("✅ Majburiy obuna o'chirildi")
        await admin_channel_menu(query)
        return

    elif data.startswith("del_faq_"):
        faq_id = int(data.split("_")[2])
        delete_faq(faq_id)
        await query.answer("✅ O'chirildi")
        await admin_faq_menu(query)
        return
        
    elif data.startswith("del_tpl_"):
        tpl_id = int(data.split("_")[2])
        delete_template(tpl_id)
        await query.answer("✅ Shablon o'chirildi")
        await admin_templates_menu(query)
        return

    elif data == "admin_broadcast_info":
        await query.answer("Broadcast uchun /broadcast buyrug'idan foydalaning.", show_alert=True)
        return
        
    elif data == "admin_system":
        await admin_system_menu(query)
        return
    
    elif data == "admin_maint_toggle":
        current = get_setting("maintenance_mode")
        new_status = "off" if current == "on" else "on"
        set_setting("maintenance_mode", new_status)
        status_msg = "yoqildi" if new_status == "on" else "o'chirildi"
        await query.answer(f"Texnik tanaffus {status_msg}!")
        await admin_system_menu(query)
        return

    elif data == "admin_backup":
        await send_backup(update, context)
        return
    
    elif data == "admin_operator_stats":
        await export_operator_stats_excel(update, context)
        return

    elif data == "admin_stats_export":
        await export_stats_excel(update, context)
        return

    elif data == "noop":
        await query.answer()
        return

    # --- Operator Management ---
    elif data.startswith("del_op_"):
        op_id = int(data.split("_")[2])
        delete_operator(op_id)
        await query.answer("✅ Operator o'chirildi")
        await show_operators_menu(query)
        return

    # --- Case Assignment (Existing Logic) ---
    elif data.startswith("assign_"):
        await query.answer()
        case_number = int(data.split("_")[1])
        operators = get_active_operators()
        
        if not operators:
            await query.answer("⚠️ Operatorlar yo'q! Admin panel orqali qo'shing.", show_alert=True)
            return
            
        keyboard = []
        for op in operators:
            keyboard.append([InlineKeyboardButton(f"👨‍💼 {op['full_name']}", callback_data=f"set_op_{case_number}_{op['id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data=f"back_case_{case_number}")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("set_op_"):
        await query.answer()
        _, _, case_number, op_id = data.split("_")
        case = get_case_by_number_admin(int(case_number))
        if not case: return
            
        assign_case_operator(case['case_id'], int(op_id))
        op_name = get_operator_name(int(op_id))
        
        # Xabar matnini yangilash
        msg = query.message
        original_text = msg.caption_html if msg.caption else msg.text_html
        
        if "👨‍💼 Operator:" in original_text:
            new_text = re.sub(r"👨‍💼 Operator: .*", f"👨‍💼 Operator: {op_name}", original_text)
        else:
            new_text = original_text + f"\n\n👨‍💼 Operator: {op_name}"
            
        keyboard = get_approval_keyboard(int(case_number))
        
        if msg.caption:
            await msg.edit_caption(caption=new_text, parse_mode='HTML', reply_markup=keyboard)
        else:
            await msg.edit_text(text=new_text, parse_mode='HTML', reply_markup=keyboard)
            
        await query.answer(f"Biriktirildi: {op_name}")

        # Operatorga xabar yuborish
        op_telegram_id = get_operator_telegram_id(int(op_id))
        if op_telegram_id:
            try:
                keyboard = [[InlineKeyboardButton("✅ Qabul qilish", callback_data=f"op_accept_{case['case_id']}")]]
                await context.bot.send_message(
                    chat_id=op_telegram_id,
                    text=f"👨‍💼 <b>Yangi murojaat biriktirildi!</b>\n\n"
                         f"🆔 Murojaat: #{case_number}\n"
                         f"📌 Mavzu: {case.get('topic', 'Mavzusiz')}\n\n"
                         f"Iltimos, qabul qiling.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Failed to notify operator {op_id}: {e}")

    elif data.startswith("back_case_"):
        await query.answer()
        case_number = int(data.split("_")[2])
        await query.edit_message_reply_markup(reply_markup=get_approval_keyboard(case_number))


async def show_operators_menu(query):
    operators = get_active_operators()
    keyboard = []
    
    for op in operators:
        keyboard.append([
            InlineKeyboardButton(f"👤 {op['full_name']}", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"del_op_{op['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Operator qo'shish", callback_data="add_op_start")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    await query.edit_message_text(
        "👥 <b>Operatorlar boshqaruvi:</b>", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='HTML'
    )

async def add_operator_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding operator"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✍️ <b>Yangi operator ismini kiriting:</b>\n\n"
        "Bekor qilish uchun /cancel ni bosing.",
        parse_mode='HTML'
    )
    return ADMIN_ADD_OP_NAME

async def add_operator_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save name and ask gender"""
    context.user_data['new_op_name'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("👨 Erkak", callback_data="gender_male"),
         InlineKeyboardButton("👩 Ayol", callback_data="gender_female")]
    ]
    await update.message.reply_text("Jinsini tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_ADD_OP_GENDER

async def add_operator_gender_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save operator with gender"""
    query = update.callback_query
    await query.answer()
    
    gender = query.data.split("_")[1]
    name = context.user_data['new_op_name']
    context.user_data['new_op_gender'] = gender
    
    await query.edit_message_text(
        "🆔 <b>Operatorning Telegram ID sini kiriting:</b>\n\n"
        "Bu operatorga xabarnoma yuborish uchun kerak.\n"
        "Agar bilmasangiz /skip ni bosing.",
        parse_mode='HTML'
    )
    return ADMIN_ADD_OP_ID

async def add_operator_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save operator with ID"""
    id_text = update.message.text
    telegram_id = None
    
    if id_text.isdigit():
        telegram_id = int(id_text)
    
    name = context.user_data['new_op_name']
    gender = context.user_data['new_op_gender']
    
    add_operator(name, gender, telegram_id)
    
    id_display = telegram_id if telegram_id else "Yo'q"
    await update.message.reply_text(f"✅ Operator qo'shildi: <b>{name}</b> (ID: {id_display})", parse_mode='HTML')
    await admin_panel(update, context)
    return ConversationHandler.END

async def add_operator_skip_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip ID"""
    name = context.user_data['new_op_name']
    gender = context.user_data['new_op_gender']
    
    add_operator(name, gender, None)
    
    await update.message.reply_text(f"✅ Operator qo'shildi: <b>{name}</b> (ID: Yo'q)", parse_mode='HTML')
    await admin_panel(update, context)
    return ConversationHandler.END

async def add_operator_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    await admin_panel(update, context)
    return ConversationHandler.END

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi bahosini qabul qilish"""
    query = update.callback_query
    await query.answer()
    
    try:
        _, case_id, rating = query.data.split("_")
        case_id = int(case_id)
        rating = int(rating)
        
        update_case_rating(case_id, rating)
        
        await query.edit_message_text(
            f"✅ Rahmat! Siz xizmat sifatini <b>{rating}</b> ball bilan baholadingiz.",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Rating error: {e}")
        await query.answer("Xatolik yuz berdi", show_alert=True)

async def export_stats_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Excel statistika yaratish va yuborish"""
    query = update.callback_query
    await query.answer("⏳ Statistika tayyorlanmoqda...")
    
    stats = get_all_stats_for_export()
    
    if not stats:
        await query.message.reply_text("⚠️ Statistika uchun ma'lumot yo'q.")
        return

    # Excel yaratish
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Murojaatlar"
    
    # Header
    headers = ["Case #", "Operator", "Javob vaqti", "Baho"]
    ws.append(headers)
    
    # Data
    for row in stats:
        ws.append([
            row['case_number'],
            row['full_name'] or "Admin",
            str(row['replied_at'])[:16] if row['replied_at'] else "",
            row['rating'] or "Baholanmagan"
        ])
    
    # Column width
    for col in ['B', 'C']:
        ws.column_dimensions[col].width = 20
        
    # Save to buffer
    file_stream = io.BytesIO()
    # Blocking operatsiyani alohida thread da bajarish
    await asyncio.to_thread(wb.save, file_stream)
    file_stream.seek(0)
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=file_stream,
        filename=f"statistika_{datetime.now().strftime('%Y%m%d')}.xlsx",
        caption="📊 Haftalik va oylik statistika"
    )
async def export_operator_stats_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Excel statistika yaratish va yuborish"""
    query = update.callback_query
    await query.answer("⏳ Operator statistika tayyorlanmoqda...")

    stats = get_operator_statistics()
    
    if not stats:
        await query.message.reply_text("⚠️ Operatorlar statistikasi topilmadi.")
        return

    # Excel yaratish
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Operatorlar Statistikasi"
    
    # Header
    headers = ["Operator", "Jami biriktirilgan", "Yopilgan (Closed)", "Jarayonda (Accepted)", "Kutilmoqda (Pending)"]
    ws.append(headers)
    
    # Data
    for row in stats:
        ws.append([
            row['full_name'],
            row['total_assigned'] or 0,
            row['closed_cases'] or 0,
            row['accepted_cases'] or 0,
            row['pending_cases'] or 0
        ])
    
    # Column width
    for col in ['A']:
        ws.column_dimensions[col].width = 25
    for col in ['B', 'C', 'D', 'E']:
        ws.column_dimensions[col].width = 20
        
    # Save to buffer
    file_stream = io.BytesIO()
    await asyncio.to_thread(wb.save, file_stream)
    file_stream.seek(0)
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=file_stream,
        filename=f"operator_statistika_{datetime.now().strftime('%Y%m%d')}.xlsx",
        caption="📊 Operatorlar faoliyati statistikasi"
    )

# handle_admin_reply funksiyasini yangilash
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward admin reply to user with operator info"""
    message = update.message
    
    if message.chat.id != GROUP_CHAT_ID or not message.reply_to_message:
        return
    
    if not is_admin(message.from_user.id):
        return
    
    case_data = get_case_by_message_id(message.reply_to_message.message_id)
    if not case_data:
        try:
            if message.reply_to_message.reply_to_message:
                case_data = get_case_by_message_id(message.reply_to_message.reply_to_message.message_id)
        except Exception:
            pass
    
    if not case_data:
        return
    
    case_id = case_data['case_id']
    user_id = case_data['user_id']
    
    # Javob berish vaqtini hisoblash
    created_at_str = case_data.get('created_at')
    duration_str = "Noma'lum"
    
    if created_at_str:
        try:
            # SQLite vaqti (UTC)
            created_at = datetime.strptime(str(created_at_str), "%Y-%m-%d %H:%M:%S")
            now = datetime.utcnow()
            diff = now - created_at
            
            days = diff.days
            hours, remainder = divmod(diff.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            parts = []
            if days > 0: parts.append(f"{days} kun")
            if hours > 0: parts.append(f"{hours} soat")
            if minutes > 0: parts.append(f"{minutes} daqiqa")
            
            duration_str = " ".join(parts) if parts else "1 daqiqa ichida"
        except Exception as e:
            logger.error(f"Vaqt hisoblashda xatolik: {e}")
    
    # Operator ma'lumotlarini olish
    op_info = get_case_operator_info(case_id)
    
    operator_name = op_info['full_name'] if op_info else "Admin"
    
    header = (
        f"🆔 <b>Murojaatingiz raqami:</b> #{case_data['case_number']}\n"
        f"📌 <b>Murojaatingiz qisqa mavzusi:</b> {case_data['topic'] or 'Mavzusiz'}\n"
        f"⏱ <b>Javob berilish vaqti:</b> {duration_str}\n"
        f"👨‍💼 <b>Javob berdi:</b> {operator_name}\n\n"
        f"<b>Sizning murojaatingizga quyidagicha javob beramiz:</b>\n\n"
    )
    
    try:
        # Send message
        if message.text:
            await context.bot.send_message(user_id, header + message.text, parse_mode='HTML')
        elif message.photo:
            await context.bot.send_photo(user_id, photo=message.photo[-1].file_id, caption=header + (message.caption or ""), parse_mode='HTML')
        elif message.video:
            await context.bot.send_video(user_id, video=message.video.file_id, caption=header + (message.caption or ""), parse_mode='HTML')
        elif message.document:
            await context.bot.send_document(user_id, document=message.document.file_id, caption=header + (message.caption or ""), parse_mode='HTML')
        elif message.voice:
            await context.bot.send_voice(user_id, voice=message.voice.file_id, caption=header + (message.caption or ""), parse_mode='HTML')
        else:
            return
        
        # Baholash tugmalari
        rating_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1⭐", callback_data=f"rate_{case_id}_1"),
                InlineKeyboardButton("2⭐", callback_data=f"rate_{case_id}_2"),
                InlineKeyboardButton("3⭐", callback_data=f"rate_{case_id}_3"),
                InlineKeyboardButton("4⭐", callback_data=f"rate_{case_id}_4"),
                InlineKeyboardButton("5⭐", callback_data=f"rate_{case_id}_5")
            ]
        ])
        
        await context.bot.send_message(
            user_id, 
            "Xizmat sifatini baholang:", 
            reply_markup=rating_keyboard
        )
        
        await message.reply_text(f"✅ User {user_id} ga javob yuborildi.")
        
        update_case_status(case_id, 'closed')
        update_case_reply_info(case_id)
        
    except Forbidden:
        await message.reply_text(f"⚠️ User {user_id} botni bloklagan!")
        update_case_status(case_id, 'rejected')
    except Exception as e:
        logger.error(f"Reply error: {e}")
        await message.reply_text(f"⚠️ Xatolik: {e}")

async def cancel_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Boshqa buyruq berilganda joriy jarayonni to'xtatish"""
    command = update.message.text
    
    # Agar /start yoki /admin bo'lsa, ularni bajaramiz
    if command.startswith("/start"):
        await start(update, context)
    elif command.startswith("/admin"):
        await admin_panel(update, context)
    else:
        await update.message.reply_text("⚠️ Avvalgi jarayon to'xtatildi.", reply_markup=get_main_keyboard(get_user_language(update.effective_user.id)))
        context.user_data.clear()
        
    return ConversationHandler.END

# ===================================================================
# RE-APPEAL (QAYTA MUROJAAT) HANDLERS
# ===================================================================
@check_ban
async def start_re_appeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qayta murojaat qilishni boshlash"""
    query = update.callback_query
    await query.answer()
    
    try:
        case_number = int(query.data.split("_")[2])
        context.user_data['re_appeal_case_number'] = case_number
        
        await query.message.reply_text(
            f"🔄 <b>Murojaat #{case_number} bo'yicha qayta xabar yozish.</b>\n\n"
            "Marhamat, savolingiz yoki xabaringizni yozib qoldiring (matn, rasm, video...):",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardRemove()
        )
        return RE_APPEAL_COLLECTING
    except (IndexError, ValueError):
        await query.message.reply_text("⚠️ Xatolik yuz berdi.")
        return ConversationHandler.END

async def handle_re_appeal_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qayta murojaat xabarini qabul qilish va guruhga yuborish"""
    user = update.effective_user
    case_number = context.user_data.get('re_appeal_case_number')
    
    if not case_number:
        await update.message.reply_text("⚠️ Xatolik: Murojaat raqami yo'qolgan.", reply_markup=get_main_keyboard(get_user_language(user.id)))
        return ConversationHandler.END

    # Case ma'lumotlarini olish
    case = get_case_by_number_and_user(case_number, user.id)
    if not case:
        await update.message.reply_text("⚠️ Murojaat topilmadi.", reply_markup=get_main_keyboard(get_user_language(user.id)))
        return ConversationHandler.END

    # Operator ma'lumotini olish
    op_info = get_case_operator_info(case['case_id'])
    op_name = op_info['full_name'] if op_info else "Biriktirilmagan (Admin)"
    
    # Xabar ma'lumotlarini olish
    file_id, text, msg_type, _, _ = extract_message_data(update.message)
    text = text or ""

    # Guruhga yuboriladigan matn
    group_text = (
        f"🔄 <b>QAYTA MUROJAAT #{case_number}</b>\n\n"
        f"📌 <b>Mavzu:</b> {case['topic'] or '—'}\n"
        f"👨‍💼 <b>Oldingi operator:</b> {op_name}\n"
        f"{get_user_contact_text(user)}\n\n"
        f"📝 <b>Yangi xabar:</b>\n{text}"
    )

    try:
        # Guruhga yuborish
        sent_msg = None
        if msg_type == 'text':
            sent_msg = await context.bot.send_message(GROUP_CHAT_ID, group_text, parse_mode='HTML', reply_markup=get_re_appeal_keyboard(case_number))
        elif msg_type == 'photo':
            sent_msg = await context.bot.send_photo(GROUP_CHAT_ID, photo=file_id, caption=group_text, parse_mode='HTML', reply_markup=get_re_appeal_keyboard(case_number))
        elif msg_type == 'video':
            sent_msg = await context.bot.send_video(GROUP_CHAT_ID, video=file_id, caption=group_text, parse_mode='HTML', reply_markup=get_re_appeal_keyboard(case_number))
        elif msg_type == 'document':
            sent_msg = await context.bot.send_document(GROUP_CHAT_ID, document=file_id, caption=group_text, parse_mode='HTML', reply_markup=get_re_appeal_keyboard(case_number))
        elif msg_type == 'voice':
            sent_msg = await context.bot.send_voice(GROUP_CHAT_ID, voice=file_id, caption=group_text, parse_mode='HTML', reply_markup=get_re_appeal_keyboard(case_number))
        
        if sent_msg:
            # Xabarni case bilan bog'lash (Admin reply qilishi uchun)
            add_media_message_map(sent_msg.message_id, case['case_id'])
            
            # Statusni yangilash (ixtiyoriy, lekin foydali)
            update_case_status(case['case_id'], 'pending')
            
            await update.message.reply_text("✅ Xabaringiz operatorga yuborildi!", reply_markup=get_main_keyboard(get_user_language(user.id)))
        else:
            await update.message.reply_text("⚠️ Xabarni yuborishda xatolik.", reply_markup=get_main_keyboard(get_user_language(user.id)))
            
    except Exception as e:
        logger.error(f"Re-appeal error: {e}")
        await update.message.reply_text("⚠️ Tizim xatoligi.", reply_markup=get_main_keyboard(get_user_language(user.id)))

    context.user_data.clear()
    return ConversationHandler.END


@check_ban
@subscription_required
async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Takliflar bo'limi - 1-qadam"""
    await update.message.reply_text(
        "💡 <b>Taklif va shikoyatlar</b>\n\n"
        "Bot faoliyati bo'yicha taklif yoki shikoyatingizni yozib qoldiring.\n"
        "Xabaringiz to'g'ridan-to'g'ri adminga yuboriladi.",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)
    )
    return SUGGESTION_WAITING


async def suggestion_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Taklifni qabul qilish va adminga yuborish"""
    user = update.effective_user
    text = update.message.text
    
    # Birinchi adminga yuborish (Owner)
    target_admin_id = ADMIN_IDS[0] if ADMIN_IDS else None
    
    if target_admin_id:
        try:
            await context.bot.send_message(
                chat_id=target_admin_id,
                text=f"💡 <b>BOT UCHUN TAKLIF/SHIKOYAT</b>\n\n"
                     f"{get_user_contact_text(user)}\n\n"
                     f"📝 <b>Mazmuni:</b>\n{text}",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Taklifni adminga yuborishda xato: {e}")
    
    await update.message.reply_text(
        "✅ Taklifingiz qabul qilindi va adminga yuborildi!\nE'tiboringiz uchun rahmat.", 
        reply_markup=get_main_keyboard(get_user_language(user.id))
    )
    return ConversationHandler.END


async def suggestion_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Taklifni bekor qilish"""
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=get_main_keyboard(get_user_language(update.effective_user.id)))
    return ConversationHandler.END


async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obunani tekshirish tugmasi"""
    query = update.callback_query
    
    if await check_membership(query.from_user.id, context):
        await query.answer("✅ Rahmat! Obuna tasdiqlandi.", show_alert=True)
        # Asl start funksiyasini chaqiramiz (qayta tekshirmaslik uchun)
        await start.__wrapped__(update, context)
    else:
        await query.answer("❌ Siz hali kanalga obuna bo'lmadingiz!", show_alert=True)


# ==================== FAQ HANDLERS ====================
@check_ban
@subscription_required
async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """FAQ bo'limi - Foydalanuvchi uchun"""
    faqs = get_faqs()
    if not faqs:
        await update.message.reply_text("📭 Hozircha savollar yo'q.", reply_markup=get_main_keyboard(get_user_language(update.effective_user.id)))
        return
    
    keyboard = []
    for faq in faqs:
        keyboard.append([InlineKeyboardButton(f"❓ {faq['question']}", callback_data=f"faq_show_{faq['id']}")])
    
    await update.message.reply_text(
        "❓ <b>Tez-tez so'raladigan savollar:</b>\n\nSavol ustiga bosing:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def faq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """FAQ navigatsiya"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "faq_back":
        faqs = get_faqs()
        keyboard = []
        for faq in faqs:
            keyboard.append([InlineKeyboardButton(f"❓ {faq['question']}", callback_data=f"faq_show_{faq['id']}")])
        
        await query.edit_message_text(
            "❓ <b>Tez-tez so'raladigan savollar:</b>\n\nSavol ustiga bosing:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif data.startswith("faq_show_"):
        faq_id = int(data.split("_")[2])
        faq = get_faq(faq_id)
        
        if faq:
            await query.edit_message_text(
                f"❓ <b>{faq['question']}</b>\n\n💬 {faq['answer']}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="faq_back")]])
            )
        else:
            await query.answer("Savol topilmadi!", show_alert=True)
            # Refresh list
            await show_faq(update, context)

async def admin_faq_menu(query):
    """Admin FAQ menu"""
    faqs = get_faqs()
    keyboard = []
    
    for faq in faqs:
        keyboard.append([
            InlineKeyboardButton(f"❓ {faq['question'][:20]}...", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"del_faq_{faq['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Savol qo'shish", callback_data="add_faq_start")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    await query.edit_message_text(
        "❓ <b>FAQ Sozlamalari:</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_faq_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding FAQ"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✍️ <b>Yangi savolni kiriting:</b>\n\n"
        "Bekor qilish uchun /cancel ni bosing.",
        parse_mode='HTML'
    )
    return FAQ_QUESTION

async def add_faq_question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_faq_question'] = update.message.text
    await update.message.reply_text("✍️ <b>Endi javobni kiriting:</b>", parse_mode='HTML')
    return FAQ_ANSWER

async def add_faq_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = context.user_data['new_faq_question']
    answer = update.message.text
    
    add_faq(question, answer)
    
    await update.message.reply_text(f"✅ FAQ qo'shildi:\n\n❓ {question}\n💬 {answer}")
    await admin_panel(update, context)
    return ConversationHandler.END

async def add_faq_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    await admin_panel(update, context)
    return ConversationHandler.END


# ==================== ADMIN CHANNEL SETTINGS ====================
async def admin_channel_menu(query):
    """Majburiy obuna menyusi"""
    current = get_setting("required_channel_id")
    status_text = current if current else "❌ O'rnatilmagan"
    text = f"📢 <b>Majburiy Obuna Sozlamalari</b>\n\nHozirgi kanal: {status_text}"
    
    keyboard = [
        [InlineKeyboardButton("✏️ O'zgartirish", callback_data="set_channel_start")]
    ]
    
    if current:
        keyboard.append([InlineKeyboardButton("🗑 O'chirib tashlash", callback_data="del_channel_confirm")])
        
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def set_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni o'zgartirishni boshlash"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 <b>Kanal ID yoki Username ni yuboring:</b>\n\n"
        "Masalan: <code>@kanal_username</code> yoki <code>-100123456789</code>\n\n"
        "⚠️ <b>Muhim:</b> Bot ushbu kanalda <b>ADMIN</b> bo'lishi shart!",
        parse_mode='HTML'
    )
    return ADMIN_SET_CHANNEL

async def set_channel_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni saqlash"""
    channel_id = update.message.text.strip()
    
    # Tekshirish
    try:
        chat = await context.bot.get_chat(channel_id)
        member = await context.bot.get_chat_member(channel_id, context.bot.id)
        if member.status != 'administrator':
            await update.message.reply_text("⚠️ Bot ushbu kanalda admin emas! Iltimos, avval botni kanalga admin qiling.")
            return ADMIN_SET_CHANNEL
    except Exception as e:
        await update.message.reply_text(f"⚠️ Kanalni tekshirishda xatolik: {e}\nKanal username/ID to'g'riligini va bot admin ekanligini tekshiring.")
        return ADMIN_SET_CHANNEL

    set_setting("required_channel_id", channel_id)
    await update.message.reply_text(f"✅ Majburiy obuna kanali o'zgartirildi: {channel_id}")
    await admin_panel(update, context)
    return ConversationHandler.END


# ==================== ADMIN WELCOME SETTINGS ====================
async def admin_welcome_menu(query):
    """Welcome message menyusi"""
    current = get_setting("welcome_message")
    if not current:
        preview = "<i>(Default matn ishlatilmoqda)</i>"
    else:
        preview = f"{current[:100]}..." if len(current) > 100 else current

    text = f"📝 <b>Welcome Message Sozlamalari</b>\n\nHozirgi matn:\n{preview}"
    
    keyboard = [
        [InlineKeyboardButton("✏️ O'zgartirish", callback_data="set_welcome_start")],
        [InlineKeyboardButton("🔄 Default holatga qaytarish", callback_data="reset_welcome")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def set_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome matnini o'zgartirishni boshlash"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 <b>Yangi Welcome matnini yuboring:</b>\n\n"
        "HTML format qo'llab quvvatlanadi (<b>bold</b>, <i>italic</i>).\n"
        "Bekor qilish uchun /cancel ni bosing.",
        parse_mode='HTML'
    )
    return ADMIN_SET_WELCOME

async def set_welcome_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome matnini saqlash"""
    new_text = update.message.text
    set_setting("welcome_message", new_text)
    
    await update.message.reply_text("✅ Welcome matni yangilandi!")
    await admin_panel(update, context)
    return ConversationHandler.END


# ==================== ADMIN BLOCKED USERS ====================
async def admin_blocked_menu(query):
    """Bloklangan foydalanuvchilar menyusi"""
    blocked_users = get_blocked_users_list()
    keyboard = []
    
    for user in blocked_users:
        keyboard.append([
            InlineKeyboardButton(f"👤 {user['user_id']} ({user['reason'] or 'Sababsiz'})", callback_data="noop"),
            InlineKeyboardButton("🔓 Ochish", callback_data=f"unblock_{user['user_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Bloklash (ID orqali)", callback_data="ban_user_start")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    await query.edit_message_text(
        f"🚫 <b>Bloklangan foydalanuvchilar:</b> {len(blocked_users)} ta",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ban_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchini bloklashni boshlash"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🚫 <b>Bloklanadigan foydalanuvchi ID sini yuboring:</b>\n\n"
        "Masalan: <code>123456789</code>",
        parse_mode='HTML'
    )
    return ADMIN_BAN_ID

async def ban_user_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchini bloklash"""
    user_id_text = update.message.text.strip()
    if not user_id_text.isdigit():
        await update.message.reply_text("⚠️ Iltimos, faqat raqamli ID yuboring!")
        return ADMIN_BAN_ID
    
    user_id = int(user_id_text)
    block_user(user_id, reason="Admin tomonidan", admin_id=update.effective_user.id)
    
    await update.message.reply_text(f"✅ Foydalanuvchi {user_id} bloklandi!")
    await admin_panel(update, context)
    return ConversationHandler.END


async def show_operator_stats(query):
    """Operatorlar statistikasini ko'rsatish"""
    stats = get_operator_statistics()
    
    if not stats:
        text = "👨‍💼 <b>Operatorlar statistikasi:</b>\n\nMa'lumot topilmadi yoki operatorlar yo'q."
    else:
        text = "👨‍💼 <b>Operatorlar statistikasi:</b>\n\n"
        for op in stats:
            text += (
                f"👤 <b>{op['full_name']}</b>\n"
                f"✅ Javob berilgan: <b>{op['closed_cases'] or 0}</b>\n"
                f"⏳ Jarayonda: <b>{op['accepted_cases'] or 0}</b>\n"
                f"📥 Jami biriktirilgan: <b>{op['total_assigned'] or 0}</b>\n"
                f"➖➖➖➖➖➖➖➖\n"
            )
            
    keyboard = [[InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def operator_accept_case(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Operator murojaatni qabul qilishi"""
    query = update.callback_query
    await query.answer()
    
    case_id = int(query.data.split("_")[2])
    
    update_case_status(case_id, 'accepted')
    
    await query.edit_message_text(
        query.message.text_html + "\n\n✅ <b>Siz murojaatni qabul qildingiz!</b>",
        parse_mode='HTML'
    )

async def admin_system_menu(query):
    """Tizim sozlamalari menyusi"""
    maintenance = get_setting("maintenance_mode")
    status_text = "✅ YOQILGAN" if maintenance == "on" else "❌ O'CHIRILGAN"
    
    current_limit = get_setting("rate_limit_per_day")
    limit_text = current_limit if current_limit else str(RATE_LIMIT_PER_DAY)
    
    keyboard = [
        [InlineKeyboardButton(f"🛑 Texnik Tanaffus: {status_text}", callback_data="admin_maint_toggle")],
        [InlineKeyboardButton(f"🔢 Kunlik Limit: {limit_text}", callback_data="set_limit_start")],
        [InlineKeyboardButton("💾 To'liq Backup (JSON)", callback_data="admin_backup")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        "⚙️ <b>Tizim Sozlamalari</b>\n\n"
        "• <b>Texnik Tanaffus:</b> Yoqilsa, oddiy foydalanuvchilar yangi murojaat yubora olmaydi (Adminlar mustasno).\n"
        "• <b>Kunlik Limit:</b> Foydalanuvchi bir kunda nechta murojaat yubora olishi.\n"
        "• <b>Backup:</b> Barcha ma'lumotlarni JSON formatida yuklab olish.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Backup faylini yuborish"""
    query = update.callback_query
    await query.answer("⏳ Backup tayyorlanmoqda...")
    
    data = get_full_backup_data()
    
    # JSON string yaratish
    json_str = json.dumps(data, indent=4, ensure_ascii=False)
    
    # Fayl oqimini yaratish
    file_stream = io.BytesIO(json_str.encode('utf-8'))
    file_stream.seek(0)
    
    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    
    await context.bot.send_document(
        chat_id=query.message.chat_id,
        document=file_stream,
        filename=filename,
        caption="💾 <b>To'liq Ma'lumotlar Bazasi (Backup)</b>\nFormat: JSON",
        parse_mode='HTML'
    )

async def set_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Limitni o'zgartirishni boshlash"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔢 <b>Yangi kunlik limitni kiriting:</b>\n\n"
        "Faqat raqam yuboring (masalan: 5, 10, 20).\n"
        "Bekor qilish uchun /cancel ni bosing.",
        parse_mode='HTML'
    )
    return ADMIN_SET_LIMIT

async def set_limit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Limitni saqlash"""
    limit_text = update.message.text.strip()
    
    if not limit_text.isdigit():
        await update.message.reply_text("⚠️ Iltimos, faqat raqam yuboring!")
        return ADMIN_SET_LIMIT
    
    limit = int(limit_text)
    if limit < 1:
        await update.message.reply_text("⚠️ Limit kamida 1 bo'lishi kerak!")
        return ADMIN_SET_LIMIT

    set_setting("rate_limit_per_day", str(limit))
    
    await update.message.reply_text(f"✅ Kunlik limit o'zgartirildi: {limit} ta")
    await admin_panel(update, context)
    return ConversationHandler.END

# ==================== TEMPLATES HANDLERS ====================
@check_ban
@subscription_required
async def show_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchiga shablonlarni ko'rsatish"""
    templates = get_templates()
    if not templates:
        await update.message.reply_text("📭 Hozircha shablonlar yo'q.", reply_markup=get_main_keyboard(get_user_language(update.effective_user.id)))
        return
    
    keyboard = []
    for t in templates:
        keyboard.append([InlineKeyboardButton(f"📄 {t['title']}", callback_data=f"tpl_dl_{t['id']}")])
    
    await update.message.reply_text(
        "📄 <b>Ariza shablonlari:</b>\n\nYuklab olish uchun kerakli shablonni tanlang:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def download_template_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shablonni yuklab berish"""
    query = update.callback_query
    await query.answer()
    
    try:
        tpl_id = int(query.data.split("_")[2])
        template = get_template(tpl_id)
        
        if template:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=template['file_id'],
                caption=f"📄 <b>{template['title']}</b>",
                parse_mode='HTML'
            )
        else:
            await query.answer("Shablon topilmadi!", show_alert=True)
    except Exception as e:
        logger.error(f"Template download error: {e}")
        await query.answer("Xatolik yuz berdi", show_alert=True)

async def admin_templates_menu(query):
    """Admin shablonlar menyusi"""
    templates = get_templates()
    keyboard = []
    
    for t in templates:
        keyboard.append([
            InlineKeyboardButton(f"📄 {t['title']}", callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"del_tpl_{t['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("➕ Shablon qo'shish", callback_data="add_tpl_start")])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    await query.edit_message_text(
        "📄 <b>Shablonlar boshqaruvi:</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def add_template_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📄 <b>Yangi shablon faylini yuboring (PDF/DOC):</b>\n\n"
        "Bekor qilish uchun /cancel ni bosing.",
        parse_mode='HTML'
    )
    return ADMIN_ADD_TEMPLATE_FILE

async def add_template_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("⚠️ Iltimos, fayl yuboring!")
        return ADMIN_ADD_TEMPLATE_FILE
        
    context.user_data['new_tpl_file_id'] = doc.file_id
    context.user_data['new_tpl_name'] = doc.file_name
    
    await update.message.reply_text(
        f"✅ Fayl qabul qilindi.\n\n"
        f"✍️ <b>Shablon nomini kiriting:</b>\n"
        f"(Hozirgi fayl nomi: {doc.file_name})",
        parse_mode='HTML'
    )
    return ADMIN_ADD_TEMPLATE_NAME

async def add_template_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text
    file_id = context.user_data['new_tpl_file_id']
    
    add_template(title, file_id)
    
    await update.message.reply_text(f"✅ Shablon qo'shildi: <b>{title}</b>", parse_mode='HTML')
    await admin_panel(update, context)
    return ConversationHandler.END

async def add_template_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    await admin_panel(update, context)
    return ConversationHandler.END

# ==================== LANGUAGE HANDLERS ====================
async def show_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Til tanlash menyusini ko'rsatish"""
    keyboard = [
        [InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]
    ]
    
    text = get_text('lang_select', lang='uz') # Default to uz for selection prompt
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tilni saqlash"""
    query = update.callback_query
    await query.answer()
    
    lang = query.data.split("_")[1]
    user = query.from_user
    
    set_user_language(user.id, lang)
    
    # Yangi tilda xabar
    await query.delete_message()
    await context.bot.send_message(
        chat_id=user.id,
        text=get_text('lang_set', lang=lang),
        reply_markup=get_main_keyboard(lang)
    )
    
    # Start ni qayta chaqirish (welcome message uchun)
    await start.__wrapped__(update, context)

# ==================== BOOKING HANDLERS ====================
@check_ban
@subscription_required
async def show_booking_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchiga bo'sh vaqtlarni ko'rsatish"""
    slots = get_available_slots()
    
    if not slots:
        await update.message.reply_text(
            "📅 <b>Qabulga yozilish:</b>\n\n"
            "Hozircha bo'sh vaqtlar mavjud emas. Keyinroq tekshirib ko'ring.",
            parse_mode='HTML', reply_markup=get_main_keyboard(get_user_language(update.effective_user.id))
        )
        return

    keyboard = []
    row = []
    for slot in slots:
        # Format: 27-Okt 14:00
        dt = slot['slot_datetime']
        btn_text = dt.strftime("%d-%b %H:%M")
        row.append(InlineKeyboardButton(f"🕒 {btn_text}", callback_data=f"book_slot_{slot['id']}"))
        
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    await update.message.reply_text(
        "📅 <b>Qabulga yozilish:</b>\n\n"
        "O'zingizga qulay vaqtni tanlang:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def book_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vaqtni band qilish"""
    query = update.callback_query
    user = update.effective_user
    try:
        slot_id = int(query.data.split("_")[2])
    except (IndexError, ValueError):
        await query.answer("Xatolik!", show_alert=True)
        return
    
    if book_slot(slot_id, user.id):
        await query.answer("✅ Muvaffaqiyatli band qilindi!", show_alert=True)
        await query.edit_message_text(
            f"✅ <b>Qabulga yozildingiz!</b>\n\n"
            f"👤 Ism: {user.full_name}\n"
            f"🕒 Vaqt muvaffaqiyatli band qilindi.\n\n"
            f"Iltimos, belgilangan vaqtda aloqada bo'ling yoki ofisga keling.",
            parse_mode='HTML'
        )
    else:
        await query.answer("⚠️ Bu vaqt allaqachon band qilingan!", show_alert=True)
        await show_booking_slots(update, context)

async def admin_booking_menu(query):
    """Admin booking menyusi"""
    keyboard = [
        [InlineKeyboardButton("➕ Ertangi kun uchun vaqt ochish", callback_data="add_slots_tomorrow")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
    ]
    
    slots = get_available_slots()
    count = len(slots)
    
    await query.edit_message_text(
        f"📅 <b>Qabul Vaqtlari Boshqaruvi</b>\n\n"
        f"Hozirda aktiv bo'sh vaqtlar: <b>{count}</b> ta\n\n"
        f"Vaqt qo'shish tugmasi ertangi kun uchun 09:00 dan 17:00 gacha soatlik vaqtlarni avtomatik yaratadi.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_add_slots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ertangi kun uchun slot yaratish"""
    query = update.callback_query
    
    tomorrow = datetime.now().date() + timedelta(days=1)
    create_daily_slots(tomorrow)
    
    await query.answer(f"✅ {tomorrow} sanasi uchun vaqtlar yaratildi!")
    await admin_booking_menu(query)