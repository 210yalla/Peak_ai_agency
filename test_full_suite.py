"""
═══════════════════════════════════════════════════════════════════
PEAK AI Agency © 2025 | peakvault.com | All rights reserved
tests/test_full_suite.py — اختبارات شاملة لكل بنوك الخوارزميات

التشغيل:
    cd backend/functions
    python -m pytest tests/ -v

أو بدون pytest (fallback مدمج):
    python tests/test_full_suite.py

فلسفة الاختبار هنا:
  لكل دالة: حالة سعيدة (happy path) + حالات حدّية (edge cases)
  + حالات فشل متعمدة (adversarial inputs). الهدف ليس "تغطية 100%
  سطرياً" بل "تغطية 100% للسلوك المتوقع تحت الضغط والخبث".
═══════════════════════════════════════════════════════════════════
"""

import sys
import os
import time
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib import algorithms, probability, balancing, color_engine, payment_router


# ═══════════════════════════════════════════════════════════════
# Minimal test framework (works without pytest installed)
# ═══════════════════════════════════════════════════════════════

_PASSED = 0
_FAILED = 0
_FAILURES: list[str] = []


def check(condition: bool, description: str) -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
    else:
        _FAILED += 1
        _FAILURES.append(description)
        print(f"  ❌ FAILED: {description}")


def expect_raises(exception_type, fn, description: str) -> None:
    try:
        fn()
        check(False, f"{description} (expected {exception_type.__name__}, no exception raised)")
    except exception_type:
        check(True, description)
    except Exception as e:
        check(False, f"{description} (expected {exception_type.__name__}, got {type(e).__name__})")


def section(name: str) -> None:
    print(f"\n── {name} ──")


# ═══════════════════════════════════════════════════════════════
# § ALGORITHMS BANK TESTS
# ═══════════════════════════════════════════════════════════════

def test_algorithms():
    section("algorithms.py")

    # --- smart_sort ---
    check(algorithms.smart_sort([]) == [], "sort: empty list")
    check(algorithms.smart_sort([5]) == [5], "sort: single element")
    check(algorithms.smart_sort([3, 1, 2]) == [1, 2, 3], "sort: basic ascending")
    check(algorithms.smart_sort([3, 1, 2], reverse=True) == [3, 2, 1], "sort: reverse")
    check(
        algorithms.smart_sort([{"v": 3}, {"v": 1}], key=lambda x: x["v"]) == [{"v": 1}, {"v": 3}],
        "sort: with key function"
    )
    expect_raises(TypeError, lambda: algorithms.smart_sort(42), "sort: non-iterable raises TypeError")

    # --- binary_search ---
    check(algorithms.binary_search([1, 2, 3, 4, 5], 3) == 2, "binary_search: found middle")
    check(algorithms.binary_search([1, 2, 3], 1) == 0, "binary_search: found first")
    check(algorithms.binary_search([1, 2, 3], 3) == 2, "binary_search: found last")
    check(algorithms.binary_search([1, 2, 3], 99) is None, "binary_search: not found")
    check(algorithms.binary_search([], 1) is None, "binary_search: empty list")

    # --- dedupe_preserving_order ---
    check(algorithms.dedupe_preserving_order([1, 2, 1, 3, 2, 1]) == [1, 2, 3], "dedupe: preserves first occurrence order")
    check(algorithms.dedupe_preserving_order([]) == [], "dedupe: empty list")
    check(algorithms.dedupe_preserving_order([1, 1, 1]) == [1], "dedupe: all duplicates")

    # --- secure_token ---
    tok1 = algorithms.secure_token()
    tok2 = algorithms.secure_token()
    check(len(tok1) == 64, "secure_token: default length 64 hex chars (32 bytes)")
    check(tok1 != tok2, "secure_token: two calls produce different tokens")
    expect_raises(ValueError, lambda: algorithms.secure_token(8), "secure_token: rejects insecure short length")

    # --- constant_time_compare ---
    check(algorithms.constant_time_compare("abc", "abc") is True, "constant_time_compare: equal strings")
    check(algorithms.constant_time_compare("abc", "abd") is False, "constant_time_compare: different strings")
    check(algorithms.constant_time_compare("", "") is True, "constant_time_compare: empty strings")

    # --- sign_payload / verify_payload ---
    secret = "test_secret_key_123"
    sig = algorithms.sign_payload("order_data_xyz", secret)
    check(algorithms.verify_payload("order_data_xyz", sig, secret) is True, "sign/verify: valid signature passes")
    check(algorithms.verify_payload("order_data_xyz", sig, "wrong_secret") is False, "sign/verify: wrong secret fails")
    check(algorithms.verify_payload("tampered_data", sig, secret) is False, "sign/verify: tampered payload fails")

    # --- TokenBucket (rate limiting) ---
    bucket = algorithms.TokenBucket(capacity=3, refill_rate=100.0)  # fast refill for test
    check(bucket.consume() is True, "TokenBucket: first consume succeeds")
    check(bucket.consume() is True, "TokenBucket: second consume succeeds")
    check(bucket.consume() is True, "TokenBucket: third consume succeeds")
    check(bucket.consume() is False, "TokenBucket: fourth consume fails (exhausted)")
    time.sleep(0.05)  # allow refill
    check(bucket.consume() is True, "TokenBucket: refills over time")

    # --- generate_idempotency_key ---
    k1 = algorithms.generate_idempotency_key("user_a", "product_x")
    k2 = algorithms.generate_idempotency_key("user_a", "product_x")
    k3 = algorithms.generate_idempotency_key("user_b", "product_x")
    check(k1 == k2, "idempotency_key: same inputs same window = same key")
    check(k1 != k3, "idempotency_key: different user = different key")

    # --- validate_amount (adversarial inputs) ---
    check(algorithms.validate_amount(49.99) == 49.99, "validate_amount: normal value passes")
    check(algorithms.validate_amount("49.99") == 49.99, "validate_amount: string number coerced")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(None), "validate_amount: None rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(-5), "validate_amount: negative rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(0), "validate_amount: zero rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(float("nan")), "validate_amount: NaN rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(float("inf")), "validate_amount: Infinity rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount(999_999_999), "validate_amount: absurdly large rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_amount("not_a_number"), "validate_amount: garbage string rejected")

    # --- validate_order_id (path traversal / injection attempts) ---
    check(algorithms.validate_order_id("PV-1234-ABCD") == "PV-1234-ABCD", "validate_order_id: valid format passes")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_order_id("../../etc/passwd"), "validate_order_id: path traversal rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_order_id("<script>alert(1)</script>"), "validate_order_id: XSS payload rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_order_id("'; DROP TABLE orders;--"), "validate_order_id: SQL injection payload rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_order_id(""), "validate_order_id: empty string rejected")
    expect_raises(algorithms.ValidationError, lambda: algorithms.validate_order_id(12345), "validate_order_id: non-string rejected")


# ═══════════════════════════════════════════════════════════════
# § PROBABILITY BANK TESTS
# ═══════════════════════════════════════════════════════════════

def test_probability():
    section("probability.py")

    # --- assess_payment_risk ---
    low = probability.assess_payment_risk(amount=50)
    check(low.level == probability.RiskLevel.LOW, "risk: normal small amount = LOW")
    check(low.requires_human_review is False, "risk: LOW does not require review")

    critical = probability.assess_payment_risk(
        amount=10_000, account_age_hours=0.05,
        requests_in_last_hour=20, currency_mismatch=True, is_first_time_buyer=True
    )
    check(critical.requires_human_review is True, "risk: stacked red flags require human review")
    check(len(critical.signals) >= 4, "risk: multiple signals detected and recorded")

    # Edge: zero amount handled gracefully (not negative, just edge)
    zero_risk = probability.assess_payment_risk(amount=0.01)
    check(isinstance(zero_risk.score, float), "risk: tiny amount doesn't crash")

    # --- confidence_score ---
    high_conf = probability.confidence_score(
        pattern_match_strength=0.95, response_length=150, has_specific_numbers=False
    )
    check(0.8 <= high_conf <= 1.0, "confidence: clear pattern + no numbers = high confidence")

    low_conf = probability.confidence_score(
        pattern_match_strength=0.3, response_length=5, has_specific_numbers=True, ambiguous_keywords_count=3
    )
    check(low_conf < 0.3, "confidence: weak pattern + ambiguity = low confidence")

    check(0.0 <= high_conf <= 1.0, "confidence: always bounded [0,1] upper")
    check(0.0 <= low_conf <= 1.0, "confidence: always bounded [0,1] lower")

    # --- detect_outliers_zscore ---
    # بيانات أكثر تجعل Z-score القيمة الشاذة أوضح (عينة أكبر = انحراف معياري أصغر نسبياً)
    normal = [10.0, 11.0, 12.0, 10.0, 11.0, 13.0, 9.0, 500.0, 11.0, 10.0, 12.0, 13.0]
    outliers = probability.detect_outliers_zscore(normal)
    check(7 in outliers, "outliers: extreme value detected")
    check(probability.detect_outliers_zscore([5, 5, 5]) == [], "outliers: identical values = no outliers (zero stdev)")
    check(probability.detect_outliers_zscore([1, 2]) == [], "outliers: too few points returns empty")

    # --- exponential_moving_average ---
    ema = probability.exponential_moving_average([10, 20, 30])
    check(len(ema) == 3, "ema: same length as input")
    check(ema[0] == 10, "ema: first value unchanged")
    check(probability.exponential_moving_average([]) == [], "ema: empty input handled")

    # --- predict_next_value ---
    pred = probability.predict_next_value([10, 20, 30, 40])
    check(pred is not None and pred > 0, "predict: returns a sensible forecast")
    check(probability.predict_next_value([]) is None, "predict: empty input returns None")

    # --- is_statistically_significant ---
    sig_result = probability.is_statistically_significant(50, 1000, 120, 1000)
    check(sig_result["significant"] is True, "ab_test: clear difference is significant")
    check(sig_result["winner"] == "b", "ab_test: correctly identifies winner")

    no_sig = probability.is_statistically_significant(100, 1000, 102, 1000)
    check(no_sig["significant"] is False, "ab_test: tiny difference not significant")

    zero_visitors = probability.is_statistically_significant(0, 0, 0, 0)
    check(zero_visitors["winner"] == "inconclusive", "ab_test: zero visitors handled gracefully")


# ═══════════════════════════════════════════════════════════════
# § BALANCING BANK TESTS
# ═══════════════════════════════════════════════════════════════

def test_balancing():
    section("balancing.py")

    # --- DistributedBruteForceGuard ---
    guard = balancing.DistributedBruteForceGuard(max_attempts_before_lock=3)
    allowed, retry = guard.check("ip_1")
    check(allowed is True, "brute_force: unknown identity allowed initially")

    for _ in range(3):
        guard.record_failure("ip_1")
    allowed, retry = guard.check("ip_1")
    check(allowed is False, "brute_force: locked after threshold")
    check(retry is not None and retry > 0, "brute_force: returns retry-after time")

    guard.record_success("ip_1")
    allowed, _ = guard.check("ip_1")
    check(allowed is True, "brute_force: success resets lockout")

    # Escalation: repeated lockouts should escalate
    guard2 = balancing.DistributedBruteForceGuard(max_attempts_before_lock=2)
    for _ in range(2):
        guard2.record_failure("ip_2")
    tier1 = guard2.record_failure("ip_2")  # 3rd failure after already locked conceptually
    check(isinstance(tier1, balancing.LockoutTier), "brute_force: escalation returns a tier")

    # --- Distributed attack pattern detection ---
    guard3 = balancing.DistributedBruteForceGuard(distributed_pattern_threshold=10)
    for i in range(10):
        guard3.record_failure(f"fake_identity_{i}")  # 10 DIFFERENT identities, 1 fail each
    check(guard3.check_distributed_pattern() is True, "brute_force: detects distributed attack across many identities")

    guard4 = balancing.DistributedBruteForceGuard(distributed_pattern_threshold=100)
    guard4.record_failure("single_user")
    check(guard4.check_distributed_pattern() is False, "brute_force: single normal failure is not a distributed attack")

    # --- CircuitBreaker ---
    cb = balancing.CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.1)
    check(cb.allow_request() is True, "circuit_breaker: starts closed, allows requests")
    cb.record_failure()
    check(cb.allow_request() is True, "circuit_breaker: still closed after 1 failure (threshold=2)")
    cb.record_failure()
    check(cb.state == balancing.CircuitState.OPEN, "circuit_breaker: opens after threshold failures")
    check(cb.allow_request() is False, "circuit_breaker: rejects requests while open")

    time.sleep(0.15)
    check(cb.state == balancing.CircuitState.HALF_OPEN, "circuit_breaker: transitions to half-open after timeout")

    cb.record_success()
    check(cb.state == balancing.CircuitState.CLOSED, "circuit_breaker: success in half-open closes circuit fully")

    # --- select_least_loaded_node ---
    nodes = [
        balancing.WorkerNode("a", capacity=100, current_load=99),
        balancing.WorkerNode("b", capacity=1000, current_load=100),
        balancing.WorkerNode("c", capacity=50, current_load=50),  # full
        balancing.WorkerNode("d", capacity=100, current_load=10, health_score=0.3),  # unhealthy
    ]
    best = balancing.select_least_loaded_node(nodes)
    check(best.node_id == "b", "load_balance: picks node with best relative headroom, ignoring unhealthy")

    check(balancing.select_least_loaded_node([]) is None, "load_balance: empty node list returns None")

    all_full = [balancing.WorkerNode("x", capacity=10, current_load=10)]
    check(balancing.select_least_loaded_node(all_full) is None, "load_balance: all-full nodes returns None")

    # --- estimate_required_capacity ---
    est = balancing.estimate_required_capacity(100_000)
    check(est["expected_concurrent_users"] == 100_000, "capacity: echoes input correctly")
    check(est["estimated_peak_requests_per_second"] > 0, "capacity: produces positive RPS estimate")
    check(0 < est["recommended_cdn_cache_hit_ratio"] <= 1, "capacity: cache ratio is a valid percentage")


# ═══════════════════════════════════════════════════════════════
# § COLOR ENGINE BANK TESTS
# ═══════════════════════════════════════════════════════════════

def test_color_engine():
    section("color_engine.py")

    gold = "#c8a45a"

    # --- conversions round-trip ---
    rgb = color_engine.hex_to_rgb(gold)
    check(rgb == color_engine.RGB(200, 164, 90), "color: hex_to_rgb correct values")
    check(color_engine.rgb_to_hex(rgb) == gold, "color: rgb_to_hex round-trip")

    expect_raises(ValueError, lambda: color_engine.hex_to_rgb("not_a_color"), "color: invalid hex raises")
    expect_raises(ValueError, lambda: color_engine.hex_to_rgb("#fff"), "color: short hex (3-digit) rejected")

    # --- contrast & WCAG ---
    high_contrast = color_engine.contrast_ratio("#ffffff", "#000000")
    check(high_contrast == 21.0, "color: pure white/black = max contrast 21:1")

    low_contrast = color_engine.contrast_ratio("#222222", "#1a1a1a")
    check(low_contrast < 1.5, "color: near-identical colors = low contrast")

    check(color_engine.meets_wcag_aa("#ffffff", "#050508") is True, "color: white on near-black passes WCAG AA")
    check(color_engine.meets_wcag_aa("#333333", "#222222") is False, "color: dark on dark fails WCAG AA")

    # --- ensure_accessible_color ---
    fixed = color_engine.ensure_accessible_color("#3a3a3a", "#050508", min_ratio=4.5)
    check(color_engine.contrast_ratio(fixed, "#050508") >= 4.5, "color: accessibility enforcement guarantees minimum ratio")

    already_good = color_engine.ensure_accessible_color("#ffffff", "#000000", min_ratio=4.5)
    check(already_good == "#ffffff", "color: already-accessible color unchanged")

    # --- status palette ---
    palette = color_engine.generate_status_palette(42.0)
    check(len({palette.success, palette.danger, palette.warning, palette.info}) == 4, "color: status palette produces 4 distinct colors")

    # --- tint scale ---
    scale = color_engine.generate_tint_scale(gold, steps=5)
    check(len(scale) == 5, "color: tint scale has requested step count")
    check(len(set(scale)) == 5, "color: tint scale steps are all distinct")

    single = color_engine.generate_tint_scale(gold, steps=1)
    check(len(single) == 1, "color: tint scale handles steps=1 without crashing")

    # --- complementary / analogous ---
    comp = color_engine.complementary_color(gold)
    comp_hsl = color_engine.hex_to_hsl(comp)
    gold_hsl = color_engine.hex_to_hsl(gold)
    check(abs((comp_hsl.h - gold_hsl.h) % 360 - 180) < 1, "color: complementary is ~180° apart on hue wheel")

    left, right = color_engine.analogous_colors(gold)
    check(left != right, "color: analogous colors are distinct from each other")


# ═══════════════════════════════════════════════════════════════
# § PAYMENT ROUTER TESTS (most critical — real money logic)
# ═══════════════════════════════════════════════════════════════

def test_payment_router():
    section("payment_router.py (CRITICAL — financial logic)")

    secret = algorithms.secure_token(32)
    generator = payment_router.PaymentLinkGenerator(secret_key=secret)

    expect_raises(
        ValueError, lambda: payment_router.PaymentLinkGenerator(secret_key="too_short"),
        "payment_router: rejects weak secret key"
    )

    # --- basic link creation ---
    link = generator.create_link(
        amount_usd=49.99, currency="USDT-TRC20",
        wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
        customer_identity="customer_001", product_reference="lexforge-ai",
    )
    check(link.status == payment_router.PaymentLinkStatus.PENDING, "payment_link: starts as pending")
    check(len(link.link_id) == 48, "payment_link: link_id has expected length")
    check(generator.verify_link_integrity(link) is True, "payment_link: integrity check passes for untouched link")

    # --- tampering detection ---
    original_amount = link.amount_usd
    link.amount_usd = 999999.0  # simulate tampering
    check(generator.verify_link_integrity(link) is False, "payment_link: tampering with amount detected")
    link.amount_usd = original_amount  # restore

    # --- public dict never leaks signature ---
    public = link.to_public_dict()
    check("internal_signature" not in public, "payment_link: public dict never exposes internal signature")
    check("order_id" not in public or public.get("order_id") != link.order_id,
          "payment_link: public dict doesn't leak raw internal order_id")

    # --- idempotency: duplicate requests within window return same link ---
    link_dup = generator.create_link(
        amount_usd=49.99, currency="USDT-TRC20",
        wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
        customer_identity="customer_001", product_reference="lexforge-ai",
    )
    check(link_dup.link_id == link.link_id, "payment_link: idempotency prevents duplicate link creation")

    # --- different customer = different link, even same product/amount ---
    link_other_customer = generator.create_link(
        amount_usd=49.99, currency="USDT-TRC20",
        wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
        customer_identity="customer_002", product_reference="lexforge-ai",
    )
    check(link_other_customer.link_id != link.link_id, "payment_link: different customer gets different link")

    # --- confirm_payment: happy path ---
    success, msg = generator.confirm_payment(link.link_id, confirmed_amount=49.99)
    check(success is True, "payment_confirm: exact amount match succeeds")
    check(link.status == payment_router.PaymentLinkStatus.CONFIRMED, "payment_confirm: status updates to confirmed")

    # --- confirm_payment: double confirmation rejected (replay protection) ---
    success2, msg2 = generator.confirm_payment(link.link_id, confirmed_amount=49.99)
    check(success2 is False, "payment_confirm: double-confirmation rejected (prevents double delivery)")

    # --- confirm_payment: amount mismatch rejected ---
    link2 = generator.create_link(
        amount_usd=100.0, currency="BTC", wallet_address="bc1qtest123",
        customer_identity="customer_003", product_reference="other-product",
    )
    success3, msg3 = generator.confirm_payment(link2.link_id, confirmed_amount=0.50)
    check(success3 is False, "payment_confirm: wildly wrong amount rejected")

    # --- confirm_payment: amount within tolerance (network fee variance) accepted ---
    link3 = generator.create_link(
        amount_usd=100.0, currency="BTC", wallet_address="bc1qtest456",
        customer_identity="customer_004", product_reference="product-y",
    )
    success4, _ = generator.confirm_payment(link3.link_id, confirmed_amount=100.5)  # +0.5% — within tolerance
    check(success4 is True, "payment_confirm: small positive variance within tolerance accepted")

    # --- confirm_payment: nonexistent link ---
    success5, msg5 = generator.confirm_payment("nonexistent_link_id_xyz", confirmed_amount=50.0)
    check(success5 is False, "payment_confirm: nonexistent link rejected safely")

    # --- expiry ---
    short_link = generator.create_link(
        amount_usd=10.0, currency="ETH", wallet_address="0xtest",
        customer_identity="customer_005", product_reference="quick-product",
        ttl_seconds=0,  # immediately expired
    )
    time.sleep(0.01)
    check(short_link.is_expired() is True, "payment_link: zero-TTL link is immediately expired")
    success6, msg6 = generator.confirm_payment(short_link.link_id, confirmed_amount=10.0)
    check(success6 is False, "payment_confirm: expired link rejected even with correct amount")

    # create a FRESH expired link that hasn't been touched (status still PENDING)
    # confirm_payment above already set short_link to EXPIRED, so we need a new one
    stale_link = generator.create_link(
        amount_usd=5.0, currency="ETH", wallet_address="0xstale",
        customer_identity="customer_006_stale", product_reference="stale-product",
        ttl_seconds=0,
    )
    time.sleep(0.01)
    # Do NOT call confirm_payment on it — let expire_stale_links find it
    expired_count = generator.expire_stale_links()
    check(expired_count >= 1, "payment_link: expire_stale_links cleans up expired pending links")

    # --- adversarial: negative/zero amount rejected at creation ---
    expect_raises(
        algorithms.ValidationError,
        lambda: generator.create_link(
            amount_usd=-50, currency="BTC", wallet_address="bc1qtest",
            customer_identity="attacker", product_reference="x",
        ),
        "payment_link: negative amount rejected at creation (defense in depth)"
    )


# ═══════════════════════════════════════════════════════════════
# § INTEGRATION TEST — full realistic flow
# ═══════════════════════════════════════════════════════════════

def test_integration_full_flow():
    section("INTEGRATION: full realistic payment flow")

    secret = algorithms.secure_token(32)
    generator = payment_router.PaymentLinkGenerator(secret_key=secret)
    guard = balancing.DistributedBruteForceGuard(max_attempts_before_lock=5)
    cb = balancing.CircuitBreaker(failure_threshold=3)

    # 1. Customer is rate-limit checked before allowing payment init
    allowed, _ = guard.check("customer_session_999")
    check(allowed is True, "integration: new customer passes rate limit check")

    # 2. Risk assessment before showing payment link
    risk = probability.assess_payment_risk(amount=49.99, is_first_time_buyer=True)
    check(risk.level in (probability.RiskLevel.LOW, probability.RiskLevel.MEDIUM),
          "integration: normal small purchase has acceptable risk")

    # 3. Payment link created only if risk acceptable
    if not risk.requires_human_review:
        link = generator.create_link(
            amount_usd=49.99, currency="USDT-TRC20",
            wallet_address="TMwPuew1ULFpUN8s9U3R4JvXUYfH6TTc3p",
            customer_identity="customer_session_999",
            product_reference="lexforge-ai-001",
        )
        check(link is not None, "integration: link created for low-risk transaction")

        # 4. External blockchain check would happen here via Circuit Breaker
        check(cb.allow_request() is True, "integration: circuit breaker allows blockchain API call")

        # 5. Simulate successful blockchain confirmation
        success, _ = generator.confirm_payment(link.link_id, confirmed_amount=49.99)
        check(success is True, "integration: full flow completes with payment confirmed")
        cb.record_success()

    # 6. Simulate a brute-force attempt on a different identity
    for _ in range(6):
        guard.record_failure("malicious_actor_ip")
    blocked, retry = guard.check("malicious_actor_ip")
    check(blocked is False, "integration: repeated failures correctly block malicious actor")


# ═══════════════════════════════════════════════════════════════
# RUN ALL
# ═══════════════════════════════════════════════════════════════

def run_all():
    print("═" * 70)
    print("PEAK AI Agency — Full Backend Test Suite")
    print("═" * 70)

    test_algorithms()
    test_probability()
    test_balancing()
    test_color_engine()
    test_payment_router()
    test_integration_full_flow()

    print("\n" + "═" * 70)
    total = _PASSED + _FAILED
    print(f"RESULTS: {_PASSED}/{total} passed, {_FAILED} failed")
    if _FAILED > 0:
        print("\nFAILED TESTS:")
        for f in _FAILURES:
            print(f"  • {f}")
        print("═" * 70)
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")
        print("═" * 70)


if __name__ == "__main__":
    run_all()
