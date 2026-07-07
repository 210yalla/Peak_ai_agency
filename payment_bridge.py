import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
import config
import database as db
from products import get_product

log = logging.getLogger("PEAK-BRIDGE")
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
SEEN_FILE = Path("seen_tx_bridge.json")

def load_seen():
    try:
        if SEEN_FILE.exists():
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data.get("txids", []))
    except Exception:
        pass
    return set()

def save_seen(seen):
    try:
        recent = list(seen)[-2000:]
        SEEN_FILE.write_text(json.dumps({"txids": recent}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def fetch_usdt_transfers(wallet, limit=20):
    url = f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20"
    params = {"contract_address": USDT_CONTRACT, "only_to": "true", "limit": limit}
    headers = {"Accept": "application/json"}
    if config.TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        log.error("TronGrid error: %s", e)
    return []

def parse_transfer(tx):
    try:
        tx_id = tx.get("transaction_id", "")
        usdt = int(tx.get("value", 0)) / 1_000_000
        from_ = tx.get("from", "")
        if usdt < config.MIN_USDT:
            return None
        return {"txid": tx_id, "usdt": usdt, "from": from_}
    except Exception:
        return None

async def process_new_payment(bot, tx):
    amount = tx["usdt"]
    tx_id = tx["txid"]
    matched = db.get_pending_orders_for_amount(amount)
    if not matched:
        if config.ADMIN_CHAT_ID:
            try:
                await bot.send_message(chat_id=config.ADMIN_CHAT_ID,
                    text=f"دفعة غير مطابقة\nالمبلغ: {amount:.2f} USDT\nTX: {tx_id[:20]}...")
            except Exception:
                pass
        return
    order = matched[0]
    order_id = order["id"]
    customer_id = order["telegram_id"]
    product_id = order["product_id"]
    product_name = order["product_name"]
    amount_usd = order["amount_usd"]
    product = get_product(product_id)
    delivery_note = product.delivery_note if product else "سيتواصل معك الفريق قريباً."
    db.mark_order_paid(order_id, tx_id)
    from handlers.payment import send_payment_confirmation, send_admin_payment_alert
    await send_payment_confirmation(bot, customer_id, order_id, product_name, amount_usd, tx_id, delivery_note)
    await send_admin_payment_alert(bot, order_id, product_name, amount_usd, customer_id, tx_id)
    db.schedule_followup(order_id, customer_id, config.FOLLOWUP_DAYS)

async def run_payment_monitor(bot):
    seen = load_seen()
    log.info("مراقبة الدفعات بدأت")
    consecutive_errors = 0
    while True:
        try:
            transfers = fetch_usdt_transfers(config.WALLET_ADDRESS)
            for tx_raw in transfers:
                tx = parse_transfer(tx_raw)
                if not tx or tx["txid"] in seen:
                    continue
                seen.add(tx["txid"])
                save_seen(seen)
                await process_new_payment(bot, tx)
                await asyncio.sleep(1)
            consecutive_errors = 0
        except asyncio.CancelledError:
            break
        except Exception as e:
            consecutive_errors += 1
            log.error("خطأ: %s", e)
            if consecutive_errors >= 5:
                await asyncio.sleep(300)
                consecutive_errors = 0
        await asyncio.sleep(config.MONITOR_POLL_INTERVAL)
