import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi } from "../src/api.js";
import { normalizeMessage } from "../src/normalize.js";
import { Store } from "../src/store.js";
import { WhatsAppListener } from "../src/whatsapp.js";

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
    assert.deepEqual(asked[0], { count: 50, id: "A1", remoteJid: GROUP, tsMs: 1_760_000_000_000 });
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
    assert.deepEqual(calls[0], { jid: GROUP, count: 100, pages: 1 }); // count capped, one page per call
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
