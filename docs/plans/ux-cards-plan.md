# Swiss UX cards: Today, Stock, Welcome (request 91, WA-53)

Three text-heavy WhatsApp replies became image cards. Black on white, letter-spaced
header (`MESIRI · TODAY|STOCK|WELCOME`) with site/date at the right, thick rule, big
numbers, red only for a problem, a black (red when LOW) footer bar. The text always
stays: it is the caption, and it is what goes out if a card cannot be made.

## Where it lives

`apps/whatsapp-assistant/src/channel/cards/`: `base.html` + `base.py` (shared frame,
Jinja2 autoescape, embedded fonts from `channel/receipt`), `today.py`, `stock.py`,
`welcome.py`, `payload.py`. The PNG comes from the existing `ReceiptRenderer`
(one Chromium, shared with receipts and onboarding cards). `send_image` has an
optional `filename` (default `receipt.png`).

| Card | Sent from | How |
| --- | --- | --- |
| Today | `runtime/site_day_review.py` (gap check, no update, confirm) and `runtime/project_auto_dpr.py` (project report) | The queued notification payload carries `card` (plain dict). `runtime/send_pending_notifications.py` draws it at send time, inside the 24h window only: header image of the same buttons, or a captioned image for the report. Outside the window the approved template is untouched. |
| Stock | `runtime/agent/query_entry.py` (`_stock_card`), attached in `runtime/message_journey.py` | All-materials question (no material named, 2+ rows). One image, the reply as caption (`ReplySpec.caption_image`). One-material questions stay text. |
| Welcome | `runtime/contact_share_journey.py` (`invite_after_member_added`) | Joiner gets the card with the JOINED text as caption. |

## Numbers

- Today: read from the day's report payload (`daily_report_versions.payload`), the same
  source as the DPR draft. Labour and Attendance are only read.
- Stock: `MaterialInventoryQueryService.query` rows; "≈N days at this week's use" is
  stock ÷ (last 7 days of usage ÷ 7), from one read-only query
  (`usage_last_days`, `material_movements`). Left out with no usage. Red at stock ≤ 0;
  red LOW footer at ≤ 0 or under 3 days left.
- "Today" is the site's timezone (consistent with request 90).

## Risks and rollback

Chromium load at the evening peak: one render per site on the already warm shared
instance. Rollback: revert the WA-53 commits; each card also falls back to its text
by itself when rendering or the image upload fails. No migration.
