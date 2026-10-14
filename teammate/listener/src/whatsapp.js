// The linked-device connection to the spare WhatsApp number.
//
// It records everything it sees. The only thing it ever sends is a message
// through send() (TM-04), which the API allows only into chats labelled
// "team" -- never a customer group, a reaction, a read receipt or presence.

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  Browsers,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  makeWASocket,
  normalizeMessageContent,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import pino from "pino";
import { MEDIA_KINDS, normalizeMessage } from "./normalize.js";

const MAX_MEDIA_BYTES = 25 * 1024 * 1024;
const EXT_BY_MIME = {
  "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "video/mp4": "mp4",
  "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "application/pdf": "pdf",
};

function extFor(mime) {
  const base = (mime || "").split(";")[0].trim();
  return EXT_BY_MIME[base] || base.split("/")[1]?.replace(/[^a-z0-9]/gi, "") || "bin";
}

export class WhatsAppListener {
  /** @param {{ store: import('./store.js').Store, dataDir: string, log?: (msg: string) => void }} opts */
  constructor({ store, dataDir, log = console.log }) {
    this.store = store;
    this.authDir = join(dataDir, "auth");
    this.mediaDir = join(dataDir, "media");
    mkdirSync(this.mediaDir, { recursive: true });
    this.log = log;
    this.sock = null;
    this.state = "starting";
    this.registered = false;
    this.lastEventAt = null;
    this.retryDelayMs = 2_000;
    this.saving = Promise.resolve();
    this.waVersion = undefined;
    this.namesTried = new Set();
    this.waLogger = pino({ level: process.env.TEAMMATE_WA_LOG_LEVEL || "warn" });
  }

  status() {
    return {
      state: this.state,
      linked_as: this.sock?.user?.id?.split(":")[0]?.split("@")[0] || null,
      last_event_at: this.lastEventAt,
    };
  }

  async start() {
    const { state, saveCreds } = await useMultiFileAuthState(this.authDir);
    this.registered = Boolean(state.creds.registered);
    // An outdated client version makes WhatsApp refuse to link ("Something went
    // wrong"); ask for the current one once, fall back to Baileys' built-in.
    if (this.waVersion === undefined) {
      const { version, error } = await fetchLatestBaileysVersion().catch((e) => ({ error: e }));
      this.waVersion = error ? null : version;
      this.log(`WhatsApp client version: ${this.waVersion ? this.waVersion.join(".") : "built-in (lookup failed)"}`);
    }
    const sock = makeWASocket({
      ...(this.waVersion ? { version: this.waVersion } : {}),
      auth: state,
      logger: this.waLogger,
      browser: Browsers.macOS("Chrome"),
      markOnlineOnConnect: false, // keep the phone getting notifications; never look "online"
      syncFullHistory: false,
      shouldIgnoreJid: (jid) => jid === "status@broadcast" || jid?.endsWith("@newsletter"),
    });
    this.sock = sock;
    this.state = this.registered ? "connecting" : "waiting_for_pairing";
    this.pairingReady = false;

    // Writes are chained so a restart can wait for the last one (see onConnectionUpdate).
    sock.ev.on("creds.update", () => {
      this.saving = this.saving.then(saveCreds).catch((e) => this.log(`saving the session failed: ${e}`));
    });
    sock.ev.on("connection.update", (u) => this.onConnectionUpdate(u));
    sock.ev.on("messages.upsert", ({ messages }) => {
      for (const msg of messages) this.record(msg, { downloadMedia: true }).catch((e) => this.log(`record failed: ${e}`));
    });
    sock.ev.on("messaging-history.set", ({ messages = [] }) => {
      for (const msg of messages) this.record(msg, { downloadMedia: false }).catch(() => {});
    });
    sock.ev.on("groups.upsert", (groups) => groups.forEach((g) => this.saveGroup(g)));
    sock.ev.on("groups.update", (groups) => groups.forEach((g) => g.id && g.subject && this.saveGroup(g)));
  }

  saveGroup(g) {
    this.store.upsertChat({ jid: g.id, name: g.subject || null, is_group: true });
  }

  async onConnectionUpdate({ connection, lastDisconnect, qr }) {
    if (qr && !this.pairingReady) {
      this.pairingReady = true;
      this.log("reached WhatsApp; ready to link -- run `inbox.py pair <phone>`");
    }
    if (connection === "open") {
      this.state = "connected";
      this.registered = true;
      this.retryDelayMs = 2_000;
      this.log(`connected as ${this.status().linked_as}`);
      try {
        const groups = await this.sock.groupFetchAllParticipating();
        Object.values(groups).forEach((g) => this.saveGroup(g));
      } catch (e) {
        this.log(`group list failed: ${e}`);
      }
      return;
    }
    if (connection !== "close") return;

    const code = lastDisconnect?.error?.output?.statusCode;
    this.log(`connection closed: ${code ?? "no code"} ${lastDisconnect?.error?.message || ""}`.trim());
    // Linking ends with WhatsApp asking for a restart. Reconnecting before the new
    // session is on disk logs in with a half-written one, which WhatsApp answers
    // with "logged out" -- so always let pending writes finish first.
    await this.saving;
    if (code === DisconnectReason.loggedOut) {
      // Unlinked from the phone (or banned). Forget the session so the number
      // can be linked again with POST /pair.
      this.log("logged out by WhatsApp -- clearing session; link again with `inbox.py pair`");
      this.state = "logged_out";
      rmSync(this.authDir, { recursive: true, force: true });
      this.registered = false;
    } else {
      this.state = this.registered ? "connecting" : "waiting_for_pairing";
    }
    const delay = code === DisconnectReason.restartRequired ? 0 : this.retryDelayMs;
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, 60_000);
    setTimeout(() => this.start().catch((e) => this.log(`restart failed: ${e}`)), delay);
  }

  async requestPairingCode(phone) {
    if (this.registered) throw new Error("already linked; unlink it from the phone first to link another number");
    if (!this.sock || !this.pairingReady) throw new Error("not connected to WhatsApp yet, try again in a few seconds");
    return this.sock.requestPairingCode(phone);
  }

  /** Sends text, or an image with an optional caption. Callers check the chat is a team chat. */
  async send(jid, { text = null, image = null, caption = null } = {}) {
    if (this.state !== "connected" || !this.sock) throw new Error(`WhatsApp is ${this.state}, not connected`);
    const content = image ? { image, caption: caption || undefined } : { text };
    const sent = await this.sock.sendMessage(jid, content);
    return sent?.key?.id || null;
  }

  async record(msg, { downloadMedia }) {
    const rec = normalizeMessage(msg);
    if (!rec) return;
    this.lastEventAt = new Date().toISOString();

    if (!rec.is_group && !rec.from_me && rec.sender_name) {
      this.store.upsertChat({ jid: rec.chat_jid, name: rec.sender_name, is_group: false });
    }
    const n = this.store.addMessage(rec);
    if (n === null) return; // seen before

    if (rec.is_group && !this.store.hasChatName(rec.chat_jid) && !this.namesTried.has(rec.chat_jid)) {
      this.namesTried.add(rec.chat_jid);
      this.sock?.groupMetadata(rec.chat_jid).then((g) => this.saveGroup(g)).catch(() => {});
    }

    const mediaKind = rec.kind === "voice" ? "audio" : rec.kind;
    if (downloadMedia && MEDIA_KINDS.has(mediaKind)) {
      const content = normalizeMessageContent(msg.message) || {};
      const inner = Object.values(content).find((v) => v && typeof v === "object" && "mimetype" in v);
      const size = Number(inner?.fileLength?.toString?.() ?? inner?.fileLength ?? 0);
      if (size > MAX_MEDIA_BYTES) return;
      try {
        const buf = await downloadMediaMessage(msg, "buffer", {}, {
          logger: this.waLogger,
          reuploadRequest: this.sock.updateMediaMessage,
        });
        const path = join(this.mediaDir, `${n}.${extFor(rec.media_mime)}`);
        writeFileSync(path, buf);
        this.store.setMediaPath(n, path);
      } catch (e) {
        this.log(`media download failed for message ${n}: ${e}`);
      }
    }
  }
}
