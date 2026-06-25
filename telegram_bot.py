"""
═══════════════════════════════════════════════════════════════════
PEAK AI Agency © 2025 | peakvault.com | All rights reserved
telegram_bot.py — البوت الكامل

╔═══════════════════════════════════════════════════════════════╗
║  ما يفعله هذا البوت:                                           ║
║  1. يستقبل إشعار الدفع من main.py                              ║
║  2. يرسل الملف/الرابط للعميل تلقائياً في ثوانٍ               ║
║  3. لوحة تحكم كاملة لك عبر الأوامر                            ║
║  4. Recovery Bot: يتابع الطلبات المعلقة تلقائياً              ║
║  5. ضد Brute Force وSpam                                        ║
╚═══════════════════════════════════════════════════════════════╝

التشغيل:
    pip install -r requirements.txt
    python telegram_bot.py

متغيرات البيئة المطلوبة (.env):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_ADMIN_CHAT_ID
    FIREBASE_CREDENTIALS_PATH (مسار ملف service account JSON)
    PAYMENT_SIGNING_SECRET

Architecture:
    - Polling mode (لا يحتاج domain/SSL للتشغيل المحلي)
    - Webhook mode (للإنتاج على Cloud Run)
    - كل الأوامر محمية: Admin فقط لأوامر الإدارة
    - file_id caching: ترفع الملف مرة واحدة، تسلّمه مئة ألف مرة
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, Document, InputFile,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)
import firebase_admin
from firebase_admin import credentials, firestore as admin_firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# ── مكتبات البنك المحلي ──
sys.path.insert(0, os.path.dirname(__file__))
from lib.algorithms import (
    secure_token, sign_payload, generate_idempotency_key,
    TokenBucket, ValidationError
)
from lib.probability import assess_payment_risk, RiskLevel
from lib.balancing import DistributedBruteForceGuard

# ══════════════════════════════════════════════════════════════
# § 0 — CONFIG & INIT
# ══════════════════════════════════════════════════════════════

load_dotenv()
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("peak_bot")

BOT_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID   = int(os.environ["TELEGRAM_ADMIN_CHAT_ID"])
SIGNING_SECRET  = os.environ["PAYMENT_SIGNING_SECRET"]
FIREBASE_CREDS  = os.environ.get("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")

# ── Firebase Init ──
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CREDS)
    firebase_admin.initialize_app(cred)

def db() -> admin_firestore.Client:
    return admin_firestore.client()


# ══════════════════════════════════════════════════════════════
# § 1 — FILE_ID CACHE (رفع مرة → تسليم مليون مرة مجاناً)
# ══════════════════════════════════════════════════════════════

class FileIdCache:
    """
    يخزّن Telegram file_id لكل منتج.

    Layer 4: Telegram يعطي file_id دائم بعد أول رفع.
             أي إرسال لاحق لنفس الملف = send_document(file_id)
             بدون رفع جديد — فوري ومجاني.

    Layer 5: هذا هو جوهر "التسليم التلقائي" —
             لا storage تكاليف متكررة، لا بطء رفع،
             فقط file_id ثابت يُرسَل للعميل في ثانية.
    """

    def __init__(self, cache_path: str = ".file_id_cache.json"):
        self._path = Path(cache_path)
        self._cache: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text())
            except Exception:
                self._cache = {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._cache, indent=2))
        except Exception as e:
            logger.error(f"FileIdCache save error: {e}")

    def get(self, product_id: str) -> Optional[str]:
        return self._cache.get(product_id)

    def set(self, product_id: str, file_id: str) -> None:
        self._cache[product_id] = file_id
        self._save()
        logger.info(f"Cached file_id for product: {product_id}")

    def clear(self, product_id: str) -> None:
        self._cache.pop(product_id, None)
        self._save()


FILE_CACHE = FileIdCache()


# ══════════════════════════════════════════════════════════════
# § 2 — RATE LIMITING (Anti-Spam للبوت)
# ══════════════════════════════════════════════════════════════

# bucket لكل user_id — يُنشأ عند الحاجة
_user_buckets: dict[int, TokenBucket] = {}
_GUARD = DistributedBruteForceGuard(max_attempts_before_lock=10)


def get_user_bucket(user_id: int) -> TokenBucket:
    if user_id not in _user_buckets:
        _user_buckets[user_id] = TokenBucket(capacity=5, refill_rate=0.5)
    return _user_buckets[user_id]


def is_rate_limited(user_id: int) -> bool:
    return not get_user_bucket(user_id).consume()


# ══════════════════════════════════════════════════════════════
# § 3 — ADMIN GUARD (كل الأوامر الحساسة للـ Admin فقط)
# ══════════════════════════════════════════════════════════════

def admin_only(func):
    """Decorator: يرفض أي أمر حساس من غير الـ Admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id != ADMIN_CHAT_ID:
            await update.message.reply_text(
                "⛔ هذا الأمر للمسؤول فقط.",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.warning(f"Unauthorized admin command attempt from user_id={user_id}")
            _GUARD.record_failure(str(user_id))
            return
        if is_rate_limited(user_id):
            await update.message.reply_text("⏳ انتظر ثانية قبل الأمر التالي.")
            return
        return await func(update, context)
    return wrapper


# ══════════════════════════════════════════════════════════════
# § 4 — PRODUCT DELIVERY ENGINE
# ══════════════════════════════════════════════════════════════

@dataclass
class DeliveryResult:
    success: bool
    method: str       # 'file_id' | 'upload' | 'link' | 'manual'
    message: str
    file_id_cached: Optional[str] = None


async def deliver_product(
    bot: Bot,
    chat_id: int,
    product_id: str,
    customer_reference: str,
    *,
    language: str = "ar",
) -> DeliveryResult:
    """
    محرك التسليم التلقائي — يسلّم المنتج للعميل بأفضل طريقة متاحة.

    Layer 1: يرسل الملف للعميل عبر تلجرام.

    Layer 2: يجرب التسليم بالترتيب:
             1. file_id مخزَّن (الأسرع)
             2. رفع ملف من Firebase Storage
             3. رسالة رابط تحميل
             4. تنبيه Admin للتدخل اليدوي

    Layer 3: يعمل لأي نوع منتج رقمي — PDF, ZIP, HTML tool, رابط SaaS.

    Layer 4: الفصل بين "كيف نحصل على الملف" (مصدر) و"كيف نرسله"
             (قناة) يسمح بإضافة مصادر جديدة (S3, Dropbox) دون
             تغيير منطق الإرسال.

    Layer 5: التسليم الفوري ليس "ميزة" — هو الوعد الأساسي الذي
             يُبرّر الدفع الكريبتوي. أي تأخير يكسر الثقة التي
             يبنيها كل شيء آخر في المشروع.
    """
    # ── جلب بيانات المنتج من Firestore ──
    try:
        product_doc = db().collection("products").document(product_id).get()
        if not product_doc.exists:
            logger.error(f"Product not found in Firestore: {product_id}")
            return DeliveryResult(False, "manual", f"Product {product_id} not found")
        product = product_doc.to_dict()
    except Exception as e:
        logger.error(f"Firestore product fetch error: {e}")
        return DeliveryResult(False, "manual", str(e))

    delivery_method = product.get("delivery_method", "link")
    delivery_value  = product.get("delivery_value", "")  # file_path أو URL
    product_name    = product.get("name", {}).get(language, product.get("name", {}).get("en", product_id))

    # رسالة ترحيب للعميل
    welcome_texts = {
        "ar": (
            f"✅ *تم تأكيد دفعتك!*\n\n"
            f"📦 *{product_name}*\n"
            f"🔖 مرجع طلبك: `{customer_reference}`\n\n"
            f"⚡ جاري تسليم منتجك..."
        ),
        "en": (
            f"✅ *Payment confirmed!*\n\n"
            f"📦 *{product_name}*\n"
            f"🔖 Your order reference: `{customer_reference}`\n\n"
            f"⚡ Delivering your product..."
        ),
    }
    welcome = welcome_texts.get(language, welcome_texts["en"])

    try:
        await bot.send_message(chat_id, welcome, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass  # لا نكسر التسليم إن فشلت رسالة الترحيب

    # ── محاولة 1: file_id مخزَّن ──
    cached_file_id = FILE_CACHE.get(product_id)
    if cached_file_id:
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=cached_file_id,
                caption=_delivery_caption(product_name, customer_reference, language),
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info(f"Delivered {product_id} via cached file_id to chat {chat_id}")
            return DeliveryResult(True, "file_id", "Delivered via cached file_id", cached_file_id)
        except Exception as e:
            logger.warning(f"Cached file_id failed for {product_id}: {e} — clearing cache")
            FILE_CACHE.clear(product_id)  # file_id قد تنتهي صلاحيته نادراً

    # ── محاولة 2: رفع ملف مباشر ──
    if delivery_method == "file" and delivery_value:
        local_path = Path(delivery_value)
        if local_path.exists():
            try:
                with open(local_path, "rb") as f:
                    msg = await bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(f, filename=local_path.name),
                        caption=_delivery_caption(product_name, customer_reference, language),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                # احفظ الـ file_id للمرات القادمة
                if msg.document:
                    FILE_CACHE.set(product_id, msg.document.file_id)
                logger.info(f"Delivered {product_id} via file upload to chat {chat_id}")
                return DeliveryResult(True, "upload", "Delivered via file upload", msg.document.file_id if msg.document else None)
            except Exception as e:
                logger.error(f"File upload failed for {product_id}: {e}")

    # ── محاولة 3: رابط تحميل/وصول ──
    if delivery_method in ("link", "url", "saas") and delivery_value:
        # توليد رابط موقَّع (يصلح 72 ساعة)
        signed_url = _generate_signed_delivery_url(delivery_value, customer_reference)
        link_text = {
            "ar": (
                f"🔗 *رابط الوصول لمنتجك:*\n\n"
                f"`{signed_url}`\n\n"
                f"⏰ صالح 72 ساعة من الآن\n"
                f"📧 احفظ هذا الرابط في مكان آمن"
            ),
            "en": (
                f"🔗 *Your product access link:*\n\n"
                f"`{signed_url}`\n\n"
                f"⏰ Valid for 72 hours\n"
                f"📧 Save this link in a safe place"
            ),
        }.get(language, f"🔗 Access link:\n`{signed_url}`")

        try:
            await bot.send_message(chat_id, link_text, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Delivered {product_id} via signed URL to chat {chat_id}")
            return DeliveryResult(True, "link", "Delivered via signed URL")
        except Exception as e:
            logger.error(f"Link delivery failed: {e}")

    # ── محاولة 4: تنبيه Admin للتدخل ──
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"⚠️ *تسليم يدوي مطلوب*\n\n"
        f"المنتج: `{product_id}`\n"
        f"المرجع: `{customer_reference}`\n"
        f"Chat ID: `{chat_id}`\n\n"
        f"استخدم: `/deliver {customer_reference}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return DeliveryResult(False, "manual", "Admin notified for manual delivery")


def _delivery_caption(product_name: str, customer_reference: str, language: str) -> str:
    if language == "ar":
        return (
            f"📦 *{product_name}*\n"
            f"🔖 مرجع طلبك: `{customer_reference}`\n"
            f"✅ شكراً لثقتك بـ PEAK AI Agency"
        )
    return (
        f"📦 *{product_name}*\n"
        f"🔖 Order ref: `{customer_reference}`\n"
        f"✅ Thank you for trusting PEAK AI Agency"
    )


def _generate_signed_delivery_url(base_url: str, customer_reference: str) -> str:
    """يولّد رابط موقَّع يصلح 72 ساعة — يمنع مشاركة الرابط مع آخرين."""
    expires = int(time.time()) + 72 * 3600
    token = sign_payload(f"{base_url}|{customer_reference}|{expires}", SIGNING_SECRET)[:16]
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}ref={customer_reference}&exp={expires}&sig={token}"


# ══════════════════════════════════════════════════════════════
# § 5 — BOT COMMANDS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر /start — ترحيب."""
    user = update.effective_user
    if not user:
        return

    if user.id == ADMIN_CHAT_ID:
        text = (
            "👑 *PEAK AI Agency — لوحة التحكم*\n\n"
            "أوامرك:\n"
            "`/stats` — إحصاءات اليوم\n"
            "`/orders` — آخر الطلبات\n"
            "`/revenue` — الإيرادات\n"
            "`/deliver <ref>` — تسليم يدوي\n"
            "`/pending` — الطلبات المعلقة\n"
            "`/products` — إدارة المنتجات\n"
            "`/broadcast <msg>` — رسالة للجميع\n"
            "`/health` — فحص النظام\n"
        )
    else:
        text = (
            "👋 *مرحباً بك في PEAK AI Agency*\n\n"
            "هذا البوت يُستخدم لاستلام منتجاتك بعد إتمام الدفع.\n\n"
            "لشراء منتجاتنا: peakvault.com/store\n"
            "للتواصل: @T963996767062"
        )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — إحصاءات اليوم."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).timestamp()

    try:
        orders_ref = db().collection("payment_links")

        # اليوم
        today_docs = list(orders_ref.where("status", "==", "confirmed").stream())
        today_revenue = sum(
            d.to_dict().get("amount_usd", 0)
            for d in today_docs
            if d.to_dict().get("confirmed_at") and
            (d.to_dict()["confirmed_at"].timestamp() if hasattr(d.to_dict()["confirmed_at"], "timestamp") else 0) >= today_start
        )
        today_count = sum(
            1 for d in today_docs
            if d.to_dict().get("confirmed_at") and
            (d.to_dict()["confirmed_at"].timestamp() if hasattr(d.to_dict()["confirmed_at"], "timestamp") else 0) >= today_start
        )

        # الإجمالي
        all_confirmed = [d.to_dict() for d in today_docs]
        total_revenue = sum(d.get("amount_usd", 0) for d in all_confirmed)
        total_count   = len(all_confirmed)

        # معلق
        pending_count = len(list(orders_ref.where("status", "==", "pending").limit(100).stream()))

        text = (
            f"📊 *إحصاءات PEAK AI*\n\n"
            f"*اليوم:*\n"
            f"💰 الإيراد: `${today_revenue:.2f}`\n"
            f"📦 الطلبات: `{today_count}`\n\n"
            f"*الإجمالي:*\n"
            f"💰 الإيراد: `${total_revenue:.2f}`\n"
            f"📦 الطلبات: `{total_count}`\n"
            f"⏳ معلق: `{pending_count}`\n\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
        )
    except Exception as e:
        text = f"❌ خطأ في جلب الإحصاءات: {e}"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/orders — آخر 10 طلبات مؤكدة."""
    try:
        docs = list(
            db().collection("payment_links")
            .where("status", "==", "confirmed")
            .order_by("confirmed_at", direction="DESCENDING")
            .limit(10)
            .stream()
        )

        if not docs:
            await update.message.reply_text("لا توجد طلبات مؤكدة بعد.")
            return

        lines = ["📋 *آخر 10 طلبات:*\n"]
        for doc in docs:
            d = doc.to_dict()
            confirmed_time = ""
            if d.get("confirmed_at") and hasattr(d["confirmed_at"], "strftime"):
                confirmed_time = d["confirmed_at"].strftime("%m/%d %H:%M")
            lines.append(
                f"• `{d.get('customer_reference', '?')}` — "
                f"${d.get('amount_usd', 0):.2f} {d.get('currency', '')} "
                f"— {d.get('product_id', '?')} — {confirmed_time}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


@admin_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pending — الطلبات المعلقة والمنتهية الصلاحية."""
    try:
        now = time.time()
        docs = list(
            db().collection("payment_links")
            .where("status", "==", "pending")
            .order_by("created_at", direction="DESCENDING")
            .limit(20)
            .stream()
        )

        if not docs:
            await update.message.reply_text("✅ لا توجد طلبات معلقة.")
            return

        active, expired = [], []
        for doc in docs:
            d = doc.to_dict()
            if now > d.get("expires_at", 0):
                expired.append(d)
            else:
                active.append(d)

        lines = [f"⏳ *طلبات معلقة: {len(active)} نشط · {len(expired)} منتهٍ*\n"]
        for d in active[:5]:
            remaining = max(0, d.get("expires_at", 0) - now)
            lines.append(
                f"🟡 `{d.get('customer_reference','?')}` — "
                f"${d.get('amount_usd',0):.2f} — "
                f"{int(remaining//60)}د متبقية"
            )
        if expired:
            lines.append(f"\n❌ منتهية الصلاحية: {len(expired)}")

        keyboard = [[InlineKeyboardButton("🗑 تنظيف المنتهية", callback_data="cleanup_expired")]]
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


@admin_only
async def cmd_deliver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deliver <customer_reference> [chat_id] — تسليم يدوي فوري."""
    args = context.args or []
    if not args:
        await update.message.reply_text("الاستخدام: `/deliver REF-XXXXXXXX [chat_id]`", parse_mode=ParseMode.MARKDOWN)
        return

    customer_ref = args[0].strip()
    target_chat_id = int(args[1]) if len(args) > 1 else None

    # ابحث عن الطلب
    try:
        docs = list(
            db().collection("payment_links")
            .where("customer_reference", "==", customer_ref)
            .limit(1)
            .stream()
        )
        if not docs:
            await update.message.reply_text(f"❌ لا يوجد طلب بالمرجع: `{customer_ref}`", parse_mode=ParseMode.MARKDOWN)
            return
        order = docs[0].to_dict()
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في قاعدة البيانات: {e}")
        return

    chat_id = target_chat_id or order.get("telegram_chat_id")
    if not chat_id:
        await update.message.reply_text(
            f"⚠️ لا يوجد Chat ID للعميل. أرسل له رسالة يدوياً.\n"
            f"المنتج: `{order.get('product_id')}`\n"
            f"المرجع: `{customer_ref}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(f"⚡ جاري التسليم لـ `{customer_ref}`...", parse_mode=ParseMode.MARKDOWN)

    result = await deliver_product(
        context.bot, chat_id,
        order.get("product_id", ""),
        customer_ref,
    )

    status_emoji = "✅" if result.success else "⚠️"
    await update.message.reply_text(
        f"{status_emoji} *نتيجة التسليم:*\n"
        f"الطريقة: `{result.method}`\n"
        f"الرسالة: {result.message}",
        parse_mode=ParseMode.MARKDOWN,
    )

    # سجّل في Audit Log
    db().collection("audit_log").add({
        "event_type": "MANUAL_DELIVERY",
        "customer_reference": customer_ref,
        "product_id": order.get("product_id"),
        "method": result.method,
        "success": result.success,
        "admin_id": ADMIN_CHAT_ID,
        "timestamp": SERVER_TIMESTAMP,
    })


@admin_only
async def cmd_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/revenue — تقرير الإيرادات مفصّل بالعملة."""
    try:
        docs = list(db().collection("payment_links").where("status", "==", "confirmed").stream())
        by_currency: dict[str, dict] = {}
        for doc in docs:
            d = doc.to_dict()
            cur = d.get("currency", "UNKNOWN")
            if cur not in by_currency:
                by_currency[cur] = {"count": 0, "total_usd": 0.0}
            by_currency[cur]["count"] += 1
            by_currency[cur]["total_usd"] += d.get("amount_usd", 0)

        lines = ["💰 *تقرير الإيرادات بالعملة:*\n"]
        total_usd = 0.0
        for cur, stats in sorted(by_currency.items(), key=lambda x: -x[1]["total_usd"]):
            lines.append(f"• {cur}: `${stats['total_usd']:.2f}` ({stats['count']} طلب)")
            total_usd += stats["total_usd"]
        lines.append(f"\n💵 *الإجمالي: ${total_usd:.2f}*")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


@admin_only
async def cmd_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/products — قائمة المنتجات المتاحة."""
    try:
        docs = list(db().collection("products").stream())
        if not docs:
            await update.message.reply_text("لا توجد منتجات في قاعدة البيانات بعد.")
            return

        lines = [f"📦 *المنتجات ({len(docs)}):*\n"]
        for doc in docs:
            d = doc.to_dict()
            name = d.get("name", {}).get("ar", doc.id)
            lines.append(
                f"• `{doc.id}` — {name} — "
                f"${d.get('price_usd', 0):.2f} — "
                f"{'✅ متاح' if d.get('status') == 'available' else '⛔ غير متاح'}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


@admin_only
async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/health — فحص صحة النظام الكامل."""
    checks = {}

    # Firestore
    try:
        db().collection("products").limit(1).get()
        checks["🟢 Firestore"] = "متصل"
    except Exception as e:
        checks["🔴 Firestore"] = str(e)[:50]

    # Telegram API
    try:
        me = await context.bot.get_me()
        checks["🟢 Telegram Bot"] = f"@{me.username}"
    except Exception as e:
        checks["🔴 Telegram Bot"] = str(e)[:50]

    # متغيرات البيئة
    checks["🟢 ENV: BOT_TOKEN"] = "موجود" if BOT_TOKEN else "🔴 مفقود"
    checks["🟢 ENV: SIGNING_SECRET"] = "موجود" if len(SIGNING_SECRET) >= 32 else "🔴 قصير جداً"
    checks["🟢 ENV: ADMIN_CHAT_ID"] = str(ADMIN_CHAT_ID)

    # File Cache
    checks["📁 File Cache"] = f"{len(FILE_CACHE._cache)} منتج محفوظ"

    # Brute Force Guard
    guard_stats = _GUARD.stats()
    distributed = guard_stats.get("distributed_attack_suspected", False)
    checks["🔐 Brute Force Guard"] = (
        f"⚠️ هجوم موزّع مشتبه!" if distributed
        else f"{guard_stats.get('currently_locked', 0)} محظور حالياً"
    )

    text = "🏥 *فحص صحة النظام:*\n\n" + "\n".join(f"{k}: `{v}`" for k, v in checks.items())
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast <message> — رسالة لكل عملاء telegram_chat_id."""
    if not context.args:
        await update.message.reply_text("الاستخدام: `/broadcast رسالتك هنا`", parse_mode=ParseMode.MARKDOWN)
        return

    message = " ".join(context.args)

    # جمع كل chat_ids من الطلبات المؤكدة
    try:
        docs = list(db().collection("payment_links").where("status", "==", "confirmed").stream())
        chat_ids = set(
            int(d.to_dict()["telegram_chat_id"])
            for d in docs
            if d.to_dict().get("telegram_chat_id")
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب العملاء: {e}")
        return

    if not chat_ids:
        await update.message.reply_text("لا توجد Chat IDs محفوظة بعد.")
        return

    await update.message.reply_text(f"📢 إرسال رسالة لـ {len(chat_ids)} عميل...")

    sent, failed = 0, 0
    for chat_id in chat_ids:
        try:
            await context.bot.send_message(
                chat_id, f"📢 *PEAK AI Agency*\n\n{message}", parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)  # تجنّب flood limits
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ أُرسلت لـ {sent} | ❌ فشلت: {failed}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════
# § 6 — PAYMENT CONFIRMATION FLOW (من العميل مباشرة)
# ══════════════════════════════════════════════════════════════

async def handle_payment_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    يستقبل رسالة تأكيد الدفع من العميل.
    العميل يرسل: "تأكيد REF-XXXXXXXX" أو يضغط زر التأكيد.
    """
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if not user:
        return

    # Rate Limiting
    if is_rate_limited(user.id):
        await update.message.reply_text("⏳ انتظر قليلاً قبل إعادة المحاولة.")
        return

    text = update.message.text.strip()

    # استخراج المرجع من الرسالة
    customer_ref = None
    if "REF-" in text.upper():
        parts = text.upper().split("REF-")
        if len(parts) > 1:
            ref_part = parts[1].split()[0][:12]
            customer_ref = f"REF-{ref_part}"

    if not customer_ref:
        # رسالة مفيدة للعميل
        await update.message.reply_text(
            "👋 مرحباً!\n\n"
            "لتأكيد دفعتك، أرسل رقم المرجع بهذا الشكل:\n"
            "`تأكيد REF-XXXXXXXX`\n\n"
            "ستجد رقم المرجع في صفحة الدفع.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ابحث عن الطلب
    try:
        docs = list(
            db().collection("payment_links")
            .where("customer_reference", "==", customer_ref)
            .limit(1)
            .stream()
        )
    except Exception as e:
        logger.error(f"Firestore search error: {e}")
        await update.message.reply_text("❌ خطأ مؤقت، حاول مجدداً.")
        return

    if not docs:
        await update.message.reply_text(
            f"❌ لا يوجد طلب بالمرجع: `{customer_ref}`\n"
            f"تحقق من الرقم وحاول مجدداً.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    order = docs[0].to_dict()
    status = order.get("status", "unknown")

    if status == "confirmed":
        # أعد التسليم
        await update.message.reply_text(
            f"✅ طلبك مؤكد بالفعل.\n"
            f"🔖 المرجع: `{customer_ref}`\n\n"
            "جاري إعادة إرسال منتجك...",
            parse_mode=ParseMode.MARKDOWN,
        )
        await deliver_product(context.bot, user.id, order.get("product_id", ""), customer_ref)
        return

    if status == "expired":
        await update.message.reply_text(
            f"⏰ انتهت صلاحية هذا الطلب.\n"
            "يرجى إنشاء طلب جديد من الموقع.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # status == pending — أبلغ الـ Admin
    # احفظ telegram_chat_id للعميل لاستخدامه لاحقاً
    try:
        db().collection("payment_links").document(docs[0].id).update({
            "telegram_chat_id": user.id,
            "telegram_username": user.username or "",
        })
    except Exception:
        pass

    await update.message.reply_text(
        f"⏳ *طلبك قيد المراجعة*\n\n"
        f"🔖 المرجع: `{customer_ref}`\n"
        f"💵 المبلغ: `${order.get('amount_usd', 0):.2f} {order.get('currency', '')}`\n\n"
        "سيتم تأكيد دفعتك وإرسال منتجك خلال دقائق. ✉️",
        parse_mode=ParseMode.MARKDOWN,
    )

    # أبلغ الـ Admin
    keyboard = [
        [InlineKeyboardButton(
            f"✅ تأكيد وتسليم {customer_ref}",
            callback_data=f"confirm:{customer_ref}:{user.id}"
        )],
        [InlineKeyboardButton(
            "❌ رفض الطلب",
            callback_data=f"reject:{customer_ref}:{user.id}"
        )],
    ]
    try:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"🔔 *طلب تأكيد دفع*\n\n"
            f"📦 المنتج: `{order.get('product_id', '?')}`\n"
            f"🔖 المرجع: `{customer_ref}`\n"
            f"💵 المبلغ: `${order.get('amount_usd', 0):.2f} {order.get('currency', '')}`\n"
            f"👤 العميل: @{user.username or 'N/A'} (`{user.id}`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")


# ══════════════════════════════════════════════════════════════
# § 7 — INLINE KEYBOARD CALLBACKS
# ══════════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعالج ضغطات الأزرار في رسائل الـ Admin."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await query.answer("⛔ غير مصرح.", show_alert=True)
        return

    await query.answer()
    data = query.data or ""

    # ── تأكيد وتسليم ──
    if data.startswith("confirm:"):
        parts = data.split(":")
        customer_ref = parts[1]
        customer_chat_id = int(parts[2]) if len(parts) > 2 else None

        # ابحث عن الطلب وأكّده
        try:
            docs = list(
                db().collection("payment_links")
                .where("customer_reference", "==", customer_ref)
                .limit(1).stream()
            )
            if docs:
                db().collection("payment_links").document(docs[0].id).update({
                    "status": "confirmed",
                    "confirmed_at": SERVER_TIMESTAMP,
                    "confirmed_by": "admin_bot",
                })
                order = docs[0].to_dict()
                chat_id = customer_chat_id or order.get("telegram_chat_id")

                if chat_id:
                    result = await deliver_product(
                        context.bot, chat_id,
                        order.get("product_id", ""), customer_ref,
                    )
                    status_text = "✅ تم التسليم" if result.success else "⚠️ يحتاج مراجعة"
                else:
                    status_text = "⚠️ لا يوجد Chat ID للعميل"

                await query.edit_message_text(
                    f"✅ *تم التأكيد والتسليم*\n\n"
                    f"المرجع: `{customer_ref}`\n"
                    f"الحالة: {status_text}",
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")

    # ── رفض الطلب ──
    elif data.startswith("reject:"):
        parts = data.split(":")
        customer_ref = parts[1]
        customer_chat_id = int(parts[2]) if len(parts) > 2 else None

        try:
            docs = list(
                db().collection("payment_links")
                .where("customer_reference", "==", customer_ref)
                .limit(1).stream()
            )
            if docs:
                db().collection("payment_links").document(docs[0].id).update({
                    "status": "rejected",
                    "rejected_at": SERVER_TIMESTAMP,
                    "rejected_by": "admin_bot",
                })
                if customer_chat_id:
                    await context.bot.send_message(
                        customer_chat_id,
                        "⚠️ لم يتم التحقق من دفعتك بعد.\n"
                        "يرجى التواصل مع الدعم عبر واتساب.\n"
                        "https://wa.me/963996767062",
                    )
            await query.edit_message_text(f"❌ تم رفض الطلب: `{customer_ref}`", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")

    # ── تنظيف الطلبات المنتهية ──
    elif data == "cleanup_expired":
        try:
            now = time.time()
            batch = db().batch()
            count = 0
            for doc in db().collection("payment_links").where("status", "==", "pending").stream():
                d = doc.to_dict()
                if now > d.get("expires_at", 0):
                    batch.update(doc.reference, {"status": "expired", "expired_at": SERVER_TIMESTAMP})
                    count += 1
            if count > 0:
                batch.commit()
            await query.edit_message_text(f"🗑 تم تنظيف {count} طلب منتهٍ.", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await query.edit_message_text(f"❌ {e}")


# ══════════════════════════════════════════════════════════════
# § 8 — PAYMENT RECOVERY BOT (يتابع الطلبات المعلقة تلقائياً)
# ══════════════════════════════════════════════════════════════

async def payment_recovery_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يعمل كل 30 دقيقة: يجد الطلبات المعلقة ويرسل لأصحابها تذكيراً.

    Layer 5: Recovery Bot هو تجسيد لمبدأ "لا طلب يضيع صامتاً".
    عميل نسي صفحة الدفع مفتوحة أو انقطع اتصاله يحصل على
    فرصة ثانية تلقائياً — هذا يحوّل الخسارة لإيراد.
    """
    try:
        now = time.time()
        # الطلبات التي مضى عليها 20+ دقيقة ولم تُؤكَّد ولم تنتهِ
        twenty_min_ago = now - 1200
        docs = list(
            db().collection("payment_links")
            .where("status", "==", "pending")
            .stream()
        )

        recovered = 0
        for doc in docs:
            d = doc.to_dict()
            expires_at = d.get("expires_at", 0)

            # تجاهل المنتهية والجديدة جداً
            if now > expires_at or expires_at - now > 600:
                continue

            # لديها telegram_chat_id فقط
            chat_id = d.get("telegram_chat_id")
            if not chat_id:
                continue

            customer_ref = d.get("customer_reference", "")
            amount = d.get("amount_usd", 0)
            currency = d.get("currency", "")
            remaining = max(0, expires_at - now)

            try:
                await context.bot.send_message(
                    chat_id,
                    f"⏰ *تذكير: طلبك ينتهي قريباً!*\n\n"
                    f"🔖 المرجع: `{customer_ref}`\n"
                    f"💵 المبلغ: `${amount:.2f} {currency}`\n"
                    f"⏳ متبقي: `{int(remaining//60)} دقيقة`\n\n"
                    f"إن أتممت الدفع، أرسل:\n"
                    f"`تأكيد {customer_ref}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                recovered += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass  # العميل ربما حظر البوت

        if recovered > 0:
            logger.info(f"Recovery bot sent {recovered} reminders")
    except Exception as e:
        logger.error(f"Recovery job error: {e}")


# ══════════════════════════════════════════════════════════════
# § 9 — RECEIVE DELIVERY TRIGGER (من Firebase Function → Bot)
# ══════════════════════════════════════════════════════════════

async def handle_delivery_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يستقبل رسائل JSON مشفّرة من Firebase Function (عبر webhook أو
    رسالة خاصة للبوت) لتشغيل التسليم التلقائي.

    الصيغة: {"action":"deliver","product_id":"X","customer_reference":"Y","chat_id":123}
    """
    if not update.message or not update.message.text:
        return

    # فقط من webhook endpoint موثوق
    text = update.message.text.strip()
    if not text.startswith("{"):
        return

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return

    if payload.get("action") != "deliver":
        return

    sig = payload.pop("sig", "")
    payload_str = json.dumps(payload, sort_keys=True)
    if not _verify_internal_signature(payload_str, sig):
        logger.warning(f"Invalid internal signature in delivery trigger")
        return

    product_id  = str(payload.get("product_id", ""))
    customer_ref = str(payload.get("customer_reference", ""))
    chat_id     = int(payload.get("chat_id", 0))

    if not all([product_id, customer_ref, chat_id]):
        return

    result = await deliver_product(context.bot, chat_id, product_id, customer_ref)
    logger.info(f"Auto-delivery triggered: {customer_ref} → {result.method} → {result.success}")


def _verify_internal_signature(payload: str, signature: str) -> bool:
    """يتحقق من توقيع داخلي بين Firebase Function والبوت."""
    from lib.algorithms import verify_payload, constant_time_compare
    return verify_payload(payload, signature, SIGNING_SECRET)


# ══════════════════════════════════════════════════════════════
# § 10 — MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main() -> None:
    """
    نقطة التشغيل الرئيسية — يبني التطبيق ويبدأ polling أو webhook.
    """
    logger.info("═" * 60)
    logger.info("PEAK AI Agency — Telegram Bot Starting")
    logger.info("═" * 60)

    app = Application.builder().token(BOT_TOKEN).build()

    # ── تسجيل الأوامر ──
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("orders",    cmd_orders))
    app.add_handler(CommandHandler("pending",   cmd_pending))
    app.add_handler(CommandHandler("deliver",   cmd_deliver))
    app.add_handler(CommandHandler("revenue",   cmd_revenue))
    app.add_handler(CommandHandler("products",  cmd_products))
    app.add_handler(CommandHandler("health",    cmd_health))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # ── Inline Keyboard ──
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ── رسائل العملاء ──
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)(تأكيد|confirm|REF-)"),
        handle_payment_confirmation,
    ))

    # ── Recovery Job كل 30 دقيقة ──
    app.job_queue.run_repeating(
        payment_recovery_job,
        interval=1800,
        first=60,
        name="payment_recovery",
    )

    # ── إعداد أوامر البوت (تظهر في Telegram menu) ──
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start",     "بدء البوت"),
            BotCommand("stats",     "إحصاءات اليوم"),
            BotCommand("orders",    "آخر الطلبات"),
            BotCommand("pending",   "الطلبات المعلقة"),
            BotCommand("deliver",   "تسليم يدوي"),
            BotCommand("revenue",   "تقرير الإيرادات"),
            BotCommand("products",  "إدارة المنتجات"),
            BotCommand("health",    "فحص النظام"),
        ])
        logger.info(f"Bot started: @{(await application.bot.get_me()).username}")
        await application.bot.send_message(
            ADMIN_CHAT_ID,
            "🚀 *PEAK AI Bot — Started*\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC",
            parse_mode=ParseMode.MARKDOWN,
        )

    app.post_init = post_init

    # ── تحديد وضع التشغيل ──
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if webhook_url:
        # Webhook mode (للإنتاج)
        port = int(os.environ.get("PORT", 8080))
        logger.info(f"Starting in WEBHOOK mode on port {port}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            url_path="/webhook",
            secret_token=SIGNING_SECRET[:32],
        )
    else:
        # Polling mode (للتطوير)
        logger.info("Starting in POLLING mode (development)")
        app.run_polling(
            drop_pending_updates=True,
            poll_interval=1.0,
        )


if __name__ == "__main__":
    main()
