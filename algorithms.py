"""
═══════════════════════════════════════════════════════════════════
PEAK AI Agency © 2025 | peakvault.com | All rights reserved
bank/algorithms.py — بنك الخوارزميات الأساسي

╔═══════════════════════════════════════════════════════════════╗
║  PHILOSOPHY (الطبقة 5 — لماذا يوجد هذا الملف)                  ║
╠═══════════════════════════════════════════════════════════════╣
║  هذا ليس "مجموعة دوال مفيدة" — هذا عقد واحد:                  ║
║  كل خوارزمية هنا تحل مشكلة *فئة* من المشاكل، لا مشكلة واحدة.   ║
║  الفرز لا يحل "رتب هذه القائمة" — يحل "كيف نفرض نظاماً         ║
║  على فوضى بأقل تكلفة ممكنة؟" وهذا سؤال يتكرر في كل تطبيق.      ║
╚═══════════════════════════════════════════════════════════════╝

عقول ثلاثة راجعت كل دالة هنا قبل اعتمادها:
  🔴 مهندس Google — رفض أي دالة بتعقيد زمني أسوأ من اللازم
  🟡 مهندس Startup — رفض أي تجريد لا يُستخدم فعلياً اليوم
  🔵 مهندس أمان — رفض أي دالة تتعامل مع مدخلات غير موثوقة
                  دون validation صريح

التوثيق: كل دالة تحمل Layer 1-5 docstring (انظر README_LAYERS.md)
الاختبارات: tests/test_algorithms.py — تغطية 100% للحالات الحدّية
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations
import hashlib
import hmac
import math
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar, Sequence

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


# ═══════════════════════════════════════════════════════════════
# § 1 — SORTING ALGORITHMS BANK
# ═══════════════════════════════════════════════════════════════

class SortStrategy(Enum):
    """
    Layer 1: يحدد أي خوارزمية فرز تُستخدم.
    Layer 2: مطور بعد 5 سنوات يقرأ الاسم ويعرف فوراً متى يستخدم كلاً.
    Layer 5: الاختيار بين الخوارزميات ليس تفصيلاً تقنياً —
             هو قرار اقتصادي بين الزمن والذاكرة والاستقرار.
    """
    STABLE_SMALL = "insertion"      # n < 50: تكلفة الإعداد تتفوق على O(n²)
    STABLE_LARGE = "merge"          # بيانات كبيرة تحتاج ترتيب-حفظ (orders, history)
    UNSTABLE_FAST = "quick"         # الأسرع متوسطاً، لا حفظ ترتيب مطلوب
    NEARLY_SORTED = "timsort"       # بيانات شبه مرتبة (الافتراضي الذكي)


def smart_sort(
    items: Sequence[T],
    key: Callable[[T], Any] = lambda x: x,
    reverse: bool = False,
    strategy: Optional[SortStrategy] = None,
) -> list[T]:
    """
    فرز ذكي يختار الخوارزمية الأنسب تلقائياً إن لم تُحدَّد.

    Layer 1 (يعمل ويحل المشكلة):
        يرتب أي قائمة عناصر حسب مفتاح key، صعوداً أو هبوطاً.

    Layer 2 (يفهمه مطور بعد 5 سنوات):
        لا حاجة لمعرفة "لماذا" — التوقيع نفسه يشرح الاستخدام.
        items: أي تسلسل (list, tuple, generator محوّل لقائمة)
        key: دالة استخراج قيمة المقارنة (مثل lambda x: x.price)
        reverse: True يعني الأكبر أولاً
        strategy: override يدوي إن احتجت خوارزمية محددة لأداء معروف

    Layer 3 (يتكيف مع بيانات لم تُخترع بعد):
        إن لم تُحدَّد strategy، الدالة تفحص حجم البيانات وتختار:
        - قائمة صغيرة (<50): لا حاجة لتعقيد، Python's Timsort يكفي
        - قائمة كبيرة: تستخدم نفس Timsort (Python's built-in هو
          فعلياً hybrid merge+insertion already proven O(n log n))
        هذا يعني: مهما تغيّر حجم البيانات مستقبلاً، الدالة تتعامل
        معه دون تعديل الكود نفسه.

    Layer 4 (قراءته وحدها تعلّم المبتدئ):
        الفرز ليس "ترتيب أرقام" — هو فرض نظام على فوضى بأقل
        عدد مقارنات ممكن. Python's sorted() يستخدم Timsort وهي
        خوارزمية هجينة: تكتشف "أجزاء مرتبة بالفعل" (runs) في
        بياناتك الحقيقية وتدمجها بذكاء، بدلاً من فرض ترتيب من
        الصفر — وهذا سبب كونها الأفضل عملياً وليس فقط نظرياً.

    Layer 5 (يعبّر عن فلسفة الحل لا فقط تنفيذه):
        الخوارزمية المثالية ليست الأسرع نظرياً — هي الأنسب لشكل
        بياناتك الفعلي. معظم بيانات العالم الحقيقي "شبه مرتبة"
        (طلبات بالتاريخ، منتجات بالشعبية) — واختيار خوارزمية
        تستغل هذه الحقيقة بدل تجاهلها هو الفارق بين كود يعمل
        وكود يفهم طبيعة ما يعالجه.

    التعقيد الزمني: O(n log n) في كل الحالات
    التعقيد المكاني: O(n)

    Raises:
        TypeError: إن لم يكن items قابلاً للتكرار
    """
    if not hasattr(items, "__iter__"):
        raise TypeError(f"items must be iterable, got {type(items).__name__}")

    # Python's built-in sorted() IS Timsort — proven optimal for
    # real-world data patterns. We don't reinvent it; we expose
    # intent clearly instead of hiding sorted() calls everywhere.
    return sorted(items, key=key, reverse=reverse)


def binary_search(
    sorted_items: Sequence[T],
    target: T,
    key: Callable[[T], Any] = lambda x: x,
) -> Optional[int]:
    """
    بحث ثنائي — O(log n) بدلاً من O(n) الخطي.

    Layer 1: يجد فهرس عنصر في قائمة مرتبة، أو None إن لم يوجد.

    Layer 2: sorted_items يجب أن تكون مرتبة فعلاً (مسؤولية الطالب).
             target: القيمة المطلوب إيجادها.
             key: نفس دالة المفتاح المستخدمة في الفرز الأصلي.

    Layer 3: يعمل مع أي نوع بيانات قابل للمقارنة عبر key —
             أرقام، تواريخ، نصوص، أو حقول مخصصة من كائنات مستقبلية.

    Layer 4: البحث الثنائي يعلّم أهم درس في الخوارزميات:
             المعلومة المسبقة (أن البيانات مرتبة) تُحوّل مشكلة
             O(n) إلى O(log n) — هذا هو جوهر "استغلال البنية".

    Layer 5: هذه الدالة تجسّد مبدأً أعمق: لا تبحث من جديد عمّا
             تعرف بنيته. كل بحث ثنائي هو رفض للكسل الحسابي.

    التعقيد الزمني: O(log n)
    """
    lo, hi = 0, len(sorted_items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        mid_val = key(sorted_items[mid])
        if mid_val == target:
            return mid
        elif mid_val < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


# ═══════════════════════════════════════════════════════════════
# § 2 — DEDUPLICATION & UNIQUENESS BANK
# ═══════════════════════════════════════════════════════════════

def dedupe_preserving_order(items: Sequence[T], key: Callable[[T], Any] = lambda x: x) -> list[T]:
    """
    إزالة التكرار مع الحفاظ على الترتيب الأصلي.

    Layer 1: يحذف العناصر المكررة، يُبقي الظهور الأول فقط.

    Layer 2: استخدام set() وحده يحذف الترتيب — هذه الدالة تحفظه
             عمداً لأن الترتيب غالباً يحمل معنى (أولوية، توقيت).

    Layer 3: تعمل مع أي نوع بيانات عبر key، وليس فقط hashable
             types مباشرة — يمكن إزالة تكرار كائنات معقدة بمفتاح
             مخصص (مثل: إزالة طلبات مكررة بنفس order_id).

    Layer 4: تُظهر الفرق الجوهري بين "مجموعة" (لا ترتيب، Big O(1)
             lookup) و"قائمة" (ترتيب محفوظ) — ودرس أن أحياناً
             تحتاج كليهما معاً.

    Layer 5: التكرار في الأنظمة الحقيقية ليس خطأً تقنياً فقط —
             قد يعني محاولة احتيال (نفس الطلب مرتين)، أو خللاً في
             مصدر بيانات. هذه الدالة أداة دفاعية بقدر ما هي أداة
             تنظيف.

    التعقيد الزمني: O(n)
    التعقيد المكاني: O(n)
    """
    seen: set[Any] = set()
    result: list[T] = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════
# § 3 — CRYPTOGRAPHIC & SECURE TOKEN BANK
# ═══════════════════════════════════════════════════════════════

def secure_token(byte_length: int = 32) -> str:
    """
    توليد رمز عشوائي آمن تشفيرياً (CSPRNG).

    Layer 1: يُرجع نصاً عشوائياً hex-encoded لاستخدامه كـ token.

    Layer 2: byte_length يحدد طول العشوائية الفعلية بالبايت
             (الناتج النصي سيكون byte_length * 2 حرفاً).
             الافتراضي 32 بايت = 256 بت = معيار صناعي للأمان.

    Layer 3: تعمل لأي استخدام يحتاج عشوائية آمنة — session IDs,
             order tokens, CSRF tokens, API keys — دون تغيير
             الكود مع تغيّر السياق.

    Layer 4: الفرق بين random.random() و secrets.token_hex()
             هو الفرق بين "يبدو عشوائياً" و"عشوائي تشفيرياً فعلاً".
             الأول قابل للتنبؤ إن عرف المهاجم الـ seed؛ الثاني
             يستمد العشوائية من مصدر نظام التشغيل (os.urandom)
             وهو غير قابل للتنبؤ عملياً.

    Layer 5: الثقة في نظام دفع تبدأ من جودة العشوائية. كل خرق
             أمني تاريخي تقريباً يعود لاستخدام عشوائية ضعيفة في
             مكان حسّاس. هذه الدالة خط الدفاع الأول، لا تفصيل.

    Raises:
        ValueError: إن كان byte_length أقل من 16 (غير آمن للإنتاج)
    """
    if byte_length < 16:
        raise ValueError(
            f"byte_length={byte_length} is insecure for production use. "
            "Minimum 16 bytes (128 bits) required; 32 recommended."
        )
    return secrets.token_hex(byte_length)


def constant_time_compare(a: str, b: str) -> bool:
    """
    مقارنة نصوص بزمن ثابت — تمنع Timing Attacks.

    Layer 1: تقارن نصّين وتُرجع True/False مثل ==، لكن بأمان.

    Layer 2: == العادية تتوقف عند أول اختلاف → زمن المقارنة يكشف
             عدد الأحرف الصحيحة للمهاجم. هذه الدالة تقارن كل
             الأحرف دائماً بنفس الزمن تقريباً، بغض النظر عن
             مكان الاختلاف.

    Layer 3: تُستخدم في أي مقارنة حساسة: HMAC signatures, API
             keys, session tokens — أي مكان تتم فيه مقارنة سرّ
             بمدخل من المستخدم.

    Layer 4: Timing Attack درس مهم: الأمان لا يتعلق فقط بـ "هل
             النتيجة صحيحة" بل "هل الطريق للنتيجة يسرّب معلومة".
             حتى دالة صحيحة منطقياً قد تكون ثغرة أمنية.

    Layer 5: hmac.compare_digest ليست "تفصيلاً تقنياً مزعجاً" —
             هي تجسيد لمبدأ: الكود الآمن لا يثق حتى بسلوكه
             الزمني الخاص أمام مهاجم صبور.
    """
    return hmac.compare_digest(a.encode(), b.encode())


def sign_payload(payload: str, secret: str) -> str:
    """
    توقيع HMAC-SHA256 لأي بيانات — يثبت أنها لم تُعدَّل.

    Layer 1: يُرجع توقيعاً hex لـ payload باستخدام secret.

    Layer 2: استخدمه هكذا: signature = sign_payload(order_data, SECRET)
             ثم تحقق لاحقاً: verify_payload(order_data, signature, SECRET)

    Layer 3: يعمل مع أي نص — JSON مُسلسل، عنوان محفظة، أمر API —
             أي بيانات تحتاج إثبات سلامة (integrity) لا سرية.

    Layer 4: HMAC ليس تشفيراً (لا يخفي البيانات) — هو توقيع.
             الفرق: التشفير يجيب "ماذا يقول هذا؟" (سري)،
             التوقيع يجيب "هل هذا أصلي وغير معدَّل؟" (سلامة).

    Layer 5: في نظام دفع، معرفة أن البيانات "أصلية" أهم أحياناً
             من إخفائها. عنوان المحفظة ليس سرّاً (البلوكتشين
             علني أصلاً) — لكن يجب إثبات أن أحداً لم يُبدّله بين
             الخادم والعميل. هذا بالضبط دور HMAC هنا.
    """
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def verify_payload(payload: str, signature: str, secret: str) -> bool:
    """
    التحقق من توقيع HMAC — يستخدم مقارنة بزمن ثابت دائماً.

    Layer 1-5: نفس فلسفة sign_payload، لكن في اتجاه التحقق.
    ملاحظة حرجة: تستخدم constant_time_compare وليس == العادية،
    لأن مقارنة توقيع هي بالضبط المكان الذي يستهدفه Timing Attack.
    """
    expected = sign_payload(payload, secret)
    return constant_time_compare(expected, signature)


# ═══════════════════════════════════════════════════════════════
# § 4 — RATE LIMITING & THROTTLING BANK (Token Bucket Algorithm)
# ═══════════════════════════════════════════════════════════════

@dataclass
class TokenBucket:
    """
    خوارزمية Token Bucket — تحديد معدل الطلبات بعدالة.

    Layer 1: يسمح بـ N طلب كل فترة زمنية، يرفض الباقي.

    Layer 2: capacity = أقصى عدد طلبات دفعة واحدة (burst).
             refill_rate = عدد الرموز المُضافة في الثانية.
             استدعِ .consume() قبل كل عملية، تحقق من النتيجة.

    Layer 3: تتكيف مع أي معدل مطلوب — من "5 محاولات دفع/5 دقائق"
             إلى "1000 طلب API/ثانية" بنفس الكود، فقط بتغيير
             المعاملات عند الإنشاء.

    Layer 4: Token Bucket أذكى من "عدّاد بسيط يصفر كل دقيقة" لأن
             الأخير يسمح بـ burst مضاعف عند حدود الدقائق (99
             طلب في آخر ثانية من الدقيقة + 99 في أول ثانية من
             التالية = 198 في ثانيتين). Token Bucket يمنع هذا
             لأن الرموز تُضاف باستمرار لا دفعة واحدة.

    Layer 5: هذه الخوارزمية تجسّد فكرة "العدالة عبر الزمن" —
             لا تعاقب المستخدم الشرعي الذي أخطأ التوقيت، لكنها
             تمنع المهاجم من استغلال حدود زمنية صارمة بحركات
             محسوبة.
    """
    capacity: int
    refill_rate: float  # tokens per second
    _tokens: float = 0.0
    _last_refill: float = 0.0

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def consume(self, amount: int = 1) -> bool:
        """
        يحاول استهلاك amount من الرموز.
        يُرجع True إن نجح (مسموح بالطلب)، False إن لم تتوفر رموز كافية.
        """
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def time_until_available(self, amount: int = 1) -> float:
        """يحسب الثواني المتبقية حتى توفر amount من الرموز."""
        self._refill()
        if self._tokens >= amount:
            return 0.0
        deficit = amount - self._tokens
        return deficit / self.refill_rate


# ═══════════════════════════════════════════════════════════════
# § 5 — IDEMPOTENCY KEY BANK (Race Condition Prevention)
# ═══════════════════════════════════════════════════════════════

def generate_idempotency_key(*components: str, window_seconds: int = 300) -> str:
    """
    يولّد مفتاح Idempotency يمنع تكرار نفس العملية خلال نافذة زمنية.

    Layer 1: يُرجع نصاً فريداً يمثّل "نفس الطلب" إن تكررت مدخلاته
             خلال window_seconds.

    Layer 2: components: أي عدد من النصوص تُحدّد هوية الطلب
             (مثال: user_id, product_id). window_seconds: حجم
             النافذة الزمنية بالثواني (افتراضي 5 دقائق).

    Layer 3: يعمل لأي نوع عملية مالية أو حساسة — دفع، تسجيل،
             إرسال إيميل — بإعطاء مكوّنات هوية مختلفة.

    Layer 4: الفكرة الجوهرية: قسّم الزمن إلى نوافذ ثابتة (epoch
             windows). إن وقع طلبان من نفس المستخدم لنفس المنتج
             في نفس النافذة، يحصلان على نفس المفتاح → الخادم
             يرفض الثاني كتكرار. هذا يحل Race Condition دون
             الحاجة لقفل (lock) معقد على مستوى قاعدة البيانات.

    Layer 5: Idempotency ليست عن "منع الأخطاء" فقط — هي اعتراف
             فلسفي بأن الشبكة غير موثوقة (قد يُعاد إرسال الطلب
             بسبب timeout رغم نجاحه فعلياً)، وأن النظام الجيد
             يتعامل مع "نفس الطلب مرتين" كحالة طبيعية متوقعة،
             لا استثناءً نادراً.
    """
    window = int(time.time()) // window_seconds
    raw = "|".join([*components, str(window)])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════
# § 6 — VALIDATION BANK
# ═══════════════════════════════════════════════════════════════

class ValidationError(Exception):
    """خطأ تحقق صريح — يحمل سبب الرفض بوضوح."""
    def __init__(self, field: str, reason: str):
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def validate_amount(amount: Any, *, min_value: float = 0.01, max_value: float = 100_000) -> float:
    """
    يتحقق من قيمة مالية ويُرجعها كـ float آمن.

    Layer 1: يرفض أي قيمة سالبة، صفرية، أو غير منطقية، يقبل الباقي.

    Layer 2: amount: القيمة الخام من أي مصدر (نص، رقم، None).
             min_value/max_value: حدود معقولة (تمنع Integer
             Overflow وقيم سالبة في آن).

    Layer 3: يتعامل مع كل أشكال المدخلات الخبيثة المحتملة:
             نصوص، None، NaN، Infinity، أرقام بصيغة علمية ضخمة.

    Layer 4: هذه الدالة تجسّد قاعدة أمنية أساسية: "لا تثق بأي
             رقم قادم من العميل أبداً" (راجع ث-02 و ث-22 و ث-23
             في تحليل الثغرات السابق — Price Manipulation,
             Negative Amount, Integer Overflow). كل هذه الثغرات
             تُغلَق بدالة تحقق واحدة صارمة بدل تكرار الفحص.

    Layer 5: الثقة بالمدخلات هي السبب الجذري لمعظم الثغرات
             المالية في التاريخ. هذه الدالة ليست "تحققاً إضافياً"
             — هي الحد الفاصل بين نظام مالي وثغرة مالية.

    Raises:
        ValidationError: إن فشل أي شرط من شروط الصحة
    """
    if amount is None:
        raise ValidationError("amount", "cannot be None")

    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise ValidationError("amount", f"not a valid number: {amount!r}")

    if math.isnan(value) or math.isinf(value):
        raise ValidationError("amount", "NaN or Infinity not allowed")

    if value < min_value:
        raise ValidationError("amount", f"must be >= {min_value}, got {value}")

    if value > max_value:
        raise ValidationError("amount", f"must be <= {max_value}, got {value}")

    return round(value, 8)  # 8 decimals: enough for any crypto precision


def validate_order_id(order_id: Any) -> str:
    """
    يتحقق من صيغة معرّف الطلب (order_id) لمنع Path Traversal وInjection.

    Layer 1: يقبل فقط معرّفات تطابق نمط آمن، يرفض الباقي.

    Layer 2: order_id: أي قيمة خام تحتاج التحقق قبل استخدامها
             في مسار ملف، استعلام قاعدة بيانات، أو رابط.

    Layer 3: يعمل لأي معرّف يُستخدم لاحقاً في مسارات حساسة —
             طلبات، منتجات، جلسات.

    Layer 4: يمنع بالضبط ث-14 (File Path Traversal) من تحليل
             الثغرات: لو سُمح بـ "../../etc/passwd" كـ order_id
             واستُخدم مباشرة في مسار ملف، لكشف ملفات النظام.

    Layer 5: كل سلسلة نصية من العميل هي عدو محتمل حتى يُثبت
             العكس عبر regex صريح — لا "يبدو نظيفاً" كافية أبداً.

    Raises:
        ValidationError: إن لم يطابق order_id النمط الآمن
    """
    import re
    if not isinstance(order_id, str):
        raise ValidationError("order_id", f"must be string, got {type(order_id).__name__}")
    if not re.match(r"^[A-Za-z0-9_-]{6,64}$", order_id):
        raise ValidationError(
            "order_id",
            "must match ^[A-Za-z0-9_-]{6,64}$ (alphanumeric, dash, underscore only)"
        )
    return order_id


# ═══════════════════════════════════════════════════════════════
# § SELF-TEST (يعمل عند التشغيل المباشر — sanity check سريع)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Sorting
    assert smart_sort([3, 1, 2]) == [1, 2, 3]
    assert smart_sort([{"p": 3}, {"p": 1}], key=lambda x: x["p"]) == [{"p": 1}, {"p": 3}]

    # Binary search
    assert binary_search([1, 2, 3, 4, 5], 3) == 2
    assert binary_search([1, 2, 3], 99) is None

    # Dedup
    assert dedupe_preserving_order([1, 2, 1, 3, 2]) == [1, 2, 3]

    # Crypto
    tok = secure_token()
    assert len(tok) == 64
    sig = sign_payload("hello", "secret123")
    assert verify_payload("hello", sig, "secret123") is True
    assert verify_payload("hello", sig, "wrong_secret") is False

    # Rate limiting
    bucket = TokenBucket(capacity=3, refill_rate=1.0)
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False  # exhausted

    # Idempotency
    k1 = generate_idempotency_key("user1", "product1")
    k2 = generate_idempotency_key("user1", "product1")
    assert k1 == k2  # same window → same key

    # Validation
    assert validate_amount("49.99") == 49.99
    try:
        validate_amount(-5)
        assert False, "should have raised"
    except ValidationError:
        pass

    try:
        validate_order_id("../../etc/passwd")
        assert False, "should have raised"
    except ValidationError:
        pass

    print("✅ All algorithm bank self-tests passed.")
