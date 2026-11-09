"""Unit tests for the customer delivery success rate and risk engine."""

from src.processing.orders.customer_risk import (
    CustomerRiskTier,
    clean_phone_11_digits,
    score_customer_delivery_risk,
)


def test_clean_phone_11_digits():
    assert clean_phone_11_digits("+8801712345678") == "01712345678"
    assert clean_phone_11_digits("8801812345678") == "01812345678"
    assert clean_phone_11_digits("01912-345678") == "01912345678"
    assert clean_phone_11_digits("1712345678") == "01712345678"


def test_customer_risk_tiers():
    # Excellent tier (≥ 90%)
    vip = score_customer_delivery_risk(
        "01711111111", delivered_count=19, returned_count=1
    )
    assert vip.tier == CustomerRiskTier.EXCELLENT
    assert vip.success_rate == 95
    assert vip.risk_level == "LOW"

    # Good tier (80 - 89%)
    good = score_customer_delivery_risk(
        "01722222222", delivered_count=8, returned_count=2
    )
    assert good.tier == CustomerRiskTier.GOOD
    assert good.success_rate == 80
    assert good.risk_level == "LOW"

    # Moderate tier (60 - 79%)
    mod = score_customer_delivery_risk(
        "01733333333", delivered_count=7, returned_count=3
    )
    assert mod.tier == CustomerRiskTier.MODERATE
    assert mod.success_rate == 70
    assert mod.risk_level == "MEDIUM"

    # Risky tier (< 60%)
    risky = score_customer_delivery_risk(
        "01744444444", delivered_count=4, returned_count=6
    )
    assert risky.tier == CustomerRiskTier.RISKY
    assert risky.success_rate == 40
    assert risky.risk_level == "HIGH"

    # New customer
    new_cust = score_customer_delivery_risk(
        "01755555555", delivered_count=0, returned_count=0
    )
    assert new_cust.tier == CustomerRiskTier.NEW
    assert new_cust.success_rate == 100
    assert new_cust.risk_level == "LOW"
