"""
PEAK AI Agency — Start Handler
معالج /start وسؤال نوع المشروع
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from products import BUSINESS_TYPE_LABELS

log = logging.getLogger("PEAK-START")

WELCOME_TEXT = """\
PEAK AI Agency

نساعد الشركات على تطبيق الذكاء الاصطناعي — اليوم لا غداً.
15 منتجاً جاهزاً للتشغيل. تسليم خلال أيام. دعم كامل.

لنبدأ: ما نوع مشروعك؟\
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log.info("start: %d — @%s", user.id, user.username or "")

    db.upsert_customer(
        telegram_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
    )

    keyboard = [
        [
            InlineKeyboardButton(BUSINESS_TYPE_LABELS["store"], callback_data="btype:store"),
            InlineKeyboardButton(BUSINESS_TYPE_LABELS["services"], callback_data="btype:services"),
        ],
        [
            InlineKeyboardButton(BUSINESS_TYPE_LABELS["social"], callback_data="btype:social"),
            InlineKeyboardButton(BUSINESS_TYPE_LABELS["other"], callback_data="btype:other"),
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=markup)


async def handle_business_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    business_type = query.data.split(":")[1]
    user = query.from_user
    db.set_business_type(user.id, business_type)
    label = BUSINESS_TYPE_LABELS.get(business_type, business_type)
    context.user_data["business_type"] = business_type
    await query.edit_message_text(f"اخترت: {label}\n\nهذه المنتجات الاكثر ملاءمة لمشروعك:")
    from handlers.catalog import show_recommendations
    await show_recommendations(update, context, business_type)
