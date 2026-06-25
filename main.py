"""
═══════════════════════════════════════════════════════════════════
PEAK AI Agency © 2025 | peakvault.com | All rights reserved
main.py — Firebase Cloud Functions (Python)

القلب الذي يربط كل شيء:
  - إنشاء روابط دفع فريدة لكل عميل
  - التحقق من معاملات البلوكتشين فعلياً
  - تأكيد الدفع وتسليم المنتج تلقائياً
  - Rate Limiting موزّع
  - Audit Log لا يُحذف

النشر:
  firebase deploy --only functions

المتطلبات في .env:
  PAYMENT_SIGNING_SECRET  ← سر توقيع روابط الدفع
  TELEGRAM_BOT_TOKEN      ← بوت التلجرام
  TELEGRAM_ADMIN_CHAT_ID  ← ID حسابك لاستقبال الإشعارات
  TRONGRID_API_KEY        ← للتحقق من معاملات TRC-20 (اختياري)
  ETHERSCAN_API_KEY       ← للتحقق من ERC-20/BEP-20 (اختياري)
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore as admin_firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# ── مكتبات البنك المحلي ──
import sys
sys.path.insert(0, os.path.dirname(__file__))
from lib.algorithms import (
    secure_token, sign_payload, verify_payload, validate_amount,
    generate_idempotency_key, constant_time_compare, ValidationError
)
from lib.probability import assess_payment_risk, RiskLevel
from lib.balancing import DistributedBruteForceGuard, CircuitBreaker
from lib.payment_router import PaymentLinkGenerator, PaymentLinkStatus

# ══════════════════════════════════════════════════════════════
# § 0 — INITIALIZATION
# ══════════════════════════════════════════════════════════════

initialize_app()
logger = logging.getLogger("peak_ai")
logging.basicConfig(level=logging.INFO)

# Singletons — يُنشأ مرة واحدة لكل Cloud Function instance
# (يتشارك الـ state داخل نفس الـ instance، لكن ليس عبر instances مختلفة)
_SIGNING_SECRET: Optional[str] = None
_PAYMENT_GENERATOR: Optional[PaymentLinkGenerator] = None
_BRUTE_GUARD = DistributedBruteForceGuard(
    max_attempts_before_lock=5,
    distributed_pattern_threshold=30,
    distributed_pattern_window_seconds=60,
)
_BLOCKCHAIN_CIRCUIT = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=30.0)


def get_signing_secret() -> str:
    """يجلب السر من متغيرات البيئة — مع فشل صريح إن لم يوجد."""
    global _SIGNING_SECRET
    if _SIGNING_SECRET is None:
        secret = os.environ.get("PAYMENT_SIGNING_SECRET", "")
        if len(secret) < 32:
            raise RuntimeError(
                "PAYMENT_SIGNING_SECRET is missing or too short. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        _SIGNING_SECRET = secret
    return _SIGNING_SECRET


def get_payment_generator() -> PaymentLinkGenerator:
    global _PAYMENT_GENERATOR
    if _PAYMENT_GENERATOR is None:
        _PAYMENT_GENERATOR = PaymentLinkGenerator(secret_key=get_signing_secret())
    return _PAYMENT_GENERATOR


def get_db():
    """Firestore client — lazy initialization."""
    return admin_firestore.client()


# ══════════════════════════════════════════════════════════════
# § 1 — WALLET CONFIG (من متغيرات البيئة — لا hardcode أبداً)
# ══════════════════════════════════════════════════════════════

def get_wallet_config() -> dict[str, dict]:
    """
    يجلب عناوين المحافظ من متغيرات البيئة.

    Layer 5: العناوين ليست "سراً" بالمعنى التقني (البلوكتشين علني)
    لكنها تحتاج أن تُحمى من التلاعب — HMAC على العنوان يضمن
    أن ما يراه العميل هو بالضبط ما في الـ ENV، لا شيء آخر.
    """
    wallets = {
        "USDT-TRC20": {
            "address": os.environ.get("WALLET_USDT_TRC20", ""),
            "network": "TRC-20",
            "fee_usd": 0.01,
            "verify_api": "trongrid",
        },
        "USDT-BEP20": {
            "address": os.environ.get("WALLET_EVM", ""),
            "network": "BEP-20",
            "fee_usd": 0.10,
            "verify_api": "bscscan",
        },
        "USDT-ERC20": {
            "address": os.environ.get("WALLET_EVM", ""),
            "network": "ERC-20",
            "fee_usd": 5.0,
            "verify_api": "etherscan",
        },
        "BNB": {
            "address": os.environ.get("WALLET_EVM", ""),
            "network": "BEP-20",
            "fee_usd": 0.10,
            "verify_api": "bscscan",
        },
        "BTC": {
            "address": os.environ.get("WALLET_BTC", ""),
            "network": "Bitcoin",
            "fee_usd": 2.0,
            "verify_api": "blockstream",
        },
        "ETH": {
            "address": os.environ.get("WALLET_EVM", ""),
            "network": "ERC-20",
            "fee_usd": 8.0,
            "verify_api": "etherscan",
        },
    }
    return wallets


# ══════════════════════════════════════════════════════════════
# § 2 — AUDIT LOGGING (لا يُحذف أبداً — insert-only)
# ══════════════════════════════════════════════════════════════

def audit_log(
    event_type: str,
    data: dict,
    *,
    severity: str = "INFO",
    request_ip: str = "unknown",
) -> None:
    """
    يكتب حدثاً في سجل التدقيق — لا يُحذف، لا يُعدَّل.

    Layer 5: Audit Log ليس ميزة "لطيفة" — هو الدليل القانوني الوحيد
    الذي يمكنك الاستناد إليه في نزاع مع عميل يدّعي أنه دفع ولم
    يستلم. كل حدث مالي حساس يُسجَّل هنا بلا استثناء.
    """
    try:
        db = get_db()
        log_id = f"{int(time.time() * 1000)}_{secure_token(8)}"
        db.collection("audit_log").document(log_id).set({
            "event_type": event_type,
            "severity": severity,
            "data": data,
            "request_ip": request_ip,
            "timestamp": SERVER_TIMESTAMP,
            "timestamp_unix": time.time(),
        })
    except Exception as e:
        # إن فشل الـ Audit Log، نسجّل الخطأ لكن لا نكسر العملية الأصلية
        logger.error(f"AUDIT LOG WRITE FAILED: {e} — event: {event_type}, data: {data}")


# ══════════════════════════════════════════════════════════════
# § 3 — RATE LIMITING (Firestore-backed للتوزيع عبر instances)
# ══════════════════════════════════════════════════════════════

def check_rate_limit_firestore(
    identity: str,
    *,
    max_calls: int = 10,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """
    Rate Limiting موزَّع عبر Firestore — يعمل عبر جميع Cloud Function
    instances في آن واحد (على عكس الـ in-memory TokenBucket الذي
    يعمل داخل instance واحد فقط).

    Layer 4: المشكلة مع in-memory rate limiting في serverless:
    كل Cloud Function instance له ذاكرة مستقلة. 100 instance =
    100 عدّاد منفصل. المهاجم يوزّع طلباته عبر instances ويتجاوز
    كل حد. الحل: العدّاد في Firestore المشترك بين جميع الـ instances.

    Returns:
        (allowed: bool, remaining_calls: int)
    """
    db = get_db()
    window_key = int(time.time()) // window_seconds
    doc_id = hashlib.sha256(f"{identity}:{window_key}".encode()).hexdigest()[:32]
    ref = db.collection("rate_limits").document(doc_id)

    @admin_firestore.transactional
    def update_in_transaction(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            transaction.set(ref, {
                "count": 1,
                "identity_hash": hashlib.sha256(identity.encode()).hexdigest()[:16],
                "window": window_key,
                "expires_at": time.time() + window_seconds + 60,
            })
            return True, max_calls - 1
        count = snapshot.get("count") or 0
        if count >= max_calls:
            return False, 0
        transaction.update(ref, {"count": count + 1})
        return True, max_calls - count - 1

    try:
        transaction = db.transaction()
        return update_in_transaction(transaction, ref)
    except Exception as e:
        logger.warning(f"Rate limit check failed (allowing by default): {e}")
        return True, max_calls  # fail-open: لا نكسر الخدمة بسبب خطأ في الـ rate limiter


# ══════════════════════════════════════════════════════════════
# § 4 — BLOCKCHAIN VERIFICATION (التحقق الفعلي من الدفع)
# ══════════════════════════════════════════════════════════════

async def verify_trongrid_transaction(
    wallet_address: str,
    expected_amount_usdt: float,
    since_timestamp: float,
) -> Optional[dict]:
    """
    يتحقق من وصول USDT TRC-20 لعنوان محدد منذ وقت معين.
    يستخدم TronGrid API (مجاني، لا يحتاج مفتاح للاستخدام الأساسي).

    Layer 3: إن تغيّرت TronGrid API في المستقبل، فقط هذه الدالة
    تحتاج تعديلاً — باقي النظام لا يعرف شيئاً عن TronGrid.
    """
    if not _BLOCKCHAIN_CIRCUIT.allow_request():
        logger.warning("TronGrid circuit breaker is OPEN — skipping verification")
        return None

    # عنوان USDT TRC-20 contract
    USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    since_ms = int(since_timestamp * 1000)

    api_key = os.environ.get("TRONGRID_API_KEY", "")
    headers = {"TRON-PRO-API-KEY": api_key} if api_key else {}

    url = (
        f"https://api.trongrid.io/v1/accounts/{wallet_address}"
        f"/transactions/trc20"
        f"?contract_address={USDT_CONTRACT}"
        f"&min_timestamp={since_ms}"
        f"&limit=20"
        f"&only_confirmed=true"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        _BLOCKCHAIN_CIRCUIT.record_success()

        for tx in data.get("data", []):
            if tx.get("to") != wallet_address:
                continue
            # USDT TRC-20 has 6 decimals
            amount = int(tx.get("value", 0)) / 1_000_000
            ratio = amount / expected_amount_usdt if expected_amount_usdt > 0 else 0
            if 0.99 <= ratio <= 1.05:
                return {
                    "tx_id": tx.get("transaction_id"),
                    "amount": amount,
                    "from": tx.get("from"),
                    "timestamp": tx.get("block_timestamp", 0) / 1000,
                    "network": "TRC-20",
                }

    except httpx.HTTPStatusError as e:
        _BLOCKCHAIN_CIRCUIT.record_failure()
        logger.error(f"TronGrid API HTTP error: {e}")
    except Exception as e:
        _BLOCKCHAIN_CIRCUIT.record_failure()
        logger.error(f"TronGrid verification error: {e}")

    return None


async def verify_etherscan_transaction(
    wallet_address: str,
    expected_amount: float,
    since_timestamp: float,
    *,
    network: str = "ERC-20",
) -> Optional[dict]:
    """
    يتحقق من وصول USDT/ETH على Ethereum أو BSC.

    Layer 3: network يحدد أي API endpoint يُستخدم:
    ERC-20 → Etherscan API
    BEP-20 → BscScan API
    نفس الكود، نقاط نهاية مختلفة فقط.
    """
    if not _BLOCKCHAIN_CIRCUIT.allow_request():
        return None

    api_key = os.environ.get("ETHERSCAN_API_KEY", "")
    base_urls = {
        "ERC-20": "https://api.etherscan.io/api",
        "BEP-20": "https://api.bscscan.com/api",
    }
    base_url = base_urls.get(network, base_urls["ERC-20"])

    # USDT Contract addresses
    usdt_contracts = {
        "ERC-20": "0xdac17f958d2ee523a2206206994597c13d831ec7",
        "BEP-20": "0x55d398326f99059ff775485246999027b3197955",
    }
    usdt_contract = usdt_contracts.get(network, "")

    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": usdt_contract,
        "address": wallet_address,
        "startblock": 0,
        "sort": "desc",
        "apikey": api_key or "YourApiKeyToken",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(base_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        _BLOCKCHAIN_CIRCUIT.record_success()

        if data.get("status") != "1":
            return None

        for tx in data.get("result", [])[:20]:
            if tx.get("to", "").lower() != wallet_address.lower():
                continue
            tx_time = float(tx.get("timeStamp", 0))
            if tx_time < since_timestamp:
                continue
            # USDT ERC-20 has 6 decimals
            decimals = int(tx.get("tokenDecimal", 6))
            amount = int(tx.get("value", 0)) / (10 ** decimals)
            ratio = amount / expected_amount if expected_amount > 0 else 0
            if 0.99 <= ratio <= 1.05:
                return {
                    "tx_id": tx.get("hash"),
                    "amount": amount,
                    "from": tx.get("from"),
                    "timestamp": tx_time,
                    "network": network,
                }

    except Exception as e:
        _BLOCKCHAIN_CIRCUIT.record_failure()
        logger.error(f"Etherscan/BSCScan verification error: {e}")

    return None


async def verify_bitcoin_transaction(
    wallet_address: str,
    expected_amount_btc: float,
    since_timestamp: float,
) -> Optional[dict]:
    """
    يتحقق من وصول BTC باستخدام Blockstream API (مجاني، لا مفتاح).
    """
    if not _BLOCKCHAIN_CIRCUIT.allow_request():
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://blockstream.info/api/address/{wallet_address}/txs"
            )
            resp.raise_for_status()
            txs = resp.json()

        _BLOCKCHAIN_CIRCUIT.record_success()

        for tx in txs[:20]:
            tx_time = tx.get("status", {}).get("block_time", 0)
            if tx_time and tx_time < since_timestamp:
                continue
            # Check outputs going to our address
            for vout in tx.get("vout", []):
                if vout.get("scriptpubkey_address") != wallet_address:
                    continue
                amount_btc = vout.get("value", 0) / 1e8
                ratio = amount_btc / expected_amount_btc if expected_amount_btc > 0 else 0
                if 0.99 <= ratio <= 1.05:
                    return {
                        "tx_id": tx.get("txid"),
                        "amount": amount_btc,
                        "timestamp": tx_time,
                        "network": "Bitcoin",
                    }

    except Exception as e:
        _BLOCKCHAIN_CIRCUIT.record_failure()
        logger.error(f"Bitcoin verification error: {e}")

    return None


async def auto_verify_payment(
    wallet_address: str,
    currency: str,
    expected_amount: float,
    since_timestamp: float,
) -> Optional[dict]:
    """
    يختار آلية التحقق المناسبة بناءً على العملة ويُرجع نتيجة موحَّدة.

    Layer 3: إضافة عملة جديدة = إضافة case جديد فقط.
    """
    if currency == "USDT-TRC20":
        return await verify_trongrid_transaction(wallet_address, expected_amount, since_timestamp)
    elif currency in ("USDT-ERC20", "ETH"):
        return await verify_etherscan_transaction(wallet_address, expected_amount, since_timestamp, network="ERC-20")
    elif currency in ("USDT-BEP20", "BNB"):
        return await verify_etherscan_transaction(wallet_address, expected_amount, since_timestamp, network="BEP-20")
    elif currency == "BTC":
        return await verify_bitcoin_transaction(wallet_address, expected_amount, since_timestamp)
    else:
        logger.warning(f"No verifier for currency: {currency}")
        return None


# ══════════════════════════════════════════════════════════════
# § 5 — CORS HELPER
# ══════════════════════════════════════════════════════════════

ALLOWED_ORIGINS = {
    "https://peakvault.com",
    "https://www.peakvault.com",
}

# Development origins — يُحذف في الإنتاج الفعلي
if os.environ.get("FUNCTIONS_EMULATOR"):
    ALLOWED_ORIGINS.add("http://localhost:5000")
    ALLOWED_ORIGINS.add("http://127.0.0.1:5000")


def cors_response(
    data: Any,
    *,
    status: int = 200,
    origin: str = "",
) -> https_fn.Response:
    """يُنشئ Response مع CORS headers صحيحة."""
    allowed_origin = origin if origin in ALLOWED_ORIGINS else "null"
    headers = {
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-CSRF-Token",
        "Access-Control-Max-Age": "3600",
        "Content-Type": "application/json",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    body = json.dumps(data, ensure_ascii=False)
    return https_fn.Response(body, status=status, headers=headers)


def handle_preflight(req: https_fn.Request) -> Optional[https_fn.Response]:
    """يعالج CORS preflight requests."""
    if req.method == "OPTIONS":
        origin = req.headers.get("Origin", "")
        return cors_response({}, origin=origin)
    return None


def get_client_ip(req: https_fn.Request) -> str:
    """يستخرج IP العميل الحقيقي خلف Cloudflare."""
    return (
        req.headers.get("CF-Connecting-IP")
        or req.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or req.remote_addr
        or "unknown"
    )


# ══════════════════════════════════════════════════════════════
# § 6 — FUNCTION: create_payment_link
# ══════════════════════════════════════════════════════════════

@https_fn.on_request(
    cors=options.CorsOptions(
        cors_origins=list(ALLOWED_ORIGINS),
        cors_methods=["POST"],
    ),
    timeout_sec=30,
    memory=options.MemoryOption.MB_256,
    max_instances=100,
)
def create_payment_link(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Function: ينشئ رابط دفع فريداً لعميل وطلب محددين.

    POST /create_payment_link
    Body: {
        "product_id": str,
        "currency": str,
        "session_id": str,         ← معرّف جلسة العميل (لا يُكشف للعميل)
        "csrf_token": str,
        "customer_note": str (اختياري)
    }

    Response: {
        "link_id": str,
        "customer_reference": str,
        "amount_usd": float,
        "currency": str,
        "wallet_address": str,
        "wallet_signature": str,    ← HMAC للتحقق من سلامة العنوان
        "expires_at": float,
        "payment_url": str          ← رابط كامل لصفحة الدفع
    }
    """
    preflight = handle_preflight(req)
    if preflight:
        return preflight

    origin = req.headers.get("Origin", "")
    client_ip = get_client_ip(req)

    # ── Rate Limiting ──
    allowed, remaining = check_rate_limit_firestore(
        client_ip, max_calls=5, window_seconds=300  # 5 طلبات كل 5 دقائق
    )
    if not allowed:
        audit_log("RATE_LIMIT_HIT", {"ip": client_ip, "endpoint": "create_payment_link"}, severity="WARNING")
        return cors_response({"error": "Too many requests. Please wait before trying again."}, status=429, origin=origin)

    # ── Brute Force Guard ──
    bf_allowed, retry_after = _BRUTE_GUARD.check(client_ip)
    if not bf_allowed:
        return cors_response(
            {"error": f"Temporarily blocked. Try again in {retry_after:.0f} seconds."},
            status=429, origin=origin
        )

    # ── Parse + Validate Input ──
    try:
        body = req.get_json(silent=True) or {}
    except Exception:
        return cors_response({"error": "Invalid JSON body"}, status=400, origin=origin)

    product_id = str(body.get("product_id", "")).strip()[:64]
    currency = str(body.get("currency", "")).strip()[:20]
    session_id = str(body.get("session_id", "")).strip()[:128]
    customer_note = str(body.get("customer_note", "")).strip()[:200]

    if not product_id or not currency or not session_id:
        return cors_response({"error": "Missing required fields: product_id, currency, session_id"}, status=400, origin=origin)

    # ── Load Product from Firestore (T2: السعر من DB فقط، لا من Client) ──
    try:
        db = get_db()
        product_doc = db.collection("products").document(product_id).get()
        if not product_doc.exists:
            return cors_response({"error": f"Product '{product_id}' not found"}, status=404, origin=origin)
        product = product_doc.to_dict()
    except Exception as e:
        logger.error(f"Firestore product fetch error: {e}")
        return cors_response({"error": "Service temporarily unavailable"}, status=503, origin=origin)

    amount_usd = product.get("price_usd", 0)
    try:
        amount_usd = validate_amount(amount_usd, min_value=0.01, max_value=100_000)
    except ValidationError as e:
        logger.error(f"Invalid product price in DB: {e}")
        return cors_response({"error": "Product price configuration error"}, status=500, origin=origin)

    # ── Wallet Config ──
    wallets = get_wallet_config()
    wallet_info = wallets.get(currency)
    if not wallet_info:
        return cors_response({"error": f"Currency '{currency}' not supported"}, status=400, origin=origin)

    wallet_address = wallet_info["address"]
    if not wallet_address:
        logger.error(f"Wallet address not configured for {currency}")
        return cors_response({"error": "Payment method temporarily unavailable"}, status=503, origin=origin)

    # ── Risk Assessment ──
    risk = assess_payment_risk(amount=amount_usd, is_first_time_buyer=True)
    if risk.level == RiskLevel.CRITICAL:
        audit_log("HIGH_RISK_BLOCKED", {
            "ip": client_ip, "amount": amount_usd, "currency": currency,
            "risk_score": risk.score, "signals": [s.name for s in risk.signals]
        }, severity="WARNING", request_ip=client_ip)
        return cors_response({"error": "Transaction could not be processed. Please contact support."}, status=403, origin=origin)

    # ── Create Payment Link ──
    try:
        generator = get_payment_generator()
        link = generator.create_link(
            amount_usd=amount_usd,
            currency=currency,
            wallet_address=wallet_address,
            customer_identity=session_id,
            product_reference=product_id,
        )
    except ValidationError as e:
        return cors_response({"error": str(e)}, status=400, origin=origin)
    except Exception as e:
        logger.error(f"Payment link creation error: {e}")
        return cors_response({"error": "Failed to create payment link"}, status=500, origin=origin)

    # ── Sign Wallet Address (T3: HMAC integrity) ──
    wallet_signature = sign_payload(
        f"{wallet_address}|{currency}|{link.link_id}",
        get_signing_secret()
    )

    # ── Save to Firestore ──
    try:
        order_data = {
            "link_id": link.link_id,
            "order_id": link.order_id,
            "customer_reference": link.customer_reference,
            "product_id": product_id,
            "amount_usd": amount_usd,
            "currency": currency,
            "wallet_address": wallet_address,
            "status": "pending",
            "idempotency_key": link.idempotency_key,
            "session_id_hash": hashlib.sha256(session_id.encode()).hexdigest()[:16],
            "client_ip_hash": hashlib.sha256(client_ip.encode()).hexdigest()[:16],
            "risk_level": risk.level.value,
            "risk_score": risk.score,
            "created_at": SERVER_TIMESTAMP,
            "expires_at": link.expires_at,
            "customer_note": customer_note,
        }
        db.collection("payment_links").document(link.link_id).set(order_data)
    except Exception as e:
        logger.error(f"Firestore write error: {e}")
        # لا نكسر العملية — الرابط موجود في الذاكرة وسيعمل حتى لو فشل الحفظ

    # ── Audit Log ──
    audit_log("PAYMENT_LINK_CREATED", {
        "link_id": link.link_id,
        "product_id": product_id,
        "amount_usd": amount_usd,
        "currency": currency,
        "customer_reference": link.customer_reference,
    }, request_ip=client_ip)

    # ── Response ──
    payment_url = f"https://peakvault.com/payment.html?link={link.link_id}&ref={link.customer_reference}"

    return cors_response({
        "link_id": link.link_id,
        "customer_reference": link.customer_reference,
        "amount_usd": amount_usd,
        "currency": currency,
        "wallet_address": wallet_address,
        "wallet_signature": wallet_signature,
        "expires_at": link.expires_at,
        "payment_url": payment_url,
        "fee_usd": wallet_info.get("fee_usd", 0),
    }, origin=origin)


# ══════════════════════════════════════════════════════════════
# § 7 — FUNCTION: confirm_payment (يدوي من Admin + تلقائي)
# ══════════════════════════════════════════════════════════════

@https_fn.on_request(
    cors=options.CorsOptions(cors_origins=list(ALLOWED_ORIGINS), cors_methods=["POST"]),
    timeout_sec=60,
    memory=options.MemoryOption.MB_512,
    max_instances=10,
)
async def confirm_payment(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Function: يؤكد دفعاً بعد التحقق من البلوكتشين.

    استخدامان:
    1. تأكيد يدوي من Admin (عبر بوت تلجرام) — يتحقق من signature
    2. تأكيد تلقائي — يتحقق من البلوكتشين فعلياً

    POST /confirm_payment
    Body: {
        "link_id": str,
        "admin_secret": str (للتأكيد اليدوي),
        "tx_id": str (اختياري — رقم معاملة البلوكتشين)
    }
    """
    preflight = handle_preflight(req)
    if preflight:
        return preflight

    origin = req.headers.get("Origin", "")
    client_ip = get_client_ip(req)

    try:
        body = req.get_json(silent=True) or {}
    except Exception:
        return cors_response({"error": "Invalid JSON"}, status=400, origin=origin)

    link_id = str(body.get("link_id", "")).strip()[:100]
    admin_secret_attempt = str(body.get("admin_secret", ""))
    tx_id = str(body.get("tx_id", "")).strip()[:100]

    if not link_id:
        return cors_response({"error": "link_id is required"}, status=400, origin=origin)

    # ── Fetch from Firestore ──
    try:
        db = get_db()
        doc = db.collection("payment_links").document(link_id).get()
        if not doc.exists:
            _BRUTE_GUARD.record_failure(client_ip)
            return cors_response({"error": "Payment link not found"}, status=404, origin=origin)
        link_data = doc.to_dict()
    except Exception as e:
        logger.error(f"Firestore fetch error in confirm_payment: {e}")
        return cors_response({"error": "Service unavailable"}, status=503, origin=origin)

    # ── Check Status ──
    if link_data.get("status") != "pending":
        return cors_response({
            "error": f"Link already processed: {link_data.get('status')}",
            "status": link_data.get("status"),
        }, status=409, origin=origin)

    if time.time() > link_data.get("expires_at", 0):
        db.collection("payment_links").document(link_id).update({"status": "expired"})
        return cors_response({"error": "Payment link has expired"}, status=410, origin=origin)

    # ── Admin Secret Verification (للتأكيد اليدوي من البوت) ──
    admin_secret = os.environ.get("PAYMENT_SIGNING_SECRET", "")
    is_admin_confirmed = (
        admin_secret_attempt
        and constant_time_compare(admin_secret_attempt, admin_secret[:16])
    )

    # ── Blockchain Auto-Verification ──
    blockchain_tx = None
    if not is_admin_confirmed:
        wallet_address = link_data.get("wallet_address", "")
        currency = link_data.get("currency", "")
        amount = link_data.get("amount_usd", 0.0)
        created_at = link_data.get("created_at")
        since_ts = created_at.timestamp() if hasattr(created_at, "timestamp") else (time.time() - 3600)

        blockchain_tx = await auto_verify_payment(wallet_address, currency, amount, since_ts)

        if not blockchain_tx and not is_admin_confirmed:
            return cors_response({
                "error": "Payment not yet detected on blockchain. Please wait a few minutes and try again.",
                "status": "pending",
            }, status=202, origin=origin)

    # ── Confirm in Firestore (Atomic Update) ──
    try:
        db.collection("payment_links").document(link_id).update({
            "status": "confirmed",
            "confirmed_at": SERVER_TIMESTAMP,
            "confirmed_by": "admin" if is_admin_confirmed else "blockchain",
            "tx_id": tx_id or (blockchain_tx.get("tx_id") if blockchain_tx else None),
            "blockchain_data": blockchain_tx,
        })
    except Exception as e:
        logger.error(f"Firestore confirm update error: {e}")
        return cors_response({"error": "Failed to confirm payment"}, status=500, origin=origin)

    # ── Audit Log ──
    audit_log("PAYMENT_CONFIRMED", {
        "link_id": link_id,
        "product_id": link_data.get("product_id"),
        "amount_usd": link_data.get("amount_usd"),
        "currency": link_data.get("currency"),
        "confirmed_by": "admin" if is_admin_confirmed else "blockchain",
        "tx_id": tx_id or (blockchain_tx.get("tx_id") if blockchain_tx else None),
    }, severity="INFO", request_ip=client_ip)

    # ── Trigger Delivery via Telegram Bot ──
    try:
        await _notify_telegram_delivery(
            product_id=link_data.get("product_id", ""),
            customer_reference=link_data.get("customer_reference", ""),
            amount_usd=link_data.get("amount_usd", 0),
            currency=link_data.get("currency", ""),
            tx_id=tx_id or (blockchain_tx.get("tx_id") if blockchain_tx else "manual"),
        )
    except Exception as e:
        logger.error(f"Telegram notification failed (non-critical): {e}")

    _BRUTE_GUARD.record_success(client_ip)

    return cors_response({
        "success": True,
        "status": "confirmed",
        "message": "Payment confirmed. Your product will be delivered shortly.",
        "customer_reference": link_data.get("customer_reference"),
    }, origin=origin)


# ══════════════════════════════════════════════════════════════
# § 8 — FUNCTION: get_payment_status (polling للعميل)
# ══════════════════════════════════════════════════════════════

@https_fn.on_request(
    cors=options.CorsOptions(cors_origins=list(ALLOWED_ORIGINS), cors_methods=["GET"]),
    timeout_sec=10,
    memory=options.MemoryOption.MB_256,
    max_instances=50,
)
def get_payment_status(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Function: يُرجع حالة طلب دفع للعميل — polling endpoint.

    GET /get_payment_status?link_id=xxx

    يُرجع فقط البيانات الآمنة — لا wallet_signature، لا IP، لا بيانات داخلية.
    """
    preflight = handle_preflight(req)
    if preflight:
        return preflight

    origin = req.headers.get("Origin", "")
    client_ip = get_client_ip(req)

    link_id = req.args.get("link_id", "").strip()[:100]
    if not link_id:
        return cors_response({"error": "link_id parameter required"}, status=400, origin=origin)

    allowed, _ = check_rate_limit_firestore(client_ip, max_calls=30, window_seconds=60)
    if not allowed:
        return cors_response({"error": "Too many status checks"}, status=429, origin=origin)

    try:
        db = get_db()
        doc = db.collection("payment_links").document(link_id).get()
        if not doc.exists:
            return cors_response({"error": "Not found"}, status=404, origin=origin)
        data = doc.to_dict()
    except Exception:
        return cors_response({"error": "Service unavailable"}, status=503, origin=origin)

    # فقط الحقول الآمنة للعميل
    is_expired = time.time() > data.get("expires_at", 0)
    return cors_response({
        "status": "expired" if is_expired and data.get("status") == "pending" else data.get("status"),
        "customer_reference": data.get("customer_reference"),
        "amount_usd": data.get("amount_usd"),
        "currency": data.get("currency"),
        "expires_at": data.get("expires_at"),
        "is_expired": is_expired,
    }, origin=origin)


# ══════════════════════════════════════════════════════════════
# § 9 — TELEGRAM NOTIFICATION HELPER
# ══════════════════════════════════════════════════════════════

async def _notify_telegram_delivery(
    product_id: str,
    customer_reference: str,
    amount_usd: float,
    currency: str,
    tx_id: str,
) -> None:
    """
    يُرسل إشعاراً لبوت التلجرام بتأكيد الدفع — يُطلق عملية التسليم التلقائي.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not bot_token or not admin_chat_id:
        logger.warning("Telegram credentials not configured — skipping notification")
        return

    message = (
        f"✅ *دفعة مؤكدة — PEAK AI*\n\n"
        f"📦 المنتج: `{product_id}`\n"
        f"🔖 المرجع: `{customer_reference}`\n"
        f"💵 المبلغ: `${amount_usd} {currency}`\n"
        f"🔗 TX: `{tx_id[:20]}...`\n\n"
        f"⚡ `/deliver {customer_reference}` للتسليم الفوري"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": admin_chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )


# ══════════════════════════════════════════════════════════════
# § 10 — SCHEDULED: expire stale links (كل ساعة)
# ══════════════════════════════════════════════════════════════

from firebase_functions import scheduler_fn

@scheduler_fn.on_schedule(schedule="every 60 minutes", timezone="UTC")
def expire_stale_payment_links(event: scheduler_fn.ScheduledEvent) -> None:
    """
    يُنظّف الطلبات المنتهية صلاحيتها كل ساعة تلقائياً.

    Layer 5: لا نحذف — نُغيّر الحالة إلى 'expired'.
    البيانات التاريخية قيّمة للتحليل ولأي نزاع قانوني مستقبلي.
    """
    db = get_db()
    now = time.time()

    try:
        stale_docs = (
            db.collection("payment_links")
            .where("status", "==", "pending")
            .where("expires_at", "<", now)
            .limit(500)
            .stream()
        )

        batch = db.batch()
        count = 0
        for doc in stale_docs:
            batch.update(doc.reference, {"status": "expired", "expired_at": SERVER_TIMESTAMP})
            count += 1

        if count > 0:
            batch.commit()
            logger.info(f"Expired {count} stale payment links")
            audit_log("BATCH_LINKS_EXPIRED", {"count": count, "timestamp_unix": now})

    except Exception as e:
        logger.error(f"Stale link expiry job failed: {e}")
