// TM-22: Mesiri pokes the production watch through the listener when a request was just made.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createApi } from "../src/api.js";

const TOKEN = "t".repeat(20);

async function withApi(brain, fn) {
  const store = { stats: () => ({}) };
  const wa = { status: () => ({ state: "open" }) };
  const server = createApi({ store, wa, token: TOKEN, brain });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    await fn(base);
  } finally {
    server.close();
  }
}

const post = (base, path, body, token = TOKEN) =>
  fetch(`${base}${path}`, { method: "POST", headers: { authorization: `Bearer ${token}`, "content-type": "application/json" }, body: JSON.stringify(body) });

test("a poke reaches the brain, with the token only", async () => {
  const pokes = [];
  await withApi({ poke: (req) => pokes.push(req) }, async (base) => {
    assert.equal((await post(base, "/teammate/watch/poke", { project: "mesiri", correlation_id: "cor_ab" })).status, 202);
    assert.equal((await post(base, "/watch/poke", { project: "mesiri" }, "wrong-token-0000000")).status, 401);
    assert.equal((await post(base, "/watch/poke", { project: "Bad Name!" })).status, 400);
  });
  assert.deepEqual(pokes, [{ project: "mesiri", correlation_id: "cor_ab" }]);
});

test("without a brain the poke says so", async () => {
  await withApi(null, async (base) => {
    assert.equal((await post(base, "/watch/poke", { project: "mesiri" })).status, 503);
  });
});

// 3 Nov: the bot crash-looped all night unseen. The public /health carries its state so the uptime check can alert.
test("the public health says whether the team bot is up, and for how long", async () => {
  await withApi({ health: async () => ({ state: "up", up_s: 412 }) }, async (base) => {
    const body = await (await fetch(`${base}/teammate/health`)).json();
    assert.deepEqual(body.brain, { state: "up", up_s: 412 });
    assert.equal(body.inbox, undefined); // still nothing private without the token
  });
  await withApi({ health: async () => ({ state: "down" }) }, async (base) => {
    assert.equal((await (await fetch(`${base}/health`)).json()).brain.state, "down");
  });
  await withApi(null, async (base) => {
    assert.equal((await (await fetch(`${base}/health`)).json()).brain, undefined);
  });
});
