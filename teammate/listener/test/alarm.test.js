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
