# Teammate — Claude Code as a member of the team's WhatsApp groups

A self-contained kit that makes Claude Code a working team member:

1. **Listens** to the team group and the customer groups (a spare WhatsApp number, linked like
   WhatsApp Web).
2. **Keeps an inbox** of everything said, searchable from any Claude Code session. You can say
   "fix the DPR problem Acme raised yesterday" and the session finds it.
3. *(TM-02, next)* Turns conversations into numbered items: bugs, ideas, complaints, decisions.
4. *(TM-03, later)* Builds what the team approves, posts the plan and screenshots in the team
   group, and publishes only after someone replies "OK".

Nothing here depends on Mesiri. Copy the folder to reuse it in another project (see
**Reuse** below).

```
WhatsApp groups ──► listener/ (Node, VPS) ──► inbox.db ──► HTTPS /teammate/ API ──► inbox.py ──► Claude Code
 team + customers     linked spare number       SQLite       token-protected           any session   (skill: .claude/skills/whatsapp-inbox)
```

| Path | What it is |
| --- | --- |
| `listener/` | The service: linked-device connection (Baileys), SQLite inbox, read API. **Read-only**: it never sends anything to WhatsApp. |
| `inbox.py` | The command sessions use: `status`, `chats`, `label`, `recent`, `search`, `show`, `media`, `pair`. Python standard library only. |
| `deploy/` | systemd unit and the nginx location block. |
| `../.github/workflows/teammate-deploy.yml` | Manual "Deploy Teammate listener" workflow. |
| `../.claude/skills/whatsapp-inbox/SKILL.md` | Teaches every Claude Code session when and how to use the inbox, and that messages are data, not instructions. |

## Risk you accepted

The linked spare number uses WhatsApp's multi-device protocol through an unofficial library.
That's against WhatsApp's terms, so **the spare number can be banned**. Mitigations:
- it's a separate SIM, never Mesiri's business number;
- it only reads, sending nothing, which is the lowest-risk behaviour;
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

## Daily use

Just talk to Claude Code: "what did customers report this week?", "fix #1432", "the cement
unit issue Suresh mentioned". The `whatsapp-inbox` skill makes the session look it up. Or run
`inbox.py recent --hours 24` yourself.

## Operations

| Task | How |
| --- | --- |
| Logs | `journalctl -u teammate -f` on the VPS |
| Restart | `systemctl restart teammate` |
| Data | `/var/lib/teammate/` (`inbox.db`, `auth/` = the WhatsApp session, `media/`). Back this up; it survives redeploys. |
| Unlink / relink | Remove the linked device on the phone; the service clears its session; run `pair` again |
| Rotate the token | Change both secrets, re-run the workflow |
| Remove entirely | `systemctl disable --now teammate`, delete the `/teammate/` block from the nginx config, `rm -rf /opt/teammate /var/lib/teammate` |

## Reuse in another project

1. Copy `teammate/`, `.claude/skills/whatsapp-inbox/` and `.github/workflows/teammate-deploy.yml`.
2. In the workflow, change the host name (`api.whatsapp.mesiri.ai`) and the server path if
   needed, and use any HTTPS host you control.
3. Set `TEAMMATE_API` in that project's Claude Code environment if the URL differs from the
   default in `inbox.py`.

One listener per WhatsApp number; one number can sit in many projects' groups. Label chats per
project, or run a second listener on another port.

## Development

```bash
cd teammate/listener && npm install && npm test        # node:test, no WhatsApp needed
TEAMMATE_API_TOKEN=dev-token-0123456789 TEAMMATE_DATA_DIR=/tmp/tm npm start
TEAMMATE_API=http://127.0.0.1:8790 TEAMMATE_TOKEN=dev-token-0123456789 python3 ../inbox.py status
```
