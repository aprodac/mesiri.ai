// 3 Nov: the bot was down all night; the GitHub uptime check ran only every few hours. The listener watches it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { BrainWatch } from "../src/brainwatch.js";

function make(states) {
  let t = Date.parse("2026-11-02T17:30:00Z"); // 23:00 IST
  const posts = [];
  const w = new BrainWatch({ health: async () => states.shift(), post: async (x) => posts.push(x), now: () => (t += 60_000) });
  return { w, posts };
}

test("down for 3 minutes: one needs-you post; back: one post", async () => {
  const { w, posts } = make([{ state: "down" }, { state: "down" }, { state: "down" }, { state: "down" }, { state: "down" }, { state: "up", up_s: 400 }, { state: "up", up_s: 460 }]);
  for (let i = 0; i < 7; i++) await w.tick();
  assert.equal(posts.length, 2);
  assert.match(posts[0], /^🙋 \*Needs you:\* the team bot is not answering since 23:01/);
  assert.match(posts[1], /^✅ The team bot is back \(it was down about 5 min\)/);
});

test("a crash loop (up a few seconds each time) counts as down; a short blip is never posted", async () => {
  const loop = make([{ state: "up", up_s: 4 }, { state: "up", up_s: 3 }, { state: "up", up_s: 5 }, { state: "up", up_s: 2 }]);
  for (let i = 0; i < 4; i++) await loop.w.tick();
  assert.match(loop.posts[0], /keeps restarting/);
  const blip = make([{ state: "down" }, { state: "up", up_s: 40 }, { state: "up", up_s: 100 }]);
  for (let i = 0; i < 3; i++) await blip.w.tick();
  assert.equal(blip.posts.length, 0);
});
