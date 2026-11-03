// TM-49 (3 Nov): 46 bot messages and 1 from a person in a day; the team couldn't follow. Only news and questions reach
// the group; work in progress is filed under its request. The lines are the real ones from 3 Nov.
import assert from "node:assert/strict";
import { test } from "node:test";
import { destination, planOf, quietSend } from "../src/quiet.js";
import { boardText, eveningText, stageOf } from "../src/board.js";

const history = [
  "📥 #cf124a · *Ilan* (ADMIN, Paraclette) told Mesiri: missing feature: add a team member ⏎ Looking into it now; the plan follows here in a few minutes.",
  "▶️ Building [207] v3: add a team member to a project from WhatsApp here on the bot's server (warm build copy). I'll post progress and the result here.",
  "🛠 Building [207]: add a team member to a project from WhatsApp + stop duplicate \"Rana Mart\" creates",
  "↩️ [209] v3: after creating a project …: the build was cut off when the bot restarted. Starting it again from the current main.",
  "🔓 [210] v3: \"primer\" saved as \"Paint\" isn't held any more; starting it now.",
  "[203] pushed c1f9449 “WA-149 [205]: a waiting entry is corrected in place”, deploy green ✅.",
  "[205] progress: found both causes in code.",
  "[203] landed but didn't report: c1f9449 is deployed (green) and the session said nothing for 20 min.",
  "⚠️ No preview went to Ilan for #cf124a (the watch turn did not send one).",
  "🔐 *Needs your permission*\nWhile working I was blocked from:\n• Bash: cat src/agent_api/units.py",
  "*Production watch:* nothing new, so no new plan. It's the same conversation as [206].",
];
const group = [
  "*Production watch:* Ilan (ADMIN, Paraclette), 23:11–00:59. *1 new plan* (chat above). …",
  "✅ [203] verified live: Ilan's exact message now saves both lines.",
  "[207] is built and tested, but *not pushed*: GitHub refused the push (403).",
  "🙋 *Needs you* ✋ [208] Bot upgrade: post_fixed_card always fails\nWaiting for an owner because it touches the bot itself.",
  "🔐 *Needs a credential*\nThe GitHub token can't push.",
  "Thanks Ilan. I can't give myself that permission from here.",
];

test("work in progress is history; news, problems, questions and replies reach the group", () => {
  for (const t of history) assert.equal(destination({ text: t }), "history", t);
  for (const t of group) assert.equal(destination({ text: t }), "group", t);
  assert.equal(destination({ caption: "👀 Preview sent to Ilan #cf124a: …" }), "history");
  assert.equal(destination({ caption: "[207] Ilan (ADMIN) · Paraclette · \"add Sahal\" not possible in chat" }), "group"); // the conversation picture: context
  assert.equal(planOf("↩️ [209] v3: …"), 209);
});

test("history goes to its request's log; 1-on-1 chats and the switch-off are untouched", async () => {
  const sent = [];
  const notes = [];
  const send = quietSend(async (b) => (sent.push(b), { ok: true }), async (id, b) => notes.push({ id, ...b }));
  await send({ chat: "T@g.us", project: "mesiri", text: history[1] });
  await send({ chat: "T@g.us", project: "mesiri", text: group[1] });
  await send({ chat: "999@s.whatsapp.net", project: "mesiri", text: history[1] });
  assert.deepEqual(sent.map((b) => b.chat), ["T@g.us", "999@s.whatsapp.net"]);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].id, 207);
  assert.match(notes[0].note, /^🗒 ▶️ Building \[207\]/);
  const off = [];
  await quietSend(async (b) => off.push(b), async () => {}, { on: false })({ chat: "T@g.us", text: history[1] });
  assert.equal(off.length, 1);
});

const NOW = Date.parse("2026-11-03T14:00:00Z"); // 19:30 IST
const items = [
  { id: 207, title: "v3: add a team member to a project", status: "in_progress", started_at: "2026-11-03T03:26:00Z", created_at: "2026-11-03T03:25:00Z", asked_by: "Ilan (ADMIN, Paraclette)" },
  { id: 208, title: "[bot upgrade] post_fixed_card fails", status: "open", held: "it touches the bot itself", created_at: "2026-11-03T03:33:00Z" },
  { id: 205, title: "renamed project create vanished", status: "done", verified: "ok", live_at: "2026-11-03T03:26:00Z", updated_at: "2026-11-03T03:33:00Z", created_at: "2026-11-02T17:00:00Z" },
  { id: 150, title: "old", status: "done", updated_at: "2026-10-20T03:33:00Z", created_at: "2026-10-20T03:00:00Z" },
];

test("@bot status: open requests, the one that needs you first, in plain words", () => {
  const text = boardText(items, NOW);
  assert.match(text, /^\*Open requests: 2\* · 🙋 1 needs you/);
  assert.ok(text.indexOf("[208]") < text.indexOf("[207]"));
  assert.match(text, /\[208\] bot: post_fixed_card fails\n {3}🙋 waiting for you/);
  assert.match(text, /\[207\] .* · asked by Ilan\n {3}🛠 being built/);
  assert.match(text, /Done today:_ \[205\]/);
  assert.doesNotMatch(text, /\[150\]/);
  assert.equal(stageOf({ status: "in_progress", pushed_at: "x" }).key, "deploying");
});

test("the evening summary: four lines; nothing on a quiet day", () => {
  const text = eveningText(items, NOW);
  assert.match(text, /2 new requests \(\[207\] \[208\]\)/);
  assert.match(text, /✅ 1 went live \(\[205\]\), 1 confirmed/);
  assert.match(text, /🛠 1 being built \(\[207\]\)/);
  assert.match(text, /🙋 Needs you: \[208\] bot: post_fixed_card fails \(reply @bot ok 208\)/);
  assert.equal(eveningText([items[3]], NOW), null);
});

// TM-60: a cap says what it waits for; an unanswered 🙋 is brought back.
test("a capped plan waits without asking anyone; a needs-you is listed in the morning and reminded once after 3 h", async () => {
  assert.match(stageOf({ id: 9, status: "open", held: "today's 12 automatic builds are used" }).text, /^⏸ waiting: today's 12 automatic builds are used \(@bot ok 9 builds it now\)/);
  assert.equal(stageOf({ id: 9, status: "open", held: "today's 12 automatic builds are used" }).you, false);
  const { Reminders } = await import("../src/board.js");
  const { mkdtempSync, rmSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const dir = mkdtempSync(join(tmpdir(), "rem-"));
  let t = Date.parse("2026-11-04T03:40:00Z"); // 09:10 IST
  const posts = [];
  const waiting = [{ id: 207, title: "add a team member", status: "in_progress", held: "built, not on GitHub: 403", updated_at: "2026-11-04T03:30:00Z" }];
  const r = new Reminders({ projects: ["mesiri"], items: async () => waiting, notify: async (p, x) => posts.push(x), file: join(dir, "r.json"), now: () => t });
  try {
    await r.tick();
    assert.match(posts[0], /^\*Good morning\. Waiting on you:\*\n• \[207\] add a team member: built, not on GitHub: 403/);
    t += 2 * 3600_000; await r.tick(); // 11:10: too soon
    assert.equal(posts.length, 1);
    t += 4.5 * 3600_000; await r.tick(); // 15:40: waited 3 h+, last reminder 6 h+ ago
    assert.match(posts[1], /^🙋 \*Still waiting on you:\*\n• \[207\]/);
    t += 6 * 3600_000; await r.tick(); // 21:40: night, nothing
    assert.equal(posts.length, 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
