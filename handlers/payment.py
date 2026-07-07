import logging
from urllib.parse import urlencode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database as db
import config
from products import get_product

log = logging.getLogger("PEAK-PAYMENT")

def build_payment_url(product_id, amount, order_id):
    params = {"product": product_id, "amount": f"{amount:.0f}", "order": str(order_id), "wallet": config.WALLET_ADDRESS}
    return f"{config.PAYMENT_BASE_URL}?{urlencode(params)}"

async def handle_payment_intent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":")[1]
    product = get_product(product_id)
    user = query.from_user
    if not product:
        await query.edit_message_text("المنتج غير متاح. اكتب /start للمحاولة.")
        return
    payment_url = build_payment_url(product_id, product.price_usd, 0)
    order_id = db.create_order(customer_id=user.id, product_id=product.id, product_name=product.name, amount_usd=product.price_usd, payment_url=payment_url)
    payment_url = build_payment_url(product_id, product.price_usd, order_id)
    short_wallet = config.WALLET_ADDRESS[:8] + "..." + config.WALLET_ADDRESS[-6:]
    text = f"تفاصيل الدفع — طلب #{order_id}\n\nالمنتج: {product.name}\nالمبلغ: {product.price_usd:.0f} USDT TRC-20\nالمحفظة: {short_wallet}\n\nخطوات الدفع:\n1. افتح صفحة الدفع\n2. انسخ عنوان المحفظة\n3. ارسل المبلغ عبر TRC-20\n\nرقم طلبك: #{order_id}"
    keyboard = [[InlineKeyboardButton("فتح صفحة الدفع", url=payment_url)], [InlineKeyboardButton("تواصل مع الفريق", url="https://t.me/PeakAISupport")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    if config.ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=f"طلب جديد #{order_id}\nالعميل: {user.full_name}\nالمنتج: {product.name}\nالمبلغ: ${product.price_usd:.0f}")
        except Exception:
            pass

async def send_payment_confirmation(bot, customer_id, order_id, product_name, amount_usd, tx_id, delivery_note):
    short_tx = tx_id[:14] + "..." if len(tx_id) > 14 else tx_id
    text = f"تم استلام دفعتك\n\nالمنتج: {product_name}\nالمبلغ: ${amount_usd:.0f} USDT\nTX: {short_tx}\nطلب: #{order_id}\n\nالخطوة التالية:\n{delivery_note}\n\npeakvault.com"
    try:
        await bot.send_message(chat_id=customer_id, text=text)
    except Exception as e:
        log.error("فشل تأكيد الدفع: %s", e)

async def send_admin_payment_alert(bot, order_id, product_name, amount_usd, customer_id, tx_id):
    if not config.ADMIN_CHAT_ID:
        return
    try:
        await bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=f"دفعة مؤكدة — طلب #{order_id}\nالمنتج: {product_name}\nالمبلغ: ${amount_usd:.0f} USDT\nالعميل: {customer_id}")
    except Exception:
        pass
