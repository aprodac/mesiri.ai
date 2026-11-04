// The inbox: every chat the linked number is in, and every message seen.
// SQLite via node:sqlite (built into Node >= 22.13), so the folder carries no
// native build step and moves to another project as-is.

import { DatabaseSync } from "node:sqlite";

// "assistant-test": the chat with the Mesiri assistant's number, which the bot may message to test it (set by an owner on the server, never automatically).
export const ROLES = ["unlabelled", "team", "customer", "ignore", "assistant-test"];
// One listener serves several repos' groups; a chat's project keeps each repo's
// sessions to their own groups (TM-05). Lowercase slug, e.g. "mesiri", "mercon".
const PROJECT_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS chats (
  jid         TEXT PRIMARY KEY,
  name        TEXT,
  is_group    INTEGER NOT NULL,
  role        TEXT NOT NULL DEFAULT 'unlabelled',
  project     TEXT,
  first_seen  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  rowid        INTEGER PRIMARY KEY,
  id           TEXT NOT NULL,
  chat_jid     TEXT NOT NULL REFERENCES chats(jid),
  sender_jid   TEXT,
  sender_pn    TEXT,
  sender_name  TEXT,
  from_me      INTEGER NOT NULL,
  at           TEXT NOT NULL,
  kind         TEXT NOT NULL,
  text         TEXT,
  quoted_id    TEXT,
  quoted_text  TEXT,
  media_mime   TEXT,
  media_path   TEXT,
  reaction_to  TEXT,
  stored_at    TEXT NOT NULL,
  transcript   TEXT,
  translation  TEXT,
  language     TEXT,
  ai_done      INTEGER NOT NULL DEFAULT 0,
  ai_attempts  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (chat_jid, id)
);
CREATE INDEX IF NOT EXISTS ix_messages_chat_at ON messages (chat_jid, at);
CREATE INDEX IF NOT EXISTS ix_messages_at ON messages (at);
-- TM-08: what each group asked for, and what was done about it.
CREATE TABLE IF NOT EXISTS items (
  id          INTEGER PRIMARY KEY,
  chat_jid    TEXT NOT NULL REFERENCES chats(jid),
  type        TEXT NOT NULL,
  title       TEXT NOT NULL,
  summary     TEXT,
  source      TEXT,
  status      TEXT NOT NULL DEFAULT 'open',
  done_ref    TEXT,
  created_by  TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_items_chat ON items (chat_jid, status);
-- TM-03: who may tag the bot to request work (member) or also approve others (owner), per project.
CREATE TABLE IF NOT EXISTS people (
  id          INTEGER PRIMARY KEY,
  project     TEXT NOT NULL,
  jid         TEXT,
  pn          TEXT,
  name        TEXT,
  role        TEXT NOT NULL,
  added_by    TEXT,
  added_at    TEXT NOT NULL,
  removed_by  TEXT,
  removed_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_people_project ON people (project, removed_at);
-- Every Gemini call: what it was for and what it cost (owner wants costs in rupees).
CREATE TABLE IF NOT EXISTS ai_usage (
  id             INTEGER PRIMARY KEY,
  at             TEXT NOT NULL,
  n              INTEGER,
  model          TEXT,
  input_tokens   INTEGER,
  output_tokens  INTEGER,
  usd            REAL,
  inr            REAL
);
CREATE TABLE IF NOT EXISTS item_log (
  item_id  INTEGER NOT NULL REFERENCES items(id),
  at       TEXT NOT NULL,
  status   TEXT,
  ref      TEXT,
  note     TEXT
);
-- TM-79: what each request cost in Claude usage: one row per Claude turn (the bot's) or per report (a session's).
-- pct_5h / pct_7d: share of that account's 5-hour / weekly window, in percent; null when not known.
CREATE TABLE IF NOT EXISTS item_usage (
  item_id   INTEGER NOT NULL REFERENCES items(id),
  at        TEXT NOT NULL,
  account   TEXT,
  by        TEXT,
  cost_usd  REAL,
  tokens    INTEGER,
  pct_5h    REAL,
  pct_7d    REAL
);
CREATE INDEX IF NOT EXISTS ix_item_usage_item ON item_usage (item_id);
-- TM-78: each Claude account's latest plan-limit reading, as the brain last saw it (one JSON per account).
CREATE TABLE IF NOT EXISTS claude_accounts (
  id          TEXT PRIMARY KEY,
  json        TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
`;
const clip = (v, n) => (v === null || v === undefined ? null : String(v).slice(0, n));
export const ITEM_TYPES = ["bug", "feature", "question", "complaint", "task"];
export const ITEM_STATUSES = ["open", "in_progress", "done", "wont_do"];
export const PEOPLE_ROLES = ["owner", "member"];
/**
 * TM-19: per request, who asked in production and what happened after it shipped.
 *   asked_by   "Name (role, company)"; never a phone number
 *   asked_ref  the production message ids (correlation ids), comma-separated
 *   asked_who  the sender's pseudonymous id from the production watch (md5), to see them use Mesiri again
 *   held       why autobuild is waiting for an owner's ok (cleared once it starts)
 *   live_at    when it was deployed;  verified "ok" | "broken" (+ verified_at): the bot's live re-test
 *   tried_at   when the person who asked used Mesiri again after it went live
 */
export const ITEM_TRACKING = ["asked_by", "asked_ref", "asked_who", "held", "started_at", "pushed_at", "live_at", "verified", "verified_at", "tried_at", "claimed_by", "claimed_at"];
/** TM-50: a claim older than this, on a request nobody finished, can be taken by someone else. */
export const CLAIM_HOURS = 6;
export const VERIFIED = ["ok", "broken"];

/** TM-79: a request's Claude usage, summed over its turns; joined onto every list and single read. */
const USAGE_JOIN = `LEFT JOIN (
  SELECT item_id, round(sum(cost_usd), 3) AS usage_usd, round(sum(pct_5h), 1) AS usage_5h, round(sum(pct_7d), 1) AS usage_7d,
         count(*) AS usage_turns, group_concat(DISTINCT account) AS usage_accounts
  FROM item_usage GROUP BY item_id
) u ON u.item_id = i.id`;
const USAGE_COLUMNS = "u.usage_usd, u.usage_5h, u.usage_7d, u.usage_turns, u.usage_accounts";
const num = (v, lo, hi) => {
  const n = Number(v);
  return v === null || v === undefined || v === "" || !Number.isFinite(n) || n < lo || n > hi ? null : n;
};

/** One request's stage, for lists and counts (TM-19). */
export function itemStage(i) {
  if (i.status === "wont_do") return "dropped";
  if (i.verified === "broken") return "broken";
  if (i.verified === "ok") return "verified";
  if (i.status === "done") return "live";
  if (i.status === "in_progress") return "building";
  return i.held ? "waiting" : "asked";
}
export const STAGES = {
  asked: "📥 asked", waiting: "✋ waiting for ok", building: "🛠 building", live: "🚀 live", verified: "✅ verified",
  broken: "❌ broken", dropped: "🚫 dropped",
};

/** Start of today and of this month in India time (UTC+5:30), as ISO strings. */
export function istStarts(now = Date.now()) {
  const IST = 330 * 60_000;
  const local = new Date(now + IST);
  return {
    day: new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate()) - IST).toISOString(),
    month: new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), 1) - IST).toISOString(),
  };
}

const nowIso = () => new Date().toISOString();

// Messages still waiting for Gemini (TM-07); see Store.pendingAi.
const PENDING_AI = `
  FROM messages m JOIN chats c ON c.jid = m.chat_jid
  WHERE m.ai_done = 0 AND m.ai_attempts < 3 AND c.role IN ('team', 'customer')
    AND ((m.kind IN ('voice', 'audio') AND m.media_path IS NOT NULL)
      OR (m.kind NOT IN ('voice', 'audio', 'reaction') AND COALESCE(m.text, '') != ''))`;

// What the API returns for a message: the internal rowid is the public,
// short, stable number people and sessions refer to ("message 1432").
const MESSAGE_COLUMNS = `
  m.rowid AS n, m.id, m.chat_jid, c.name AS chat_name, c.role AS chat_role, c.project AS chat_project,
  m.sender_jid, m.sender_pn, m.sender_name, m.from_me, m.at, m.kind, m.text,
  m.quoted_id, m.quoted_text, m.media_mime, (m.media_path IS NOT NULL) AS has_media,
  m.reaction_to, m.transcript, m.translation, m.language, m.options_json`;

/** Swaps the stored options_json for a parsed `options` array (null when the message has none). */
function withOptions(row) {
  if (!row) return row;
  const { options_json, ...rest } = row;
  let options = null;
  try {
    options = options_json ? JSON.parse(options_json) : null;
  } catch {
    // unreadable: treat as no options
  }
  return { ...rest, options };
}

export class Store {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
    this.db.exec(SCHEMA);
    // Inboxes created before TM-05 have no project column; add it in place.
    const cols = this.db.prepare("PRAGMA table_info(chats)").all().map((c) => c.name);
    if (!cols.includes("project")) this.db.exec("ALTER TABLE chats ADD COLUMN project TEXT");
    // ...and before TM-07 no transcript / translation columns.
    const mcols = this.db.prepare("PRAGMA table_info(messages)").all().map((c) => c.name);
    for (const [name, type] of [
      ["transcript", "TEXT"], ["translation", "TEXT"], ["language", "TEXT"],
      ["ai_done", "INTEGER NOT NULL DEFAULT 0"], ["ai_attempts", "INTEGER NOT NULL DEFAULT 0"],
      ["options_json", "TEXT"], // menu/button options of an interactive message
    ]) {
      if (!mcols.includes(name)) this.db.exec(`ALTER TABLE messages ADD COLUMN ${name} ${type}`);
    }
    // ...and before TM-20 every Gemini call was a translation of one message.
    const ucols = this.db.prepare("PRAGMA table_info(ai_usage)").all().map((c) => c.name);
    for (const [name, type] of [["kind", "TEXT"], ["project", "TEXT"], ["calls", "INTEGER"]]) {
      if (!ucols.includes(name)) this.db.exec(`ALTER TABLE ai_usage ADD COLUMN ${name} ${type}`);
    }
    // ...and before TM-19 nothing about who asked (from production) or what happened after it shipped.
    const icols = this.db.prepare("PRAGMA table_info(items)").all().map((c) => c.name);
    for (const name of ITEM_TRACKING) {
      if (!icols.includes(name)) this.db.exec(`ALTER TABLE items ADD COLUMN ${name} TEXT`);
    }
  }

  close() {
    this.db.close();
  }

  upsertChat({ jid, name = null, is_group }) {
    const now = nowIso();
    this.db
      .prepare(
        `INSERT INTO chats (jid, name, is_group, first_seen, updated_at) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(jid) DO UPDATE SET
           name = COALESCE(excluded.name, chats.name), updated_at = excluded.updated_at`,
      )
      .run(jid, name, is_group ? 1 : 0, now, now);
  }

  hasChatName(jid) {
    const row = this.db.prepare("SELECT name FROM chats WHERE jid = ?").get(jid);
    return Boolean(row?.name);
  }

  /** A chat by exact jid, or by a name substring that matches exactly one chat. */
  findChat(jidOrName) {
    if (!jidOrName) return null;
    const exact = this.db.prepare("SELECT jid, name, role, project, is_group FROM chats WHERE jid = ?").get(jidOrName);
    if (exact) return exact;
    const hits = this.db.prepare("SELECT jid, name, role, project, is_group FROM chats WHERE name LIKE ?").all(`%${jidOrName}%`);
    return hits.length === 1 ? hits[0] : null;
  }

  /** `project` undefined leaves it as is; null clears it. */
  setRole(jid, role, project) {
    if (!ROLES.includes(role)) throw new Error(`role must be one of ${ROLES.join(", ")}`);
    if (project != null && !PROJECT_RE.test(project)) {
      throw new Error("project must be a lowercase slug (letters, digits, - and _), e.g. mercon");
    }
    const res =
      project === undefined
        ? this.db.prepare("UPDATE chats SET role = ?, updated_at = ? WHERE jid = ?").run(role, nowIso(), jid)
        : this.db
            .prepare("UPDATE chats SET role = ?, project = ?, updated_at = ? WHERE jid = ?")
            .run(role, project, nowIso(), jid);
    return res.changes > 0;
  }

  /** Inserts a normalized message once; returns its public number, or null if already stored. */
  addMessage(rec) {
    this.upsertChat({ jid: rec.chat_jid, is_group: rec.is_group });
    const res = this.db
      .prepare(
        `INSERT OR IGNORE INTO messages
          (id, chat_jid, sender_jid, sender_pn, sender_name, from_me, at, kind, text,
           quoted_id, quoted_text, media_mime, reaction_to, options_json, stored_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        rec.id, rec.chat_jid, rec.sender_jid, rec.sender_pn, rec.sender_name, rec.from_me ? 1 : 0,
        rec.at, rec.kind, rec.text, rec.quoted_id, rec.quoted_text, rec.media_mime,
        rec.reaction_to, rec.options?.length ? JSON.stringify(rec.options) : null, nowIso(),
      );
    return res.changes > 0 ? Number(res.lastInsertRowid) : null;
  }

  /** The oldest stored message of a chat: the anchor for asking the phone for older ones (TM-06). */
  oldestMessage(jid) {
    return this.db
      .prepare("SELECT id, from_me, sender_jid, at FROM messages WHERE chat_jid = ? ORDER BY at ASC, rowid ASC LIMIT 1")
      .get(jid);
  }

  /**
   * Messages still waiting for a transcript / translation (TM-07), newest
   * first: voice notes and audio with their file, and anything with text.
   * Only chats labelled team or customer -- personal and unlabelled chats are
   * never sent to Gemini.
   */
  pendingAi(limit = 20) {
    return this.db
      .prepare(
        `SELECT m.rowid AS n, m.kind, m.text, m.media_path, m.media_mime ${PENDING_AI}
         ORDER BY m.rowid DESC LIMIT ?`,
      )
      .all(limit);
  }

  /** Records the result; `null` fields mean nothing to add (e.g. already English). */
  setAi(n, { transcript = null, translation = null, language = null } = {}) {
    this.db
      .prepare("UPDATE messages SET transcript = ?, translation = ?, language = ?, ai_done = 1 WHERE rowid = ?")
      .run(transcript, translation, language, n);
  }

  failAi(n) {
    this.db.prepare("UPDATE messages SET ai_attempts = ai_attempts + 1 WHERE rowid = ?").run(n);
  }

  /** Gives messages that used up their attempts (e.g. while the model was misconfigured) another chance. */
  retryFailedAi() {
    return Number(this.db.prepare("UPDATE messages SET ai_attempts = 0 WHERE ai_done = 0 AND ai_attempts > 0").run().changes);
  }

  /** `kind`: what the call was for (empty = translating message `n`); `project` for a call tied to no message; `calls` when one row totals a CI run. */
  addAiUsage({ n = null, model = null, input_tokens = 0, output_tokens = 0, usd = 0, inr = 0, kind = null, project = null, calls = 1 }) {
    this.db
      .prepare("INSERT INTO ai_usage (at, n, model, input_tokens, output_tokens, usd, inr, kind, project, calls) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .run(nowIso(), n, model, input_tokens, output_tokens, usd, inr, kind, project, calls);
  }

  aiUsageRows(select, tail, since, project, until) {
    const params = [since, ...(until ? [until] : []), ...(project ? [project] : [])];
    return this.db
      .prepare(
        `SELECT ${select}, COALESCE(SUM(COALESCE(u.calls, 1)), 0) AS calls, COALESCE(SUM(u.input_tokens), 0) AS input_tokens, COALESCE(SUM(u.output_tokens), 0) AS output_tokens,
                COALESCE(SUM(u.usd), 0) AS usd, COALESCE(SUM(u.inr), 0) AS inr
         FROM ai_usage u LEFT JOIN messages m ON m.rowid = u.n LEFT JOIN chats c ON c.jid = m.chat_jid
         WHERE u.at >= ? ${until ? "AND u.at < ?" : ""} ${project ? "AND COALESCE(u.project, c.project) = ?" : ""} ${tail}`,
      )
      .all(...params);
  }

  /** Gemini spend in [since, until), optionally only for one project. */
  aiUsageSince(since, project, until) {
    return this.aiUsageRows("1 AS scope", "", since, project, until)[0];
  }

  /** The same per kind of work, most expensive first. */
  aiUsageByKind(since, project, until) {
    return this.aiUsageRows("COALESCE(u.kind, 'translate') AS kind", "GROUP BY 1 ORDER BY inr DESC", since, project, until);
  }

  countPendingAi() {
    return this.db.prepare(`SELECT COUNT(*) AS n ${PENDING_AI}`).get().n;
  }

  setMediaPath(n, path) {
    this.db.prepare("UPDATE messages SET media_path = ? WHERE rowid = ?").run(path, n);
  }

  /** With `project`: that project's chats plus untagged ones (so new groups can be labelled). */
  listChats({ project } = {}) {
    return this.db
      .prepare(
        `SELECT c.jid, c.name, c.is_group, c.role, c.project, c.first_seen,
                COUNT(m.rowid) AS messages, MAX(m.at) AS last_message_at
         FROM chats c LEFT JOIN messages m ON m.chat_jid = c.jid
         ${project ? "WHERE c.project = ? OR c.project IS NULL" : ""}
         GROUP BY c.jid ORDER BY last_message_at DESC NULLS LAST`,
      )
      .all(...(project ? [project] : []));
  }

  /**
   * Newest first. `chat` matches a jid exactly or a chat name by substring;
   * `q` is space-separated words that must all appear (case-insensitive) in
   * the text, the quoted text, or the sender's name. Chats labelled "ignore"
   * are left out unless asked for by jid. `project` keeps only that project's
   * chats -- untagged chats are left out, since they may belong to another.
   */
  findMessages({ chat, role, project, q, since, until, sender, limit = 50, before } = {}) {
    const where = [];
    const params = [];
    if (project) {
      where.push("c.project = ?");
      params.push(project);
    }
    if (chat) {
      where.push("(m.chat_jid = ? OR c.name LIKE ?)");
      params.push(chat, `%${chat}%`);
    } else {
      where.push("c.role != 'ignore'");
    }
    if (role) {
      where.push("c.role = ?");
      params.push(role);
    }
    for (const word of (q || "").split(/\s+/).filter(Boolean)) {
      where.push("(m.text LIKE ? OR m.quoted_text LIKE ? OR m.sender_name LIKE ? OR m.transcript LIKE ? OR m.translation LIKE ?)");
      params.push(...Array(5).fill(`%${word}%`));
    }
    if (since) {
      where.push("m.at >= ?");
      params.push(since);
    }
    if (until) {
      where.push("m.at < ?");
      params.push(until);
    }
    if (sender) {
      where.push("(m.sender_name LIKE ? OR m.sender_pn LIKE ? OR m.sender_jid LIKE ?)");
      params.push(`%${sender}%`, `%${sender}%`, `%${sender}%`);
    }
    if (before) {
      where.push("m.rowid < ?");
      params.push(Number(before));
    }
    params.push(Math.min(Math.max(Number(limit) || 50, 1), 500));
    return this.db
      .prepare(
        `SELECT ${MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.jid = m.chat_jid
         ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
         ORDER BY m.at DESC, m.rowid DESC LIMIT ?`,
      )
      .all(...params)
      .map(withOptions);
  }

  getMessage(n) {
    const row = this.db
      .prepare(`SELECT ${MESSAGE_COLUMNS}, m.media_path FROM messages m JOIN chats c ON c.jid = m.chat_jid WHERE m.rowid = ?`)
      .get(Number(n));
    return withOptions(row);
  }

  /** The message plus `around` messages either side in the same chat, oldest first. */
  getContext(n, around = 10) {
    const msg = this.getMessage(n);
    if (!msg) return null;
    const before = this.db
      .prepare(
        `SELECT ${MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.jid = m.chat_jid
         WHERE m.chat_jid = ? AND (m.at < ? OR (m.at = ? AND m.rowid < ?))
         ORDER BY m.at DESC, m.rowid DESC LIMIT ?`,
      )
      .all(msg.chat_jid, msg.at, msg.at, msg.n, around)
      .map(withOptions)
      .reverse();
    const after = this.db
      .prepare(
        `SELECT ${MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.jid = m.chat_jid
         WHERE m.chat_jid = ? AND (m.at > ? OR (m.at = ? AND m.rowid > ?))
         ORDER BY m.at ASC, m.rowid ASC LIMIT ?`,
      )
      .all(msg.chat_jid, msg.at, msg.at, msg.n, around)
      .map(withOptions);
    delete msg.media_path;
    return { message: msg, thread: [...before, msg, ...after] };
  }

  /** Logs a request from a group (TM-08). `source`: message numbers, e.g. "6,7". */
  addItem({ chat_jid, type, title, summary = null, source = null, created_by = null, asked_by = null, asked_ref = null, asked_who = null }) {
    if (!ITEM_TYPES.includes(type)) throw new Error(`type must be one of ${ITEM_TYPES.join(", ")}`);
    if (!String(title || "").trim()) throw new Error("title is required");
    const now = nowIso();
    const res = this.db
      .prepare(
        `INSERT INTO items (chat_jid, type, title, summary, source, created_by, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(chat_jid, type, String(title).trim(), summary, source, created_by, now, now);
    const id = Number(res.lastInsertRowid);
    this.db.prepare("UPDATE items SET asked_by = ?, asked_ref = ?, asked_who = ? WHERE id = ?").run(clip(asked_by, 200), clip(asked_ref, 1000), clip(asked_who, 64), id);
    this.db.prepare("INSERT INTO item_log (item_id, at, status, note) VALUES (?, ?, 'open', ?)").run(id, now, asked_by ? `logged; asked by ${clip(asked_by, 200)}` : "logged");
    return id;
  }

  /** Changes status / details; every change is kept in the item's log. */
  /**
   * TM-50 (3 Nov: the team bot and a Claude Code session fixed the same thing twice, [206] / WA-151 and [208] / TM-48):
   * one worker per request. Returns { ok: true, item } when `by` now holds it (or already did), or { ok: false, by, at }
   * naming who does. A finished request, a claim older than CLAIM_HOURS, or `take` frees it.
   */
  claimItem(id, by, { take = false } = {}) {
    const item = this.getItem(id);
    if (!item) return null;
    const holder = item.claimed_by;
    const fresh = item.claimed_at && Date.now() - Date.parse(item.claimed_at) < CLAIM_HOURS * 3600_000;
    const open = item.status === "open" || item.status === "in_progress";
    if (holder && holder !== by && fresh && open && !take) return { ok: false, by: holder, at: item.claimed_at };
    if (holder === by && fresh) return { ok: true, item };
    return { ok: true, item: this.updateItem(id, { claimed_by: by, claimed_at: nowIso(), note: holder && holder !== by ? `claimed by ${by} (was ${holder})` : `claimed by ${by}` }) };
  }

  updateItem(id, { status, ref = null, note = null, title, summary, type, ...tracking } = {}) {
    const item = this.getItem(id);
    if (!item) return null;
    if (status !== undefined && !ITEM_STATUSES.includes(status)) throw new Error(`status must be one of ${ITEM_STATUSES.join(", ")}`);
    if (type !== undefined && !ITEM_TYPES.includes(type)) throw new Error(`type must be one of ${ITEM_TYPES.join(", ")}`);
    const now = nowIso();
    this.db
      .prepare("UPDATE items SET status = ?, type = ?, title = ?, summary = ?, done_ref = ?, updated_at = ? WHERE id = ?")
      .run(
        status ?? item.status, type ?? item.type, title ?? item.title, summary ?? item.summary,
        ref ? (item.done_ref ? `${item.done_ref}, ${ref}` : ref) : item.done_ref, now, id,
      );
    if (tracking.verified !== undefined && tracking.verified !== null && !VERIFIED.includes(tracking.verified)) {
      throw new Error(`verified must be one of ${VERIFIED.join(", ")}`);
    }
    // TM-19 fields: a value sets it, null clears it, absent leaves it. Starting work clears "held".
    const set = Object.entries(tracking).filter(([k, v]) => ITEM_TRACKING.includes(k) && v !== undefined);
    if (status === "in_progress" && !set.some(([k]) => k === "held")) set.push(["held", null]);
    if (tracking.verified && tracking.verified_at === undefined) set.push(["verified_at", now]);
    for (const [k, v] of set) this.db.prepare(`UPDATE items SET ${k} = ? WHERE id = ?`).run(v === null ? null : clip(v, 1000), id);
    const what = set.filter(([k, v]) => v !== null && k !== "asked_who").map(([k, v]) => `${k}=${clip(v, 80)}`).join(", ");
    this.db.prepare("INSERT INTO item_log (item_id, at, status, ref, note) VALUES (?, ?, ?, ?, ?)").run(id, now, status ?? null, ref, [note, what].filter(Boolean).join(" · ") || null);
    return this.getItem(id);
  }

  /**
   * TM-79: add one turn's (or one session's) Claude usage to a request. Numbers outside sane bounds are dropped, not
   * stored (a cost of $10,000 or 300% of a window is a bug in the sender). Returns false for an unknown request.
   */
  addItemUsage(id, { account = null, by = null, cost_usd = null, tokens = null, pct_5h = null, pct_7d = null } = {}) {
    if (!this.db.prepare("SELECT 1 FROM items WHERE id = ?").get(Number(id))) return false;
    const row = { cost: num(cost_usd, 0, 1000), tokens: num(tokens, 0, 1e9), p5: num(pct_5h, 0, 100), p7: num(pct_7d, 0, 100) };
    if (row.cost === null && row.tokens === null && row.p5 === null && row.p7 === null) throw new Error("usage needs cost_usd, tokens, pct_5h or pct_7d");
    this.db
      .prepare("INSERT INTO item_usage (item_id, at, account, by, cost_usd, tokens, pct_5h, pct_7d) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
      .run(Number(id), nowIso(), clip(account, 60), clip(by, 120), row.cost, row.tokens === null ? null : Math.round(row.tokens), row.p5, row.p7);
    return true;
  }

  /** TM-78: the brain's latest reading of every Claude account (label, plan windows, limited-until). */
  setClaudeAccounts(list) {
    const now = nowIso();
    const put = this.db.prepare("INSERT INTO claude_accounts (id, json, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at");
    for (const a of list) {
      const id = String(a?.id || "").toLowerCase();
      if (!/^[a-z0-9]{1,8}$/.test(id)) continue;
      put.run(id, JSON.stringify({ ...a, id }).slice(0, 4000), now);
    }
  }

  claudeAccounts() {
    return this.db
      .prepare("SELECT json, updated_at FROM claude_accounts ORDER BY id")
      .all()
      .map((r) => ({ ...JSON.parse(r.json), seen_at: r.updated_at }));
  }

  /** getItem with its stage (TM-19). */
  getItem(id) {
    const item = this.db
      .prepare(`SELECT i.*, c.name AS chat_name, c.project AS project, ${USAGE_COLUMNS} FROM items i JOIN chats c ON c.jid = i.chat_jid ${USAGE_JOIN} WHERE i.id = ?`)
      .get(Number(id));
    if (item) {
      item.log = this.db.prepare("SELECT at, status, ref, note FROM item_log WHERE item_id = ? ORDER BY at, rowid").all(item.id);
      item.stage = itemStage(item);
    }
    return item;
  }

  /** Newest first. `chat` matches a jid or a name substring; `project` keeps to that project's chats. */
  listItems({ chat, project, status, type } = {}) {
    const where = [];
    const params = [];
    if (chat) {
      where.push("(i.chat_jid = ? OR c.name LIKE ?)");
      params.push(chat, `%${chat}%`);
    }
    for (const [col, val] of [["c.project", project], ["i.status", status], ["i.type", type]]) {
      if (val) {
        where.push(`${col} = ?`);
        params.push(val);
      }
    }
    return this.db
      .prepare(
        `SELECT i.id, i.chat_jid, c.name AS chat_name, c.project, i.type, i.title, i.summary, i.source,
                i.status, i.done_ref, i.created_by, i.created_at, i.updated_at, ${ITEM_TRACKING.map((k) => `i.${k}`).join(", ")}, ${USAGE_COLUMNS}
         FROM items i JOIN chats c ON c.jid = i.chat_jid ${USAGE_JOIN}
         ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
         ORDER BY i.updated_at DESC, i.id DESC`,
      )
      .all(...params)
      .map((i) => ({ ...i, stage: itemStage(i) }));
  }

  /**
   * TM-19 "@bot requests [open|done|all|<stage>]": counts by stage, then a numbered list, newest first (at most 25).
   * Plain code, no AI. `open` = not live yet; `done` = live, verified or broken.
   */
  requestsText(project, filter = "") {
    const all = this.listItems({ project });
    const f = String(filter || "").trim().toLowerCase();
    const counts = Object.fromEntries(Object.keys(STAGES).map((k) => [k, 0]));
    for (const i of all) counts[i.stage] += 1;
    const pick = {
      open: (i) => ["asked", "waiting", "building"].includes(i.stage),
      done: (i) => ["live", "verified", "broken"].includes(i.stage),
      users: (i) => Boolean(i.asked_by),
    }[f] || (STAGES[f] ? (i) => i.stage === f : () => true);
    const list = all.filter(pick);
    const head = `📋 *Requests · ${project}* (${all.length})\n` +
      Object.entries(STAGES).filter(([k]) => counts[k]).map(([k, label]) => `${label} ${counts[k]}`).join(" · ");
    if (!list.length) return `${head}\n\nNothing ${f ? `"${f}" ` : ""}to list.`;
    const day = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
    const lines = list.slice(0, 25).map((i, n) => {
      const who = i.asked_by ? `asked by ${i.asked_by}` : `from ${i.created_by || i.chat_name}`;
      const extra = [i.held && i.stage === "waiting" ? `held: ${i.held}` : null, i.done_ref ? `commit ${i.done_ref}` : null, i.tried_at ? "they used it after ✓" : null]
        .filter(Boolean).join(" · ");
      return `${n + 1}. [${i.id}] ${i.title} · ${STAGES[i.stage]}\n    ${who} · ${day(i.created_at)}${extra ? ` · ${extra}` : ""}`;
    });
    const more = list.length > 25 ? `\n…and ${list.length - 25} more (the control panel's Requests page has them all).` : "";
    return `${head}\n\n${lines.join("\n")}${more}\n\n@bot requests open | done | users | all`;
  }

  /** The active approval matching any of these ids (jid or phone-number jid), or null. Project "*" = every project. */
  findPerson(project, ids) {
    const list = [...new Set(ids.filter(Boolean))];
    if (!project || !list.length) return null;
    const marks = list.map(() => "?").join(", ");
    return (
      this.db
        .prepare(
          `SELECT * FROM people WHERE project IN (?, '*') AND removed_at IS NULL AND (jid IN (${marks}) OR pn IN (${marks}))
           ORDER BY role = 'owner' DESC, project = '*' LIMIT 1`,
        )
        .get(project, ...list, ...list) || null
    );
  }

  /** Every project these ids are approved for ('*' = all of them), with the best role for each. */
  personProjects(ids) {
    const list = [...new Set(ids.filter(Boolean))];
    if (!list.length) return [];
    const marks = list.map(() => "?").join(", ");
    return this.db
      .prepare(
        `SELECT project, MAX(role = 'owner') AS owner FROM people
         WHERE removed_at IS NULL AND (jid IN (${marks}) OR pn IN (${marks})) GROUP BY project`,
      )
      .all(...list, ...list)
      .map((r) => ({ project: r.project, role: r.owner ? "owner" : "member" }));
  }

  /** Every project that has a team chat: the ones a person can be asked to choose between. */
  teamProjects() {
    return this.db.prepare("SELECT DISTINCT project FROM chats WHERE role = 'team' AND project IS NOT NULL ORDER BY project").all().map((r) => r.project);
  }

  /** A 1-on-1 chat's remembered project, without changing its role. */
  setChatProject(jid, project) {
    if (project != null && !PROJECT_RE.test(project)) throw new Error("project must be a lowercase slug");
    return this.db.prepare("UPDATE chats SET project = ?, updated_at = ? WHERE jid = ?").run(project, nowIso(), jid).changes > 0;
  }

  /** The ids a 1-on-1 chat's other person is known by: the chat jid and any phone number seen in it. */
  chatIdentities(jid) {
    const pns = this.db.prepare("SELECT DISTINCT sender_pn FROM messages WHERE chat_jid = ? AND from_me = 0 AND sender_pn IS NOT NULL").all(jid);
    return [jid, ...pns.map((r) => r.sender_pn)];
  }

  /** The chat labelled assistant-test for a project, or null. */
  assistantTestChat(project) {
    return this.db.prepare("SELECT jid, name FROM chats WHERE project = ? AND role = 'assistant-test' ORDER BY updated_at DESC LIMIT 1").get(project) || null;
  }

  /** Approves someone for a project (or changes their role). Returns the row. */
  allowPerson({ project, jid = null, pn = null, name = null, role = "member", added_by = null }) {
    if (project !== "*" && !PROJECT_RE.test(project || "")) throw new Error('project must be a lowercase slug, e.g. mercon, or "*" for all');
    if (!PEOPLE_ROLES.includes(role)) throw new Error(`role must be one of ${PEOPLE_ROLES.join(", ")}`);
    if (!jid && !pn) throw new Error("a phone number or WhatsApp id is required");
    const existing = this.findPerson(project, [jid, pn]);
    const now = nowIso();
    // An all-projects approval already covers this one: don't add a narrower duplicate.
    if (existing?.project === "*" && project !== "*" && existing.role === "owner") return existing;
    if (existing) {
      this.db
        .prepare("UPDATE people SET role = ?, name = COALESCE(?, name), jid = COALESCE(jid, ?), pn = COALESCE(pn, ?) WHERE id = ?")
        .run(role, name, jid, pn, existing.id);
      return this.db.prepare("SELECT * FROM people WHERE id = ?").get(existing.id);
    }
    const res = this.db
      .prepare("INSERT INTO people (project, jid, pn, name, role, added_by, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
      .run(project, jid, pn, name, role, added_by, now);
    return this.db.prepare("SELECT * FROM people WHERE id = ?").get(Number(res.lastInsertRowid));
  }

  /** Removes an approval (kept, marked removed, for the record). */
  removePerson(project, ids, removed_by = null) {
    const person = this.findPerson(project, ids);
    // An all-projects approval can only be removed at that level (from the server), not from one project's group.
    if (!person || (person.project === "*" && project !== "*")) return null;
    this.db.prepare("UPDATE people SET removed_at = ?, removed_by = ? WHERE id = ?").run(nowIso(), removed_by, person.id);
    return person;
  }

  listPeople(project) {
    return this.db
      .prepare(
        `SELECT project, jid, pn, name, role, added_by, added_at FROM people
         WHERE removed_at IS NULL ${project ? "AND project IN (?, '*')" : ""} ORDER BY project, role = 'owner' DESC, added_at`,
      )
      .all(...(project ? [project] : []));
  }

  /** The chat labelled team for a project (where the bot may reply), or null. */
  teamChat(project) {
    return this.db.prepare("SELECT jid, name FROM chats WHERE project = ? AND role = 'team' ORDER BY updated_at DESC LIMIT 1").get(project) || null;
  }

  /** Our stored number for a message id in a chat (to find what a reply quotes). */
  messageNumber(chat_jid, id) {
    return this.db.prepare("SELECT rowid AS n FROM messages WHERE chat_jid = ? AND id = ?").get(chat_jid, id)?.n ?? null;
  }

  /** Whether a message in a chat was sent by the linked number itself (the bot). */
  isOwnMessage(chat_jid, id) {
    return this.db.prepare("SELECT from_me FROM messages WHERE chat_jid = ? AND id = ?").get(chat_jid, id)?.from_me === 1;
  }

  stats() {
    const row = this.db.prepare("SELECT COUNT(*) AS messages, MAX(at) AS last_message_at FROM messages").get();
    const chats = this.db.prepare("SELECT COUNT(*) AS n FROM chats").get().n;
    return { ...row, chats };
  }
}
