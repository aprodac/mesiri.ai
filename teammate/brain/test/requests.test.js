// TM-19: who asked, the live check after it ships, and whether the person used Mesiri again.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Brain } from "../src/brain.js";
import { mkdirSync, writeFileSync } from "node:fs";
import { whoAsked } from "../src/tools.js";
import { Watchdog } from "../src/watchdog.js";

const ok = (text, id) => ({ type: "result", subtype: "success", is_error: false, result: text, session_id: id, duration_ms: 1, total_cost_usd: 0, permission_denials: [] });
const conv = { who: "h1", person: "Ilan", role: "admin", company: "Paraclette", messages: [{ correlation_id: "cor_1", text: "puthiya project create cheyyanam" }, { correlation_id: "cor_2", text: "ok" }] };

test("whoAsked: the person, their id and words from the watch; a live check's fix inherits them, one round more", () => {
  const a = whoAsked({ watch_conversations: [conv] }, ["cor_1"]);
  assert.deepEqual(a, { asked_for: ["cor_1"], asked_by: "Ilan (admin, Paraclette)", asked_who: "h1", asked_text: "puthiya project create cheyyanam" });
  assert.deepEqual(whoAsked({ watch_conversations: [conv] }, ["nope"]), {});
  const plans = { get: () => ({ id: 81, round: 0, ...a }) };
  const fix = whoAsked({ verify_plan: 81 }, [], plans);
  assert.equal(fix.asked_by, "Ilan (admin, Paraclette)");
  assert.equal(fix.fix_of, 81);
  assert.equal(fix.round, 1);
});

function setup(answer) {
  const dir = mkdtempSync(join(tmpdir(), "req-"));
  const sent = [];
  const items = [];
  const prompts = [];
  let lastCtx = null;
  let plansApi = null;
  const brain = new Brain({
    queryFn: ({ prompt }) => (prompts.push(prompt), (async function* () {
      for (const m of await answer({ ctx: lastCtx, plans: plansApi })) yield m;
    })()),
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      addItem: async () => ({ item: { id: 81 } }),
      updateItem: async (id, b) => (items.push({ id, ...b }), {}),
      chats: async () => ({ chats: [{ jid: "M@g.us", role: "team", project: "mesiri", name: "Mesiri team" }] }),
    },
    tools: (ctx, plans) => ((lastCtx = ctx), (plansApi = plans), {}),
    now: () => new Date("2026-11-01T15:00:00Z"),
  });
  return { brain, sent, items, prompts, ctx: () => lastCtx, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("a shipped plan someone asked for gets ONE live check: marked live, re-tested in a 'verify' turn, never twice", async () => {
  const { brain, items, prompts, ctx, done } = setup(async () => [ok("✅ [81] verified live: the project is created.", "V")]);
  try {
    brain.plans.save({ id: 81, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", title: "Create a project from WhatsApp", plan: "Add create_project to v2.", asked_for: ["cor_1"], asked_by: "Ilan (admin, Paraclette)", asked_text: "puthiya project create cheyyanam" });
    const plan = brain.planStore.plans[81];
    assert.equal(brain.needsVerify(plan), true);
    await brain.verifyLive(plan, "abc1234");
    assert.match(prompts[0], /LIVE CHECK for plan \[81\][\s\S]*asked for by Ilan \(admin, Paraclette\)[\s\S]*puthiya project/);
    assert.equal(ctx().verify_plan, 81);
    assert.equal(ctx().session, "verify");
    assert.ok(items.some((i) => i.id === 81 && i.live_at && i.ref === "abc1234"));
    assert.equal(brain.needsVerify(plan), false);
    assert.equal(brain.needsVerify({ asked_for: ["x"], round: 2 }), false); // a fix of a fix of a fix is left to people
    assert.equal(brain.needsVerify({ approved_by: "an owner" }), false); // nobody asked in production, not autobuild
  } finally {
    done();
  }
});

test("the person who asked using Mesiri again after it went live is recorded once", async () => {
  const { brain, items, done } = setup(async () => []);
  try {
    brain.plans.save({ id: 81, project: "mesiri", chat_project: "mesiri", title: "x", plan: "y", asked_who: "h1", live_at: "2026-11-01T15:00:00Z" });
    const live = Date.parse("2026-11-01T15:00:00Z") / 1000;
    const reviewed = [];
    brain.reviewInUse = async (plan, rows) => reviewed.push([plan.id, rows.length]); // TM-46, tested below
    brain.markTried("mesiri", [{ who: "h1", at: live - 60 }, { who: "h2", at: live + 60 }]);
    assert.equal(brain.planStore.plans[81].tried_at, undefined);
    brain.markTried("mesiri", [{ who: "h1", at: live + 120 }]);
    assert.equal(brain.planStore.plans[81].tried_at, "2026-11-01T15:02:00.000Z");
    await new Promise((r) => setImmediate(r)); // the first check has finished
    brain.markTried("mesiri", [{ who: "h1", at: live + 999 }]);
    await new Promise((r) => setImmediate(r));
    assert.equal(items.filter((i) => i.tried_at).length, 1);
    assert.deepEqual(reviewed, [[81, 1], [81, 1]]); // each new use goes to the real-use check
  } finally {
    done();
  }
});

test("watchdog: the session marked it done; the live check waits for a running deploy, then starts", async () => {
  const calls = [];
  const plan = { id: 81, status: "running_in_cloud", asked_for: ["cor_1"] };
  let deploy = "running";
  const brain = {
    now: () => new Date("2026-11-01T15:00:00Z"),
    planStore: { plans: { 81: plan } },
    savePlans: () => {},
    log: () => {},
    listener: { send: async () => {} },
    workStatus: async () => ({ item: { status: "done" }, commits: [{ sha: "s", short: "abc1234", at: "2026-11-01T14:50:00Z", deploy: { state: deploy } }] }),
    needsVerify: (p) => !p.verify_started,
    verifyLive: async (p, sha) => (calls.push(sha), (p.verify_started = true)),
  };
  const dir = mkdtempSync(join(tmpdir(), "wd-"));
  try {
    const wd = new Watchdog(brain, { dir });
    await wd.check(plan);
    assert.equal(calls.length, 0);
    assert.equal(plan.status, "running_in_cloud");
    deploy = "green";
    await wd.check(plan);
    assert.deepEqual(calls, ["abc1234"]);
    assert.equal(plan.status, "done");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("watchdog: a job started more than 2 days ago is closed quietly, never alerted", async () => {
  const sent = [];
  const old = { id: 30, status: "running_in_cloud", fired_at: "2026-10-18T10:00:00Z" };
  const fresh = { id: 197, status: "running_in_cloud", fired_at: "2026-11-01T14:56:00Z" };
  const checked = [];
  const brain = {
    now: () => new Date("2026-11-01T15:20:00Z"),
    planStore: { plans: { 30: old, 197: fresh } },
    savePlans: () => {},
    log: () => {},
    listener: { send: async (b) => sent.push(b) },
    workStatus: async (p) => (checked.push(p.id), { item: null, commits: [], lastActivityAt: null }),
  };
  const dir = mkdtempSync(join(tmpdir(), "wd-"));
  try {
    await new Watchdog(brain, { dir }).tick();
    assert.equal(old.status, "stale");
    assert.deepEqual(checked, [197]);
    assert.equal(sent.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("owner, 1 Nov: a shipped plan whose asker has no 'it works now' message gets one at once; one that has it doesn't", async () => {
  const root = mkdtempSync(join(tmpdir(), "repo-"));
  try {
    mkdirSync(join(root, "apps/whatsapp-assistant"), { recursive: true });
    const notes = (ids) => writeFileSync(join(root, "apps/whatsapp-assistant/release_notes.json"), JSON.stringify({ notes: [{ id: "x", date: "2026-11-01", for: ids, message: "works now" }] }));
    const { brain, sent, prompts, done } = setup(async () => [ok("✅", "V")]);
    try {
      brain.projects.mesiri.cwd = root;
      brain.prepare = () => {};
      const base = { project: "mesiri", chat_project: "mesiri", chat: "M@g.us", title: "Create a project", plan: "p", asked_for: ["cor_1"], asked_by: "Ilan (admin, Paraclette)" };
      notes(["cor_other"]);
      brain.plans.save({ id: 81, ...base });
      await brain.verifyLive(brain.planStore.plans[81]);
      assert.match(sent.find((m) => /⚠️/.test(m.text)).text, /\[81\] is live, but no "it works now" message names Ilan \(admin, Paraclette\)/);
      assert.match(prompts.at(-1), /FIRST: apps\/whatsapp-assistant\/release_notes\.json has no note for their messages \(cor_1\)[\s\S]*Release note for \[81\]/);

      notes(["cor_2", "cor_1"]);
      brain.plans.save({ id: 82, ...base });
      const warned = () => sent.filter((m) => /⚠️/.test(m.text)).length;
      const before = warned();
      await brain.verifyLive(brain.planStore.plans[82]);
      assert.equal(warned(), before);
      assert.doesNotMatch(prompts.at(-1), /FIRST:/);
    } finally {
      done();
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("TM-46: the person's real use after 'it works now' is judged once per use, with what they did and what Mesiri said", async () => {
  const { brain, prompts, ctx, done } = setup(async ({ plans }) => {
    plans.update(81, { in_use: "broken", in_use_note: "Save still refused", in_use_at: "2026-11-01T15:05:00Z" });
    return [ok("🔧 [81] not right in real use", "R")];
  });
  try {
    brain.plans.save({ id: 81, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", reply_chat: "M@g.us", title: "TMT saves", plan: "bars convert", asked_by: "Ilan (admin, Paraclette)", asked_who: "h1", live_at: "2026-11-01T14:00:00Z" });
    const plan = brain.planStore.plans[81];
    await brain.reviewInUse(plan, [{ who: "h1", at: Date.parse("2026-11-01T14:30:00Z") / 1000, kind: "text", text: "10 TMT bar use aaki", reply: "Ready.", refused: "10 TMT :: expected load" }], "mesiri");
    assert.match(prompts[0], /REAL-USE CHECK for plan \[81\] "TMT saves" \(round 1 of 3\)[\s\S]*Ilan \(admin, Paraclette\)[\s\S]*10 TMT bar use aaki[\s\S]*REFUSED ON SAVE: 10 TMT :: expected load[\s\S]*in_use_verdict/);
    assert.equal(ctx().verify_plan, 81);
    assert.equal(plan.in_use_reviews, 1);
    assert.equal(plan.use_since, "2026-11-01T15:00:00.000Z"); // broken: their next use is judged again
  } finally {
    done();
  }
});

test("TM-46 guard: a plan that works in real use is not judged again; three rounds at most", () => {
  const { brain, done } = setup(async () => []);
  try {
    const reviewed = [];
    brain.reviewInUse = async (plan) => reviewed.push(plan.id);
    const live = Date.parse("2026-11-01T14:00:00Z") / 1000;
    brain.plans.save({ id: 82, project: "mesiri", chat_project: "mesiri", title: "a", plan: "b", asked_who: "h1", live_at: "2026-11-01T14:00:00Z", in_use: "works" });
    brain.plans.save({ id: 83, project: "mesiri", chat_project: "mesiri", title: "a", plan: "b", asked_who: "h1", live_at: "2026-11-01T14:00:00Z", in_use_reviews: 3 });
    brain.markTried("mesiri", [{ who: "h1", at: live + 60 }]);
    assert.deepEqual(reviewed, []);
  } finally {
    done();
  }
});
