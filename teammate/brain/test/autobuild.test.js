// TM-18: plans start building without "@bot ok", except what CLAUDE.md still reserves for an owner.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AutoBuild, holdReason, touchedText } from "../src/autobuild.js";

const plan = (text, title = "Create a project from WhatsApp", extra = {}) => ({ id: 7, title, plan: text, status: "proposed", ...extra });

test("a product plan, roles included, is not held; the reserved modules and data changes are", () => {
  assert.equal(holdReason(plan("Add create_project to v2 for admins and site engineers (a role check in the tool). Tests: evals.")), null);
  assert.equal(holdReason(plan("Additive migration 0497: a new nullable column for the project code.")), null);
  assert.match(holdReason(plan("Change how attendance is counted for the day.")), /Attendance/);
  assert.match(holdReason(plan("Show the payroll total on the card.")), /Payroll/);
  assert.match(holdReason(plan("Migration: drop column legacy_code and backfill the codes.")), /existing data/);
  assert.match(holdReason(plan("Rotate the API key the webhook uses.")), /secrets/);
  assert.match(holdReason(plan("Relax the tenant check on /projects.")), /tenant/);
  assert.match(holdReason(plan("Edit .github/workflows/deploy.yml to skip a step.")), /CI/);
  assert.match(holdReason(plan("Fix teammate/brain/src/brain.js.")), /bot itself/);
  assert.match(holdReason(plan("anything", "x", { session: "upgrade" })), /bot itself/);
});

test("a sentence that says what stays untouched is not a reason to hold", () => {
  const text = "Add create_project to v2. Labour, Attendance, Payroll and Workforce are untouched. No migration.";
  assert.doesNotMatch(touchedText(text), /Labour/);
  assert.equal(holdReason(plan(text)), null);
  assert.match(holdReason(plan("Add create_project. Also change the attendance card wording.")), /Attendance/);
  // Ilan, 1 Nov: Labour is a normal module.
  assert.equal(holdReason(plan("Labour shift correction adds instead of replacing (20 -> day total 40): fix change_line for labour lines.")), null);
});

test("on by default, owners switch it in the team group, the daily cap holds, and it lasts across restarts", () => {
  const dir = mkdtempSync(join(tmpdir(), "ab-"));
  try {
    const file = join(dir, "autobuild.json");
    const ab = new AutoBuild({ file, now: () => Date.parse("2026-11-01T06:00:00Z"), perDay: 2, defaultOn: true });
    const ok = plan("Add create_project to v2.");
    assert.equal(ab.decide(ok, "mesiri"), null);
    ab.started("mesiri");
    ab.started("mesiri");
    assert.match(ab.decide(ok, "mesiri"), /2 automatic builds are used/);

    const member = { text: "autobuild", project: "mesiri", sender_role: "member" };
    assert.match(ab.command(member), /\*on\*/);
    assert.equal(ab.command({ ...member, text: "show me the dpr" }), undefined);
    assert.equal(ab.command({ ...member, text: "autobuild off" }), "Only an owner can switch autobuild.");
    assert.equal(ab.command({ ...member, text: "autobuild off", sender_role: "owner", dm: true }), "Autobuild can be switched in the team group only.");
    assert.match(ab.command({ ...member, text: "auto build off", sender_role: "owner", sender: "Ilan" }), /\*off\*/);

    const again = new AutoBuild({ file, now: () => Date.parse("2026-11-01T07:00:00Z"), perDay: 2, defaultOn: true });
    assert.equal(again.isOn("mesiri"), false);
    assert.equal(again.decide(ok, "mesiri"), "autobuild is off");
    assert.equal(again.today("mesiri").n, 2);
    const tomorrow = new AutoBuild({ file, now: () => Date.parse("2026-11-02T06:00:00Z"), perDay: 2, defaultOn: true });
    assert.equal(tomorrow.today("mesiri").n, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// -- the brain: a planning turn's plan starts in the cloud as "autobuild"; a held one waits for @bot ok --
import { Brain } from "../src/brain.js";

const ok = (text, id) => ({ type: "result", subtype: "success", is_error: false, result: text, session_id: id, duration_ms: 1, total_cost_usd: 0, permission_denials: [] });

function brainWith(planText) {
  const dir = mkdtempSync(join(tmpdir(), "abb-"));
  const sent = [];
  const fired = [];
  const items = [];
  let lastCtx = null;
  let plansApi = null;
  const brain = new Brain({
    queryFn: () =>
      (async function* () {
        const saved = plansApi.save({ id: 81, project: "mesiri", chat_project: "mesiri", chat: lastCtx.chat, chat_name: "Mesiri team", session: lastCtx.session, title: "Create a project from WhatsApp", plan: planText, by: lastCtx.sender });
        lastCtx.new_plans?.push(saved.id); // what propose_plan does (tools.js)
        yield ok("*[81] Ravi (admin) asked to create a project.* Building it now.", "S1");
      })(),
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true }), addItem: async () => ({ item: { id: 81 } }), updateItem: async (id, b) => items.push({ id, ...b }) },
    tools: (ctx, plans) => ((lastCtx = ctx), (plansApi = plans), {}),
    routines: { mesiri: { url: "https://x/fire", token: "t" } },
    fireFn: async (routine, text) => (fired.push(text), { claude_code_session_id: "cse_9" }),
    now: () => new Date("2026-11-01T06:00:00Z"),
  });
  const ask = (extra = {}) => brain.askWatch("mesiri", "Production watch …", "NOTHING_TO_REPORT", []).then(() => extra);
  brain.listener.chats = async () => ({ chats: [{ jid: "M@g.us", role: "team", project: "mesiri", name: "Mesiri team" }] });
  return { brain, sent, fired, items, ask, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("brain: the watch's plan is built right after the report, approved by autobuild, with no @bot ok", async () => {
  const { brain, sent, fired, items, ask, done } = brainWith("Add create_project to v2 for admins and site engineers. Labour untouched.");
  try {
    await ask();
    assert.equal(fired.length, 1);
    assert.match(fired[0], /Approved by: autobuild \(TM-18/);
    assert.match(fired[0], /Plan \[81\]: Create a project from WhatsApp/);
    const texts = sent.map((m) => m.text);
    assert.match(texts[0], /Building it now/); // the report first
    assert.match(texts[1], /▶️ Working on \[81\][\s\S]*claude\.ai\/code\/session_9/);
    assert.equal(brain.planStore.plans[81].approved_by, "autobuild");
    assert.ok(items.some((i) => i.id === 81 && i.status === "in_progress"));
    assert.equal(brain.autobuild.today("mesiri").n, 1);
  } finally {
    done();
  }
});

test("brain: a plan that touches Attendance is posted with the reason and waits for @bot ok", async () => {
  const { brain, sent, fired, ask, done } = brainWith("Change how attendance is counted for the day.");
  try {
    await ask();
    assert.equal(fired.length, 0);
    assert.match(sent.at(-1).text, /✋ \[81\][\s\S]*touches Attendance[\s\S]*@bot ok 81/);
    assert.equal(brain.planStore.plans[81].status, "proposed");
  } finally {
    done();
  }
});

test("brain: after a restart a plan that is no longer held starts; one still held and old ones stay", async () => {
  const { brain, sent, fired, done } = brainWith("unused");
  try {
    const at = "2026-11-01T05:00:00.000Z"; // the fake clock is 06:00
    brain.planStore.plans[199] = { id: 199, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", session: "watch", title: "Labour shift correction adds instead of replacing", plan: "Fix change_line for labour lines.", status: "proposed", at };
    brain.planStore.plans[200] = { id: 200, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", session: "watch", title: "Payroll card", plan: "Show payroll.", status: "proposed", at };
    brain.planStore.plans[150] = { id: 150, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", session: "main", title: "Old", plan: "x", status: "proposed", at: "2026-10-30T05:00:00.000Z" };
    await brain.retryHeld();
    assert.equal(fired.length, 1);
    assert.match(fired[0], /Plan \[199\]/);
    assert.match(sent[0].text, /🔓 \[199\][\s\S]*starting it now/);
    assert.equal(brain.planStore.plans[200].status, "proposed");
    assert.equal(brain.planStore.plans[150].status, "proposed");
  } finally {
    done();
  }
});

function hereBrain({ prepareBuild }) {
  const dir = mkdtempSync(join(tmpdir(), "abh-"));
  const sent = [];
  const fired = [];
  const items = [];
  const cwds = [];
  let lastCtx = null;
  let plansApi = null;
  const brain = new Brain({
    queryFn: ({ options }) =>
      (async function* () {
        cwds.push({ cwd: options.cwd, venv: options.env.VIRTUAL_ENV || null });
        if (cwds.length === 1) {
          const saved = plansApi.save({ id: 81, project: "mesiri", chat_project: "mesiri", chat: lastCtx.chat, chat_name: "Mesiri team", session: lastCtx.session, title: "Add a tool", plan: "Add the expense route to v3.", by: lastCtx.sender });
          lastCtx.new_plans?.push(saved.id);
        }
        yield ok(cwds.length === 1 ? "Building it now." : "Pushed abc1234.", `S${cwds.length}`);
      })(),
    projects: { mesiri: { name: "mesiri", branch: "main", cwd: "/r/mesiri", buildCwd: "/b/mesiri", flow: "claude.md" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true }), addItem: async () => ({ item: { id: 81 } }), updateItem: async (id, b) => items.push({ id, ...b }) },
    tools: (ctx, plans) => ((lastCtx = ctx), (plansApi = plans), {}),
    routines: { mesiri: { url: "https://x/fire", token: "t" } },
    fireFn: async (routine, text) => (fired.push(text), { claude_code_session_id: "cse_9" }),
    prepareBuild,
    now: () => new Date("2026-11-01T06:00:00Z"),
  });
  brain.listener.chats = async () => ({ chats: [{ jid: "M@g.us", role: "team", project: "mesiri", name: "Mesiri team" }] });
  brain.autobuild.whereCommand({ text: "build here", project: "mesiri", sender_role: "owner", sender: "Ilan" });
  const ask = () => brain.askWatch("mesiri", "Production watch …", "NOTHING_TO_REPORT", []);
  return { brain, sent, fired, items, cwds, ask, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("TM-31: with 'build here' the plan is built in the build copy, not in the cloud, and stays followed", async () => {
  let prepared = 0;
  const { brain, sent, fired, items, cwds, ask, done } = hereBrain({ prepareBuild: () => (prepared += 1, "warm") });
  try {
    await ask();
    for (let i = 0; i < 20 && cwds.length < 2; i++) await new Promise((r) => setTimeout(r, 5)); // the build queue
    assert.equal(fired.length, 0);
    assert.equal(prepared, 1);
    assert.deepEqual(cwds.map((c) => c.cwd), ["/r/mesiri", "/b/mesiri"]); // planning in the shared copy, build in its own
    assert.equal(cwds[1].venv, "/b/mesiri/.venv");
    assert.ok(sent.some((m) => /▶️ Building \[81\][\s\S]*bot's server/.test(m.text)));
    assert.equal(brain.planStore.plans[81].status, "running_here"); // the watchdog follows its commit and deploy
    assert.ok(items.some((i) => i.id === 81 && i.status === "done" && /built here/.test(i.note)));
    assert.ok(items.some((i) => i.id === 81 && i.started_at));
  } finally {
    done();
  }
});

test("TM-31: when the build copy can't be made ready, the plan is built in the cloud as before", async () => {
  const { brain, sent, fired, cwds, ask, done } = hereBrain({ prepareBuild: () => { throw new Error("uv: not found"); } });
  try {
    await ask();
    for (let i = 0; i < 20 && fired.length < 1; i++) await new Promise((r) => setTimeout(r, 5));
    assert.equal(fired.length, 1);
    assert.equal(cwds.length, 1); // no build turn here
    assert.ok(sent.some((m) => /build copy on the server isn't ready \(uv: not found\)/.test(m.text)));
    assert.equal(brain.planStore.plans[81].status, "running_in_cloud");
  } finally {
    done();
  }
});

test("TM-31: '@bot build here | cloud' is the owners' switch, in the team group", () => {
  const dir = mkdtempSync(join(tmpdir(), "abw-"));
  try {
    const ab = new AutoBuild({ file: join(dir, "a.json") });
    const req = { project: "mesiri", sender_role: "member" };
    assert.match(ab.whereCommand({ ...req, text: "build" }), /in the cloud/);
    assert.equal(ab.whereCommand({ ...req, text: "build here" }), "Only an owner can change where builds run.");
    assert.equal(ab.whereCommand({ ...req, text: "build here", sender_role: "owner", dm: true }), "Where builds run can be changed in the team group only.");
    assert.match(ab.whereCommand({ ...req, text: "build here", sender_role: "owner" }), /Builds run here/);
    assert.equal(ab.buildHere("mesiri"), true);
    assert.match(ab.whereCommand({ ...req, text: "build cloud", sender_role: "owner" }), /in the cloud/);
    assert.equal(ab.buildHere("mesiri"), false);
    assert.equal(ab.whereCommand({ ...req, text: "build me a house" }), undefined);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// 3 Nov ([207]): the planner wrote "⚠️ Needs your OK: this gives the AI the power to grant project access" and the
// code built it anyway. The planner's flag now holds it, whether given as owner_ok or left in the words.
test("a plan its planner says needs an owner's ok is held", () => {
  assert.match(holdReason(plan("Allow POST /projects/{id}/members.", "Add a member", { owner_ok: "grants project access" })), /owner's ok \(grants project access\)/);
  assert.match(holdReason(plan("Allow POST /projects/{id}/members. ⚠️ Needs your OK: this gives the AI the power to grant project access.")), /owner's ok/);
  assert.match(holdReason(plan("Allow the route.", "v3: add a team member to a project (owner: grants access)")), /owner's ok/);
  // guard: saying no ok is needed is not a hold
  assert.equal(holdReason(plan("Product roles: no owner ok needed (Ilan, 1 Nov). Doesn't need your ok.")), null);
});

test("brain: a plan whose text asks for an owner's ok is posted held, not built", async () => {
  const { brain, fired, sent, ask, done } = brainWith("Allow POST /projects/{id}/members for admins. Needs your OK: grants project access.");
  try {
    await ask();
    assert.equal(fired.length, 0);
    assert.match(sent.at(-1).text, /✋ \[81\][\s\S]*needs an owner's ok[\s\S]*@bot ok 81/);
    assert.equal(brain.planStore.plans[81].status, "proposed");
  } finally {
    done();
  }
});

// TM-50 (3 Nov: [206] / WA-151 and [208] / TM-48 were fixed twice): a request someone else is on isn't autobuilt.
test("brain: a plan whose request a Claude Code session claimed waits instead of building", async () => {
  const { brain, fired, sent, ask, done } = brainWith("Add create_project to v2. Labour untouched.");
  const claims = [];
  brain.listener.claimItem = async (id, b) => (claims.push({ id, ...b }), { ok: false, by: "Claude Code session ab12cd34" });
  try {
    await ask();
    assert.equal(fired.length, 0);
    assert.deepEqual(claims, [{ id: 81, by: "team bot", project: "mesiri" }]);
    assert.match(sent.at(-1).text, /\[81\] .*not building, Claude Code session ab12cd34 is already on it\. @bot ok 81 builds it anyway/);
    assert.equal(brain.planStore.plans[81].status, "proposed");
  } finally {
    done();
  }
});

// TM-53 (3 Nov: TMT went [203] → [206] → WA-151 → WA-152): a second fix of the same complaint needs its mechanism.
test("a second fix of the same complaint needs a root cause and a failing test", async () => {
  const { refixOf, refixReady } = await import("../src/tools.js");
  const all = [{ id: 203, status: "done", asked_for: ["cor_aaaaaaaa11"] }, { id: 150, status: "done", asked_for: ["cor_bbbbbbbb22"] }, { id: 210, status: "proposed", asked_for: ["cor_cccccccc33"] }];
  assert.deepEqual(refixOf({ title: "TMT unit", plan: "x", asked: ["cor_aaaaaaaa11"] }, all).map((p) => p.id), [203]);
  assert.deepEqual(refixOf({ title: "TMT unit: [203] still broken here", plan: "x", asked: [] }, all).map((p) => p.id), [203]);
  assert.deepEqual(refixOf({ title: "x", plan: "This re-opens [150].", asked: [] }, all).map((p) => p.id), [150]);
  assert.deepEqual(refixOf({ title: "x", plan: "x", asked: [] }, all, 203).map((p) => p.id), [203]); // a failed live check
  assert.deepEqual(refixOf({ title: "new thing", plan: "x", asked: ["cor_dddddddd44"] }, all), []); // guard: a new complaint
  assert.equal(refixReady("Root cause: the stock unit is kg, the API refuses nos.\nFailing test: test_replay_plan_206."), true);
  assert.equal(refixReady("*Root cause:* x\n- Failing test: y"), true);
  assert.equal(refixReady("The root cause is probably the unit. We'll add a test."), false);
});
