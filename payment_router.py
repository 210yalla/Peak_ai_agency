"""
═══════════════════════════════════════════════════════════════════
PEAK AI Agency © 2025 | peakvault.com | All rights reserved
bank/payment_router.py — نظام روابط الدفع الفريدة لكل عميل

╔═══════════════════════════════════════════════════════════════╗
║  PHILOSOPHY — توضيح صادق قبل أي كود                            ║
╠═══════════════════════════════════════════════════════════════╣
║  البلوكتشين شفّاف بطبيعته — لا يوجد "رابط دفع يخفي عنوان        ║
║  المحفظة" بأمان حقيقي بدون بنية معقدة (HD Wallets + مفتاح     ║
║  أساسي حساس جداً). الحل هنا مختلف وأكثر واقعية:                ║
║                                                                  ║
║  كل عميل يحصل على "مسار طلب" (route) فريد به:                  ║
║    - order_id فريد ومُوقَّع                                     ║
║    - توقيت دفع محدد بنافذة زمنية                                ║
║    - رصد مستقل للمعاملة على البلوكتشين عبر API علني             ║
║                                                                  ║
║  هذا بالضبط ما تفعله NOWPayments وCoinbase Commerce داخلياً —   ║
║  ليس إخفاءً للعنوان، بل نظام تتبع احترافي مستقل لكل طلب.        ║
╚═══════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .algorithms import secure_token, sign_payload, verify_payload, validate_amount, generate_idempotency_key


# ═══════════════════════════════════════════════════════════════
# § 1 — PAYMENT LINK MODEL
# ═══════════════════════════════════════════════════════════════

class PaymentLinkStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class PaymentLink:
    """
    رابط دفع فريد لعميل واحد ولطلب واحد.

    Layer 1: يحمل كل بيانات طلب الدفع — معرّف، مبلغ، عملة، حالة.

    Layer 2: كل حقل واضح الاسم والغرض. status يتغيّر عبر دورة
             حياة الطلب الكاملة (pending → confirmed/expired/cancelled).

    Layer 3: لا يفترض نوع منتج معين — يعمل لأي مبلغ وأي عملة
             مدعومة، حالياً أو مستقبلاً.

    Layer 4: لاحظ الفصل بين customer_reference (ما يراه العميل،
             آمن للمشاركة) وinternal_signature (للتحقق الداخلي
             فقط، لا يُعرض أبداً). هذا الفصل هو جوهر تصميم آمن.

    Layer 5: هذا الكائن هو "العقد الموثَّق" بين الوعد (عميل سيدفع)
             والواقع (تأكيد فعلي على البلوكتشين) — كل حقل هنا
             موجود ليُغلق فجوة محتملة بين الاثنين.
    """
    link_id: str                          # معرّف عام آمن للمشاركة في الرابط
    order_id: str                         # معرّف داخلي للطلب
    customer_reference: str               # رمز قصير يراه العميل (لا يكشف شيئاً حساساً)
    amount_usd: float
    currency: str                         # USDT-TRC20, BTC, etc.
    wallet_address: str                   # العنوان الفعلي (نفسه لكل العملاء لنفس العملة)
    status: PaymentLinkStatus = PaymentLinkStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    confirmed_at: Optional[float] = None
    internal_signature: str = ""          # HMAC، لا يُعرض للعميل أبداً
    idempotency_key: str = ""
    metadata: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_public_dict(self) -> dict:
        """
        يُرجع فقط الحقول الآمنة للعرض للعميل — أبداً internal_signature.

        Layer 5: هذه الدالة هي خط الدفاع الأخير ضد تسريب بيانات
                 داخلية بالخطأ عبر API response كامل لكائن Python.
                 الأمان الجيد لا يعتمد على "تذكّر عدم الإرسال" —
                 بل على دالة صريحة تحدد ما هو آمن للخروج.
        """
        return {
            "link_id": self.link_id,
            "customer_reference": self.customer_reference,
            "amount_usd": self.amount_usd,
            "currency": self.currency,
            "wallet_address": self.wallet_address,
            "status": self.status.value,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired(),
        }


# ═══════════════════════════════════════════════════════════════
# § 2 — PAYMENT LINK GENERATOR
# ═══════════════════════════════════════════════════════════════

class PaymentLinkGenerator:
    """
    يولّد روابط دفع فريدة وآمنة لكل عميل — القلب الفعلي لـ
    "نظام خيارات دفع الكريبتو الخاص" المطلوب.

    Layer 1 (يعمل ويحل المشكلة):
        ينشئ رابط دفع جديد لكل طلب، فريد، موقَّع، له مهلة زمنية،
        ومرتبط بـ Idempotency Key يمنع تكراره عن طريق الخطأ.

    Layer 2 (يفهمه مطور بعد 5 سنوات):
        أنشئ instance واحد مع secret_key سري (من متغيرات البيئة،
        لا hardcoded أبداً). استدعِ .create_link(...) لكل طلب جديد.
        استخدم .verify_link(link_id, signature) عند أي استرجاع.

    Layer 3 (يتكيف مع بيانات لم تُخترع بعد):
        يدعم أي عملة جديدة تُضاف لاحقاً (مجرد سلسلة نصية)، وأي
        نظام عملاء مستقبلي (customer_id اختياري ومرن).

    Layer 4 (قراءته وحدها تعلّم المبتدئ):
        لاحظ الفرق بين 3 معرّفات مختلفة الغرض هنا:
        - order_id: داخلي، للسجلات والتدقيق
        - link_id: عام، يظهر في الرابط نفسه (URL)
        - customer_reference: قصير وودود، ما يكتبه العميل كمرجع
          عند التواصل ("طلبي رقم REF-A8F3")
        كل واحد له دور مختلف — الخلط بينها خطأ شائع في الأنظمة
        الأقل نضجاً.

    Layer 5 (يعبّر عن فلسفة الحل لا فقط تنفيذه):
        "الخصوصية" الحقيقية في نظام الدفع هذا ليست إخفاء العنوان
        (مستحيل تقنياً على بلوكتشين علني) — هي عزل كل طلب عن
        الآخرين بحيث لا يمكن لأي طرف ثالث ربط طلبات عميل واحد
        ببعضها من خلال الرابط وحده. هذا هدف واقعي وقابل للتحقيق.
    """

    def __init__(self, secret_key: str, *, default_ttl_seconds: int = 1800):
        if len(secret_key) < 32:
            raise ValueError(
                "secret_key must be at least 32 characters for production security. "
                "Generate one with: secrets.token_hex(32)"
            )
        self._secret = secret_key
        self._default_ttl = default_ttl_seconds
        self._active_links: dict[str, PaymentLink] = {}

    def create_link(
        self,
        *,
        amount_usd: float,
        currency: str,
        wallet_address: str,
        customer_identity: str,  # أي معرّف عميل ثابت (session id، رقم هاتف مُجزَّأ، إلخ)
        product_reference: str = "",
        ttl_seconds: Optional[int] = None,
    ) -> PaymentLink:
        """
        ينشئ رابط دفع جديداً فريداً وآمناً.

        Raises:
            ValidationError: من validate_amount إن كان المبلغ غير صالح
        """
        validated_amount = validate_amount(amount_usd, max_value=100_000)

        # Idempotency: نفس العميل + نفس المنتج + نفس النافذة الزمنية
        # = نفس المفتاح، يمنع إنشاء طلبات مكررة بالخطأ (راجع ث-01)
        idem_key = generate_idempotency_key(
            customer_identity, product_reference, str(validated_amount), window_seconds=300
        )

        # إن وُجد طلب نشط بنفس idempotency key، أعد استخدامه بدل تكراره
        existing = self._active_links.get(idem_key)
        if existing and not existing.is_expired() and existing.status == PaymentLinkStatus.PENDING:
            return existing

        link_id = secure_token(24)
        order_id = f"PV-{int(time.time())}-{secure_token(16)[:8].upper()}"
        customer_ref = self._generate_customer_reference(customer_identity, order_id)

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl

        link = PaymentLink(
            link_id=link_id,
            order_id=order_id,
            customer_reference=customer_ref,
            amount_usd=validated_amount,
            currency=currency,
            wallet_address=wallet_address,
            expires_at=time.time() + ttl,
            idempotency_key=idem_key,
            metadata={"product_reference": product_reference},
        )

        # توقيع داخلي يربط كل الحقول الحرجة معاً — أي تلاعب لاحق يُكتشف فوراً
        payload = f"{link.link_id}|{link.order_id}|{link.amount_usd}|{link.currency}|{link.wallet_address}"
        link.internal_signature = sign_payload(payload, self._secret)

        self._active_links[idem_key] = link
        return link

    def verify_link_integrity(self, link: PaymentLink) -> bool:
        """
        يتحقق أن بيانات الرابط لم تُعدَّل بعد إنشائه (دفاع ضد
        تلاعب محتمل في قاعدة البيانات أو أثناء النقل).
        """
        payload = f"{link.link_id}|{link.order_id}|{link.amount_usd}|{link.currency}|{link.wallet_address}"
        return verify_payload(payload, link.internal_signature, self._secret)

    def confirm_payment(self, link_id: str, *, confirmed_amount: float) -> tuple[bool, str]:
        """
        يؤكد دفعاً بعد التحقق الخارجي (من فحص البلوكتشين الفعلي).

        Layer 4: لاحظ أن هذه الدالة لا "تثق" بالمبلغ المُرسَل لها
                 بشكل أعمى — تتحقق من تطابقه مع المبلغ المتوقع
                 بهامش معقول (راجع ث-05 Amount Underflow في تحليل
                 الثغرات السابق).

        Returns:
            (success: bool, message: str)
        """
        link = self._find_by_id(link_id)
        if link is None:
            return False, "Link not found"

        if link.status != PaymentLinkStatus.PENDING:
            return False, f"Link already in status: {link.status.value}"

        if link.is_expired():
            link.status = PaymentLinkStatus.EXPIRED
            return False, "Link has expired"

        if not self.verify_link_integrity(link):
            return False, "Link integrity check failed — possible tampering detected"

        # هامش تحقق 1%-5% للتعامل مع تقلبات رسوم الشبكة الطفيفة
        ratio = confirmed_amount / link.amount_usd if link.amount_usd > 0 else 0
        if not (0.99 <= ratio <= 1.05):
            return False, (
                f"Amount mismatch: expected ~{link.amount_usd}, "
                f"got {confirmed_amount} (ratio: {ratio:.3f})"
            )

        link.status = PaymentLinkStatus.CONFIRMED
        link.confirmed_at = time.time()
        return True, "Payment confirmed successfully"

    def expire_stale_links(self) -> int:
        """ينظّف الروابط منتهية الصلاحية — يُستدعى دورياً (Cloud Scheduler)."""
        count = 0
        for link in self._active_links.values():
            if link.status == PaymentLinkStatus.PENDING and link.is_expired():
                link.status = PaymentLinkStatus.EXPIRED
                count += 1
        return count

    def _find_by_id(self, link_id: str) -> Optional[PaymentLink]:
        for link in self._active_links.values():
            if link.link_id == link_id:
                return link
        return None

    @staticmethod
    def _generate_customer_reference(customer_identity: str, order_id: str) -> str:
        """
        مرجع قصير وودود للعميل — لا يكشف بنية order_id الداخلية.

        Layer 5: حتى المعرّفات "غير الحساسة" يجب ألا تكشف بنية
                 النظام الداخلية (تسلسل الطلبات، التوقيت الدقيق).
                 هذا hash قصير مشتق، لا تسلسل مباشر.
        """
        h = hashlib.sha256(f"{customer_identity}|{order_id}".encode()).hexdigest()
        return f"REF-{h[:8].upper()}"


# ═══════════════════════════════════════════════════════════════
# § 3 — BLOCKCHAIN VERIFICATION ADAPTER (Interface)
# ═══════════════════════════════════════════════════════════════

class BlockchainVerifier:
    """
    واجهة (interface) للتحقق من معاملات البلوكتشين الفعلية.

    Layer 1: يحدد العقد الذي يجب أن تلتزم به أي عملية تحقق حقيقية.

    Layer 2: هذا abstract base — التطبيق الفعلي (TronVerifier,
             EthereumVerifier) يرث منه ويطبّق check_transaction.

    Layer 3: يسمح بإضافة شبكات جديدة (Solana، Polygon) دون تغيير
             أي كود يستخدم الواجهة، فقط بإضافة implementation جديد.

    Layer 4: هذا Dependency Inversion Principle عملياً — الكود
             الذي يستخدم "تحقق من معاملة" لا يعرف أو يهتم أي شبكة
             بلوكتشين فعلياً يُستخدَم خلف الكواليس.

    Layer 5: الفصل بين "ماذا نريد" (تحقق من دفعة) و"كيف نحققه"
             (API محدد لشبكة محددة) يحمي كل الكود المعتمد على
             هذا البنك من التغييرات المستقبلية في تفاصيل أي شبكة.
    """

    def check_transaction(
        self, wallet_address: str, expected_amount: float, since_timestamp: float
    ) -> Optional[dict]:
        """
        يبحث عن معاملة واردة تطابق العنوان والمبلغ التقريبي بعد
        since_timestamp. يُرجع تفاصيل المعاملة إن وُجدت، أو None.

        يجب أن تُطبَّق هذه الدالة فعلياً لكل شبكة عبر استدعاء API
        علني حقيقي (مثل TronGrid لـ TRC-20، Etherscan لـ ERC-20).
        هذا الملف يعرّف العقد فقط — التطبيق في طبقة الـ Cloud
        Function الرئيسية (main.py) حيث تتوفر مفاتيح API بأمان.
        """
        raise NotImplementedError(
            "Subclasses must implement check_transaction() with real blockchain API calls. "
            "See main.py for TronGrid/Etherscan integration examples."
        )


# ═══════════════════════════════════════════════════════════════
# § SELF-TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    generator = PaymentLinkGenerator(secret_key=secure_token(32))

    link = generator.create_link(
        amount_usd=49.99,
        currency="USDT-TRC20",
        wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
        customer_identity="customer_session_abc123",
        product_reference="lexforge-ai-001",
    )

    assert link.status == PaymentLinkStatus.PENDING
    assert link.link_id is not None
    assert len(link.link_id) == 48  # 24 bytes hex
    assert generator.verify_link_integrity(link) is True

    public = link.to_public_dict()
    assert "internal_signature" not in public  # تأكيد عدم تسريب السر

    # Duplicate request within window → same link (idempotency)
    link2 = generator.create_link(
        amount_usd=49.99,
        currency="USDT-TRC20",
        wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
        customer_identity="customer_session_abc123",
        product_reference="lexforge-ai-001",
    )
    assert link2.link_id == link.link_id  # نفس الرابط، لا تكرار

    # Confirm payment
    success, msg = generator.confirm_payment(link.link_id, confirmed_amount=49.99)
    assert success is True
    assert link.status == PaymentLinkStatus.CONFIRMED

    # Tampered amount should fail
    link3 = generator.create_link(
        amount_usd=100.0, currency="BTC", wallet_address="bc1qtest",
        customer_identity="customer_2", product_reference="other-product",
    )
    success2, msg2 = generator.confirm_payment(link3.link_id, confirmed_amount=1.0)
    assert success2 is False

    print("✅ All payment router self-tests passed.")
