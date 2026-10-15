import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi } from "../src/api.js";
import { normalizeMessage } from "../src/normalize.js";
import { Store, istStarts } from "../src/store.js";
import { WhatsAppListener } from "../src/whatsapp.js";
import { AiWorker, Transcriber, needsTranslation } from "../src/transcribe.js";
import { Bot, parseCommand } from "../src/bot.js";

const GROUP = "120363000000000001@g.us";
const TOKEN = "test-token-0123456789";

function groupMsg(id, text, { participant = "919876543210@s.whatsapp.net", name = "Ravi", ts = 1_760_000_000, extra = {} } = {}) {
  return {
    key: { id, remoteJid: GROUP, participant, fromMe: false },
    pushName: name,
    messageTimestamp: ts,
    message: { conversation: text },
    ...extra,
  };
}

test("normalize: plain group text", () => {
  const r = normalizeMessage(groupMsg("A1", "50 bags cement arrived"));
  assert.equal(r.kind, "text");
  assert.equal(r.text, "50 bags cement arrived");
  assert.equal(r.is_group, true);
  assert.equal(r.sender_jid, "919876543210@s.whatsapp.net");
  assert.equal(r.sender_name, "Ravi");
  assert.equal(r.at, new Date(1_760_000_000_000).toISOString());
});

test("normalize: reply keeps the quoted text; ephemeral wrapper is unwrapped", () => {
  const r = normalizeMessage({
    key: { id: "A2", remoteJid: GROUP, participant: "x@lid", participantPn: "919999999999@s.whatsapp.net" },
    messageTimestamp: 1_760_000_100,
    message: {
      ephemeralMessage: {
        message: {
          extendedTextMessage: {
            text: "this is still broken",
            contextInfo: { stanzaId: "A1", quotedMessage: { conversation: "DPR not coming" } },
          },
        },
      },
    },
  });
  assert.equal(r.text, "this is still broken");
  assert.equal(r.quoted_id, "A1");
  assert.equal(r.quoted_text, "DPR not coming");
  assert.equal(r.sender_pn, "919999999999@s.whatsapp.net");
});

test("normalize: voice note, image caption, reaction", () => {
  const voice = normalizeMessage({ ...groupMsg("V1", ""), message: { audioMessage: { ptt: true, mimetype: "audio/ogg; codecs=opus" } } });
  assert.equal(voice.kind, "voice");
  assert.equal(voice.media_mime, "audio/ogg; codecs=opus");

  const img = normalizeMessage({ ...groupMsg("I1", ""), message: { imageMessage: { caption: "crack in slab", mimetype: "image/jpeg" } } });
  assert.equal(img.kind, "image");
  assert.equal(img.text, "crack in slab");

  const react = normalizeMessage({ ...groupMsg("R1", ""), message: { reactionMessage: { text: "👍", key: { id: "A1" } } } });
  assert.equal(react.kind, "reaction");
  assert.equal(react.reaction_to, "A1");
});

test("normalize: ignores plumbing, status and broken messages", () => {
  assert.equal(normalizeMessage({ ...groupMsg("P1", ""), message: { protocolMessage: { type: 0 } } }), null);
  assert.equal(normalizeMessage({ key: { id: "S1", remoteJid: "status@broadcast" }, message: { conversation: "x" } }), null);
  assert.equal(normalizeMessage({ key: {}, message: { conversation: "x" } }), null);
  assert.equal(normalizeMessage({ key: { id: "E1", remoteJid: GROUP } }), null);
});

function seeded() {
  const store = new Store(":memory:");
  store.upsertChat({ jid: GROUP, name: "Mesiri x Acme Builders", is_group: true });
  store.upsertChat({ jid: "120363000000000002@g.us", name: "Mesiri team", is_group: true });
  store.setRole(GROUP, "customer");
  store.setRole("120363000000000002@g.us", "team");
  store.addMessage(normalizeMessage(groupMsg("A1", "DPR PDF not coming since Monday", { ts: 1_760_000_000 })));
  store.addMessage(normalizeMessage(groupMsg("A2", "cement entry shows wrong unit", { ts: 1_760_000_060, name: "Suresh" })));
  store.addMessage(
    normalizeMessage({ ...groupMsg("T1", "let's fix the DPR first", { ts: 1_760_000_120, name: "Alan" }), key: { id: "T1", remoteJid: "120363000000000002@g.us", participant: "a@s.whatsapp.net" } }),
  );
  return store;
}

test("store: dedupes, searches by words/chat/role, returns a thread", () => {
  const store = seeded();
  assert.equal(store.addMessage(normalizeMessage(groupMsg("A1", "DPR PDF not coming since Monday"))), null);

  assert.equal(store.findMessages({ q: "dpr" }).length, 2);
  assert.equal(store.findMessages({ q: "dpr monday" }).length, 1);
  assert.equal(store.findMessages({ chat: "Acme" }).length, 2);
  assert.equal(store.findMessages({ role: "team" })[0].text, "let's fix the DPR first");
  assert.equal(store.findMessages({ sender: "suresh" })[0].text, "cement entry shows wrong unit");

  const newest = store.findMessages({ chat: "Acme" })[0];
  const ctx = store.getContext(newest.n, 5);
  assert.deepEqual(ctx.thread.map((m) => m.id), ["A1", "A2"]);

  store.setRole(GROUP, "ignore");
  assert.equal(store.findMessages({ q: "cement" }).length, 0);
  assert.throws(() => store.setRole(GROUP, "boss"));
});

async function call(server, method, path, { token = TOKEN, body } = {}) {
  const { port } = server.address();
  const res = await fetch(`http://127.0.0.1:${port}${path}`, {
    method,
    headers: { ...(token ? { authorization: `Bearer ${token}` } : {}), "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, body: await res.json() };
}

test("api: auth, search, thread, role, pairing", async () => {
  const store = seeded();
  const paired = [];
  const wa = { status: () => ({ state: "connected" }), requestPairingCode: async (p) => (paired.push(p), "ABCD-EFGH") };
  const server = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const publicHealth = await call(server, "GET", "/health", { token: null });
    assert.deepEqual(publicHealth.body, { ok: true, state: "connected" });
    assert.equal((await call(server, "GET", "/health")).body.inbox.messages, 3);
    assert.equal((await call(server, "GET", "/chats", { token: null })).status, 401);
    assert.equal((await call(server, "GET", "/chats", { token: "wrong-token-0123456789" })).status, 401);

    const chats = await call(server, "GET", "/teammate/chats"); // nginx prefix accepted
    assert.equal(chats.body.chats.length, 2);

    const found = await call(server, "GET", "/messages?q=cement");
    assert.equal(found.body.messages[0].sender_name, "Suresh");

    const thread = await call(server, "GET", `/messages/${found.body.messages[0].n}?around=3`);
    assert.equal(thread.body.thread.length, 2);

    assert.equal((await call(server, "POST", "/chats/role", { body: { jid: GROUP, role: "team" } })).status, 200);
    assert.equal((await call(server, "POST", "/chats/role", { body: { jid: GROUP, role: "boss" } })).status, 400);

    const pair = await call(server, "POST", "/pair", { body: { phone: "+91 98765 43210" } });
    assert.equal(pair.body.code, "ABCD-EFGH");
    assert.deepEqual(paired, ["919876543210"]);
    assert.equal((await call(server, "GET", "/media/1")).status, 404);
  } finally {
    server.close();
  }
});

test("api: refuses to start with a short token", () => {
  assert.throws(() => createApi({ store: new Store(":memory:"), wa: {}, token: "short" }));
});

test("api: posts only into team chats, with size and rate limits", async () => {
  const store = seeded(); // GROUP = customer "Mesiri x Acme Builders", ...002 = team "Mesiri team"
  const sent = [];
  const wa = {
    status: () => ({ state: "connected" }),
    requestPairingCode: async () => "",
    send: async (jid, content) => (sent.push({ jid, ...content }), `id${sent.length}`),
  };
  process.env.TEAMMATE_SEND_PER_HOUR = "30";
  const server = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const ok = await call(server, "POST", "/send", { body: { chat: "Mesiri team", text: "*Update:* fixed #12" } });
    assert.equal(ok.status, 200);
    assert.deepEqual(sent[0], { jid: "120363000000000002@g.us", text: "*Update:* fixed #12", image: null, caption: null });

    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47]).toString("base64");
    const img = await call(server, "POST", "/send", { body: { chat: "120363000000000002@g.us", image_base64: png, caption: "after" } });
    assert.equal(img.status, 200);
    assert.ok(Buffer.isBuffer(sent[1].image) && sent[1].caption === "after");

    // Customer group: refused, nothing sent.
    const refused = await call(server, "POST", "/send", { body: { chat: "Acme", text: "hello" } });
    assert.equal(refused.status, 403);
    assert.match(refused.body.error, /labelled customer/);
    // Ambiguous or unknown name: not found. Unauthenticated: 401.
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri", text: "x" } })).status, 404);
    assert.equal((await call(server, "POST", "/send", { token: null, body: { chat: "Mesiri team", text: "x" } })).status, 401);
    // Nothing to send, or too long.
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team" } })).status, 400);
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", text: "x".repeat(4001) } })).status, 400);
    const huge = Buffer.alloc(6 * 1024 * 1024).toString("base64");
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", image_base64: huge } })).status, 413);
    assert.equal(sent.length, 2);
  } finally {
    server.close();
  }
});

test("api: send rate limit and a disconnected WhatsApp", async () => {
  const store = seeded();
  process.env.TEAMMATE_SEND_PER_HOUR = "30";
  let connected = true;
  const wa = {
    status: () => ({ state: connected ? "connected" : "connecting" }),
    send: async () => {
      if (!connected) throw new Error("WhatsApp is connecting, not connected");
      return "id";
    },
  };
  const server = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    for (let i = 0; i < 30; i++) {
      assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", text: `n${i}` } })).status, 200);
    }
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", text: "one too many" } })).status, 429);
  } finally {
    server.close();
  }
  const server2 = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server2.listen(0, "127.0.0.1", r));
  try {
    connected = false;
    const down = await call(server2, "POST", "/send", { body: { chat: "Mesiri team", text: "x" } });
    assert.equal(down.status, 503);
  } finally {
    server2.close();
  }
});

test("project (TM-05): each repo sees and posts to its own groups only", async () => {
  const store = seeded(); // Acme (customer) + Mesiri team, untagged
  const MERCON = "120363000000000003@g.us";
  store.upsertChat({ jid: MERCON, name: "Mercon Software discussions", is_group: true });
  store.addMessage(
    normalizeMessage({ ...groupMsg("M1", "trip report shows wrong date", { ts: 1_760_000_200 }), key: { id: "M1", remoteJid: MERCON, participant: "c@s.whatsapp.net" } }),
  );
  store.setRole(GROUP, "customer", "mesiri");
  store.setRole("120363000000000002@g.us", "team", "mesiri");
  assert.throws(() => store.setRole(MERCON, "customer", "Mercon!"));

  // Untagged chats are listed (so they can be labelled) but their messages stay out of project views.
  assert.equal(store.findMessages({ project: "mercon" }).length, 0);
  assert.equal(store.listChats({ project: "mercon" }).length, 1);
  store.setRole(MERCON, "customer", "mercon");
  assert.equal(store.setRole(MERCON, "customer"), true); // project left as is
  assert.deepEqual(store.findMessages({ project: "mercon" }).map((m) => m.id), ["M1"]);
  assert.equal(store.findMessages({ project: "mesiri", q: "trip" }).length, 0);
  assert.equal(store.findMessages({ q: "trip" }).length, 1); // no project: everything, as before

  const sent = [];
  const wa = { status: () => ({ state: "connected" }), send: async (jid) => (sent.push(jid), "id") };
  const server = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const chats = await call(server, "GET", "/chats?project=mercon");
    assert.deepEqual(chats.body.chats.map((c) => c.project), ["mercon"]);
    const msgs = await call(server, "GET", "/messages?project=mesiri");
    assert.equal(msgs.body.messages.length, 3);
    assert.ok(msgs.body.messages.every((m) => m.chat_project === "mesiri"));

    const n = store.findMessages({ project: "mercon" })[0].n;
    assert.equal((await call(server, "GET", `/messages/${n}?project=mercon`)).status, 200);
    assert.equal((await call(server, "GET", `/messages/${n}?project=mesiri`)).status, 404);
    assert.equal((await call(server, "GET", `/media/${n}?project=mesiri`)).status, 404);

    const label = await call(server, "POST", "/chats/role", { body: { jid: MERCON, role: "ignore", project: "mercon" } });
    assert.equal(label.status, 200);
    assert.equal((await call(server, "POST", "/chats/role", { body: { jid: MERCON, role: "customer", project: "BAD X" } })).status, 400);

    // Posting: a mercon session can't post into the mesiri team group.
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", project: "mercon", text: "x" } })).status, 403);
    assert.equal((await call(server, "POST", "/send", { body: { chat: "Mesiri team", project: "mesiri", text: "x" } })).status, 200);
    assert.deepEqual(sent, ["120363000000000002@g.us"]);
  } finally {
    server.close();
  }
});

test("project (TM-05): an inbox from before TM-05 gains the column, data kept", async () => {
  const { DatabaseSync } = await import("node:sqlite");
  const { mkdtempSync, rmSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const dir = mkdtempSync(join(tmpdir(), "tm05-"));
  const path = join(dir, "inbox.db");
  try {
    const old = new DatabaseSync(path);
    old.exec(`CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, is_group INTEGER NOT NULL,
      role TEXT NOT NULL DEFAULT 'unlabelled', first_seen TEXT NOT NULL, updated_at TEXT NOT NULL);
      INSERT INTO chats VALUES ('${GROUP}', 'Old group', 1, 'customer', '2026-10-01', '2026-10-01');`);
    old.close();
    const store = new Store(path);
    assert.deepEqual(
      store.listChats().map((c) => [c.name, c.role, c.project]),
      [["Old group", "customer", null]],
    );
    store.setRole(GROUP, "customer", "mesiri");
    assert.equal(store.listChats({ project: "mesiri" })[0].project, "mesiri");
    store.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("history (TM-06): pages back through the phone's older messages, then stops", async () => {
  const { mkdtempSync, rmSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const dir = mkdtempSync(join(tmpdir(), "tm06-"));
  try {
    const store = seeded(); // GROUP has A1 (oldest, ts 1_760_000_000) and A2
    const wa = new WhatsAppListener({ store, dataDir: dir, log: () => {} });
    const asked = [];
    // The phone has two older messages; the second request gets nothing new.
    const older = [groupMsg("H1", "old: invoice wrong", { ts: 1_759_000_000 }), groupMsg("H2", "old: need report", { ts: 1_759_100_000 })];
    wa.state = "connected";
    wa.sock = {
      fetchMessageHistory: async (count, key, tsMs) => {
        asked.push({ count, id: key.id, remoteJid: key.remoteJid, tsMs });
        const reply = asked.length === 1 ? older : [older[0]];
        // The answer arrives as a history event, with an id other than the request's.
        setImmediate(() => wa.onHistorySet({ messages: reply, syncType: 6, peerDataRequestSessionId: "other" }));
        return `REQ${asked.length}`;
      },
      groupMetadata: async () => ({ id: GROUP, subject: "x" }),
    };
    const r = await wa.fetchHistory(GROUP, { count: 50, pages: 5 });
    assert.equal(r.added, 2);
    assert.equal(r.requests, 2);
    assert.deepEqual(asked[0], { count: 50, id: "A1", remoteJid: GROUP, tsMs: 1_760_000_000 }); // seconds
    assert.equal(asked[1].id, "H1"); // second page anchored on the new oldest
    assert.equal(store.findMessages({ q: "old:" }).length, 2);
    assert.equal(wa.historyWaiters.size, 0);

    // No messages yet in a chat: nothing to anchor on. Disconnected: refused.
    await assert.rejects(wa.fetchHistory("999@g.us"), /no message stored/);
    wa.state = "connecting";
    await assert.rejects(wa.fetchHistory(GROUP), /not connected/);
    store.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("history (TM-06): API resolves the chat, keeps to the project, reports failures", async () => {
  const store = seeded();
  store.setRole(GROUP, "customer", "mercon");
  const calls = [];
  const wa = {
    status: () => ({ state: "connected" }),
    fetchHistory: async (jid, opts) => {
      calls.push({ jid, ...opts });
      if (opts.pages === 2) throw new Error("the phone didn't answer");
      return { added: 7, requests: 1, oldest_at: "2026-01-01T00:00:00.000Z" };
    },
  };
  const server = createApi({ store, wa, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const ok = await call(server, "POST", "/history", { body: { chat: "Acme", project: "mercon", count: 500 } });
    assert.equal(ok.status, 200);
    assert.equal(ok.body.added, 7);
    assert.deepEqual(calls[0], { jid: GROUP, count: 50, pages: 1 }); // count capped, one page per call
    assert.equal((await call(server, "POST", "/history", { body: { chat: "Acme", project: "mesiri" } })).status, 404);
    assert.equal((await call(server, "POST", "/history", { body: { chat: "nope" } })).status, 404);
    assert.equal((await call(server, "POST", "/history", { body: { chat: "Acme", pages: 2 } })).status, 409);
  } finally {
    server.close();
  }
});

test("normalize (Baileys 7): a sender under a privacy id keeps their phone number", () => {
  const lid = normalizeMessage({
    key: { id: "L1", remoteJid: GROUP, participant: "123456789@lid", participantAlt: "919876500000@s.whatsapp.net", fromMe: false },
    pushName: "Lazin",
    messageTimestamp: 1_760_000_300,
    message: { conversation: "mail id onnu vitero" },
  });
  assert.equal(lid.sender_jid, "123456789@lid");
  assert.equal(lid.sender_pn, "919876500000@s.whatsapp.net");

  const dm = normalizeMessage({
    key: { id: "D1", remoteJid: "55555@lid", remoteJidAlt: "919800000001@s.whatsapp.net", fromMe: false },
    messageTimestamp: 1_760_000_400,
    message: { conversation: "hi" },
  });
  assert.equal(dm.sender_pn, "919800000001@s.whatsapp.net");
  assert.equal(dm.is_group, false);
});

function fakeGemini(replies) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : null, key: init.headers?.["x-goog-api-key"] });
    if (url.endsWith("/models/gemini-3.8-flash")) return new Response("{}", { status: 200 });
    const next = replies.shift();
    if (next instanceof Error) return new Response(next.message, { status: next.status || 500 });
    return new Response(JSON.stringify({ candidates: [{ content: { parts: [{ text: JSON.stringify(next) }] } }], usageMetadata: { promptTokenCount: 1000, candidatesTokenCount: 150, thoughtsTokenCount: 50 } }), { status: 200 });
  };
  return { calls, fetchImpl };
}

test("transcribe (TM-07): voice and text requests, JSON parsing, English left alone", async () => {
  const { calls, fetchImpl } = fakeGemini([
    { transcript: "ഡ്രൈവർ കൗണ്ട് തെറ്റാണ്", translated_text: "The driver count is wrong", detected_language: "Malayalam" },
    { translated_text: "Send me another mail id", detected_language: "Malayalam" },
    { translated_text: "", detected_language: "English" },
  ]);
  const t = new Transcriber({ apiKey: "k-123", fetchImpl });
  assert.equal(await t.check(), true);
  const v = await t.voice(Buffer.from("OggS"), "audio/ogg; codecs=opus");
  const { cost, ...said } = v;
  assert.deepEqual(said, { transcript: "ഡ്രൈവർ കൗണ്ട് തെറ്റാണ്", translation: "The driver count is wrong", language: "Malayalam" });
  // 1,000 in x $0.75 + 200 out (150 + 50 thinking) x $3.75 per 1M = $0.0015; x Rs 88 = Rs 0.132
  assert.equal(cost.input_tokens, 1000);
  assert.equal(cost.output_tokens, 200);
  assert.ok(Math.abs(cost.usd - 0.0015) < 1e-12);
  assert.ok(Math.abs(cost.inr - 0.132) < 1e-9);
  const part = calls[1].body.contents[0].parts[0].inline_data;
  assert.equal(part.mime_type, "audio/ogg");
  assert.equal(part.data, Buffer.from("OggS").toString("base64"));
  assert.equal(calls[1].key, "k-123");
  assert.equal(calls[1].body.generationConfig.responseMimeType, "application/json");
  assert.deepEqual((({ cost, ...r }) => r)(await t.text("ith vere kitya mail id onnu vitero")), { translation: "Send me another mail id", language: "Malayalam" });
  assert.deepEqual((({ cost, ...r }) => r)(await t.text("total driver count still showing 27")), { translation: null, language: "English" });

  assert.equal(needsTranslation(["abc@gmail.com", "xyz@gmail.com"].join(String.fromCharCode(10))), false);
  assert.equal(needsTranslation("https://x.y/z 27"), false);
  assert.equal(needsTranslation("Ooo"), true);
});

test("transcribe (TM-07): worker fills the queue, skips private chats, retries failures 3 times", async () => {
  const store = seeded(); // Acme = customer, Mesiri team = team
  const PRIVATE = "120363000000000009@g.us";
  store.upsertChat({ jid: PRIVATE, name: "Family", is_group: true });
  store.setRole(PRIVATE, "ignore");
  store.addMessage(normalizeMessage({ ...groupMsg("P1", "dinner at 8"), key: { id: "P1", remoteJid: PRIVATE, participant: "f@s.whatsapp.net" } }));
  const voiceN = store.addMessage(normalizeMessage({ ...groupMsg("V9", ""), message: { audioMessage: { ptt: true, mimetype: "audio/ogg; codecs=opus" } } }));
  store.setMediaPath(voiceN, "/media/v9.ogg");
  const unsaved = store.addMessage(normalizeMessage({ ...groupMsg("V8", ""), message: { audioMessage: { ptt: true, mimetype: "audio/ogg" } } }));

  // 3 text messages in labelled chats + the voice note with its file; the one without a file and the private chat wait.
  assert.equal(store.countPendingAi(), 4);
  const { calls, fetchImpl } = fakeGemini([
    { transcript: "സ്ലാബിൽ വിള്ളൽ", translated_text: "Crack in the slab", detected_language: "Malayalam" },
    { translated_text: "", detected_language: "English" },
    new Error("quota"),
    { translated_text: "", detected_language: "English" },
  ]);
  const files = [];
  const worker = new AiWorker({ store, auto: true, transcriber: new Transcriber({ apiKey: "k", fetchImpl }), readFile: (p) => (files.push(p), Buffer.from("OggS")) });
  await worker.start({ intervalMs: 60_000 });
  await worker.running;
  clearInterval(worker.timer);

  assert.deepEqual(files, ["/media/v9.ogg"]);
  const voice = store.getMessage(voiceN);
  assert.equal(voice.translation, "Crack in the slab");
  assert.equal(voice.language, "Malayalam");
  assert.equal(store.findMessages({ q: "slab crack" })[0].n, voiceN); // English search finds the voice note
  assert.ok(calls.every((c) => !JSON.stringify(c.body || {}).includes("dinner"))); // private chat never sent
  assert.equal(store.getMessage(unsaved).transcript, null);
  // One text failed once; it is retried on the next run, up to 3 attempts in all.
  assert.equal(worker.status().pending, 1);
  assert.match(worker.status().last_error, /quota/);
  assert.equal(worker.status().ok, true);

  const off = new AiWorker({ store, transcriber: null, readFile: () => Buffer.alloc(0) });
  assert.deepEqual(off.status(), { enabled: false });
});

test("transcribe (TM-07): a rate limit pauses the queue without using up attempts", async () => {
  const store = seeded(); // 3 pending text messages
  const limited = Object.assign(new Error("quota exceeded"), { status: 429 });
  const { calls, fetchImpl } = fakeGemini([limited, { translated_text: "", detected_language: "English" }]);
  const worker = new AiWorker({ store, transcriber: new Transcriber({ apiKey: "k", fetchImpl }), readFile: () => Buffer.alloc(0) });
  worker.ok = true;
  assert.equal(await worker.drain(), 0);
  assert.equal(calls.length, 1); // stopped at the first 429
  assert.equal(store.countPendingAi(), 3); // nothing marked done or failed
  assert.match(worker.status().last_error, /429/);
});

test("items (TM-08): log a request, track it to done, keep the history, scope by project", async () => {
  const store = seeded(); // Acme = customer, Mesiri team = team
  store.setRole(GROUP, "customer", "mercon");
  const server = createApi({ store, wa: { status: () => ({ state: "connected" }) }, token: TOKEN });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const add = await call(server, "POST", "/items", {
      body: { chat: "Acme", project: "mercon", type: "bug", title: "Transit time counts from planned pickup", source: "9", created_by: "claude" },
    });
    assert.equal(add.status, 200);
    const id = add.body.item.id;
    assert.equal(add.body.item.status, "open");
    assert.equal(add.body.item.project, "mercon");

    // Wrong project, bad type, missing title: refused.
    assert.equal((await call(server, "POST", "/items", { body: { chat: "Acme", project: "mesiri", type: "bug", title: "x" } })).status, 404);
    assert.equal((await call(server, "POST", "/items", { body: { chat: "Acme", type: "wish", title: "x" } })).status, 400);
    assert.equal((await call(server, "POST", "/items", { body: { chat: "Acme", type: "bug", title: " " } })).status, 400);

    await call(server, "POST", `/items/${id}`, { body: { status: "in_progress", note: "planning" } });
    const done = await call(server, "POST", `/items/${id}`, { body: { status: "done", ref: "aprodac/MERCON#262", note: "count from actual loading time" } });
    assert.equal(done.body.item.status, "done");
    assert.equal(done.body.item.done_ref, "aprodac/MERCON#262");
    await call(server, "POST", `/items/${id}`, { body: { ref: "fdc9f0ef", note: "released" } });
    const shown = await call(server, "GET", `/items/${id}?project=mercon`);
    assert.equal(shown.body.item.done_ref, "aprodac/MERCON#262, fdc9f0ef");
    assert.deepEqual(shown.body.item.log.map((l) => l.status), ["open", "in_progress", "done", null]);
    assert.equal((await call(server, "GET", `/items/${id}?project=mesiri`)).status, 404);
    assert.equal((await call(server, "POST", `/items/${id}`, { body: { status: "finished" } })).status, 400);

    store.addItem({ chat_jid: "120363000000000002@g.us", type: "task", title: "Mesiri-only item" });
    const mercon = await call(server, "GET", "/items?project=mercon");
    assert.deepEqual(mercon.body.items.map((i) => i.title), ["Transit time counts from planned pickup"]);
    assert.equal((await call(server, "GET", "/items?status=done")).body.items.length, 1);
    assert.equal((await call(server, "GET", "/items")).body.items.length, 2);
  } finally {
    server.close();
  }
});

test("bot (TM-03): parseCommand", () => {
  assert.deepEqual(parseCommand("@919544376072 approve @9198"), { verb: "approve", rest: "" });
  assert.deepEqual(parseCommand("@1 make owner @2"), { verb: "owner", rest: "" });
  assert.equal(parseCommand("@1 who").verb, "who");
  assert.equal(parseCommand("@1 who changed the driver count?").verb, "request");
  assert.equal(parseCommand("@1 help me fix the driver count").verb, "request");
  assert.equal(parseCommand("@1 help").verb, "help");
  assert.equal(parseCommand("@1 add a filter to trips").verb, "request");
  assert.equal(parseCommand("@1 add @2").verb, "approve");
  assert.equal(parseCommand("@1 ok but change the colour").verb, "request");
  assert.deepEqual(parseCommand("@1 ok #12"), { verb: "ok", id: 12, rest: "#12" });
  assert.equal(parseCommand("@1 remove the old banner").verb, "request");
  assert.deepEqual(parseCommand("@1 ok [7]"), { verb: "ok", id: 7, rest: "[7]" });
  assert.equal(parseCommand("@1 OK").id, null);
  assert.deepEqual(parseCommand("@1 fix the transit time from loading"), { verb: "request", rest: "fix the transit time from loading" });
  assert.equal(parseCommand("@1").verb, "help");
});

function botSetup() {
  const store = seeded(); // GROUP = customer "Acme", ...002 = team "Mesiri team"
  const TEAM = "120363000000000002@g.us";
  store.setRole(GROUP, "customer", "mercon");
  store.setRole(TEAM, "team", "mercon");
  const OWNER_PN = "917034926395@s.whatsapp.net";
  store.allowPerson({ project: "*", pn: OWNER_PN, name: "Ilan", role: "owner", added_by: "api" });
  const sent = [];
  const wa = {
    ownIds: () => ["919544376072@s.whatsapp.net", "56672747843793@lid"],
    pnFor: async (jid) => ({ "222@lid": "919800000002@s.whatsapp.net", "333@lid": "919800000003@s.whatsapp.net" })[jid] || null,
    send: async (jid, c) => (sent.push({ jid, ...c }), "id"),
  };
  const logs = [];
  const bot = new Bot({ store, wa, log: (m) => logs.push(m) });
  let seq = 0;
  const msg = (chat, text, { from = "111@lid", pn = OWNER_PN, name = "Ilan", mentions = ["56672747843793@lid"], quoted_id = null } = {}) => {
    const rec = {
      id: `M${++seq}`, chat_jid: chat, is_group: true, sender_jid: from, sender_pn: pn, sender_name: name, from_me: false,
      at: new Date(1_760_001_000_000 + seq * 1000).toISOString(), kind: "text", text, quoted_id, quoted_text: null,
      media_mime: null, reaction_to: null, mentions,
    };
    return { rec, n: store.addMessage(rec) };
  };
  return { store, TEAM, sent, bot, msg, logs, OWNER_PN };
}

test("bot (TM-03): owners approve people from the team group; members request; customers never get replies", async () => {
  const { store, TEAM, sent, bot, msg, logs, OWNER_PN } = botSetup();

  // Not approved yet: ignored, no reply.
  let m = msg(TEAM, "@bot fix it", { from: "222@lid", pn: null, name: "Alan" });
  await bot.handle(m.rec, m.n);
  assert.equal(sent.length, 0);
  assert.match(logs.at(-1), /ignored a tag from Alan/);

  // No mention of the bot: not for us, even from the owner.
  m = msg(TEAM, "fix it", { mentions: [] });
  await bot.handle(m.rec, m.n);
  assert.equal(sent.length, 0);

  // The all-projects owner approves Alan (tagged by privacy id; the number is looked up).
  m = msg(TEAM, "@bot approve @Alan", { mentions: ["56672747843793@lid", "222@lid"] });
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /approved @919800000002/);
  assert.deepEqual(sent.at(-1).mentions, ["222@lid"]);
  assert.equal(store.findPerson("mercon", ["222@lid"]).role, "member");
  assert.equal(store.findPerson("mesiri", ["222@lid"]), null); // per project

  // Alan (member) can't approve others.
  m = msg(TEAM, "@bot approve @Bob", { from: "222@lid", pn: null, name: "Alan", mentions: ["56672747843793@lid", "333@lid"] });
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /Only an owner/);
  assert.equal(store.findPerson("mercon", ["333@lid"]), null);

  // Alan requests work, replying to a stored message: logged with both message numbers.
  const quoted = store.findMessages({ chat: TEAM })[0];
  m = msg(TEAM, "@bot fix the transit time from loading", { from: "222@lid", pn: null, name: "Alan", quoted_id: quoted.id });
  await bot.handle(m.rec, m.n);
  const item = store.listItems({ project: "mercon" })[0];
  assert.equal(item.title, "fix the transit time from loading");
  assert.equal(item.source, `${quoted.n},${m.n}`);
  assert.ok(sent.at(-1).text.includes(`Request [${item.id}]`));

  // The owner tags the bot in the customer group: logged, announced in the team group, nothing sent to customers.
  m = msg(GROUP, "@bot driver count is wrong");
  await bot.handle(m.rec, m.n);
  assert.ok(sent.every((s) => s.jid === TEAM));
  assert.match(sent.at(-1).text, /from Ilan in Mesiri x Acme Builders: driver count is wrong/);

  // OK needs the number when more than one is open; then it moves to in progress.
  m = msg(TEAM, "@bot ok");
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /Which one\?/);
  m = msg(TEAM, `@bot ok ${item.id}`);
  await bot.handle(m.rec, m.n);
  assert.equal(store.getItem(item.id).status, "in_progress");
  assert.match(store.getItem(item.id).log.at(-1).note, /OK from Ilan/);

  // who, remove; the all-projects owner can't be removed from a group.
  m = msg(TEAM, "@bot who");
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /Ilan \(owner\)/);
  m = msg(TEAM, "@bot remove @Alan", { mentions: ["56672747843793@lid", "222@lid"] });
  await bot.handle(m.rec, m.n);
  assert.equal(store.findPerson("mercon", ["222@lid"]), null);
  m = msg(TEAM, "@bot remove @Ilan", { mentions: ["56672747843793@lid", OWNER_PN] });
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /wasn't approved/);
  assert.equal(store.findPerson("mercon", [OWNER_PN]).role, "owner");
});

test("bot (TM-03): replies are capped per hour so bots can't loop", async () => {
  const { TEAM, sent, bot, msg } = botSetup();
  for (let i = 0; i < 25; i++) {
    const m = msg(TEAM, "@bot who");
    await bot.handle(m.rec, m.n);
  }
  assert.equal(sent.length, 20);
});

test("bot (TM-03b): with a brain, questions and requests go to Claude; approvals stay local", async () => {
  const { store, TEAM, sent, msg } = botSetup();
  const asked = [];
  const typing = [];
  const wa = {
    ownIds: () => ["919544376072@s.whatsapp.net", "56672747843793@lid"],
    pnFor: async () => null,
    send: async (jid, c) => (sent.push({ jid, ...c }), "id"),
    typing: (jid) => typing.push(jid),
  };
  const approved = [];
  const bot = new Bot({ store, wa, brain: { ask: async (req) => asked.push(req), approve: async (req) => approved.push(req) } });

  let m = msg(TEAM, "@bot did you understand these issues?");
  await bot.handle(m.rec, m.n);
  assert.equal(asked.length, 1);
  assert.equal(asked[0].text, "did you understand these issues?");
  assert.equal(asked[0].reply_chat, TEAM);
  assert.equal(asked[0].project, "mercon");
  assert.deepEqual(typing, [TEAM]);
  assert.equal(sent.length, 0); // Claude answers, not the bot
  assert.equal(store.listItems({ project: "mercon" }).length, 0); // Claude logs requests itself

  // Asked in a customer group: answer still goes to the team group.
  m = msg(GROUP, "@bot what did they ask for?");
  await bot.handle(m.rec, m.n);
  assert.equal(asked[1].chat, GROUP);
  assert.equal(asked[1].chat_role, "customer");
  assert.equal(asked[1].reply_chat, TEAM);

  // Asked in a second team group (e.g. "Mercon history"): answered right there.
  const HIST = "120363000000000005@g.us";
  store.upsertChat({ jid: HIST, name: "Mercon history", is_group: true });
  store.setRole(HIST, "team", "mercon");
  m = msg(HIST, "@bot did you understand these issues?");
  await bot.handle(m.rec, m.n);
  assert.equal(asked.at(-1).reply_chat, HIST);
  assert.equal(typing.at(-1), HIST);
  asked.pop();

  // A reply to one of the bot's own messages needs no @; a reply to someone else's does.
  store.addMessage({ id: "BOT1", chat_jid: TEAM, is_group: true, sender_jid: null, sender_pn: null, sender_name: null, from_me: true,
    at: new Date().toISOString(), kind: "text", text: "Plan [7] ready", quoted_id: null, quoted_text: null, media_mime: null, reaction_to: null });
  m = msg(TEAM, "looks good, but also check trucks", { mentions: [], quoted_id: "BOT1" });
  await bot.handle(m.rec, m.n);
  assert.equal(asked.at(-1).text, "looks good, but also check trucks");
  assert.equal(asked.at(-1).quoted_id, "BOT1");
  const before = asked.length;
  const other = store.findMessages({ chat: TEAM }).find((x) => !x.from_me);
  m = msg(TEAM, "agreed", { mentions: [], quoted_id: other.id });
  await bot.handle(m.rec, m.n);
  assert.equal(asked.length, before);
  asked.pop();

  // Approval commands are still handled by the bot itself.
  m = msg(TEAM, "@bot who");
  await bot.handle(m.rec, m.n);
  assert.equal(asked.length, 2);
  assert.match(sent.at(-1).text, /Approved for mercon/);

  // "ok 7" approves plan 7 through the brain -- only from the team group.
  m = msg(TEAM, "@bot ok 7");
  await bot.handle(m.rec, m.n);
  assert.deepEqual(approved, [{ project: "mercon", item_id: 7, by: "Ilan", reply_chat: TEAM }]);
  m = msg(GROUP, "@bot ok 7");
  await bot.handle(m.rec, m.n);
  assert.equal(approved.length, 1);
  assert.equal(asked.length, 2);

  // Unapproved: neither.
  m = msg(TEAM, "@bot hello", { from: "999@lid", pn: null, name: "Stranger" });
  await bot.handle(m.rec, m.n);
  assert.equal(asked.length, 2);
});

test("transcribe: a retired model (404) pauses the queue and doesn't use up attempts; failures are retried on start", async () => {
  const store = seeded(); // 3 pending text messages
  const retired = Object.assign(new Error("models/gemini-2.5-flash is no longer available"), { status: 404 });
  const { calls, fetchImpl } = fakeGemini([retired]);
  const worker = new AiWorker({ store, transcriber: new Transcriber({ apiKey: "k", fetchImpl }), readFile: () => Buffer.alloc(0) });
  worker.ok = true;
  assert.equal(await worker.drain(), 0);
  assert.equal(calls.length, 1);
  assert.equal(store.countPendingAi(), 3);

  // Messages that used up their attempts earlier get another chance.
  const n = store.pendingAi(1)[0].n;
  for (let i = 0; i < 3; i++) store.failAi(n);
  assert.equal(store.countPendingAi(), 2);
  assert.equal(store.retryFailedAi(), 1);
  assert.equal(store.countPendingAi(), 3);
});

test("translation on request (default): nothing in the background; translate(n) returns text + cost, once", async () => {
  const store = seeded(); // Acme = customer, Mesiri team = team
  const voiceN = store.addMessage(normalizeMessage({ ...groupMsg("V7", ""), message: { audioMessage: { ptt: true, mimetype: "audio/ogg" } } }));
  store.setMediaPath(voiceN, "/media/v7.ogg");
  const PRIVATE = "120363000000000009@g.us";
  store.upsertChat({ jid: PRIVATE, name: "Family", is_group: true });
  const privN = store.addMessage(normalizeMessage({ ...groupMsg("P2", "ninte veedu evide"), key: { id: "P2", remoteJid: PRIVATE, participant: "f@s.whatsapp.net" } }));
  const { calls, fetchImpl } = fakeGemini([{ transcript: "ലോഡിംഗ് സമയം", translated_text: "Loading time", detected_language: "Malayalam" }]);
  const worker = new AiWorker({ store, transcriber: new Transcriber({ apiKey: "k", fetchImpl }), readFile: () => Buffer.from("OggS") });
  await worker.start();
  assert.equal(worker.status().auto, false);
  assert.equal(calls.length, 1); // only the key check -- nothing translated by itself

  const r = await worker.translate(voiceN);
  assert.equal(r.translation, "Loading time");
  assert.ok(r.cost.inr > 0);
  const again = await worker.translate(voiceN); // stored: no new call, no new cost
  assert.equal(again.cached, true);
  assert.equal(calls.length, 2);
  const { day } = istStarts();
  assert.equal(store.aiUsageSince(day).calls, 1);
  assert.ok(Math.abs(store.aiUsageSince(day).inr - r.cost.inr) < 1e-9);

  await assert.rejects(worker.translate(privN), /isn't labelled team or customer/); // private chats never sent
  assert.equal(calls.length, 2);
});

test("bot: '@bot translate' as a reply, '#n', and '@bot cost' in rupees", async () => {
  const { store, TEAM, sent, msg } = botSetup();
  const vN = store.addMessage({ id: "VN1", chat_jid: TEAM, is_group: true, sender_jid: "c@lid", sender_pn: null, sender_name: "Customer", from_me: false,
    at: new Date().toISOString(), kind: "voice", text: null, quoted_id: null, quoted_text: null, media_mime: "audio/ogg", reaction_to: null });
  const translated = [];
  const ai = {
    transcriber: { prices: { priceIn: 0.75, priceOut: 3.75, usdInr: 88 } },
    translate: async (n) => (translated.push(n), store.addAiUsage({ n, model: "gemini-3.8-flash", input_tokens: 900, output_tokens: 100, usd: 0.001, inr: 0.088 }),
      { n, cached: false, transcript: "ലോഡിംഗ്", translation: "Loading", language: "Malayalam", cost: { model: "gemini-3.8-flash", input_tokens: 900, output_tokens: 100, usd: 0.001, inr: 0.088 } }),
  };
  const wa = { ownIds: () => ["919544376072@s.whatsapp.net", "56672747843793@lid"], pnFor: async () => null, send: async (jid, c) => (sent.push({ jid, ...c }), "id") };
  const bot = new Bot({ store, wa, ai, brain: { ask: async () => assert.fail("translate must not go to Claude") } });

  let m = msg(TEAM, "@bot translate", { quoted_id: "VN1" });
  await bot.handle(m.rec, m.n);
  assert.deepEqual(translated, [vN]);
  assert.match(sent.at(-1).text, /🗣 #\d+ \(Malayalam\)[\s\S]*⇒ EN: Loading[\s\S]*💰 ₹0\.09 · 900 in \/ 100 out tokens · gemini-3\.8-flash/);

  m = msg(TEAM, `@bot translate #${vN}`);
  await bot.handle(m.rec, m.n);
  assert.equal(translated.length, 2);

  m = msg(TEAM, "@bot translate");
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /Reply to the voice note/);

  m = msg(TEAM, "@bot cost");
  await bot.handle(m.rec, m.n);
  assert.match(sent.at(-1).text, /Today: ₹0\.18 · 2 call\(s\)[\s\S]*This month: ₹0\.18/);

  assert.equal(parseCommand("@1 translate this paragraph into arabic please").verb, "request"); // that's for Claude
  assert.equal(parseCommand("@1 gemini cost").verb, "cost");
});
