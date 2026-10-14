// Read-only inbox API for Claude Code sessions (and anything else with the token).
// Plain node:http -- the surface is small and the folder stays dependency-light.
//
//   GET  /health                      no auth: up + state; with token: linked number, counts
//   GET  /chats                       every chat with role and counts
//   POST /chats/role   {jid, role}    label a chat team | customer | ignore
//   GET  /messages?chat=&role=&q=&since=&until=&sender=&limit=&before=
//   GET  /messages/:n                 one message with its surrounding thread
//   GET  /media/:n                    the downloaded file for a media message
//   POST /pair         {phone}        start linking the spare number; returns the code
//
// Every route except /health needs `Authorization: Bearer <TEAMMATE_API_TOKEN>`.

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

async function readJson(req) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 10_000) throw new Error("body too large");
  }
  return raw ? JSON.parse(raw) : {};
}

/**
 * @param {{ store: import('./store.js').Store, wa: { status(): object, requestPairingCode(phone: string): Promise<string> }, token: string }} deps
 */
export function createApi({ store, wa, token }) {
  if (!token || token.length < 16) throw new Error("TEAMMATE_API_TOKEN must be at least 16 characters");

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
        return send(res, 200, { chats: store.listChats() });
      }
      if (req.method === "POST" && path === "/chats/role") {
        const { jid, role } = await readJson(req);
        try {
          return store.setRole(jid, role) ? send(res, 200, { ok: true }) : send(res, 404, { error: "unknown chat" });
        } catch (err) {
          return send(res, 400, { error: err.message });
        }
      }
      if (req.method === "GET" && path === "/messages") {
        const p = Object.fromEntries(url.searchParams);
        return send(res, 200, { messages: store.findMessages(p) });
      }
      let m = path.match(/^\/messages\/(\d+)$/);
      if (req.method === "GET" && m) {
        const around = Number(url.searchParams.get("around") ?? 10);
        const ctx = store.getContext(m[1], Math.min(Math.max(around, 0), 100));
        return ctx ? send(res, 200, ctx) : send(res, 404, { error: "no such message" });
      }
      m = path.match(/^\/media\/(\d+)$/);
      if (req.method === "GET" && m) {
        const msg = store.getMessage(m[1]);
        if (!msg?.media_path || !existsSync(msg.media_path)) return send(res, 404, { error: "no media" });
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
      return send(res, 404, { error: "not found" });
    } catch (err) {
      return send(res, 500, { error: String(err?.message || err) });
    }
  });
}
