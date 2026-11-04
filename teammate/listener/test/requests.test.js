// TM-19: who asked, what happened after it shipped, and "@bot requests".
import assert from "node:assert/strict";
import { test } from "node:test";
import { Store, itemStage } from "../src/store.js";
import { parseCommand } from "../src/bot.js";

function store() {
  const s = new Store(":memory:");
  s.upsertChat({ jid: "T@g.us", name: "Mesiri team", is_group: true });
  s.db.prepare("UPDATE chats SET role = 'team', project = 'mesiri' WHERE jid = 'T@g.us'").run();
  return s;
}

test("a request keeps who asked, and every later step: held, building, live, verified, tried", () => {
  const s = store();
  const id = s.addItem({ chat_jid: "T@g.us", type: "feature", title: "Create a project from WhatsApp", created_by: "the production watch via bot", asked_by: "Ilan (admin, Paraclette)", asked_ref: "cor_1", asked_who: "abc" });
  assert.equal(s.getItem(id).stage, "asked");
  assert.match(s.getItem(id).log[0].note, /asked by Ilan \(admin, Paraclette\)/);
  s.updateItem(id, { held: "it touches Attendance" });
  assert.equal(s.getItem(id).stage, "waiting");
  s.updateItem(id, { status: "in_progress", note: "approved_by: autobuild" });
  assert.equal(s.getItem(id).held, null); // starting work clears the hold
  assert.equal(s.getItem(id).stage, "building");
  s.updateItem(id, { status: "done", ref: "7798f73", live_at: "2026-11-01T15:00:00Z" });
  assert.equal(s.getItem(id).stage, "live");
  s.updateItem(id, { verified: "ok", note: "re-sent the request: it creates the project" });
  const it = s.getItem(id);
  assert.equal(it.stage, "verified");
  assert.ok(it.verified_at);
  s.updateItem(id, { tried_at: "2026-11-01T16:00:00Z" });
  assert.equal(s.listItems({ project: "mesiri" })[0].tried_at, "2026-11-01T16:00:00Z");
  assert.throws(() => s.updateItem(id, { verified: "maybe" }), /verified must be one of/);
  assert.equal(itemStage({ status: "done", verified: "broken" }), "broken");
  assert.equal(itemStage({ status: "wont_do" }), "dropped");
});

test("@bot requests: counts by stage, a numbered list with who asked, and filters", () => {
  const s = store();
  const a = s.addItem({ chat_jid: "T@g.us", type: "feature", title: "Create a project from WhatsApp", asked_by: "Ilan (admin, Paraclette)" });
  const b = s.addItem({ chat_jid: "T@g.us", type: "bug", title: "Report date is wrong", created_by: "Ravi via bot" });
  s.updateItem(b, { status: "done", ref: "abc1234", live_at: "2026-11-01T15:00:00Z" });
  const all = s.requestsText("mesiri");
  assert.match(all, /📋 \*Requests · mesiri\* \(2\)/);
  assert.match(all, /📥 asked 1 · 🚀 live 1/);
  assert.match(all, /1\. \[\d+\] .+\n    /);
  assert.match(all, new RegExp(`\\[${a}\\] Create a project from WhatsApp · 📥 asked\\n    asked by Ilan \\(admin, Paraclette\\)`));
  assert.match(all, /from Ravi via bot .* commit abc1234/);
  assert.doesNotMatch(s.requestsText("mesiri", "open"), /Report date/);
  assert.doesNotMatch(s.requestsText("mesiri", "done"), /Create a project/);
  assert.doesNotMatch(s.requestsText("mesiri", "users"), /Report date/);
  assert.match(s.requestsText("mesiri", "verified"), /Nothing "verified" to list/);
});

test("the request-list command, in its usual wordings; 'list' alone stays 'who is approved'", () => {
  assert.deepEqual(parseCommand("@bot requests"), { verb: "requests", rest: "" });
  assert.deepEqual(parseCommand("@bot requests open"), { verb: "requests", rest: "open" });
  assert.deepEqual(parseCommand("@bot features"), { verb: "requests", rest: "" });
  assert.deepEqual(parseCommand("@bot list requests"), { verb: "requests", rest: "" });
  assert.deepEqual(parseCommand("@bot send the list of requests"), { verb: "requests", rest: "" });
  assert.deepEqual(parseCommand("@bot list"), { verb: "who", rest: "" });
  assert.equal(parseCommand("@bot requests for the dashboard should be faster").verb, "request"); // a sentence is for Claude
});

// TM-50: one worker per request.
test("a request is held by one worker; finished, stale or taken frees it", () => {
  const s = store();
  const id = s.addItem({ chat_jid: "T@g.us", type: "bug", title: "TMT bars in kg" });
  assert.equal(s.claimItem(id, "Claude Code session ab12cd34").ok, true);
  assert.equal(s.claimItem(id, "Claude Code session ab12cd34").ok, true); // again: still theirs
  const busy = s.claimItem(id, "team bot");
  assert.deepEqual([busy.ok, busy.by], [false, "Claude Code session ab12cd34"]);
  assert.equal(s.claimItem(id, "team bot", { take: true }).item.claimed_by, "team bot");
  assert.match(s.getItem(id).log.at(-1).note, /claimed by team bot \(was Claude Code session ab12cd34\)/);
  s.updateItem(id, { status: "done", ref: "abc1234" });
  assert.equal(s.claimItem(id, "Claude Code session ab12cd34").ok, true); // finished: free
  s.updateItem(id, { status: "in_progress", claimed_by: "someone", claimed_at: "2026-01-01T00:00:00Z" });
  assert.equal(s.claimItem(id, "team bot").ok, true); // stale claim: free
});

test("TM-79: a request sums its Claude usage over turns; bad numbers are refused, not stored", () => {
  const s = store();
  const id = s.addItem({ chat_jid: "T@g.us", type: "bug", title: "Save tap gets no reply" });
  assert.equal(s.getItem(id).usage_turns, null); // nothing used yet
  assert.equal(s.addItemUsage(id, { account: "B (ilan-work)", by: "team bot", cost_usd: 1.25, tokens: 40000, pct_5h: 6, pct_7d: 1.5 }), true);
  s.addItemUsage(id, { account: "A", cost_usd: 0.75, pct_5h: 4 });
  const it = s.getItem(id);
  assert.equal(it.usage_usd, 2);
  assert.equal(it.usage_5h, 10);
  assert.equal(it.usage_7d, 1.5);
  assert.equal(it.usage_turns, 2);
  assert.deepEqual(it.usage_accounts.split(",").sort(), ["A", "B (ilan-work)"]);
  assert.equal(s.listItems({ project: "mesiri" })[0].usage_usd, 2);
  assert.throws(() => s.addItemUsage(id, { pct_5h: 300 }), /usage needs/); // out of range is dropped, and then nothing is left
  assert.equal(s.addItemUsage(9999, { cost_usd: 1 }), false);
});

test("TM-78: the brain's Claude account readings are kept per account, newest wins", () => {
  const s = store();
  s.setClaudeAccounts([{ id: "a", label: "A", five_hour: { pct: 20 } }, { id: "B", label: "B (ilan-work)", five_hour: { pct: 82 } }, { id: "../x" }]);
  s.setClaudeAccounts([{ id: "a", label: "A", five_hour: { pct: 35 } }]);
  const list = s.claudeAccounts();
  assert.deepEqual(list.map((a) => [a.id, a.five_hour.pct]), [["a", 35], ["b", 82]]);
  assert.ok(list[0].seen_at);
});

test("TM-84: a handover pauses the request, lets the claim go, keeps the patch until someone picks it up", () => {
  const s = store();
  const id = s.addItem({ chat_jid: "T@g.us", type: "bug", title: "Save tap gets no reply" });
  s.claimItem(id, "Claude Code session aaaa1111");
  assert.throws(() => s.addHandover(id, { note: " " }), /note is required/);
  assert.throws(() => s.addHandover(id, { note: "n", base: "main; rm -rf" }), /base must be a commit sha/);
  const it = s.addHandover(id, { by: "Claude Code session aaaa1111", account: "B (ilan-work)", base: "4f20ec2", note: "done: test added. left: the fix in agent.py. next: run the test", patch: "diff --git a/x b/x\n" });
  assert.match(it.paused, /^handed over \(account B \(ilan-work\)\): done: test added/);
  assert.equal(it.claimed_by, null); // anyone can take it now
  assert.match(it.log.at(-1).note, /⏸ handover by Claude Code session aaaa1111 with unfinished changes on 4f20ec2/);
  assert.equal(s.openHandover(id).patch, "diff --git a/x b/x\n");
  const h = s.pickHandover(id, "team bot");
  assert.equal(h.base, "4f20ec2");
  const after = s.getItem(id);
  assert.equal(after.paused, null);
  assert.equal(after.claimed_by, "team bot");
  assert.equal(s.openHandover(id), null);
  assert.equal(s.pickHandover(id, "x"), null);
  assert.equal(s.addHandover(9999, { note: "n" }), null);
});
