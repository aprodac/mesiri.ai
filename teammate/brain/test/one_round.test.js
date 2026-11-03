// TM-63 .. TM-67 (3 Nov 2026: of 6 requests first made that day, 3 needed another round: [207] → [211] [214] [216],
// [209] → [212] [213] [215] [220], [210] → [217] [218]). The end state is named, a second session tries to break the
// build before it is pushed, example lines don't hold a plan, and "first time right" is counted.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain, reviewText, acceptSection } from "../src/brain.js";
import { brainTools, acceptanceRequired } from "../src/tools.js";
import { holdReason } from "../src/autobuild.js";
import { reopens, firstTimeRight, firstTimeRightLine, eveningText } from "../src/board.js";

// ---------- TM-66: example lines don't hold a plan ----------

test("TM-66: [218]'s CLASS line naming attendance no longer holds a materials fix", () => {
  const plan = {
    title: "[210] still broken: add Primer + drum size + receipt in one Save fails",
    plan: "FIX (code, v3 Save path in agent_api/agent.py): Save runs dependent items in order.\n"
      + "CLASS: new vendor + expense; new project + its site + a receipt there; new worker + attendance; voice/text.\n"
      + "GUARDS: an exact existing material saves with no question.",
  };
  assert.equal(holdReason(plan), null);
});

test("guard TM-66: a plan that changes attendance is still held, wherever the FIX line says it", () => {
  assert.match(holdReason({ title: "Fix shift totals", plan: "FIX: attendance correction replaces the shift instead of adding.\nCLASS: voice/text." }), /Attendance/);
  assert.match(holdReason({ title: "Attendance: shift correction adds instead of replacing", plan: "CLASS: labour." }), /Attendance/);
});

// ---------- TM-63: propose_plan needs the end state ----------

function planTools(ctx) {
  const saved = [];
  const listener = { send: async () => ({}), addItem: async () => ({ item: { id: 230 } }), updateItem: async () => ({}) };
  const server = brainTools({ ctx, listener, render: null, plans: { save: (p) => (saved.push(p), p), all: () => [] }, screenshotHosts: [] });
  const tools = Object.fromEntries(Object.entries(server.instance._registeredTools));
  const call = (name, args) => (tools[name].callback || tools[name].handler)(args, {});
  return { call, saved, tools };
}

test("TM-63: a product plan without accept is refused and says what to give", async () => {
  const { call, saved } = planTools({ project: "mesiri", chat: "T@g.us", chat_name: "Team", reply_chat: "T@g.us", sender: "watch", autobuild: true, new_plans: [] });
  const r = await call("propose_plan", { title: "Primer receipt dropped", plan: "Fix the Save order in agent.py." });
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /accept: 1-8 lines.*whole journey/s);
  assert.equal(saved.length, 0);
});

test("TM-63: accept is kept on the plan and reaches the build prompt", async () => {
  const { call, saved } = planTools({ project: "mesiri", chat: "T@g.us", chat_name: "Team", reply_chat: "T@g.us", sender: "watch", autobuild: true, new_plans: [] });
  const accept = ["after Save: material Primer exists", "40 L Primer received at Green Villa, Kakkanad"];
  const r = await call("propose_plan", { title: "Primer receipt dropped", plan: "Fix the Save order in agent.py.", accept });
  assert.match(r.content[0].text, /Plan \[230\] recorded/);
  assert.deepEqual(saved[0].accept, accept);
  const section = acceptSection(saved[0]);
  assert.match(section, /WHOLE journey/);
  assert.match(section, /- 40 L Primer received at Green Villa, Kakkanad/);
  assert.match(section, /ACCEPTANCE: <test file/);
});

test("guard TM-63: bot upgrades, auto cycles and plans waiting for @bot ok don't need accept", async () => {
  assert.equal(acceptanceRequired({ autobuild: true, session: "upgrade" }), false);
  assert.equal(acceptanceRequired({ autobuild: true, auto_cycle: 3 }), false);
  assert.equal(acceptanceRequired({}), false);
  assert.equal(acceptanceRequired({ verify_plan: 7 }), true);
  const { call, saved } = planTools({ project: "mercon", chat: "C@g.us", chat_name: "Mercon", reply_chat: "C@g.us", sender: "Ilan" });
  await call("propose_plan", { title: "New driver count card", plan: "Count only active drivers." });
  assert.equal(saved.length, 1);
  assert.equal(saved[0].accept, undefined);
});

test("TM-64: review_result is offered only to a breaker review, and a prompt-only fix never passes", async () => {
  assert.equal(planTools({ project: "mesiri", chat: "T", reply_chat: "T", sender: "x" }).tools.review_result, undefined);
  const got = [];
  const { call } = planTools({ project: "mesiri", chat: "T", reply_chat: "T", sender: "x", review_of: 230, review_round: 1, review_sink: (r) => got.push(r) });
  await call("review_result", { ok: true, acceptance_covered: true, failures: [], passed: ["other wording"], prompt_only: true });
  assert.equal(got[0].ok, false);
  await call("review_result", { ok: true, acceptance_covered: false, failures: [], passed: [] });
  assert.equal(got[1].ok, false);
  await call("review_result", { ok: true, acceptance_covered: true, failures: [], passed: ["next step through Save"] });
  assert.equal(got[2].ok, true);
});

// ---------- TM-64: the breaker review gates the push ----------

const NOW = Date.parse("2026-11-03T17:10:00Z");

function make({ verdicts, pending = { ahead: 2, files: ["apps/whatsapp-assistant/src/agent_api/agent.py"], stat: " agent.py | 12 +++", uncommitted: [] } }) {
  const dir = mkdtempSync(join(tmpdir(), "oneround-"));
  const sent = [];
  const notes = [];
  const brain = new Brain({
    queryFn: () => {
      throw new Error("no AI turn in these tests");
    },
    projects: { mesiri: { cwd: "/r", buildCwd: "/b", branch: "main", flow: "f" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true }), addItem: async () => ({}), updateItem: async (id, b) => (notes.push([id, b]), {}) },
    tools: () => ({}),
    prepareBuild: () => {},
    pendingWork: () => pending,
    now: () => new Date(NOW),
  });
  const turns = [];
  let v = 0;
  brain.turn = async (req) => {
    turns.push(req);
    if (req.review_of != null) {
      const next = verdicts[v++];
      if (next) req.review_sink({ round: req.review_round, passed: [], failures: [], acceptance_covered: true, prompt_only: false, ...next });
    }
    return { ok: true };
  };
  const plan = { id: 230, title: "Primer receipt dropped", project: "mesiri", chat: "T@g.us", reply_chat: "T@g.us", plan: "Fix the Save order.", accept: ["40 L Primer received at Green Villa"] };
  brain.planStore.plans[230] = plan;
  const say = (text) => sent.push({ text });
  return { dir, brain, plan, sent, notes, turns, say };
}

const kinds = (turns) => turns.map((t) => (t.review_of != null ? "review" : t.hold_push ? "build" : "ship"));

test("TM-64: build (no push) → breaker review passes → the build is told to push", async () => {
  const { dir, brain, plan, turns, say } = make({ verdicts: [{ ok: true, passed: ["Manglish wording", "next step through Save"] }] });
  try {
    await brain.buildHere(plan, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say, announce: false });
    assert.deepEqual(kinds(turns), ["build", "review", "ship"]);
    assert.match(turns[0].text, /COMMIT, but DON'T PUSH/);
    assert.match(turns[0].text, /Acceptance \(TM-63\)/);
    assert.equal(turns[1].session, "review");
    assert.match(turns[1].text, /BREAKER REVIEW \(TM-64\) of plan \[230\]/);
    assert.match(turns[1].text, /- 40 L Primer received at Green Villa/);
    assert.match(turns[2].text, /review passed \(Manglish wording; next step through Save\)/);
    assert.match(turns[2].text, /git push origin HEAD:main/);
    assert.equal(plan.reviews.length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("TM-64: a failed review goes back to the build, is reviewed again, then shipped", async () => {
  const { dir, brain, plan, turns, notes, say } = make({
    verdicts: [{ ok: false, failures: [{ case: "talk about Live Mart B, then '2 drum thinner vannu'", why: "site taken from the last project named" }] }, { ok: true }],
  });
  try {
    await brain.buildHere(plan, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say, announce: false });
    assert.deepEqual(kinds(turns), ["build", "review", "build", "review", "ship"]);
    assert.match(turns[2].text, /found this still wrong[\s\S]*Live Mart B[\s\S]*Don't push yet/);
    assert.ok(notes.some(([, b]) => /breaker review round 1: 1 still wrong/.test(b.note || "")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("TM-64: still wrong after 2 rounds: nothing is pushed and the group is told what fails", async () => {
  const bad = { ok: false, failures: [{ case: "voice note in Malayalam", why: "receipt still dropped" }] };
  const { dir, brain, plan, turns, sent, notes, say } = make({ verdicts: [bad, bad] });
  try {
    await brain.buildHere(plan, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say, announce: false });
    assert.deepEqual(kinds(turns), ["build", "review", "build", "review"]);
    assert.equal(plan.status, "review_failed");
    assert.match(sent.at(-1).text, /❌ \[230\].*not pushed[\s\S]*voice note in Malayalam[\s\S]*@bot tell 230 push/);
    assert.ok(notes.some(([, b]) => /breaker review: still wrong after 2 rounds/.test(b.held || "")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("TM-64: a review that can't finish doesn't block the fix; the ship turn says it wasn't reviewed", async () => {
  const { dir, brain, plan, turns, say } = make({ verdicts: [null] });
  try {
    await brain.buildHere(plan, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say, announce: false });
    assert.deepEqual(kinds(turns), ["build", "review", "ship"]);
    assert.match(turns[2].text, /not reviewed: the review didn't finish/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("guard TM-64: a build that committed nothing skips the review; '@bot tell <n> push' ships without one", async () => {
  const empty = make({ verdicts: [], pending: { ahead: 0, files: [], stat: "", uncommitted: [] } });
  try {
    await empty.brain.buildHere(empty.plan, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say: empty.say, announce: false });
    assert.deepEqual(kinds(empty.turns), ["build", "ship"]);
    assert.match(empty.turns[1].text, /not reviewed: the build committed nothing/);
  } finally {
    rmSync(empty.dir, { recursive: true, force: true });
  }
  const m = make({ verdicts: [] });
  try {
    await m.brain.buildHere(m.plan, { project: "mesiri", by: "Ilan", reply_chat: "T@g.us", say: m.say, announce: false, review: false });
    assert.deepEqual(kinds(m.turns), ["ship"]);
  } finally {
    rmSync(m.dir, { recursive: true, force: true });
  }
});

test("TM-64: a held turn can't push and isn't marked done; the ship turn can", async () => {
  const dir = mkdtempSync(join(tmpdir(), "oneround-"));
  const calls = [];
  let pushed = 0;
  const updates = [];
  const brain = new Brain({
    queryFn: ({ options }) => (calls.push(options), (async function* () { yield { type: "result", subtype: "success", result: "built", session_id: "S", duration_ms: 1, total_cost_usd: 0, permission_denials: [] }; })()),
    projects: { mesiri: { cwd: "/r", buildCwd: "/b", branch: "main", flow: "f" } },
    dir,
    listener: { send: async () => ({ ok: true }), addItem: async () => ({}), updateItem: async (id, b) => (updates.push(b), {}) },
    tools: () => ({}),
    pushBuild: () => (pushed++, { ahead: 0, pushed: false, error: null }),
  });
  try {
    const plan = { id: 231, title: "t", project: "mesiri", chat: "T@g.us", status: "running_here" };
    const req = { project: "mesiri", reply_project: "mesiri", chat: "T@g.us", chat_name: "Team", chat_role: "team", reply_chat: "T@g.us", sender: "autobuild", n: null, text: "x", session: "build", build_here: true };
    brain.settings = { mesiri: { model: "claude-sonnet-5-5" } };
    await brain.turn({ ...req, hold_push: true }, "working", plan);
    assert.ok(calls[0].disallowedTools.includes("Bash(git push*)"));
    assert.equal(calls[0].model, "claude-opus-5-5"); // a build is on Opus whatever the group's chat model
    assert.equal(pushed, 0);
    assert.equal(plan.status, "running_here");
    assert.ok(!updates.some((u) => u.status === "done"));
    await brain.turn(req, "working", plan);
    assert.ok(!calls[1].disallowedTools.includes("Bash(git push*)"));
    assert.equal(pushed, 1);
    assert.ok(updates.some((u) => u.status === "done"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("TM-64: the review prompt asks for the next step, another way in, and code over prompt lines", () => {
  const text = reviewText({ id: 220, title: "Deliveries go to today's site", plan: "Site default in code." }, { ahead: 1, stat: " whatsapp.py | 4 ++" }, { round: 1, rounds: 2 });
  assert.match(text, /NEXT step/);
  assert.match(text, /the same mistake reached another\s+way/);
  assert.match(text, /prompt_only/);
  assert.match(text, /never push/);
});

// ---------- TM-67: first time right ----------

const item = (id, title, extra = {}) => ({ id, title, created_at: "2026-11-03T03:00:00Z", ...extra });
const DAY3 = [
  item(207, "v3: add a team member to a project from WhatsApp", { live_at: "2026-11-03T09:00:00Z", status: "done" }),
  item(211, "[207] marked done but not working: add project member still refused"),
  item(214, "[207]/[211] were never built: add project member from WhatsApp"),
  item(209, "v3: after creating a project, the next update goes to that new project", { live_at: "2026-11-03T09:00:00Z", status: "wont_do" }),
  item(213, "[209] closed without a fix: updates still go to the project just created"),
  item(215, "[212] never reached main: after creating a project, the next update must default to today's site"),
  item(218, "[210] still broken: add Primer + drum size + receipt in one Save fails"),
  item(217, "[210] follow-up: new material + drum conversion fails"),
  item(210, "v3: primer saved as Paint", { live_at: "2026-11-03T11:00:00Z", status: "done" }),
  item(219, "A pending question swallows the next, unrelated message", { live_at: "2026-11-03T12:00:00Z", status: "done" }),
  item(205, "v3: renamed project create vanished", { live_at: "2026-11-03T08:00:00Z", status: "done", verified: "ok" }),
  item(221, "[bot upgrade] faster cards", { live_at: "2026-11-03T08:00:00Z" }),
  item(222, "Old request", { created_at: "2026-10-20T03:00:00Z", live_at: "2026-11-03T08:00:00Z" }),
];

test("TM-67: re-opens are read from the titles the watch writes", () => {
  assert.deepEqual(reopens(DAY3[1]), [207]);
  assert.deepEqual(reopens(DAY3[2]), [207, 211]);
  assert.deepEqual(reopens(DAY3[4]), [209]);
  assert.deepEqual(reopens(DAY3[5]), [212]);
  assert.deepEqual(reopens(DAY3[7]), [210]);
  assert.deepEqual(reopens(item(1, "x", { summary: "RE-OPENS [209] (deployed e9c9b6b)" })), [209]);
  assert.deepEqual(reopens(DAY3[9]), []);
});

test("TM-67: 3 Nov counts 2 of 5 first time right; upgrades, re-opens and older requests are left out", () => {
  const since = Date.parse("2026-11-03T00:00:00Z");
  assert.deepEqual(firstTimeRight(DAY3, since), { right: 2, total: 5, missed: [207, 209, 210] });
  assert.equal(firstTimeRightLine(DAY3, since), "First time right: 2 of 5 (40%) · needed another round: [207] [209] [210]");
  assert.equal(firstTimeRightLine([], since), null);
  const broken = [item(1, "a", { live_at: "x", verified: "in_use_broken" })];
  assert.deepEqual(firstTimeRight(broken, since).missed, [1]);
});

test("TM-67: the evening summary carries the 7-day number", () => {
  const text = eveningText(DAY3, Date.parse("2026-11-03T13:30:00Z"));
  assert.match(text, /🎯 First time right: 2 of 5 \(40%\)/);
});
