"""
PEAK AI Agency — Payment Handler
"""

import logging
from urllib.parse import urlencode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import config
from products import get_product

log = logging.getLogger("PEAK-PAYMENT")


def build_payment_url(product_id, amount, order_id):
    params = {
        "product": product_id,
        "amount": f"{amount:.0f}",
        "order": str(order_id),
        "wallet": config.WALLET_ADDRESS,
    }
    return f"{config.PAYMENT_BASE_URL}?{urlencode(params)}"


async def handle_payment_intent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":")[1]
    product = get_product(product_id)
    user = query.from_user
    if not product:
        await query.edit_message_text("المنتج غير متاح. اكتب /start للمحاولة مجدداً.")
        return
    payment_url = build_payment_url(product_id, product.price_usd, 0)
    order_id = db.create_order(
        customer_id=user.id,
        product_id=product.id,
        product_name=product.name,
        amount_usd=product.price_usd,
        payment_url=payment_url,
    )
    payment_url = build_payment_url(product_id, product.price_usd, order_id)
    short_wallet = config.WALLET_ADDRESS[:8] + "..." + config.WALLET_ADDRESS[-6:]
    text = (
        f"تفاصيل الدفع — طلب #{order_id}\n"
        f"{'─' * 30}\n\n"
        f"المنتج: {product.name}\n"
        f"المبلغ: {product.price_usd:.0f} USDT TRC-20\n"
        f"المحفظة: {short_wallet}\n\n"
        f"خطوات الدفع:\n"
        f"1. افتح صفحة الدفع\n"
        f"2. انسخ عنوان المحفظة\n"
        f"3. أرسل المبلغ بالضبط عبر شبكة TRC-20\n"
        f"4. انتظر التأكيد\n\n"
        f"رقم طلبك: #{order_id}"
    )
    keyboard = [
        [InlineKeyboardButton("فتح صفحة الدفع", url=payment_url)],
        [InlineKeyboardButton("تواصل مع الفريق", url="https://t.me/PeakAISupport")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=markup)
    await notify_admin_new_order(context, user, product, order_id)


async def notify_admin_new_order(context, user, product, order_id):
    if not config.ADMIN_CHAT_ID:
        return
    try:
        text = (
            f"طلب جديد #{order_id}\n"
            f"العميل: {user.full_name} (@{user.username or 'لا يوجد'})\n"
            f"المنتج: {product.name}\n"
            f"المبلغ: ${product.price_usd:.0f} USDT"
        )
        await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=text)
    except Exception as e:
        log.warning("فشل إشعار الادمن: %s", e)


async def send_payment_confirmation(bot, customer_id, order_id, product_name, amount_usd, tx_id, delivery_note):
    short_tx = tx_id[:14] + "..." + tx_id[-8:] if len(tx_id) > 22 else tx_id
    text = (
        f"تم استلام دفعتك\n"
        f"{'─' * 30}\n\n"
        f"المنتج: {product_name}\n"
        f"المبلغ: ${amount_usd:.0f} USDT\n"
        f"TX: {short_tx}\n"
        f"طلب: #{order_id}\n\n"
        f"الخطوة التالية:\n"
        f"{delivery_note}\n\n"
        f"peakvault.com — PEAK AI Agency"
    )
    try:
        await bot.send_message(chat_id=customer_id, text=text)
    except Exception as e:
        log.error("فشل إرسال تأكيد الدفع: %s", e)


async def send_admin_payment_alert(bot, order_id, product_name, amount_usd, customer_id, tx_id):
    if not config.ADMIN_CHAT_ID:
        return
    try:
        text = (
            f"دفعة مؤكدة — طلب #{order_id}\n"
            f"المنتج: {product_name}\n"
            f"المبلغ: ${amount_usd:.0f} USDT\n"
            f"العميل: {customer_id}"
        )
        await
