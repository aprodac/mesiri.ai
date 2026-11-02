import test from "node:test";
import assert from "node:assert/strict";
import { costRows, costSql } from "../src/cost.js";
import { Screener } from "../src/prod_watch.js";

const since = "2026-10-31T18:30:00.000Z";

test("cost (TM-20): one read-only SELECT over the metered AI rows, for the period only", () => {
  const sql = costSql({ since, until: "2026-11-30T18:30:00.000Z" });
  assert.match(sql, /^WITH c AS/);
  assert.match(sql, /pe\.metered AND pe\.provider <> 'whatsapp'/);
  assert.match(sql, /pe\.created_at >= '2026-10-31T18:30:00\.000Z'/);
  assert.match(sql, /pe\.created_at < '2026-11-30T18:30:00\.000Z'/);
  assert.doesNotMatch(costSql({ since }), /created_at </);
  assert.doesNotMatch(sql, /;/); // the ops API takes one statement
});

test("cost (TM-20): anything but a plain time is refused, never put in the SQL", () => {
  assert.throws(() => costSql({ since: "2026-01-01'; DROP TABLE users; --" }), /bad period/);
  assert.throws(() => costSql({ since, until: "tomorrow" }), /bad period/);
});

test("cost (TM-20): rows come back as objects; a refused read is an error", async () => {
  const calls = [];
  const fetchFn = async (url, init) => (calls.push({ url, init }), { ok: true, json: async () => ({ columns: ["section", "name"], rows: [["work", "run_tools"]] }) });
  assert.deepEqual(await costRows({ url: "https://ops", token: "t" }, { since }, fetchFn), [{ section: "work", name: "run_tools" }]);
  assert.equal(calls[0].url, "https://ops/claude-ops/sql");
  assert.equal(calls[0].init.headers.authorization, "Bearer t");
  await assert.rejects(costRows({ url: "u", token: "t" }, { since }, async () => ({ ok: false, status: 503 })), /ops API HTTP 503/);
});

test("screen (TM-20): every answer's tokens are reported with its project", async () => {
  const seen = [];
  const usageMetadata = { promptTokenCount: 10, candidatesTokenCount: 2 };
  const fetchFn = async () => ({ ok: true, json: async () => ({ usageMetadata, candidates: [{ content: { parts: [{ text: '{"bad":[]}' }] } }] }) });
  const screener = new Screener({ apiKey: "k", model: "m", fetchFn, onUsage: (u) => seen.push(u) });
  await screener.screen([{ correlation_id: "c1", text: "hello", reply: "hi", at: 1 }], "mesiri");
  assert.deepEqual(seen, [{ project: "mesiri", model: "m", usage: usageMetadata }]);
});
