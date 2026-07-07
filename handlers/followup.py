"""
PEAK AI Agency — Followup Handler
"""

import logging
import database as db

log = logging.getLogger("PEAK-FOLLOWUP")


def build_followup_message(product_name, order_id):
    return (
        f"متابعة — طلب #{order_id}\n"
        f"{'─' * 30}\n\n"
        f"مرت 7 أيام على تسليم {product_name}.\n\n"
        f"كيف الأداء؟ هل المنتج يعمل بالشكل المتوقع؟\n\n"
        f"اذا احتجت تعديلاً:\n"
        f"t.me/PeakAISupport\n\n"
        f"PEAK AI Agency"
    )


async def send_due_followups(bot):
    due = db.get_due_followups()
    if not due:
        return
    for followup in due:
        followup_id = followup["id"]
        customer_id = followup["customer_id"]
        order_id = followup["order_id"]
        product_name = followup["product_name"]
        try:
            message = build_followup_message(product_name, order_id)
            await bot.send_message(chat_id=customer_id, text=message)
            db.mark_followup_sent(followup_id)
        except Exception as e:
            log.error("فشل إرسال المتابعة #%d: %s", followup_id, e)
            db.mark_followup_failed(followup_id)
