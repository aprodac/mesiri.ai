// TM-37: the feedback loop tried for real every morning; only a broken step reaches the group.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { SelfTest, takeSelfTests, TOKEN } from "../src/selftest.js";

function make({ replies = true, arrives = true, aiText = "You have 3 projects.", checks = () => [] } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "selftest-"));
  let t = Date.parse("2026-11-04T03:00:00Z"); // 08:30 IST
  const notes = [];
  const sent = [];
  let st;
  const listener = {
    chats: async () => ({ chats: [{ jid: "TEST@s.whatsapp.net", role: "assistant-test", project: "mesiri" }] }),
    sendStrict: async (b) => {
      sent.push(b);
      const tok = b.text.match(TOKEN);
      if (arrives && tok) setTimeout(() => st.seen(tok[0]), 0);
      return { sent_at: new Date(t).toISOString() };
    },
    messages: async () => ({ messages: replies ? [{ n: 1, from_me: false, kind: "text", text: aiText, at: new Date(t).toISOString() }] : [] }),
  };
  st = new SelfTest({ listener, projects: ["mesiri"], notify: async (p, text) => notes.push(text), file: join(dir, "s.json"),
    now: () => (t += 4_000), pollMs: 1, limits: { reply: 20_000, team: 60_000 }, checks });
  return { st, notes, sent, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("a working loop: both steps pass, nothing is posted, the evening gets one line", async () => {
  const { st, notes, sent, done } = make();
  try {
    const r = await st.run("mesiri");
    assert.equal(r.ok, true, JSON.stringify(r));
    assert.match(sent[0].text, /^mesiri fix it: SELFTEST-20261104-[a-z0-9]{4} \(the team bot's daily check/);
    assert.deepEqual(r.steps.map((s) => s.name), ["Mesiri answered in WhatsApp", "the team bot received the request", "Mesiri's AI answered a question"]);
    assert.equal(notes.length, 0);
    assert.match(st.line("mesiri"), /^• ✅ Feedback loop checked at 08:30: Mesiri answered in WhatsApp \d+ s, team bot received the request \d+ s/);
  } finally {
    done();
  }
});

test("Mesiri silent, or the hand-over broken: the broken step is posted as needs-you", async () => {
  const silent = make({ replies: false });
  try {
    const r = await silent.st.run("mesiri");
    assert.equal(r.ok, false);
    assert.match(silent.notes[0], /🙋 \*Needs you:\* the daily check[\s\S]*❌ Mesiri answered in WhatsApp: no reply/);
  } finally {
    silent.done();
  }
  const lost = make({ arrives: false });
  try {
    await lost.st.run("mesiri");
    assert.match(lost.notes[0], /❌ the team bot received the request: not received in 1 min: the hand-over from Mesiri \(poke\)/);
    assert.match(lost.st.line("mesiri"), /^• ❌ Feedback loop check/);
  } finally {
    lost.done();
  }
});

test("the watch takes the check out (no plan, no build); real requests go on", () => {
  const seen = [];
  const convs = [
    { person: "asus", messages: [{ text: "mesiri fix it: SELFTEST-20261104-ab12 (the team bot's daily check, please ignore)" }] },
    { person: "Ilan", messages: [{ text: "Mesiri add feature" }] },
  ];
  const left = takeSelfTests(convs, (t) => seen.push(t));
  assert.deepEqual(left.map((c) => c.person), ["Ilan"]);
  assert.deepEqual(seen, ["SELFTEST-20261104-ab12"]);
});

// TM-58: a reply without the AI, a push the bot can't make, a key about to expire.
test("Mesiri answering without its AI, or a GitHub login that can't push, is broken; an expiring key is posted", async () => {
  const paused = make({ aiText: "Got it 👍 Mesiri's AI is paused for a short while (the team has been told)." });
  try {
    await paused.st.run("mesiri");
    assert.match(paused.notes[0], /❌ Mesiri's AI answered a question: Mesiri answered without its AI/);
  } finally {
    paused.done();
  }
  const push = make({ checks: () => [{ name: "the bot can push to GitHub", run: async () => ({ ok: false, why: "denied to ilan2004 (403)" }) }] });
  try {
    await push.st.run("mesiri");
    assert.match(push.notes[0], /❌ the bot can push to GitHub: denied to ilan2004 \(403\)/);
  } finally {
    push.done();
  }
  const soon = make({ checks: () => [{ name: "the bot can push to GitHub", run: async () => ({ ok: true, expires: "2026-11-07T00:00:00Z" }) }] });
  try {
    const r = await soon.st.run("mesiri");
    assert.equal(r.ok, true);
    assert.match(soon.notes[0], /expires soon[\s\S]*the bot can push to GitHub: expires 2026-11-07 \(2 days\)/);
  } finally {
    soon.done();
  }
});

// 3 Nov 12:52: the conversation held the 12:41 check's message too; the first token found was the old one.
test("a check finds its own token even when an earlier check's message is in the same conversation", () => {
  const seen = [];
  const convs = [{ person: "asus", messages: [
    { text: "mesiri fix it: SELFTEST-20261103-f6xr (the team bot's daily check, please ignore)" },
    { text: "mesiri fix it: SELFTEST-20261103-x4ca (the team bot's daily check, please ignore)" },
  ] }];
  assert.deepEqual(takeSelfTests(convs, (t) => seen.push(t)), []);
  assert.deepEqual(seen, ["SELFTEST-20261103-f6xr", "SELFTEST-20261103-x4ca"]);
});
