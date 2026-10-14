import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi } from "../src/api.js";
import { normalizeMessage } from "../src/normalize.js";
import { Store } from "../src/store.js";

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
