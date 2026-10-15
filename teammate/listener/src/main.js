// Entry point: open the inbox, connect to WhatsApp, serve the API.
//
// Environment:
//   TEAMMATE_API_TOKEN   required, >= 16 chars; the Bearer token for the API
//   TEAMMATE_DATA_DIR    default ./data  (inbox.db, auth/ session, media/)
//   TEAMMATE_HOST        default 127.0.0.1 (put nginx in front, never expose directly)
//   TEAMMATE_PORT        default 8790
//   TEAMMATE_GEMINI_API_KEY  optional; turns on voice-note transcripts and English
//                            translations (TM-07)
//   TEAMMATE_GEMINI_MODEL    default gemini-3.8-flash
//   TEAMMATE_BRAIN_URL       optional, e.g. http://127.0.0.1:8791: approved tags go to Claude Code (TM-03b)

import { mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createApi } from "./api.js";
import { Store } from "./store.js";
import { AiWorker, Transcriber } from "./transcribe.js";
import { Bot } from "./bot.js";
import { WhatsAppListener } from "./whatsapp.js";

const dataDir = resolve(process.env.TEAMMATE_DATA_DIR || "./data");
const host = process.env.TEAMMATE_HOST || "127.0.0.1";
const port = Number(process.env.TEAMMATE_PORT || 8790);
const log = (msg) => console.log(`[teammate] ${msg}`);

mkdirSync(dataDir, { recursive: true });
const store = new Store(join(dataDir, "inbox.db"));
const wa = new WhatsAppListener({ store, dataDir, log });
const geminiKey = process.env.TEAMMATE_GEMINI_API_KEY;
const transcriber = geminiKey ? new Transcriber({ apiKey: geminiKey, model: process.env.TEAMMATE_GEMINI_MODEL || undefined }) : null;
const ai = new AiWorker({ store, transcriber, readFile: (p) => readFileSync(p), log });
wa.onStored = () => ai.kick();
const brainUrl = process.env.TEAMMATE_BRAIN_URL?.replace(/\/$/, "");
const brain = brainUrl
  ? (() => {
      const call = (path, body) =>
        fetch(`${brainUrl}${path}`, {
          method: "POST",
          headers: { authorization: `Bearer ${process.env.TEAMMATE_API_TOKEN}`, "content-type": "application/json" },
          body: JSON.stringify(body),
        })
          .then((r) => r.ok || log(`brain refused ${path}: HTTP ${r.status}`))
          .catch((e) => log(`brain unreachable: ${e.message}`));
      return { ask: (req) => call("/ask", req), approve: (req) => call("/approve", req) };
    })()
  : null;
const bot = new Bot({ store, wa, log, brain });
wa.onLive = (rec, n) => bot.handle(rec, n).catch((e) => log(`bot failed on #${n}: ${e}`));
const api = createApi({ store, wa, token: process.env.TEAMMATE_API_TOKEN, ai });

api.listen(port, host, () => log(`inbox API on http://${host}:${port}`));
await wa.start();
log(wa.registered ? "linked session found, connecting" : "not linked yet -- run `inbox.py pair <phone>`");
ai.start().catch((e) => log(`Gemini worker failed to start: ${e}`));

const shutdown = () => {
  api.close();
  store.close();
  process.exit(0);
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
