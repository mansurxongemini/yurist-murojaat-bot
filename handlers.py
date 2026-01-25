# handlers.py
import logging
from datetime import datetime, timezone
from typing import Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, User
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import Forbidden, BadRequest

import asyncio
from config import *
from database import *
from utils import *
import re
import io
import openpyxl

logger = logging.getLogger(__name__)


# State constants
BROADCAST_WAITING = 1
ADMIN_ADD_OP_NAME, ADMIN_ADD_OP_GENDER, RE_APPEAL_COLLECTING = range(20, 23)

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
            
            await asyncio.sleep(0.5)
            
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
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["📩 Yangi murojaat", "📋 Mening murojaatlarim"],
     ["📊 Mening statistikam", "ℹ️ Bot haqida"]],
    resize_keyboard=True, input_field_placeholder="Tanlang..."
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.id} started bot")
    
    context.user_data.clear()
    
    # Variant 3 matni
    welcome_text = (
        "👋 Assalomu alaykum!\n\n"
        "<b>🤖 Yurist Muhammadjon Bot ga xush kelibsiz!</b>\n"
        "❓ <b>Bunda siz:</b>\n"
        "✅ Tursunov Legal Volunteer jamoasidan bepul yuridik maslahat olishingiz mumkin\n"
        "✅ Biz sizga javob beramiz (24-72 soat)\n"
        "❓ <b>Qanday yuboriladi?</b>\n"
        "1️⃣ \"📩 Yangi murojaat\" → 2️⃣ Mavzu nomi → 3️⃣ xabar → 4️⃣ Yuborish\n\n"

        "<b>🚀 Murojaat yuboring va bepul yuridik maslahat oling!</b>"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='HTML',
        reply_markup=MAIN_KEYBOARD
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    user = update.effective_user
    
    if cancel_session(user.id):
        await update.message.reply_text(
            "❌ Murojaat bekor qilindi.",
            reply_markup=MAIN_KEYBOARD
        )
    else:
        await update.message.reply_text("⚠️ Bekor qilish uchun aktiv murojaat topilmadi.", reply_markup=MAIN_KEYBOARD)
    
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
            reply_markup=MAIN_KEYBOARD
        )
    except ValueError:
        await update.message.reply_text("⚠️ Noto'g'ri raqam formati!")


# ==================== Message Handlers ====================
@rate_limit
async def new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new case session"""
    user = update.effective_user
    
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
            reply_markup=MAIN_KEYBOARD
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
        await update.message.reply_text("⚠️ Aktiv murojaat topilmadi.", reply_markup=MAIN_KEYBOARD)
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
        await update.message.reply_text("⚠️ Aktiv murojaat topilmadi.", reply_markup=MAIN_KEYBOARD)
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
            reply_markup=MAIN_KEYBOARD
        )
        
        logger.info(f"✅ Murojaat #{case_number} submitted by user {user.id}")
        
    except Exception as e:
        logger.error(f"Failed to submit case: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Murojaatni yuborishda xatolik.", reply_markup=SESSION_KEYBOARD)


async def list_my_cases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's cases"""
    user = update.effective_user
    cases = get_user_cases(user.id, limit=10)
    
    if not cases:
        await update.message.reply_text("📭 Sizda hozircha murojaatlar topilmadi.", reply_markup=MAIN_KEYBOARD)
        return
    
    text = "📋 <b>Sizning murojaatlaringiz:</b>\n\n"
    keyboard = []
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
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user = update.effective_user
    stats = get_user_stats(user.id)
    
    if stats['total_cases'] == 0:
        await update.message.reply_text(
            "📊 <b>Sizning statistikangiz:</b>\n\n📭 Hozircha murojaatlar yo'q\n📩 \"Yangi murojaat\" tugmasini bosing!",
            parse_mode='HTML',
            reply_markup=MAIN_KEYBOARD
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
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=MAIN_KEYBOARD)


# handlers.py faylida bot_info funksiyasini almashtiring:

async def bot_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot haqida ma'lumotni chiqarish"""
    user = update.effective_user
    logger.info(f"User {user.id} requested bot info")
    
    context.user_data.clear()
    
    info_text = (
        "ℹ️ <b>Bot Haqida - Barcha Imkoniyatlar</b>\n\n"
        "🤖 <b>Bot nima qiladi?</b>\n"
        "Bu bot orqali siz:\n"
        "✅ <b>Murojaat yuborishingiz</b> – istalgan vaqt, istalgan joydan\n"
        "✅ <b>Holatini kuzatishingiz</b> – har bir murojaatga alohida raqam beriladi\n"
        "✅ <b>Statistika ko'rishingiz</b> – umumiy qilgan murojaatlar soni\n"
        "✅ <b>Qidirish imkoniyati</b> – eski murojaatlarizni tez toping\n\n"
        "🚀 <b>Qanday ishlatiladi? 4 oddiy qadam:</b>\n"
        "1️⃣ <b>\"📩 Yangi murojaat\"</b> tugmasini bosing\n"
        "2️⃣ <b>Mavzu yozing</b> – qisqacha, lekin tushunarli (masalan: \"Hisob-faktura to'lovi\")\n"
        "3️⃣ <b>Toʻliq matn yuboring</b> – matn, rasm, video, fayl (max 50MB)\n"
        "4️⃣ <b>\"✅ Murojaatni yuborish\"</b> tugmasini bosing – tayyor!\n\n"
        "📊 <b>Statistika va Cheklovlar:</b>\n"
        "• <b>Kunlik limit:</b> Har bir foydalanuvchi kuniga 5 ta murojaat yuborishi mumkin\n"
        "• <b>Javob vaqti:</b> Administratorlar tomonidan 24-72 soat ichida ko'rib chiqiladi\n"
        "• <b>Raqamlash:</b> Har bir murojaatga alohida raqam beriladi (masalan: #12345)\n\n"
        "👁️ <b>Qo'shimcha imkoniyatlar:</b>\n"
        "• <code>/status 12345</code> – Ma'lum murojaatning hozirgi holatini tekshiring\n"
        "• <code>/search kalitso'z</code> – Murojaatlaringiz ichida qidirish\n"
        "• 📋 <b>\"Mening murojaatlarim\"</b> – Oxirgi 10 ta murojaatingizni koʻrish\n"
        "• 📊 <b>\"Mening statistikam\"</b> – Qabul qilingan, kutilayotgan, yopilgan murojaatlar soni\n\n"
        "🔒 <b>Xavfsizlik va Maxfiylik:</b>\n"
        "• Barcha ma'lumotlar shifrlangan holda saqlanadi\n"
        "• Shaxsiy ma'lumotlar uchinchi shaxslarga bermaymiz\n"
        "• Faqat ruxsat etilgan adminlar murojaatlarga javob beradi\n\n"

        "• <b>Ish vaqti:</b> Dushanba-Juma, 09:00-18:00 (UTC+5)\n\n"
        "💡 <b>Foydali maslahatlar:</b>\n"
        "✍️ Murojaatingizni aniq va tushunarli yozing\n"
        "📷 Zarur bo'lsa, rasmlar yoki screenshotlar qoʻshing\n"
        "⏳ Javobni kutishda sabr qiling, adminlar tez orada javob beradi\n"
        "🔄 Murojaat bir necha kun ichida hal boʻlishi mumkin (murakkabligi qarab)\n\n"
        "🎯 <b>Endi boshlaysizmi?</b>\n"
        "Quyidagi <b>\"📩 Yangi murojaat\"</b> tugmasini boshing va birinchi murojaatingizni yuboring!\n\n"
        "📢 <b>Yangiliklar:</b>\n"
        "Bot doimiy ravishda yangilanib turiladi. Yangi funksiyalar haqida bu yerda e'lon qilinadi."
    )
    
    await update.message.reply_text(
        info_text,
        parse_mode='HTML',
        reply_markup=MAIN_KEYBOARD
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
                reply_markup=MAIN_KEYBOARD
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
                reply_markup=MAIN_KEYBOARD
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward admin reply to user"""
    message = update.message
    
    # Check if in group and is reply
    if message.chat.id != GROUP_CHAT_ID or not message.reply_to_message:
        return
    
    # Check admin
    if not is_admin(message.from_user.id):
        return
    
    # Get case from reply
    case_data = get_case_by_message_id(message.reply_to_message.message_id)
    if not case_data:
        # Try original message if reply is to a media message
        try:
            if message.reply_to_message.reply_to_message:
                case_data = get_case_by_message_id(message.reply_to_message.reply_to_message.message_id)
        except Exception as e:
            logger.error(f"Failed to check original message: {e}")
            return
    
    if not case_data:
        return
    
    case_id = case_data['case_id']
    user_id = case_data['user_id']
    topic = case_data['topic']
    
    # Prepare header
    topic_part = f" | {topic}" if topic else ""
    header = f"📋 <b>Murojaat #{case_data['case_number']}</b>{topic_part}\n\n<b>Admin javobi:</b>\n\n"
    
    try:
        # Send appropriate message type
        if message.text:
            await context.bot.send_message(user_id, header + message.text, parse_mode='HTML')
        elif message.photo:
            await context.bot.send_photo(
                user_id, photo=message.photo[-1].file_id,
                caption=header + (message.caption or ""),
                parse_mode='HTML'
            )
        elif message.video:
            await context.bot.send_video(
                user_id, video=message.video.file_id,
                caption=header + (message.caption or ""),
                parse_mode='HTML'
            )
        elif message.document:
            await context.bot.send_document(
                user_id, document=message.document.file_id,
                caption=header + (message.caption or ""),
                parse_mode='HTML'
            )
        elif message.voice:
            await context.bot.send_voice(
                user_id, voice=message.voice.file_id,
                caption=header + (message.caption or ""),
                parse_mode='HTML'
            )
        else:
            await message.reply_text("⚠️ Bu turdagi xabarni yuborib bo'lmadi.")
            return
        
        await message.reply_text(f"✅ User {user_id} ga javob yuborildi.")
        logger.info(f"Admin reply sent to user {user_id} for case {case_id}")
        update_case_status(case_id, 'closed')
        
    except Forbidden:
        logger.error(f"User {user_id} blocked bot")
        await message.reply_text(f"⚠️ User {user_id} botni bloklagan!")
        update_case_status(case_id, 'rejected')
    except Exception as e:
        logger.error(f"Failed to send reply: {e}", exc_info=True)
        await message.reply_text(f"⚠️ Xatolik: {e}")

    # handlers.py ga qo'shish

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: Barcha foydalanuvchilarga xabar tarqatish"""
    user = update.effective_user
    
    # Faqat adminlar uchun
    if not is_admin(user.id):
        await update.message.reply_text("⚠️ Sizda ruxsat yoʻq!")
        return
    
    # Xabar matnini olish
    if not context.args:
        await update.message.reply_text(
            "📢 <b>Broadcast yuborish:</b>\n\n"
            "Foydalanish: <code>/broadcast Sizning xabaringiz</code>\n\n"
            "⚠️ Ogohlantirish: Ko'p foydalanuvchiga yuborish vaqt oladi!",
            parse_mode='HTML'
        )
        return
    
    message_text = " ".join(context.args)
    
    # Tasdiqlash
    confirm_keyboard = ReplyKeyboardMarkup(
        [["✅ Ha, yuborish", "❌ Yo'q, bekor qilish"]],
        resize_keyboard=True
    )
    
    await update.message.reply_text(
        f"📢 <b>Broadcast tekshirish:</b>\n\n"
        f"{message_text}\n\n"
        f"Yuborilsinmi?",
        parse_mode='HTML',
        reply_markup=confirm_keyboard
    )
    
    # Keyingi qadamni saqlash
    context.user_data['broadcast_pending'] = message_text



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
            reply_markup=MAIN_KEYBOARD
        )
        return
    
    text = f"🔍 <b>'{query}' boʻyicha natijalar:</b>\n\n"
    
    for case in results:
        emoji = STATUS_EMOJIS.get(case['status'], '📝')
        status = STATUS_TEXTS.get(case['status'], 'Noma\'lum')
        topic = case['topic'] or "—"
        date = case['created_at'][:16]
        
        text += f"{emoji} <b>{topic}</b>\n🆔: #{case['case_number']} | {date}\n📊 {status}\n\n"
    
    await update.message.reply_text(text, parse_mode='HTML', reply_markup=MAIN_KEYBOARD)

# ===================================================================
# ADMIN PANEL & OPERATORS
# ===================================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel entry point"""
    if not is_admin(update.effective_user.id): return
    
    keyboard = [
        [InlineKeyboardButton("👥 Operatorlar", callback_data="admin_operators")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_info")],
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

    elif data == "admin_broadcast_info":
        await query.answer("Broadcast uchun /broadcast buyrug'idan foydalaning.", show_alert=True)
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
    
    add_operator(name, gender)
    
    await query.edit_message_text(f"✅ Operator qo'shildi: <b>{name}</b> ({'Erkak' if gender=='male' else 'Ayol'})", parse_mode='HTML')
    
    # Show admin panel again
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

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="📊 Operator statistics (Not Implemented Yet)"
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
        await update.message.reply_text("⚠️ Avvalgi jarayon to'xtatildi.", reply_markup=MAIN_KEYBOARD)
        context.user_data.clear()
        
    return ConversationHandler.END

# ===================================================================
# RE-APPEAL (QAYTA MUROJAAT) HANDLERS
# ===================================================================
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
        await update.message.reply_text("⚠️ Xatolik: Murojaat raqami yo'qolgan.", reply_markup=MAIN_KEYBOARD)
        return ConversationHandler.END

    # Case ma'lumotlarini olish
    case = get_case_by_number_and_user(case_number, user.id)
    if not case:
        await update.message.reply_text("⚠️ Murojaat topilmadi.", reply_markup=MAIN_KEYBOARD)
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
            
            await update.message.reply_text("✅ Xabaringiz operatorga yuborildi!", reply_markup=MAIN_KEYBOARD)
        else:
            await update.message.reply_text("⚠️ Xabarni yuborishda xatolik.", reply_markup=MAIN_KEYBOARD)
            
    except Exception as e:
        logger.error(f"Re-appeal error: {e}")
        await update.message.reply_text("⚠️ Tizim xatoligi.", reply_markup=MAIN_KEYBOARD)

    context.user_data.clear()
    return ConversationHandler.END