# What each AI call and WhatsApp message costs (BE-25)

> Built 15 Oct 2026. Tracker: BE-25. Read by: SA-05 (costs view), SS-09 (trial caps),
> SS-11 (cost per trial), SA-17 (Reply Insights).

Every AI provider response and every WhatsApp message the assistant sends leaves one row
in `provider_executions` with `metered = true`. Each row records the company, the model or
message category, the tokens or audio seconds, and the cost in the provider's currency and
in INR.

## How a row gets written

| What | Who reports it | Where |
| --- | --- | --- |
| AI call (Gemini, DeepSeek) | the adapter, after each successful response, with the provider's own token counts | `platform/ai/src/mesiri_ai/adapters/*/adapter.py` → `mesiri_ai.usage.report` |
| Speech-to-text (Sarvam) | the adapter, with the audio length read from the OGG file | same |
| WhatsApp message sent | `WhatsAppSender._send`, with the wamid and our category estimate (template category, or `service` for a reply) | `channel/whatsapp/outbound.py` → `channel/whatsapp/usage.py` |
| Meta's pricing for a message | the webhook, from each status's `pricing` (`billable`, `category`); this replaces our estimate | `ingress/receiver.py` → `channel/whatsapp/usage.py` |

Both report hooks go to one `UsageRecorder` (`backend/src/mesiri/application/usage/recorder.py`).
`runtime/dependencies.py` installs it in `build_container`, so both the web app and the
`arq` worker record. The recorder:

- **prices** the call (`domains/usage/prices.py`);
- **finds the company**: for an AI call, from the `usage_scope` the caller set, or from the
  inbound message its `correlation_id` belongs to; for a WhatsApp message, from the user who
  owns the recipient's number;
- **writes the row** in its own short transaction.

**Failures never reach the user.** A report is fire-and-forget: if pricing or writing fails,
it's logged (`usage.record_*_failed`) and the reply goes out as normal.

## Prices

All prices live in `domains/usage/prices.py`, with their sources and the date they were
checked. Every row stores the `price_ref` it was priced with. When a provider changes a price:
1. Edit the table in `prices.py`.
2. Bump `PRICE_REF`.

Old rows keep their old price.

| Provider | Price |
| --- | --- |
| Gemini 2.5 Flash | USD per 1M tokens: input 0.30 (audio 1.00), output 2.50 including thinking, cached input 0.03 |
| DeepSeek `deepseek-flash` | USD per 1M tokens, peak: input 0.30, cache hit 0.006, output 1.20. **Half price off-peak**: outside 01:00–04:00 and 06:00–10:00 UTC on weekdays, and all weekend |
| Sarvam speech-to-text | ₹30 per hour of audio, per second rounded up |
| WhatsApp, India | ₹ per delivered message before GST: marketing 0.8631; utility, authentication, service 0.1150 |

**WhatsApp's 1 Oct 2026 change:** service replies and utility messages inside the 24 h window
are now charged. The first 1,000 service messages per business number per month are free. Meta
says per message whether it was billable, and that verdict replaces our estimate.

**Exchange rate:** the platform setting `usage_pricing.usd_inr`, default 96.29 (the latest RBI
reference rate found, 18 May 2026). Each row keeps the INR it was worth when written, so
changing the rate doesn't rewrite history.

**An unknown model or category is stored with no cost** (`cost_inr` NULL), not as free.

**Not confirmed against the official pages.** The session's network policy blocked them, so:
- **DeepSeek:** taken from search results limited to DeepSeek's own site and LiteLLM's price
  file, which agree.
- **WhatsApp INR:** Meta's rate card as quoted by several identical rate summaries.

Check both against the DeepSeek pricing page and WhatsApp Manager billing.

## Reading

Use `PostgresUsageCostRepository` (`infrastructure/postgres/repositories/usage_costs.py`):

- **`usage_summary(org_id, since=, until=)`:** AI calls, input and output tokens, AI cost,
  WhatsApp messages and WhatsApp cost (all INR), and the total.
- **`usage_for_phone(digits, since=)`:** the same for one phone number: messages sent to it,
  plus the AI calls made while handling its messages. This is for signups, which have no
  company yet (SS-09).
- **The control panel's Costs page (SA-05)**, `GET /admin/costs`: `cost_totals`, `costs_by_day`
  (Indian calendar days), `costs_by_company`, and for one company `costs_by_inbound_message`
  and `whatsapp_messages_sent`. Rows with no price are counted as `unpriced`. WhatsApp rows
  have no `correlation_id`, so a reply's cost can't be tied to the message that caused it.
- **The control panel's Reply Insights page (SA-17)**, `GET /admin/replies`,
  `/admin/replies/messages` and `/admin/replies/messages/{correlation_id}/calls`, read through
  `PostgresReplyUsageRepository` (`repositories/reply_usage.py`): each inbound message's reply
  time (`received_at -> processed_at`, the Performance page's number) next to its metered AI
  rows (tokens incl. cached, latency, cost). Scoped by when the *message* arrived (not the
  call), optionally one company and message type. Gives the reply-time percentiles and speed
  bands (under 5 s / 5-15 / 15-30 / 30-60 / over 1 min), a trend in Indian-time buckets
  (`date_bin`, 12-30 points per window), tokens by model and by step (`purpose`, else
  `operation`), and a sortable feed (newest / slowest / most tokens / most expensive). A
  message with no AI rows was answered without the AI (`no_ai`). Read-only, platform admin.

**How the company is found:** a row's own `organization_id`, else the company of the inbound
message with the same `correlation_id`. A message resolved to its company after the AI call
still counts.

**Existing readers are unchanged.** The latency summary (`trace_logger.get_provider_summary`)
and the tenant dashboard's message detail (`users/router.py`) skip `stage = 'metered'`. The
control panel's per-message log view shows the new rows.

## Schema (migration 0478)

New columns on `provider_executions`:

| Column | Notes |
| --- | --- |
| `metered` | marks the per-call cost rows |
| `organization_id` | **no foreign key**: a deleted trial's costs stay for the funnel |
| `purpose` | what the call was for, when the caller said (e.g. `dpr_summary`, BE-18) |
| `input_tokens`, `cached_input_tokens`, `audio_input_tokens`, `output_tokens` | `output_tokens` includes thinking |
| `audio_seconds` | providers that bill by time |
| `category`, `billable`, `external_id`, `recipient` | WhatsApp; `external_id` is the wamid, unique |
| `cost_native`, `cost_currency`, `cost_inr`, `price_ref` | cost and the price table version used |

`correlation_id` is now nullable. The downgrade deletes the metered rows.

## Not covered yet

- **Dashboard photo reading** (Finance and Workforce routers) is recorded but not tied to a
  company: those calls have no message. Wrapping them in `usage_scope(organization_id=...)` is
  a one-line change per router; Workforce is a protected module, so that needs approval.
- **Meta's volume tiers** (cheaper utility and authentication above high monthly volumes) and
  **GST** are not modelled.
- **Batch, flex and priority tiers** for Gemini are not used by Mesiri, so not priced.
