"""BE-25: what an AI call or a WhatsApp message costs (no database)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from mesiri.domains.organizations import platform_settings
from mesiri.domains.usage import prices

# Thursday 15 Oct 2026.
_PEAK = dt.datetime(2026, 10, 15, 2, 30, tzinfo=dt.UTC)
_OFF_PEAK = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
_SATURDAY_PEAK_HOUR = dt.datetime(2026, 10, 17, 2, 30, tzinfo=dt.UTC)


def test_gemini_text_call() -> None:
    cost = prices.ai_cost(
        provider="gemini",
        model="gemini-2.5-flash",
        at=_PEAK,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert cost == prices.Cost(Decimal("2.80"), "USD")


def test_gemini_audio_and_cached_input_are_priced_separately() -> None:
    cost = prices.ai_cost(
        provider="gemini",
        model="gemini-2.5-flash",
        at=_PEAK,
        input_tokens=3_000_000,
        audio_input_tokens=1_000_000,
        cached_input_tokens=1_000_000,
        output_tokens=0,
    )
    # 1M plain at 0.30 + 1M audio at 1.00 + 1M cached at 0.03
    assert cost.amount == Decimal("1.33")


def test_deepseek_is_half_price_off_peak_and_at_weekends() -> None:
    def cost(at: dt.datetime) -> Decimal:
        return prices.ai_cost(
            provider="deepseek",
            model="deepseek-flash",
            at=at,
            input_tokens=1_000_000,
            cached_input_tokens=0,
            output_tokens=1_000_000,
        ).amount

    assert cost(_PEAK) == Decimal("1.50")
    assert cost(_OFF_PEAK) == Decimal("0.75")
    assert cost(_SATURDAY_PEAK_HOUR) == Decimal("0.75")


def test_model_names_are_matched_case_insensitively() -> None:
    cost = prices.ai_cost(
        provider="gemini", model=" Gemini-2.5-Flash ", at=_PEAK, input_tokens=10, output_tokens=0
    )
    assert cost.priced


def test_unknown_model_is_unpriced_not_free() -> None:
    cost = prices.ai_cost(
        provider="gemini", model="gemini-9-ultra", at=_PEAK, input_tokens=100, output_tokens=100
    )
    assert cost == prices.Cost(Decimal(0), "USD", priced=False)


def test_sarvam_bills_whole_seconds_at_30_rupees_an_hour() -> None:
    cost = prices.ai_cost(provider="sarvam", model="saaras:v2.5", at=_PEAK, audio_seconds=11.2)
    assert cost.currency == "INR"
    assert cost.amount == Decimal(12) * Decimal(30) / Decimal(3600)
    assert not prices.ai_cost(provider="sarvam", model=None, at=_PEAK).priced


@pytest.mark.parametrize(
    ("category", "amount"),
    [
        ("utility", "0.1150"),
        ("AUTHENTICATION", "0.1150"),
        ("service", "0.1150"),
        ("marketing", "0.8631"),
    ],
)
def test_whatsapp_rates_by_category(category: str, amount: str) -> None:
    assert prices.whatsapp_cost(category) == prices.Cost(Decimal(amount), "INR")


def test_whatsapp_not_billable_costs_nothing() -> None:
    assert prices.whatsapp_cost("service", billable=False).amount == 0


def test_to_inr() -> None:
    usd = prices.Cost(Decimal("2"), "USD")
    assert prices.to_inr(usd, Decimal("96.29")) == Decimal("192.58")
    inr = prices.Cost(Decimal("0.115"), "INR")
    assert prices.to_inr(inr, Decimal("96.29")) == Decimal("0.115")


def test_exchange_rate_setting() -> None:
    default = platform_settings.with_defaults("usage_pricing", None)
    assert default == {"usd_inr": 96.29}
    assert platform_settings.validate("usage_pricing", {"usd_inr": 95}) == {"usd_inr": 95.0}
    with pytest.raises(ValueError, match="between"):
        platform_settings.validate("usage_pricing", {"usd_inr": 9.6})
    with pytest.raises(ValueError, match="number"):
        platform_settings.validate("usage_pricing", {"usd_inr": "96"})
