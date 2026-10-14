// Entry point: open the inbox, connect to WhatsApp, serve the API.
//
// Environment:
//   TEAMMATE_API_TOKEN   required, >= 16 chars; the Bearer token for the API
//   TEAMMATE_DATA_DIR    default ./data  (inbox.db, auth/ session, media/)
//   TEAMMATE_HOST        default 127.0.0.1 (put nginx in front, never expose directly)
//   TEAMMATE_PORT        default 8790

import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { createApi } from "./api.js";
import { Store } from "./store.js";
import { WhatsAppListener } from "./whatsapp.js";

const dataDir = resolve(process.env.TEAMMATE_DATA_DIR || "./data");
const host = process.env.TEAMMATE_HOST || "127.0.0.1";
const port = Number(process.env.TEAMMATE_PORT || 8790);
const log = (msg) => console.log(`[teammate] ${msg}`);

mkdirSync(dataDir, { recursive: true });
const store = new Store(join(dataDir, "inbox.db"));
const wa = new WhatsAppListener({ store, dataDir, log });
const api = createApi({ store, wa, token: process.env.TEAMMATE_API_TOKEN });

api.listen(port, host, () => log(`inbox API on http://${host}:${port}`));
await wa.start();
log(wa.registered ? "linked session found, connecting" : "not linked yet -- run `inbox.py pair <phone>`");

const shutdown = () => {
  api.close();
  store.close();
  process.exit(0);
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
