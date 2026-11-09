# Client view: the client sees their project from a link (CV)

> Module 30 of the Capability Framework ("controlled client access"). Asked and approved in session by Ilan,
> 9 Nov 2026. Security-sensitive (outside people see company data), so the decisions below are Ilan's.
> Tracker: [V1_TRACKER.md › CV](V1_TRACKER.md).

## Decisions (Ilan, 9 Nov 2026)

| # | Decision |
| --- | --- |
| D-CV1 | **Access is a secret link per project**, sent on WhatsApp. No login, no OTP. Anyone holding the link sees the page until it is turned off. |
| D-CV2 | **Progress and bills.** The client sees their own contract value, bills and payments, never our rates, costs, budgets, suppliers, subcontractors, labour or money accounts. |
| D-CV3 | Links are made, listed and turned off by the roles that see client bills (`may_manage_money`: owner, admin, finance), within the projects they reach. Not project managers, as for RA bills. |

## What the client sees

Built in `backend/src/mesiri/domains/client_view/view.py`. Every field leaves through a fixed allow-list (`*_FIELDS`); a
contract test fails if any other key appears.

- Company letterhead name, phone, brand colour, logo.
- Project name, stage, start, contract finish, forecast finish (and days late), overall progress, contract value, client name.
- Milestones from the schedule (all activities, up to 60, when the schedule has none), planned / expected / done.
- Up to 40 photos from site reports the company **approved or sent** (`daily_reports` SITE level, `APPROVED` /
  `PUBLISHED`, on the photo's day). A supervisor's photo nobody reviewed never reaches the client.
- Submitted and certified RA bills (gross, retention, advance recovery, GST, TDS, net, certified), with received and
  left per bill (`receivables.settle`, the same as the Receivables page). Drafts and cancelled bills never.
- Confirmed payments (date, amount, kind, bill). Not the account, method or reference.

## How it works

- `client_links` (migration 0534, additive, tenant RLS): the token is 32 random bytes (`secrets.token_urlsafe`);
  only its SHA-256 is stored, so a database read or backup never yields a working link. The token is returned
  once, when made. `revoked_at` turns it off at once; `open_count` / `last_opened_at` show it is used.
- `GET /client/{token}` takes no login. It finds the link with no company set (as login and the WhatsApp
  webhook do), then scopes the rest of the transaction to the link's company (`apply_tenant`). Malformed, unknown
  and revoked tokens are the same 404. Responses are `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
  `X-Robots-Tag: noindex`.
- Photos are signed links that expire (10 minutes), the same as the site gallery (`signed_media_url`).
- Web: `/c/:token` (outside the app layout, its own HTTP client that never sends a staff token);
  `/billing/client-view` makes a link (copy, open, send on WhatsApp via `wa.me`), lists links, turns them off;
  "Share with client" on the RA bills page.

## Routes

| Route | Who |
| --- | --- |
| `GET /client-links` | owner, admin, finance (their projects) |
| `GET /projects/{id}/client-links` | same |
| `POST /projects/{id}/client-links` `{label}` → `{link, token}` | same |
| `POST /client-links/{id}/revoke` | same |
| `GET /client/{token}` | anyone with the link |

No agent (`ALLOWED`) route yet: sharing from WhatsApp ("send Mr. Thomas his link") is a later item if asked.

## Risks

- **A forwarded link** shows the page to whoever has it (D-CV1). Turning it off stops it at once; the list shows how
  often each link was opened.
- **Guessing** a 256-bit token is not feasible; there is no per-IP rate limit on `/client/{token}` (none exists in
  the backend today). Revisit if the endpoint is ever abused (nginx `limit_req`).
- **A new field** added to a source (bills, schedule) does not reach the client: only allow-listed keys are copied.

## Rollback

Revert the commits. Migration 0534 only adds `client_links`; its downgrade refuses while links exist. Turning off
every link (`UPDATE client_links SET revoked_at = now()`) stops all access without a deploy.

## Later (CV-04)

The client asks or complains from the page; it reaches the PM as an Issue (module 30, "client requests").
