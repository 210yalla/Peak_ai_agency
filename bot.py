import asyncio
import logging
import sys
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
import config
import database as db
from handlers.start import start, handle_business_type
from handlers.catalog import handle_product_selection, handle_back
from handlers.payment import handle_payment_intent
from payment_bridge import run_payment_monitor
from scheduler import run_followup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("PEAK-BOT")

async def error_handler(update, context):
    log.error("خطأ: %s", context.error)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "PEAK AI Agency\n\n/start — بدء جديد\n/help — المساعدة\n\nt.me/PeakAISupport"
    )

def main():
    config.validate()
    if not config.BOT_TOKEN:
        log.critical("BOT_TOKEN غير موجود")
        sys.exit(1)
    db.init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(handle_business_type, pattern=r"^btype:"))
    app.add_handler(CallbackQueryHandler(handle_product_selection, pattern=r"^product:"))
    app.add_handler(CallbackQueryHandler(handle_payment_intent, pattern=r"^pay:"))
    app.add_handler(CallbackQueryHandler(handle_back, pattern=r"^back:"))
    app.add_error_handler(error_handler)

    async def post_init(application):
        asyncio.create_task(run_payment_monitor(application.bot))
        asyncio.create_task(run_followup_scheduler(application.bot))

    app.post_init = post_init
    log.info("PEAK Bot يبدأ التشغيل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
