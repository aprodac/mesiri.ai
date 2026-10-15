"""What an AI call or a WhatsApp message costs (BE-25). Pure, no I/O.

Prices as of 15 Oct 2026. When a provider changes a price, change it here and
bump PRICE_REF: every cost row records the PRICE_REF it was priced with, so
old rows keep meaning what they meant.

Sources (checked 15 Oct 2026; the session could not open the official pages
directly, so each figure was read through search results limited to the
official site and cross-checked):

- Gemini 2.5 Flash, paid standard tier, USD per 1M tokens:
  https://ai.google.dev/gemini-api/docs/pricing -- input 0.30 (audio 1.00),
  output 2.50 incl. thinking, cached input 0.03 (audio 0.10). Same figures
  in LiteLLM's price file (litellm 1.105.1 on PyPI, 14 Oct 2026).
- Gemini 2.5 Flash-Lite (the replacement for retired 2.0 Flash-Lite, see
  mesiri_ai/model_names.py): input 0.10 (audio 0.30), output 0.40, cached
  0.01 (audio 0.03) -- from LiteLLM's price file (same release as above),
  which lists the page's 2.5 Flash figures exactly.
- DeepSeek `deepseek-flash` (DeepSeek-V4.1-Flash), USD per 1M tokens:
  https://api-docs.deepseek.com/quick_start/pricing/ -- peak: cache hit
  0.006, cache miss 0.30, output 1.20; "off-peak rates are half of the peak
  rates". Peak = 01:00-04:00 and 06:00-10:00 UTC on weekdays (Chinese public
  holidays are off-peak; not modelled, so those days are priced as peak --
  an over-estimate). LiteLLM's price file lists the same peak figures for
  `deepseek/deepseek-flash`. New pricing from 10 Sep 2026:
  https://api-docs.deepseek.com/news/news260910/
- Sarvam speech-to-text-translate (saaras): INR 30 per hour of audio, billed
  per second: https://docs.sarvam.ai/api/pricing
- WhatsApp Business Platform, India, INR per delivered message, before 18%
  GST: marketing 0.8631; utility, authentication and (from 1 Oct 2026)
  service 0.1150. Billing model and the 1 Oct 2026 change (service replies
  billed at the utility rate after 1,000 free per business number a month;
  utility inside the 24 h window billed):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
  https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages
  The INR figures come from Meta's INR rate card (a CSV the search could not
  read) as quoted, identically, by several rate summaries, e.g.
  https://www.flowcall.co/blog/whatsapp-business-api-pricing and
  https://chatmaxima.com/whatsapp-api-pricing/india/ -- check against
  WhatsApp Manager billing. Meta's own status webhook says whether each
  message was billable and in which category, and that overrides our
  estimate (free tier, free entry point windows).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from decimal import Decimal

PRICE_REF = "2026-10-15"

USD = "USD"
INR = "INR"

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class TokenPrices:
    """USD per 1M tokens."""

    input: Decimal
    output: Decimal
    cached_input: Decimal
    audio_input: Decimal | None = None
    cached_audio_input: Decimal | None = None


_GEMINI_25_FLASH = TokenPrices(
    input=Decimal("0.30"),
    output=Decimal("2.50"),
    cached_input=Decimal("0.03"),
    audio_input=Decimal("1.00"),
    cached_audio_input=Decimal("0.10"),
)
_GEMINI_25_FLASH_LITE = TokenPrices(
    input=Decimal("0.10"),
    output=Decimal("0.40"),
    cached_input=Decimal("0.01"),
    audio_input=Decimal("0.30"),
    cached_audio_input=Decimal("0.03"),
)
# Peak; off-peak is half (see _deepseek_off_peak).
_DEEPSEEK_FLASH_PEAK = TokenPrices(
    input=Decimal("0.30"),
    output=Decimal("1.20"),
    cached_input=Decimal("0.006"),
)

TOKEN_PRICES: dict[tuple[str, str], TokenPrices] = {
    ("gemini", "gemini-2.5-flash"): _GEMINI_25_FLASH,
    ("gemini", "gemini-2.5-flash-lite"): _GEMINI_25_FLASH_LITE,
    ("deepseek", "deepseek-flash"): _DEEPSEEK_FLASH_PEAK,
}

# Sarvam: INR per second of audio (INR 30 per hour).
SARVAM_INR_PER_SECOND = Decimal(30) / Decimal(3600)

# WhatsApp, India, INR per delivered message before GST. Keys are Meta's
# pricing categories, lower case, as its status webhook reports them.
WHATSAPP_INR: dict[str, Decimal] = {
    "marketing": Decimal("0.8631"),
    "utility": Decimal("0.1150"),
    "authentication": Decimal("0.1150"),
    "service": Decimal("0.1150"),
}

# DeepSeek peak windows, UTC, on weekdays.
_DEEPSEEK_PEAK_HOURS = (range(1, 4), range(6, 10))


@dataclass(frozen=True, slots=True)
class Cost:
    amount: Decimal
    currency: str
    # False when we have no price for this model; amount is then 0 and the
    # row says so rather than pretending the call was free.
    priced: bool = True


def _deepseek_off_peak(at: dt.datetime) -> bool:
    at = at.astimezone(dt.UTC)
    if at.weekday() >= 5:
        return True
    return not any(at.hour in hours for hours in _DEEPSEEK_PEAK_HOURS)


def ai_cost(
    *,
    provider: str,
    model: str | None,
    at: dt.datetime,
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    audio_input_tokens: int | None = None,
    output_tokens: int | None = None,
    audio_seconds: float | None = None,
) -> Cost:
    """The cost of one AI call, in the provider's billing currency."""
    if provider == "sarvam":
        if audio_seconds is None:
            return Cost(Decimal(0), INR, priced=False)
        # Billed per second, rounded up.
        seconds = Decimal(math.ceil(Decimal(str(audio_seconds))))
        return Cost(seconds * SARVAM_INR_PER_SECOND, INR)

    prices = TOKEN_PRICES.get((provider, (model or "").strip().lower()))
    if prices is None or input_tokens is None:
        return Cost(Decimal(0), USD, priced=False)

    total_in = input_tokens
    cached = min(cached_input_tokens or 0, total_in)
    audio = min(audio_input_tokens or 0, total_in)
    # Audio tokens are counted at the audio rate; cached tokens at the
    # cached rate. Gemini doesn't say which cached tokens were audio, so the
    # cache discount is applied at the text rate (a slight over-estimate for
    # cached audio, which we don't use).
    plain = max(total_in - cached - audio, 0)
    audio_rate = prices.audio_input if prices.audio_input is not None else prices.input
    usd = (
        Decimal(plain) * prices.input
        + Decimal(audio) * audio_rate
        + Decimal(cached) * prices.cached_input
        + Decimal(output_tokens or 0) * prices.output
    ) / _MILLION
    if provider == "deepseek" and _deepseek_off_peak(at):
        usd = usd / 2
    return Cost(usd, USD)


def whatsapp_cost(category: str | None, *, billable: bool | None = True) -> Cost:
    """The cost of one delivered WhatsApp message in INR. `billable=False`
    (Meta's own verdict: free tier, free entry point) costs nothing."""
    if billable is False:
        return Cost(Decimal(0), INR)
    rate = WHATSAPP_INR.get((category or "").strip().lower())
    if rate is None:
        return Cost(Decimal(0), INR, priced=False)
    return Cost(rate, INR)


def to_inr(cost: Cost, usd_inr: Decimal) -> Decimal:
    """`cost` in INR at the given USD->INR rate."""
    if cost.currency == INR:
        return cost.amount
    return cost.amount * usd_inr
