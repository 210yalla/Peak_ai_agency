"""
PEAK AI Agency — Catalog Handler
عرض المنتجات الموصى بها وتفاصيل كل منتج
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
from products import get_product, get_recommended_products, BUSINESS_TYPE_LABELS

log = logging.getLogger("PEAK-CATALOG")


def format_product_card(product, index: int) -> str:
    badge = " [حصري]" if product.is_exclusive else ""
    return (
        f"{index}. {product.name}{badge}\n"
        f"   {product.tagline}\n"
        f"   السعر: ${product.price_usd:.0f} USDT"
    )


async def show_recommendations(update, context, business_type):
    products = get_recommended_products(business_type)
    if not products:
        msg = "لم نتمكن من تحديد توصيات. اكتب /start للبدء من جديد."
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    lines = []
    for i, p in enumerate(products, 1):
        lines.append(format_product_card(p, i))
    text = "\n\n".join(lines) + "\n\nاختر المنتج الذي يناسبك:"
    keyboard = [
        [InlineKeyboardButton(f"{p.name} — ${p.price_usd:.0f}", callback_data=f"product:{p.id}")]
        for p in products
    ]
    keyboard.append([InlineKeyboardButton("عرض منتجات أخرى", callback_data="back:start")])
    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


async def handle_product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = query.data.split(":")[1]
    product = get_product(product_id)
    if not product:
        await query.edit_message_text("المنتج غير موجود. اكتب /start للبدء.")
        return
    user = query.from_user
    context.user_data["selected_product"] = product_id
    badge = " [منتج حصري]" if product.is_exclusive else ""
    text = (
        f"{product.name}{badge}\n"
        f"{'─' * 30}\n\n"
        f"{product.description}\n\n"
        f"السعر: ${product.price_usd:.0f} USDT TRC-20\n\n"
        f"ماذا يحدث بعد الدفع:\n"
        f"{product.delivery_note}"
    )
    keyboard = [
        [InlineKeyboardButton(f"الدفع الان — ${product.price_usd:.0f} USDT", callback_data=f"pay:{product_id}")],
        [InlineKeyboardButton("العودة للقائمة", callback_data="back:catalog")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=markup)


async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    destination = query.data.split(":")[1]
    if destination == "start":
        await query.message.reply_text("اكتب /start للبدء من جديد.")
    elif destination == "catalog":
        business_type = context.user_data.get("business_type")
        if business_type:
            await query.edit_message_text(f"اختر منتجاً آخر:")
            await show_recommendations(update, context, business_
