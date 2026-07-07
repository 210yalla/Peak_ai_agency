import os
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("PEAK-CONFIG")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")
PAYMENT_BASE_URL = os.getenv("PAYMENT_BASE_URL", "https://peakvault.com/payment.html")
MIN_USDT = float(os.getenv("MIN_USDT", "1.0"))
MONITOR_POLL_INTERVAL = int(os.getenv("MONITOR_POLL_INTERVAL", "60"))
FOLLOWUP_CHECK_INTERVAL_MIN = int(os.getenv("FOLLOWUP_CHECK_INTERVAL_MIN", "30"))
FOLLOWUP_DAYS = int(os.getenv("FOLLOWUP_DAYS", "7"))

def validate():
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN غير موجود")
    else:
        log.info("الإعدادات مكتملة")
