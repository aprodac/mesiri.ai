// The inbox: every chat the linked number is in, and every message seen.
// SQLite via node:sqlite (built into Node >= 22.13), so the folder carries no
// native build step and moves to another project as-is.

import { DatabaseSync } from "node:sqlite";

export const ROLES = ["unlabelled", "team", "customer", "ignore"];
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
CREATE TABLE IF NOT EXISTS item_log (
  item_id  INTEGER NOT NULL REFERENCES items(id),
  at       TEXT NOT NULL,
  status   TEXT,
  ref      TEXT,
  note     TEXT
);
`;
export const ITEM_TYPES = ["bug", "feature", "question", "complaint", "task"];
export const ITEM_STATUSES = ["open", "in_progress", "done", "wont_do"];
export const PEOPLE_ROLES = ["owner", "member"];

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
  m.reaction_to, m.transcript, m.translation, m.language`;

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
    ]) {
      if (!mcols.includes(name)) this.db.exec(`ALTER TABLE messages ADD COLUMN ${name} ${type}`);
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
    const exact = this.db.prepare("SELECT jid, name, role, project FROM chats WHERE jid = ?").get(jidOrName);
    if (exact) return exact;
    const hits = this.db.prepare("SELECT jid, name, role, project FROM chats WHERE name LIKE ?").all(`%${jidOrName}%`);
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
           quoted_id, quoted_text, media_mime, reaction_to, stored_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        rec.id, rec.chat_jid, rec.sender_jid, rec.sender_pn, rec.sender_name, rec.from_me ? 1 : 0,
        rec.at, rec.kind, rec.text, rec.quoted_id, rec.quoted_text, rec.media_mime,
        rec.reaction_to, nowIso(),
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
      .all(...params);
  }

  getMessage(n) {
    return this.db
      .prepare(`SELECT ${MESSAGE_COLUMNS}, m.media_path FROM messages m JOIN chats c ON c.jid = m.chat_jid WHERE m.rowid = ?`)
      .get(Number(n));
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
      .reverse();
    const after = this.db
      .prepare(
        `SELECT ${MESSAGE_COLUMNS} FROM messages m JOIN chats c ON c.jid = m.chat_jid
         WHERE m.chat_jid = ? AND (m.at > ? OR (m.at = ? AND m.rowid > ?))
         ORDER BY m.at ASC, m.rowid ASC LIMIT ?`,
      )
      .all(msg.chat_jid, msg.at, msg.at, msg.n, around);
    delete msg.media_path;
    return { message: msg, thread: [...before, msg, ...after] };
  }

  /** Logs a request from a group (TM-08). `source`: message numbers, e.g. "6,7". */
  addItem({ chat_jid, type, title, summary = null, source = null, created_by = null }) {
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
    this.db.prepare("INSERT INTO item_log (item_id, at, status, note) VALUES (?, ?, 'open', ?)").run(id, now, "logged");
    return id;
  }

  /** Changes status / details; every change is kept in the item's log. */
  updateItem(id, { status, ref = null, note = null, title, summary, type } = {}) {
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
    this.db.prepare("INSERT INTO item_log (item_id, at, status, ref, note) VALUES (?, ?, ?, ?, ?)").run(id, now, status ?? null, ref, note);
    return this.getItem(id);
  }

  getItem(id) {
    const item = this.db
      .prepare("SELECT i.*, c.name AS chat_name, c.project AS project FROM items i JOIN chats c ON c.jid = i.chat_jid WHERE i.id = ?")
      .get(Number(id));
    if (item) item.log = this.db.prepare("SELECT at, status, ref, note FROM item_log WHERE item_id = ? ORDER BY at, rowid").all(item.id);
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
                i.status, i.done_ref, i.created_at, i.updated_at
         FROM items i JOIN chats c ON c.jid = i.chat_jid
         ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
         ORDER BY i.updated_at DESC, i.id DESC`,
      )
      .all(...params);
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
