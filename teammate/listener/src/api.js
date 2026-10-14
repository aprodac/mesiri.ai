// Read-only inbox API for Claude Code sessions (and anything else with the token).
// Plain node:http -- the surface is small and the folder stays dependency-light.
//
//   GET  /health                      no auth: up + state; with token: linked number, counts
//   GET  /chats?project=              every chat with role, project and counts
//   POST /chats/role   {jid, role, project?}
//                                     label a chat team | customer | ignore, and its project
//   GET  /messages?chat=&role=&project=&q=&since=&until=&sender=&limit=&before=
//   GET  /messages/:n?project=        one message with its surrounding thread
//   GET  /media/:n?project=           the downloaded file for a media message
//   POST /pair         {phone}        start linking the spare number; returns the code
//   POST /send         {chat, project?, text?, image_base64?, caption?}
//                                     post into a chat labelled "team" -- refused anywhere else
//
// Every route except /health needs `Authorization: Bearer <TEAMMATE_API_TOKEN>`.
// `project` (TM-05) scopes a call to one repo's groups; without it, all are visible.

import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { timingSafeEqual } from "node:crypto";

function send(res, status, body) {
  const json = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(json);
}

function authorized(req, token) {
  const header = req.headers.authorization || "";
  const given = Buffer.from(header.startsWith("Bearer ") ? header.slice(7) : "");
  const expected = Buffer.from(token);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

async function readJson(req, maxBytes = 10_000) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > maxBytes) throw new Error("body too large");
  }
  return raw ? JSON.parse(raw) : {};
}

// Posting limits: an image up to 5 MB (WhatsApp's own image limit), text up to
// 4,000 characters, and at most SEND_PER_HOUR posts per hour, so a runaway
// session can't flood the group or get the number flagged.
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_TEXT_CHARS = 4000;
const SEND_PER_HOUR = Number(process.env.TEAMMATE_SEND_PER_HOUR || 30);

/**
 * @param {{ store: import('./store.js').Store, wa: { status(): object, requestPairingCode(phone: string): Promise<string> }, token: string }} deps
 */
export function createApi({ store, wa, token }) {
  if (!token || token.length < 16) throw new Error("TEAMMATE_API_TOKEN must be at least 16 characters");
  const sentAt = [];

  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://local");
      // Served behind nginx at /teammate/ on some hosts; accept both.
      const path = url.pathname.replace(/^\/teammate(?=\/)/, "");

      if (req.method === "GET" && path === "/health") {
        // Public callers learn only whether it is up; the linked number and
        // counts need the token.
        if (!authorized(req, token)) return send(res, 200, { ok: true, state: wa.status().state });
        return send(res, 200, { ok: true, whatsapp: wa.status(), inbox: store.stats() });
      }
      if (!authorized(req, token)) return send(res, 401, { error: "unauthorized" });

      if (req.method === "GET" && path === "/chats") {
        return send(res, 200, { chats: store.listChats({ project: url.searchParams.get("project") || undefined }) });
      }
      if (req.method === "POST" && path === "/chats/role") {
        const { jid, role, project } = await readJson(req);
        try {
          return store.setRole(jid, role, project) ? send(res, 200, { ok: true }) : send(res, 404, { error: "unknown chat" });
        } catch (err) {
          return send(res, 400, { error: err.message });
        }
      }
      if (req.method === "GET" && path === "/messages") {
        const p = Object.fromEntries(url.searchParams);
        return send(res, 200, { messages: store.findMessages(p) });
      }
      // A message from another project's chat is reported as missing.
      const project = url.searchParams.get("project");
      const inProject = (msg) => msg && (!project || msg.chat_project === project);
      let m = path.match(/^\/messages\/(\d+)$/);
      if (req.method === "GET" && m) {
        const around = Number(url.searchParams.get("around") ?? 10);
        const ctx = store.getContext(m[1], Math.min(Math.max(around, 0), 100));
        return inProject(ctx?.message) ? send(res, 200, ctx) : send(res, 404, { error: "no such message" });
      }
      m = path.match(/^\/media\/(\d+)$/);
      if (req.method === "GET" && m) {
        const msg = store.getMessage(m[1]);
        if (!inProject(msg) || !msg.media_path || !existsSync(msg.media_path)) return send(res, 404, { error: "no media" });
        res.writeHead(200, { "content-type": msg.media_mime || "application/octet-stream" });
        return createReadStream(msg.media_path).pipe(res);
      }
      if (req.method === "POST" && path === "/pair") {
        const { phone } = await readJson(req);
        const digits = String(phone || "").replace(/\D/g, "");
        if (digits.length < 10) return send(res, 400, { error: "phone must include the country code, digits only" });
        try {
          const code = await wa.requestPairingCode(digits);
          return send(res, 200, {
            code,
            how: "On the spare phone: WhatsApp > Settings > Linked devices > Link a device > Link with phone number instead, then enter this code. It expires in a few minutes.",
          });
        } catch (err) {
          return send(res, 409, { error: err.message });
        }
      }
      if (req.method === "POST" && path === "/send") {
        const body = await readJson(req, Math.ceil(MAX_IMAGE_BYTES * 1.4) + 20_000);
        const chat = store.findChat(String(body.chat || ""));
        if (!chat) return send(res, 404, { error: "no such chat; use the jid or a unique part of the name" });
        if (chat.role !== "team") {
          return send(res, 403, { error: `refused: '${chat.name || chat.jid}' is labelled ${chat.role}; only team chats can be posted to` });
        }
        if (body.project && chat.project !== body.project) {
          return send(res, 403, { error: `refused: '${chat.name || chat.jid}' is not a ${body.project} chat` });
        }
        const text = body.text ? String(body.text) : null;
        const caption = body.caption ? String(body.caption) : null;
        const image = body.image_base64 ? Buffer.from(String(body.image_base64), "base64") : null;
        if (!text && !image) return send(res, 400, { error: "send text or image_base64" });
        if ((text?.length || 0) > MAX_TEXT_CHARS || (caption?.length || 0) > MAX_TEXT_CHARS) {
          return send(res, 400, { error: `text is limited to ${MAX_TEXT_CHARS} characters` });
        }
        if (image && image.length > MAX_IMAGE_BYTES) return send(res, 400, { error: "image is over 5 MB" });
        const hourAgo = Date.now() - 3_600_000;
        while (sentAt.length && sentAt[0] < hourAgo) sentAt.shift();
        if (sentAt.length >= SEND_PER_HOUR) return send(res, 429, { error: `limit of ${SEND_PER_HOUR} posts per hour reached` });
        try {
          const id = await wa.send(chat.jid, { text, image, caption });
          sentAt.push(Date.now());
          return send(res, 200, { ok: true, id, chat: chat.name || chat.jid });
        } catch (err) {
          return send(res, 503, { error: err.message });
        }
      }
      return send(res, 404, { error: "not found" });
    } catch (err) {
      if (err?.message === "body too large") return send(res, 413, { error: "request too large (images up to 5 MB)" });
      if (err instanceof SyntaxError) return send(res, 400, { error: "body is not valid JSON" });
      return send(res, 500, { error: String(err?.message || err) });
    }
  });
}
