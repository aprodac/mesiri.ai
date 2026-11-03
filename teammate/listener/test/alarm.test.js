// TM-59: alarms also leave without WhatsApp; the WhatsApp link itself is watched.
import assert from "node:assert/strict";
import { test } from "node:test";
import { LinkWatch, sendAlarm } from "../src/alarm.js";

test("an ntfy topic gets plain text, a chat webhook gets JSON, no URL sends nothing", async () => {
  const calls = [];
  const fetchFn = async (url, init) => (calls.push({ url, init }), { ok: true });
  assert.equal(await sendAlarm("https://ntfy.sh/mesiri-team-x7k2", "bot down", { fetchFn }), true);
  assert.equal(calls[0].init.body, "bot down");
  await sendAlarm("https://hooks.slack.com/services/T/B/x", "bot down", { fetchFn });
  assert.deepEqual(JSON.parse(calls[1].init.body), { text: "bot down", content: "bot down" });
  assert.equal(await sendAlarm("", "x", { fetchFn }), false);
  assert.equal(await sendAlarm("https://ntfy.sh/x", "x", { fetchFn: async () => { throw new Error("offline"); } }), false);
});

test("the WhatsApp link down for 5 min: one alarm by the second way, with how to fix a logout; back: one more", async () => {
  let t = Date.parse("2026-11-03T10:00:00Z");
  const states = ["logged_out", "logged_out", "logged_out", "logged_out", "logged_out", "logged_out", "connected", "connected"];
  const sent = [];
  const w = new LinkWatch({ status: () => ({ state: states.shift() }), alarm: async (x) => sent.push(x), now: () => (t += 60_000) });
  for (let i = 0; i < 8; i++) await w.tick();
  assert.equal(sent.length, 2);
  assert.match(sent[0], /^🚨 The team's WhatsApp link is logged out since 15:31 IST[\s\S]*inbox\.py pair/);
  assert.match(sent[1], /^✅ The team's WhatsApp link is connected again/);
});

// TM-61: a nearly full disk is said once, again a day later, and once when it is fine.
test("disk under 10 % or 3 GB free: one alert, a day later another, then fine once", async () => {
  const { DiskWatch } = await import("../src/alarm.js");
  let t = 0;
  let free = 2 * 2 ** 30;
  const posts = [];
  const w = new DiskWatch({ paths: ["/", "/var/lib/x", "/nope"], statfs: async (p) => { if (p === "/nope") throw new Error("ENOENT"); return { blocks: 100 * 2 ** 18, bsize: 4096, bavail: free / 4096 }; },
    post: async (x) => posts.push(x), now: () => t });
  await w.tick();
  assert.match(posts[0], /^🙋 \*Needs you:\* the server's disk is nearly full at \/: 2\.0 GB free \(2 %\)/);
  t += 3600_000; await w.tick(); assert.equal(posts.length, 1);
  t += 86_400_000; await w.tick(); assert.equal(posts.length, 2);
  free = 50 * 2 ** 30; await w.tick();
  assert.match(posts[2], /^✅ Disk space is fine again at \/: 50\.0 GB free/);
});
