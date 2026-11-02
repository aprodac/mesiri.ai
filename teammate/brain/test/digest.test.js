// TM-26: the weekly digest in the team group.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Digest, digestSql, digestText, sendDay } from "../src/digest.js";

const ROWS = [
  { section: "complaint", name: "missing_feature: add a member from WhatsApp", n: 3 },
  { section: "complaint", name: "bad_ux: too many buttons under the stock answer", n: 1 },
  { section: "cancelled", name: "record_receipt", n: 4 },
  { section: "reason", name: "site", n: 2 },
  { section: "took_back", name: "undo_expense", n: 1 },
  { section: "step", name: "v3_model_tools", n: 40, ms: 2100 },
  { section: "step", name: "v3_facts_memory", n: 40, ms: 420 },
  { section: "step", name: "v3_before", n: 40, ms: 9000 },
  { section: "turns", name: "ok", n: 38, ms: 2800 },
  { section: "turns", name: "failed", n: 2, ms: 900 },
  { section: "verdict", name: "works", n: 5 },
  { section: "verdict", name: "still_wrong", n: 1 },
];
const SINCE = new Date("2026-10-26T03:30:00Z");
const UNTIL = new Date("2026-11-02T03:30:00Z");
const ITEMS = [
  { asked_by: "Ravi (site engineer, Paraclette)", created_at: "2026-10-30T09:20:00Z", started_at: "2026-10-30T09:26:00Z",
    pushed_at: "2026-10-30T09:56:00Z", live_at: "2026-10-30T10:00:00Z", verified: "ok", verified_at: "2026-10-30T11:00:00Z" },
  { created_by: "Ilan", live_at: "2026-10-31T10:00:00Z" },
  { asked_by: "A", live_at: "2026-10-01T10:00:00Z" }, // an older week
];

test("the digest says the four things, in order, without the person's own words", () => {
  const text = digestText({ rows: ROWS, items: ITEMS, since: SINCE, until: UNTIL });
  assert.match(text, /Mesiri this week\* \(2026-10-26 → 2026-11-02\)/);
  assert.match(text, /v3 replies: 40, 2 failed · median 2\.8 s/);
  assert.match(text, /1\. missing feature: add a member from WhatsApp \(3\)/);
  assert.match(text, /Cancelled: record_receipt 4 · why: wrong site 2/);
  assert.match(text, /Taken back \/ corrected: undo_expense 1/);
  assert.match(text, /model_tools: median 2\.1 s \(then facts_memory 420 ms\)/); // v3_before is the journey's, not v3's
  assert.match(text, /Shipped: 2 \(1 asked by users\) · live check 1 ok, 0 broken/);
  assert.match(text, /Testers said: 5 Works ✅ · 1 Still wrong ❌/);
  assert.match(text, /Time per request \(median\): plan 6 min · build 30 min · deploy 4 min/);
});

test("an empty week still reads well", () => {
  const text = digestText({ rows: [], items: [], since: SINCE, until: UNTIL });
  assert.match(text, /None this week/);
  assert.match(text, /Nothing cancelled or taken back/);
  assert.match(text, /No v3 timings this week/);
});

test("Monday from 9:00 India time only; the period is checked", () => {
  assert.equal(sendDay(Date.parse("2026-11-02T03:29:00Z")), null); // Monday 8:59 IST
  assert.equal(sendDay(Date.parse("2026-11-02T03:30:00Z")), "2026-11-02"); // Monday 9:00 IST
  assert.equal(sendDay(Date.parse("2026-11-03T05:00:00Z")), null); // Tuesday
  assert.throws(() => digestSql("2026-11-02'; DROP TABLE x; --"));
  assert.match(digestSql("2026-10-26T03:30:00Z"), /stage = 'release_feedback'/);
});

test("sent once per Monday per project; @bot digest answers now; a failure never throws", async () => {
  const dir = mkdtempSync(join(tmpdir(), "dg-"));
  try {
    const posted = [];
    let now = Date.parse("2026-11-02T04:00:00Z");
    const fetchFn = async () => ({ ok: true, json: async () => ({ columns: ["section", "name", "n", "ms"], rows: ROWS.map((r) => [r.section, r.name, r.n, r.ms ?? null]) }) });
    const d = new Digest({ sources: { mesiri: { url: "u", token: "t" } }, items: async () => ITEMS, notify: async (p, t) => posted.push([p, t]), file: join(dir, "d.json"), fetchFn, now: () => now });
    assert.equal(await d.maybeSend(), 1);
    assert.equal(await d.maybeSend(), 0); // once
    now += 7 * 86_400_000;
    assert.equal(await d.maybeSend(), 1); // next Monday
    assert.equal(posted.length, 2);
    assert.match(await d.command({ text: "digest", project: "mesiri" }), /Top complaints/);
    assert.equal(await d.command({ text: "status", project: "mesiri" }), undefined);
    const broken = new Digest({ sources: { mesiri: { url: "u", token: "t" } }, items: async () => [], notify: async () => {}, file: join(dir, "e.json"), fetchFn: async () => ({ ok: false, status: 502 }), now: () => now });
    assert.equal(await broken.maybeSend(), 0);
    assert.match(await broken.command({ text: "digest", project: "mesiri" }), /Couldn't build the digest/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
