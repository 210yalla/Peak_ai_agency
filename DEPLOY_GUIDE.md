# PEAK AI Agency — دليل النشر الكامل
## من الصفر إلى موقع حي في 30 دقيقة

---

## المتطلبات المسبقة

```bash
# تحقق من التثبيت
node --version   # يجب >= 18
python --version # يجب >= 3.11
firebase --version || npm install -g firebase-tools
```

---

## الخطوة 1 — متغيرات البيئة (الأهم — افعل هذا أولاً)

```bash
# أنشئ ملف .env في backend/functions/ (لا ترفعه على GitHub أبداً)
cat > backend/functions/.env << 'ENVEOF'
PAYMENT_SIGNING_SECRET=<أنشئه بالأمر أدناه>
TELEGRAM_BOT_TOKEN=<من @BotFather>
TELEGRAM_ADMIN_CHAT_ID=<ID حسابك على تلجرام>
GEMINI_API_KEY=<من Google AI Studio>
ENVEOF

# توليد PAYMENT_SIGNING_SECRET آمن تشفيرياً
python -c "import secrets; print(secrets.token_hex(32))"
# انسخ الناتج في .env
```

**⚠️ تحذير حرج:** `PAYMENT_SIGNING_SECRET` يوقِّع كل روابط الدفع.
إن تسرَّب، يمكن لأي أحد التلاعب بمبالغ الطلبات.
**لا تضعه في الكود، لا في GitHub، لا في أي chat.**

---

## الخطوة 2 — Firebase Setup

```bash
# سجّل دخول
firebase login

# أنشئ مشروعاً جديداً (أو استخدم موجوداً)
firebase projects:create peak-ai-agency-prod

# ربط المشروع المحلي
firebase use peak-ai-agency-prod

# تفعيل الخدمات المطلوبة (من Firebase Console):
# Firestore → Create database → Production mode
# Functions  → Upgrade to Blaze plan (مجاني حتى حدود مرتفعة جداً)
```

---

## الخطوة 3 — نشر قواعد Firestore

```bash
# انسخ قواعد الأمان
cp backend/firestore/firestore.rules firestore.rules

# انشر القواعد
firebase deploy --only firestore:rules

# تحقق: افتح Firebase Console → Firestore → Rules
# يجب أن تجد "deny all by default" في أعلى الملف
```

---

## الخطوة 4 — نشر الموقع

```bash
# اضبط firebase.json (موجود في web/)
firebase deploy --only hosting

# تحقق:
open https://peak-ai-agency-prod.web.app
```

---

## الخطوة 5 — ربط الدومين peakvault.com

```bash
# من Firebase Console → Hosting → Add custom domain
# 1. اكتب: peakvault.com
# 2. أضف DNS records الظاهرة في Cloudflare/Namecheap
# 3. انتظر 24-48 ساعة للانتشار
```

---

## الخطوة 6 — Cloudflare (للحماية و100K مستخدم)

```
1. أضف موقعك على cloudflare.com
2. حوّل nameservers لـ Cloudflare
3. إعدادات مهمة:
   SSL/TLS Mode: Full (Strict)
   Always Use HTTPS: ON
   Auto Minify: JS + CSS + HTML
   Caching Level: Standard
   Browser Cache TTL: 4 hours

4. Page Rules:
   peakvault.com/api/*  → Cache Level: Bypass (لا تخزّن API calls)
   peakvault.com/*      → Edge Cache TTL: 1 month (للـ static assets)

5. للطوارئ: Security Level → Under Attack Mode
```

---

## الخطوة 7 — اختبار ما قبل الإطلاق

```bash
# شغّل اختبارات الـ Backend
cd backend/functions
python tests/test_full_suite.py
# يجب: 126/126 passed, 0 failed

# فحص Security Headers (من المتصفح أو CLI):
curl -I https://peakvault.com | grep -i "x-frame\|strict-transport\|content-security"

# Lighthouse Audit (من Chrome DevTools → Lighthouse):
# هدف: Performance >90, Accessibility >90, Best Practices >90
```

---

## الخطوة 8 — إضافة المنتج الأول (LexForge AI)

في `web/store.html`، أضف في مصفوفة `PRODUCTS`:

```javascript
const PRODUCTS = [
  {
    id: 'lexforge-ai-v1',
    name: {
      ar: 'LexForge AI — مولّد العقود',
      en: 'LexForge AI — Contract Generator',
      fr: 'LexForge AI — Générateur de contrats',
    },
    description: {
      ar: 'يولّد عقوداً قانونية احترافية بالعربية والإنجليزية في 60 ثانية',
      en: 'Generates professional legal contracts in Arabic and English in 60 seconds',
    },
    category: 'legal',
    type: 'digital-tool',
    price: 49,
    currency: 'USD',
    status: 'available',
    deliveryMethod: 'access-link',
    icon: '⚖️',
    featured: true,
    tags: ['legal', 'ai', 'contracts', 'arabic', 'pdf'],
  },
];
```

---

## قائمة التحقق النهائية قبل الإعلان

```
□ .env موجود وكل المتغيرات ممتلئة
□ firebase deploy --only hosting نجح
□ firebase deploy --only firestore:rules نجح
□ python tests/test_full_suite.py → 126/126 passed
□ https://peakvault.com تفتح بشكل صحيح
□ اللغة تتغير (AR/EN)
□ الرفوف تعمل
□ زر واتساب يفتح المحادثة
□ Cloudflare مفعّل
□ SSL → 🔒 في المتصفح
□ Lighthouse Performance > 85
```

---

## مواجهة المشاكل الشائعة

```
مشكلة: "permission-denied" في Firestore
الحل:  firebase deploy --only firestore:rules

مشكلة: الموقع لا يظهر على الدومين المخصص
الحل:  انتظر 24-48 ساعة للـ DNS propagation

مشكلة: الخطوط بطيئة
الحل:  فعّل Cloudflare caching أو self-host الخطوط

مشكلة: TypeError في JavaScript
الحل:  افتح Console في المتصفح → اقرأ الخطأ بالضبط
```
