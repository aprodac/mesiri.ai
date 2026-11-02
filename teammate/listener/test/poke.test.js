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
