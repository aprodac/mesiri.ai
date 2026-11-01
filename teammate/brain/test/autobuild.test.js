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
  assert.match(holdReason(plan("Add create_project. Also change the labour card wording.")), /Labour/);
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
