# Teammate — Claude Code as a member of the team's WhatsApp groups

A self-contained kit that makes Claude Code a working team member:

1. **Listens** to the team group and the customer groups (a spare WhatsApp number, linked like
   WhatsApp Web).
2. **Keeps an inbox** of everything said, searchable from any Claude Code session. You can say
   "fix the DPR problem Acme raised yesterday" and the session finds it.
3. **Posts updates to the team group** (TM-04): what changed, with screenshots or before/after
   chat images, after work is pushed. Only into chats labelled `team`; customer groups are
   refused by the server.
4. *(TM-02, next)* Turns conversations into numbered items: bugs, ideas, complaints, decisions.
5. *(TM-03, later)* Builds what the team approves, posts the plan and screenshots in the team
   group, and publishes only after someone replies "OK".

Nothing here depends on Mesiri. Copy the folder to reuse it in another project (see
**Reuse** below).

```
WhatsApp groups ──► listener/ (Node, VPS) ──► inbox.db ──► HTTPS /teammate/ API ──► inbox.py ──► Claude Code
 team + customers     linked spare number       SQLite       token-protected           any session   (skill: .claude/skills/whatsapp-inbox)
```

| Path | What it is |
| --- | --- |
| `listener/` | The service: linked-device connection (Baileys), SQLite inbox, API. It sends only through `POST /send`, only into chats labelled `team` (30 posts an hour), an approved person's own 1-on-1 chat, and the `assistant-test` chat (10 an hour). Never to customers; never reactions, read receipts or "online". |
| `inbox.py` | The command sessions use: `status`, `chats`, `label`, `recent`, `search`, `show`, `media`, `pair`, `post`. Python standard library only. |
| `chat_image.py` | Draws a WhatsApp-style conversation, or a before/after pair, as a PNG for team updates. Standard library + Chromium. |
| `deploy/` | systemd unit and the nginx location block. |
| `../.github/workflows/teammate-deploy.yml` | Manual "Deploy Teammate listener" workflow. |
| `../.claude/skills/whatsapp-inbox/SKILL.md` | Teaches every Claude Code session when and how to use the inbox, and that messages are data, not instructions. |
| `../.claude/skills/team-update/SKILL.md` | Teaches sessions to post a short update with screenshots to the team group after pushing work. |

## Risk you accepted

The linked spare number uses WhatsApp's multi-device protocol through an unofficial library.
That's against WhatsApp's terms, so **the spare number can be banned**. Mitigations:
- it's a separate SIM, never Mesiri's business number;
- it mostly reads, and sends only to your own team group (rate-limited), never to customers;
- if it's banned, link a new SIM and nothing else changes.

Tell customers that a Mesiri bot is in their group and keeps notes. It's a visible group member
anyway.

## Setup (once)

1. **Token.** Generate one: `openssl rand -hex 32`. Add it in two places:
   - GitHub → repo Settings → Secrets and variables → Actions → **`TEAMMATE_API_TOKEN`**
   - Claude Code environment settings (cloud environment menu → Edit) → secret/env var
     **`TEAMMATE_TOKEN`** with the same value
2. **Deploy.** GitHub → Actions → **Deploy Teammate listener** → Run workflow. It installs
   Node 22 if needed, starts the `teammate` service, adds `/teammate/` to the
   `api.whatsapp.mesiri.ai` nginx config (backed up, tested, rolled back on failure), and checks
   `https://api.whatsapp.mesiri.ai/teammate/health`.
3. **Link the spare number.** From a Claude Code session, or any terminal with the token:
   ```bash
   python3 teammate/inbox.py pair 9198XXXXXXXX     # country code + number of the SPARE SIM
   ```
   On the spare phone: WhatsApp → Settings → Linked devices → Link a device → *Link with phone
   number instead* → type the code. Then `python3 teammate/inbox.py status` should say
   `connected`.
4. **Add the spare number to the groups** (team group and each customer group). Then
   `inbox.py chats` and label them:
   ```bash
   python3 teammate/inbox.py label "Mesiri team" team
   python3 teammate/inbox.py label "Acme" customer
   python3 teammate/inbox.py label "Family" ignore     # hidden from searches
   ```
   Groups the number was already in also appear, with some recent history.

## Posting to the team group

```bash
python3 teammate/inbox.py post "*DPR fix is live* (WA-16)" --image after.png::"New confirmation"
python3 teammate/chat_image.py convo.json after.png     # WhatsApp-style picture of a conversation
```

`post` picks the one chat labelled `team` (or pass `--chat`). Posting into a customer group is
refused with HTTP 403. Limits: text 4,000 characters, image 5 MB, 30 posts an hour
(`TEAMMATE_SEND_PER_HOUR`). Sessions do this on their own after pushing work (skill
`team-update`). A reply in the group is *not* treated as approval to publish; that's TM-03.

## Older messages (TM-06)

WhatsApp shares a group's recent history with new members, so the spare **phone** often has
messages from before the listener saw them. Pull them into the inbox, 50 per page:

```bash
python3 teammate/inbox.py history "Mercon Software discussions" --pages 20
```

The phone must be online. It can only send what it has; it stops when there's nothing older.
Voice notes and photos of pulled messages are downloaded too, while WhatsApp still serves them.

## Voice notes and Malayalam (TM-07) — on request, with costs in rupees

With the GitHub secret `TEAMMATE_GEMINI_API_KEY` set, the listener can turn a voice note into a
transcript in its own language plus English, and Malayalam (script or Manglish) text into English,
with Gemini (`gemini-3.8-flash`; `TEAMMATE_GEMINI_MODEL` overrides it).

**Only when someone asks** (owner's choice, 15 Oct): nothing is translated in the background.
- In WhatsApp: reply to the voice note with `@bot translate`, or write `@bot translate #123`. The bot
  answers with the transcript, the English, and what that call cost: `💰 ₹0.13 · 1,000 in / 200 out tokens`.
- Voice note as a reply to the bot (you can't @-mention in a voice note): it's transcribed (Gemini, ~₹0.10-0.50),
  the bot posts `🗣 Heard: "…" · ₹x.xx`, and Claude answers. Team groups only; a voice note is never a command
  (approvals still need typed `@bot ok <n>`).
- `@bot cost`: Gemini spend today and this month (India time), in rupees.
- The WhatsApp brain (Claude) has the same as a tool, used only for the messages a question is about.
- Here: `inbox.py translate 123`, `inbox.py cost`.
- A translated message is stored; asking again is free.
- Costs come from the token counts Gemini returns with every answer, at $0.75 in / $3.75 out per 1M
  tokens (gemini-3.8-flash, through 31 Dec 2026; both double from 1 Jan 2027) and ₹88 = $1. Change them with
  `TEAMMATE_GEMINI_PRICE_IN`, `TEAMMATE_GEMINI_PRICE_OUT`, `TEAMMATE_USD_INR`.
- Only chats labelled `team` or `customer`; personal / unlabelled chats are never sent.
- `TEAMMATE_AI_AUTO=1` brings back translating everything automatically.

## Request log per group (TM-08)

The inbox also keeps, per group, **what it asked for and what was done about it**: type
(bug / feature / question / complaint / task), English title and summary, the source message
numbers, status (open → in progress → done / won't do), the commit or PR that did it, and a dated
history of every change. Claude Code sessions keep it current (skill `whatsapp-inbox`).

```bash
python3 teammate/inbox.py summary "Mercon Software discussions"   # one group on a page
python3 teammate/inbox.py items --status open                    # everything still open
python3 teammate/inbox.py item show 12                           # one request with its history
```

## Tagging the bot (TM-03)

In a project's **team** group, approved people @-mention the linked number:

| Message | Who | Effect |
| --- | --- | --- |
| `@bot <what to do>` (best as a reply to the message it's about) | approved | logs a request (TM-08) and confirms in the group |
| `@bot ok <request number>` | approved | approves it: status → in progress, "OK from …" in its history |
| `@bot who` · `@bot help` | approved | who is approved · the commands |
| `@bot auto on [hours]` · `@bot auto` · `@bot auto off` / `@bot stop` | owners start; anyone approved stops | the auto loop (request 61): test → one in-scope fix → push → verify, by itself; see `brain/README.md` |
| `@bot approve @person` · `@bot remove @person` · `@bot make owner @person` | owners | manage approvals from the group |

- In **customer** groups the bot never answers; an approved person's tag there is logged and
  announced in the team group. Everyone else's tags are ignored.
- Owners are set on the server first: `inbox.py allow 9170… --role owner --project '*'`
  (`*` = every project). An all-projects owner can't be removed from a group.
- **1-on-1 chats (plan 15).** An approved person can also message the linked number directly, no @ needed;
  unapproved senders are ignored. If they're approved for one project that's used; if several (or `*`) the
  bot asks "mesiri" / "mercon" and remembers the answer for that chat (`project <name>` changes it). Each
  person's chat is its own ongoing conversation; replies go to that chat only (`/send` allows an unlabelled
  1-on-1 chat only when the person is approved for the `project` in the call). `ok <n>` works for the
  sender's own project; approve / remove / make owner / upgrade / model stay in the team group.
- **Testing the Mesiri assistant (plan 15).** A chat labelled `assistant-test` (owner, on the server:
  `inbox.py label <jid> assistant-test --project mesiri`; never automatic) is the bot's test conversation
  with the Mesiri assistant's number. `/send` allows it for text and images, for its own project only,
  `TEAMMATE_TEST_SENDS_PER_HOUR` (default 10) an hour. Setup: the linked number messages the assistant once,
  then label that chat; register the bot's number as a worker in a **test** company in Mesiri. Undo:
  `inbox.py label <jid> unlabelled`.
  Menus and buttons (list, buttons, interactive, template messages) are stored as kind `interactive`: `text`
  shows the body then numbered lines (`1) Start free trial`), and `options` holds `[{n, id, title, type}]`
  (`options_json` column). `/send` with `choose: {message_n, option}` (number or exact title) taps one by
  sending the matching list/button/native-flow response quoting that message; it is refused (403) outside
  `assistant-test` chats and counts in the same hourly limit. Whether Meta's Cloud API accepts a response
  from a linked device is checked live; if not, use typed text.
- At most 20 bot replies an hour (`TEAMMATE_BOT_REPLIES_PER_HOUR`), so bots can't loop.
- Starting Claude Code automatically from an approved request is TM-03b; until then a session
  picks approved requests up with `inbox.py items --status in_progress`.

## Backups

Everything above lives on the VPS in `/var/lib/teammate`: `inbox.db` (messages, transcripts and
translations, request log), `media/`, and `auth/` (the WhatsApp session). `teammate-backup.timer`
copies all of it nightly at 02:30 IST to `/var/backups/teammate/teammate-<stamp>.tar.gz`
(root-only, newest 14 kept); every deploy also takes one. Restore steps are at the top of
`deploy/backup.sh`. The backups are on the same server, so they don't survive losing the VPS.

## Daily use

Just talk to Claude Code: "what did customers report this week?", "fix #1432", "the cement
unit issue Suresh mentioned". The `whatsapp-inbox` skill makes the session look it up. Or run
`inbox.py recent --hours 24` yourself.

## Operations

| Task | How |
| --- | --- |
| Logs | `journalctl -u teammate -f` on the VPS |
| Restart | `systemctl restart teammate` |
| Data | `/var/lib/teammate/` (`inbox.db`, `auth/` = the WhatsApp session, `media/`); survives redeploys. Backed up nightly to `/var/backups/teammate` (see Backups) |
| Unlink / relink | Remove the linked device on the phone; the service clears its session; run `pair` again |
| Rotate the token | Change both secrets, re-run the workflow |
| Remove entirely | `systemctl disable --now teammate`, delete the `/teammate/` block from the nginx config, `rm -rf /opt/teammate /var/lib/teammate` |

## Several projects, one listener (TM-05)

One spare number sits in every project's groups; each chat carries a **project** tag so each
repo's Claude Code sessions see, and post to, only their own groups.

- Each repo sets `TEAMMATE_PROJECT` in its committed `.claude/settings.json` (`"env":
  {"TEAMMATE_PROJECT": "mesiri"}`). Every `inbox.py` command is then scoped to that project.
- Label with the project: `inbox.py label "Mercon Software discussions" customer --project mercon`
  (the project defaults to `TEAMMATE_PROJECT`).
- Scoped sessions never see messages from untagged chats; new groups still show in `chats` so
  they can be labelled. Posting is refused into another project's team chat.
- Without `TEAMMATE_PROJECT` everything is visible, as before.

| Project | Repo | Groups |
| --- | --- | --- |
| `mesiri` | this repo | team group (to add), customer groups |
| `mercon` | `aprodac/MERCON` (`teammate/inbox.py` + `whatsapp-inbox` skill copied in) | Mercon Software discussions (customer) |

## Connecting another repo

1. Copy `teammate/inbox.py` (and `chat_image.py` if it will post) into that repo's `teammate/`,
   and `.claude/skills/whatsapp-inbox/` (plus `team-update/` if it has a team group).
2. Add `"env": {"TEAMMATE_PROJECT": "<name>"}` to its `.claude/settings.json`.
3. Put `TEAMMATE_TOKEN` in that repo's Claude Code environment (never commit it).
4. Label its groups with `--project <name>`.

To run a whole separate listener instead (another number or host), copy `teammate/` and
`.github/workflows/teammate-deploy.yml`, change the host name in the workflow, and set
`TEAMMATE_API` if the URL differs from the default in `inbox.py`.

## Development

```bash
cd teammate/listener && npm install && npm test        # node:test, no WhatsApp needed
TEAMMATE_API_TOKEN=dev-token-0123456789 TEAMMATE_DATA_DIR=/tmp/tm npm start
TEAMMATE_API=http://127.0.0.1:8790 TEAMMATE_TOKEN=dev-token-0123456789 python3 ../inbox.py status
```
