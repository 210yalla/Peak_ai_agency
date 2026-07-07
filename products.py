from dataclasses import dataclass
from typing import List

@dataclass
class Product:
    id: str
    name: str
    category: str
    tagline: str
    description: str
    price_usd: float
    business_types: List[str]
    delivery_note: str
    is_exclusive: bool = False

PRODUCTS = [
    Product("replybot","ReplyBot","automation","بوت ردود ذكي 24/7","بوت ردود ذكي يعمل على واتساب وتلجرام",149,["store","services","other"],"سيتواصل معك الفريق خلال 24 ساعة"),
    Product("lexforge","LexForge","legal","تحليل عقود بالذكاء الاصطناعي","يستخرج البنود الخطرة من عقودك في ثوانٍ",199,["services","other"],"رابط الأداة خلال ساعة"),
    Product("datapulse","DataPulse","analytics","تقارير ذكية تلقائية","تقارير بصرية ذكية بالعربية والإنجليزية",249,["store","services","social","other"],"جلسة إعداد خلال 48 ساعة"),
    Product("contentai","ContentAI","content","منشورات بأسلوب علامتك","ينتج منشورات وسكريبتات بأسلوبك",99,["store","social","other"],"جاهز خلال 48 ساعة"),
    Product("storebot","StoreBot","automation","متجر داخل تلجرام","كتالوج وسلة ودفع داخل المحادثة",179,["store"],"المتجر جاهز خلال 5 أيام"),
    Product("bookwise","BookWise","automation","جدولة تلقائية للمواعيد","حجز وتذكير وإعادة جدولة تلقائية",129,["services","other"],"رابط لوحة التحكم خلال ساعتين"),
    Product("invoiceai","InvoiceAI","financial","فواتير إلكترونية ذكية","متوافق مع ZATCA السعودية وFTA الإماراتية",89,["services","store","other"],"جاهز فوراً"),
    Product("commentai","CommentAI","content","ردود تعليقات تلقائية","يرد على تعليقات انستغرام وتيك توك وفيسبوك",119,["social","store","other"],"الربط خلال 24 ساعة"),
    Product("pdf2data","PDF2Data","automation","تحويل PDF إلى Excel","دقة 98% مع دعم عربي كامل",149,["services","social","other"],"جاهز خلال ساعة"),
    Product("trackbot","TrackBot","automation","تتبع الطلبات تلقائياً","تنبيهات في كل مرحلة من مراحل الطلب",169,["store"],"الربط خلال 48 ساعة"),
    Product("gulflaw","محامي AI الخليجي","legal","قانون الخليج بالكامل","يفهم قوانين السعودية والإمارات والكويت وقطر والبحرين وعُمان",299,["services","other"],"وصول فوري مع جلسة تعريفية",True),
    Product("waccrm","WhatsApp CRM","automation","CRM بواتساب فقط","نظام CRM كامل بدون تطبيق جديد",349,["store","services","other"],"إعداد خلال 7 أيام",True),
    Product("meetingmind","MeetingMind","automation","مهام من اجتماعاتك","يستخرج المهام من Zoom ويوزعها تلقائياً",199,["services","other"],"الإعداد خلال 24 ساعة",True),
    Product("planforge","PlanForge","financial","خطط عمل للبنوك","جاهزة للبنوك والصناديق الخليجية",249,["services","other"],"الخطة جاهزة خلال 5 أيام",True),
    Product("trainbot","TrainBot","hr","تدريب موظفين ذكي","اختبارات تلقائية ومتابعة تقدم",399,["services","other"],"البرنامج جاهز خلال 10 أيام",True),
]

BUSINESS_TYPE_MAP = {
    "store":    ["storebot","replybot","trackbot"],
    "services": ["bookwise","invoiceai","lexforge"],
    "social":   ["contentai","commentai","pdf2data"],
    "other":    ["datapulse","waccrm","meetingmind"],
}

BUSINESS_TYPE_LABELS = {
    "store":    "متجر إلكتروني",
    "services": "مكتب / خدمات",
    "social":   "محتوى / سوشيال",
    "other":    "أخرى",
}

def get_product(product_id):
    return next((p for p in PRODUCTS if p.id == product_id), None)

def get_recommended_products(business_type):
    ids = BUSINESS_TYPE_MAP.get(business_type, [])
    return [p for p in PRODUCTS if p.id in ids]
