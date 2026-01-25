# main.py
import logging
import os
import signal
import sys
import warnings
from telegram.warnings import PTBUserWarning
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler

from config import *
from database import init_db, cleanup_old_sessions, init_pool, close_pool
from utils import setup_logging
from handlers import *

logger = logging.getLogger(__name__)

# PTBUserWarning ogohlantirishlarini yashirish (loglarni toza saqlash uchun)
warnings.filterwarnings("ignore", category=PTBUserWarning)

def signal_handler(signum, frame):
    """Graceful shutdown"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

async def post_stop(application: Application):
    """Cleanup on stop"""
    if 'scheduler' in application.bot_data:
        application.bot_data['scheduler'].shutdown()
    
    # Baza ulanishlarini yopish
    close_pool()
    
    logger.info("✅ Bot stopped gracefully")


async def post_init(application: Application):
    """Post initialization"""
    application.bot_data['main_keyboard'] = MAIN_KEYBOARD
    
    scheduler = AsyncIOScheduler()
    
    # Session cleanup (har soat)
    scheduler.add_job(
        lambda: cleanup_old_sessions(SESSION_TIMEOUT_HOURS),
        'interval',
        hours=1,
        id='cleanup_sessions'
    )
    
    scheduler.start()
    application.bot_data['scheduler'] = scheduler
    
    logger.info("✅ Bot va scheduler boshlandi!")


def main():
    """Main function"""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Setup logging
    setup_logging(log_file=LOG_FILE, level=LOG_LEVEL)
    
    # Validate config
    logger.info(f"GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    logger.info(f"ADMIN_IDS: {ADMIN_IDS}")
    logger.info(f"Max file size: {MAX_FILE_SIZE_MB}MB")
    
    # Initialize database
    init_pool() # Poolni yaratish
    init_db()
    cleanup_old_sessions(SESSION_TIMEOUT_HOURS)
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).post_stop(post_stop).build()
    
    # ==================== BROADCAST CONVERSATION (EN MUHIM!) ====================
    # Bu ConversationHandler boshqa MessageHandlerlardan oldin bo'lishi kerak!
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_WAITING: [
                MessageHandler(filters.Regex(r"^✅ Ha, yuborish$"), broadcast_send),
                MessageHandler(filters.Regex(r"^❌ Yo'q, bekor qilish$"), broadcast_cancel)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", broadcast_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
        name="broadcast_conversation",
        persistent=False
    )
    application.add_handler(broadcast_conv)

    # ==================== SUGGESTION CONVERSATION ====================
    suggestion_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("💡 Takliflar"), suggestion_start)],
        states={
            SUGGESTION_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^❌"), suggestion_send)]
        },
        fallbacks=[
            MessageHandler(filters.Regex(r"^❌ Bekor qilish$"), suggestion_cancel),
            CommandHandler("cancel", suggestion_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(suggestion_conv)

    # ==================== NEW SESSION CONVERSATION ====================
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Text("📩 Yangi murojaat"), new_session)],
        states={
            TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_message)],
            COLLECTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_message)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel), 
            MessageHandler(filters.Text("❌ Bekor qilish"), cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ]
    )
    application.add_handler(conv_handler)

    # ==================== RE-APPEAL CONVERSATION ====================
    re_appeal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_re_appeal, pattern=r"^reply_case_\d+$")],
        states={
            RE_APPEAL_COLLECTING: [MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.Regex(r"^❌"), handle_re_appeal_message)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(re_appeal_conv)

    # ==================== ADMIN PANEL & OPERATORS ====================
    # Admin Panel Conversation (Operator qo'shish uchun)
    admin_op_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_operator_start, pattern="^add_op_start$")],
        states={
            ADMIN_ADD_OP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_operator_name_handler)],
            ADMIN_ADD_OP_GENDER: [CallbackQueryHandler(add_operator_gender_handler, pattern="^gender_")],
            ADMIN_ADD_OP_ID: [
                MessageHandler(filters.Regex(r"^\d+$"), add_operator_id_handler),
                CommandHandler("skip", add_operator_skip_id)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", add_operator_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(admin_op_conv)

    # ==================== ADMIN FAQ CONVERSATION ====================
    admin_faq_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_faq_start, pattern="^add_faq_start$")],
        states={
            FAQ_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_faq_question_handler)],
            FAQ_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_faq_answer_handler)]
        },
        fallbacks=[
            CommandHandler("cancel", add_faq_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(admin_faq_conv)

    # ==================== ADMIN CHANNEL CONVERSATION ====================
    admin_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_channel_start, pattern="^set_channel_start$")],
        states={
            ADMIN_SET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_channel_save)]
        },
        fallbacks=[
            CommandHandler("cancel", add_operator_cancel), # Reuse cancel handler
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(admin_channel_conv)

    # ==================== ADMIN WELCOME CONVERSATION ====================
    admin_welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_welcome_start, pattern="^set_welcome_start$")],
        states={
            ADMIN_SET_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_welcome_save)]
        },
        fallbacks=[
            CommandHandler("cancel", add_operator_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(admin_welcome_conv)

    # ==================== ADMIN BAN CONVERSATION ====================
    admin_ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ban_user_start, pattern="^ban_user_start$")],
        states={
            ADMIN_BAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_save)]
        },
        fallbacks=[
            CommandHandler("cancel", add_operator_cancel),
            MessageHandler(filters.COMMAND, cancel_on_command)
        ],
    )
    application.add_handler(admin_ban_conv)

    # ==================== STANDARD COMMANDS ====================
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("status", status_command))

    # ==================== MENU HANDLERS ====================
    # Note: "📩 Yangi murojaat" is handled by conv_handler above
    application.add_handler(MessageHandler(filters.Text("📋 Mening murojaatlarim"), list_my_cases))
    application.add_handler(MessageHandler(filters.Text("📊 Mening statistikam"), show_stats))
    application.add_handler(MessageHandler(filters.Text("❓ FAQ"), show_faq))
    application.add_handler(MessageHandler(filters.Text("ℹ️ Bot haqida"), bot_info))

    application.add_handler(MessageHandler(filters.Text("👁️ Ko'rish"), preview_case))
    application.add_handler(MessageHandler(filters.Text("✅ Murojaatni yuborish"), confirm_submit))
    application.add_handler(MessageHandler(filters.Text("📝 Tahr qilish"), new_session))
    application.add_handler(MessageHandler(filters.Text("❌ Bekor qilish"), cancel))

    # ==================== ADMIN HANDLERS ====================
    application.add_handler(CallbackQueryHandler(admin_approve_reject, pattern=r"^(approve|reject)_\d+$"))
    application.add_handler(MessageHandler(filters.Chat(GROUP_CHAT_ID) & filters.REPLY, handle_admin_reply))

    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Combined callback handler
    application.add_handler(CallbackQueryHandler(admin_operations_callback, pattern=r"^(admin_|del_op_|assign_|set_op_|back_case_|noop|del_faq_|del_channel_|reset_welcome|unblock_)"))
    
    # Rating handler
    application.add_handler(CallbackQueryHandler(handle_rating, pattern=r"^rate_\d+_\d+$"))

    # FAQ callback handler
    application.add_handler(CallbackQueryHandler(faq_callback, pattern=r"^faq_"))

    # Pagination handler
    application.add_handler(CallbackQueryHandler(my_cases_pagination_callback, pattern=r"^mycases_page_"))
    
    # Filter handler
    application.add_handler(CallbackQueryHandler(my_cases_filter_callback, pattern=r"^mycases_filter_"))

    # Operator accept handler
    application.add_handler(CallbackQueryHandler(operator_accept_case, pattern=r"^op_accept_"))

    # Subscription check handler
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    # ==================== GENERAL MESSAGE HANDLER (OXIRIDA!) ====================
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL,
        collect_message
    ))




    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update caused error: {context.error}", exc_info=True)
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                f"⚠️ Xatolik yuz berdi, keyinroq qayta urinib ko'ring.\n"
                f"Xatolik bo'yicha Adminga xabar berishingiz mumkin, @{ADMIN_USERNAME}"
            )
    
    application.add_error_handler(error_handler)
    
    # Run
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()