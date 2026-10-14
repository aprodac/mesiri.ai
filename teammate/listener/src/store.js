// The inbox: every chat the linked number is in, and every message seen.
// SQLite via node:sqlite (built into Node >= 22.13), so the folder carries no
// native build step and moves to another project as-is.

import { DatabaseSync } from "node:sqlite";

export const ROLES = ["unlabelled", "team", "customer", "ignore"];

const SCHEMA = `
CREATE TABLE IF NOT EXISTS chats (
  jid         TEXT PRIMARY KEY,
  name        TEXT,
  is_group    INTEGER NOT NULL,
  role        TEXT NOT NULL DEFAULT 'unlabelled',
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
  UNIQUE (chat_jid, id)
);
CREATE INDEX IF NOT EXISTS ix_messages_chat_at ON messages (chat_jid, at);
CREATE INDEX IF NOT EXISTS ix_messages_at ON messages (at);
`;

const nowIso = () => new Date().toISOString();

// What the API returns for a message: the internal rowid is the public,
// short, stable number people and sessions refer to ("message 1432").
const MESSAGE_COLUMNS = `
  m.rowid AS n, m.id, m.chat_jid, c.name AS chat_name, c.role AS chat_role,
  m.sender_jid, m.sender_pn, m.sender_name, m.from_me, m.at, m.kind, m.text,
  m.quoted_id, m.quoted_text, m.media_mime, (m.media_path IS NOT NULL) AS has_media,
  m.reaction_to`;

export class Store {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
    this.db.exec(SCHEMA);
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
    const exact = this.db.prepare("SELECT jid, name, role FROM chats WHERE jid = ?").get(jidOrName);
    if (exact) return exact;
    const hits = this.db.prepare("SELECT jid, name, role FROM chats WHERE name LIKE ?").all(`%${jidOrName}%`);
    return hits.length === 1 ? hits[0] : null;
  }

  setRole(jid, role) {
    if (!ROLES.includes(role)) throw new Error(`role must be one of ${ROLES.join(", ")}`);
    const res = this.db.prepare("UPDATE chats SET role = ?, updated_at = ? WHERE jid = ?").run(role, nowIso(), jid);
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

  setMediaPath(n, path) {
    this.db.prepare("UPDATE messages SET media_path = ? WHERE rowid = ?").run(path, n);
  }

  listChats() {
    return this.db
      .prepare(
        `SELECT c.jid, c.name, c.is_group, c.role, c.first_seen,
                COUNT(m.rowid) AS messages, MAX(m.at) AS last_message_at
         FROM chats c LEFT JOIN messages m ON m.chat_jid = c.jid
         GROUP BY c.jid ORDER BY last_message_at DESC NULLS LAST`,
      )
      .all();
  }

  /**
   * Newest first. `chat` matches a jid exactly or a chat name by substring;
   * `q` is space-separated words that must all appear (case-insensitive) in
   * the text, the quoted text, or the sender's name. Chats labelled "ignore"
   * are left out unless asked for by jid.
   */
  findMessages({ chat, role, q, since, until, sender, limit = 50, before } = {}) {
    const where = [];
    const params = [];
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
      where.push("(m.text LIKE ? OR m.quoted_text LIKE ? OR m.sender_name LIKE ?)");
      params.push(`%${word}%`, `%${word}%`, `%${word}%`);
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

  stats() {
    const row = this.db.prepare("SELECT COUNT(*) AS messages, MAX(at) AS last_message_at FROM messages").get();
    const chats = this.db.prepare("SELECT COUNT(*) AS n FROM chats").get().n;
    return { ...row, chats };
  }
}
