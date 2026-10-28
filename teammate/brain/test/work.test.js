import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain, reportingFooter, systemAppend } from "../src/brain.js";
import { Accounts } from "../src/accounts.js";
import { brainTools, BRAIN_TOOL_NAMES } from "../src/tools.js";
import { trackerIds, commitPatterns, deployState, ciState, lastHeartbeat, collectWorkStatus, formatWorkStatus } from "../src/work_status.js";

const MIN = 60_000;
const T0 = Date.parse("2026-10-28T10:00:00Z");
const iso = (ms) => new Date(ms).toISOString();
const PLAN_TEXT = "Day facts: every 'today' answer reads Day Facts (WA-86). Also change the composer reply wording so it names the date.";

/** A Brain with a fake clock, fake git/GitHub, an in-memory request log, and a Claude that must never be asked. */
function setup({ commits = [], runs = [], item = { status: "in_progress", log: [] }, fire, accounts = null } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "work-"));
  let t = T0;
  const sent = [];
  const fired = [];
  const updates = [];
  const state = { commits, runs, item };
  let asked = 0;
  const brain = new Brain({
    queryFn: () => {
      asked++;
      throw new Error("usage limit reached; resets in 2 hours");
    },
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      updateItem: async (id, b) => (updates.push({ id, ...b }), state.item),
      getItem: async () => ({ item: state.item }),
    },
    tools: () => ({}),
    ...(accounts ? { accounts: accounts(dir) } : { routines: { mesiri: { url: "https://x/fire", token: "t" } } }),
    fireFn: async (routine, text) => {
      fired.push({ routine, text });
      if (fire) return fire(routine, text);
      return { claude_code_session_id: `cse_${fired.length}` };
    },
    work: {
      commits: async (plan, since, it) => (state.lastCommitArgs = { plan, since, it }, state.commits),
      runs: async () => state.runs,
    },
    now: () => new Date(t),
  });
  brain.planStore.plans[139] = { id: 139, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", reply_chat: "M@g.us", reply_project: "mesiri", title: "Day facts", plan: PLAN_TEXT, status: "running_in_cloud", session_url: "https://claude.ai/code/session_1", fired_at: iso(T0), approved_by: "Ilan", at: iso(T0) };
  const say = (text, extra = {}) =>
    brain.ask({ project: "mesiri", chat: "M@g.us", chat_name: "Mesiri team", chat_role: "team", reply_chat: "M@g.us", sender: "Ilan", sender_role: "owner", n: 1, text, ...extra });
  return { dir, brain, sent, fired, updates, state, say, advance: (ms) => (t += ms), asked: () => asked, done: () => rmSync(dir, { recursive: true, force: true }) };
}

const commit = (sha, subject, at) => ({ sha: sha.padEnd(40, "0"), subject, at });
const run = (sha, name, status, conclusion, at) => ({ sha: sha.padEnd(40, "0"), name, status, conclusion, at, url: `https://gh/run/${name}` });

// ---- the collector -------------------------------------------------------------------------------------------------

test("collector: tracker ids, commit patterns (request n, [n], WA-86), deploy and CI state, heartbeat", () => {
  assert.deepEqual(trackerIds("WA-86 and TM-12, not UTF-8 or SHA-256, WA-86 again"), ["WA-86", "TM-12"]);
  const pats = commitPatterns({ id: 139, title: "t", plan: PLAN_TEXT }, { log: [{ note: "see TM-12 too" }] });
  const re = (s) => pats.some((p) => new RegExp(p).test(s));
  assert.ok(re("fix: thing (request 139)") && re("[139] day facts") && re("feat: WA-86 day facts") && re("chore TM-12"));
  assert.ok(!re("request 1390") && !re("[1391]") && !re("WA-860") && !re("unrelated commit"));

  assert.equal(deployState([]).state, "none");
  assert.equal(deployState([run("a", "Deploy to Production", "in_progress", null, "t")]).state, "running");
  assert.equal(deployState([run("a", "CI", "completed", "failure", "1"), run("a", "Deploy to Production", "completed", "success", "2")]).state, "green");
  assert.equal(deployState([run("a", "Deploy to Production", "completed", "failure", "1"), run("a", "Deploy to Production", "completed", "success", "2")]).state, "green"); // the latest run counts
  assert.equal(deployState([run("a", "Deploy to Production", "completed", "cancelled", "1")]).state, "red");
  assert.equal(ciState([run("a", "CI", "completed", "success", "1"), run("a", "Deploy to Production", "completed", "failure", "2")]), "green");
  assert.equal(ciState([run("a", "CI", "completed", "failure", "1")]), "red");

  const item = { log: [{ at: iso(T0 + MIN), note: "cloud session https://x" }, { at: iso(T0 + 2 * MIN), note: "OK from Ilan in WhatsApp" }, { at: iso(T0 + 5 * MIN), note: "step 1: read the composer" }, { at: iso(T0 + 9 * MIN), note: "step 2: tests" }] };
  assert.equal(lastHeartbeat(item, iso(T0)).note, "step 2: tests");
  assert.equal(lastHeartbeat({ log: item.log.slice(0, 2) }, iso(T0)), null); // the bot's own notes aren't heartbeats
  assert.equal(lastHeartbeat(item, iso(T0 + 20 * MIN)), null);
});

test("collector: by [n], request n or tracker id; deploy status; and no commit at all", async () => {
  const plan = { id: 139, title: "Day facts", plan: PLAN_TEXT, status: "running_in_cloud", fired_at: iso(T0), session_url: "https://claude.ai/code/session_1" };
  const asked = [];
  const commits = async (p, since, it) => (asked.push({ since, it }), [commit("a0480e9", "feat(assistant): WA-86 day facts", iso(T0 + 50 * MIN))]);
  const runs = async (shas) => (assert.deepEqual(shas, ["a0480e9".padEnd(40, "0")]), [run("a0480e9", "CI", "completed", "success", iso(T0 + 52 * MIN)), run("a0480e9", "Deploy to Production", "completed", "success", iso(T0 + 58 * MIN))]);
  const item = { status: "in_progress", log: [{ at: iso(T0 + 5 * MIN), status: null, note: "reading the code" }] };
  const ws = await collectWorkStatus({ plan, item, commits, runs });
  assert.equal(asked[0].since, iso(T0));
  assert.equal(asked[0].it, item);
  assert.equal(ws.commits[0].short, "a0480e9");
  assert.deepEqual([ws.commits[0].deploy.state, ws.commits[0].ci], ["green", "green"]);
  assert.equal(ws.heartbeat.note, "reading the code");
  assert.equal(ws.lastActivityAt, T0 + 50 * MIN);
  const text = formatWorkStatus(ws, T0 + 60 * MIN);
  assert.match(text, /\*\[139\] Day facts\* — in_progress[\s\S]*a0480e9 feat\(assistant\): WA-86 day facts — deploy ✅[\s\S]*last note 55 min ago: reading the code[\s\S]*session: https:\/\/claude.ai\/code\/session_1/);

  // No commit (and a broken GitHub): still answers from the request log.
  const none = await collectWorkStatus({ plan, item, commits: async () => [], runs: async () => { throw new Error("no"); } });
  assert.deepEqual(none.commits, []);
  assert.match(formatWorkStatus(none, T0 + 10 * MIN), /no commit on main yet/);
  const broken = await collectWorkStatus({ plan, item, commits: async () => [commit("b1", "x [139]", iso(T0 + MIN))], runs: async () => { throw new Error("HTTP 403"); } });
  assert.equal(broken.commits[0].deploy.state, "none");
});

// ---- the watchdog --------------------------------------------------------------------------------------------------

test("watchdog: one post per commit and result; a quiet job is flagged once; a silent landing marks the item done", async () => {
  const c1 = commit("a1", "feat: day facts [139]", iso(T0 + 10 * MIN));
  const s = setup({ commits: [c1], runs: [run("a1", "Deploy to Production", "in_progress", null, iso(T0 + 11 * MIN))], item: { status: "in_progress", log: [{ at: iso(T0 + 5 * MIN), note: "step 1" }] } });
  try {
    const wd = s.brain.watchdog;
    s.advance(12 * MIN);
    await wd.tick();
    assert.equal(s.sent.length, 0); // deploy still running: wait for its result

    s.state.runs = [run("a1", "Deploy to Production", "completed", "success", iso(T0 + 14 * MIN))];
    s.advance(3 * MIN); // T0+15
    await wd.tick();
    await wd.tick(); // a second pass says nothing new
    assert.equal(s.sent.length, 1);
    assert.match(s.sent[0].text, /^\[139\] pushed a1\w* “feat: day facts \[139\]”, deploy green ✅/);
    assert.equal(s.sent[0].chat, "M@g.us");

    // A second commit, red deploy: its own post, once.
    s.state.commits = [c1, commit("a2", "fix [139]", iso(T0 + 16 * MIN))];
    s.state.runs = [...s.state.runs, run("a2", "Deploy to Production", "completed", "failure", iso(T0 + 18 * MIN))];
    s.advance(4 * MIN); // T0+19; the session wrote a note at T0+18
    s.state.item = { status: "in_progress", log: [{ at: iso(T0 + 18 * MIN), note: "step 3" }] };
    await wd.tick();
    await wd.tick();
    assert.equal(s.sent.length, 2);
    assert.match(s.sent[1].text, /pushed a2\w* “fix \[139\]”, deploy red ❌\.\nhttps:\/\/gh\/run\/Deploy to Production/);

    // Silence: 30 min after the last sign of life (T0+18) -> one post, with the link; not again.
    s.advance(31 * MIN); // T0+50
    await wd.tick();
    await wd.tick();
    const quiet = s.sent.filter((m) => /quiet for/.test(m.text));
    assert.equal(quiet.length, 1);
    assert.match(quiet[0].text, /quiet for 32 min[\s\S]*https:\/\/claude.ai\/code\/session_1/);

    // The deploy of the last commit goes green and the session never reports: 20 min later -> landed unreported, done.
    s.state.runs = [run("a1", "Deploy to Production", "completed", "success", iso(T0 + 14 * MIN)), run("a2", "Deploy to Production", "completed", "success", iso(T0 + 52 * MIN))];
    s.advance(10 * MIN); // T0+60: only 8 min after that deploy
    await wd.tick();
    assert.ok(!s.sent.some((m) => /landed but didn't report/.test(m.text)));
    s.advance(15 * MIN); // T0+75
    await wd.tick();
    assert.match(s.sent.at(-1).text, /\[139\] landed but didn't report: a2\w* is deployed \(green\)/);
    assert.deepEqual(s.updates.at(-1), { id: 139, status: "done", ref: "a200000", note: "watchdog: landed a200000, deploy green, the session did not report", project: "mesiri" });
    assert.equal(s.brain.planStore.plans[139].status, "done");
    const n = s.sent.length;
    await wd.tick(); // done: no longer watched
    assert.equal(s.sent.length, n);
  } finally {
    s.done();
  }
});

test("watchdog: a job whose session reported its own ✅ is closed silently; a heartbeat after the deploy is not a silent landing", async () => {
  const c1 = commit("b1", "x [139]", iso(T0 + 10 * MIN));
  const s = setup({ commits: [c1], runs: [run("b1", "Deploy to Production", "completed", "success", iso(T0 + 12 * MIN))], item: { status: "in_progress", log: [{ at: iso(T0 + 30 * MIN), note: "verifying live" }] } });
  try {
    s.advance(40 * MIN);
    await s.brain.watchdog.tick();
    assert.equal(s.sent.length, 1); // the push post only; a note after the deploy means it is still working
    assert.equal(s.brain.planStore.plans[139].status, "running_in_cloud");
    s.state.item = { status: "done", done_ref: "b1", log: [] };
    await s.brain.watchdog.tick();
    assert.equal(s.sent.length, 1);
    assert.equal(s.brain.planStore.plans[139].status, "done");
  } finally {
    s.done();
  }
});

// ---- "@bot status" -------------------------------------------------------------------------------------------------

test("status: answered by code with no AI turn, even when Claude would refuse for a usage limit", async () => {
  const s = setup({ commits: [commit("c1", "feat [139]", iso(T0 + 10 * MIN))], runs: [run("c1", "Deploy to Production", "completed", "failure", iso(T0 + 12 * MIN))], item: { status: "in_progress", log: [{ at: iso(T0 + 11 * MIN), note: "step 2: tests" }] } });
  try {
    s.brain.planStore.plans[140] = { id: 140, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", title: "Other", plan: "p", status: "proposed" };
    await s.say("status");
    assert.match(s.sent.at(-1).text, /1 job running in the cloud:[\s\S]*\[139\] Day facts[\s\S]*c100000 feat \[139\] — deploy ❌[\s\S]*last note[\s\S]*step 2: tests/);
    assert.ok(!/Other/.test(s.sent.at(-1).text));
    await s.say("status 139");
    assert.match(s.sent.at(-1).text, /\*\[139\] Day facts\*[\s\S]*started[\s\S]*session: https:\/\/claude.ai\/code\/session_1/);
    await s.say("status 140");
    assert.match(s.sent.at(-1).text, /waiting for @bot ok 140/);
    await s.say("status 999");
    assert.match(s.sent.at(-1).text, /no plan \[999\]/);
    s.brain.planStore.plans[139].status = "done";
    await s.say("status");
    assert.match(s.sent.at(-1).text, /No job is running/);
    assert.equal(s.asked(), 0);
  } finally {
    s.done();
  }
});

// ---- "@bot tell" ---------------------------------------------------------------------------------------------------

test("tell: owner only; fires a follow-up with the plan, the status, the earlier link and the message; records both links", async () => {
  const s = setup({ commits: [commit("d1", "feat [139]", iso(T0 + 10 * MIN))], runs: [run("d1", "Deploy to Production", "completed", "success", iso(T0 + 12 * MIN))], item: { status: "in_progress", log: [{ at: iso(T0 + 11 * MIN), note: "step 2" }] } });
  try {
    await s.say("tell 139 finish part D", { sender_role: "approved" });
    assert.match(s.sent.at(-1).text, /Only an owner can send a message to a job/);
    assert.equal(s.fired.length, 0);

    await s.say("tell 139 finish part D: every 'today' answer must read Day Facts; live test after 82% correction failed, see #4904-4909");
    assert.equal(s.fired.length, 1);
    const p = s.fired[0].text;
    assert.match(p, /Approved by: Ilan \(in WhatsApp/);
    assert.match(p, /Plan \[139\]: Day facts[\s\S]*Day facts: every 'today' answer reads Day Facts \(WA-86\)/); // the original plan
    assert.match(p, /FOLLOW-UP: this plan was already started in an earlier session \(https:\/\/claude.ai\/code\/session_1\)\. Do NOT restart it\./);
    assert.match(p, /Message from Ilan: finish part D: every 'today' answer must read Day Facts; live test after 82% correction failed, see #4904-4909/);
    assert.match(p, /Work so far:\n {2}- d100000 feat \[139\] \(deploy green, CI none\)[\s\S]*request-log status: in_progress; last note: step 2/);
    assert.match(p, /Pull main, read the earlier commits[\s\S]*CLAUDE\.md applies/);
    assert.match(p, /item note 139[\s\S]*"\[139\]" in every commit message[\s\S]*item done 139 --ref/); // heartbeats rules ride along
    assert.match(s.sent.at(-1).text, /^💬 \[139\] follow-up started: https:\/\/claude\.ai\/code\/session_1$/); // the fake returns cse_1
    const plan = s.brain.planStore.plans[139];
    assert.equal(plan.status, "running_in_cloud");
    assert.equal(plan.session_url, "https://claude.ai/code/session_1"); // the first link stays
    assert.equal(plan.followups.length, 1);
    assert.equal(plan.followups[0].by, "Ilan");
    assert.deepEqual(s.updates.at(-1), { id: 139, note: "cloud session (follow-up) https://claude.ai/code/session_1", project: "mesiri" });
    assert.equal(s.asked(), 0);

    // status shows both sessions
    await s.say("status 139");
    assert.match(s.sent.at(-1).text, /session: https[^\n]*\n• follow-up \([^)]*\): https/);
  } finally {
    s.done();
  }
});

test("tell: on a usage limit the follow-up goes to the next Claude account; a failed start keeps the plan running", async () => {
  const mk = (dir) =>
    new Accounts({
      list: [
        { id: "a", token: "ta", routines: { mesiri: { url: "https://A/fire", token: "x" } }, partners: {} },
        { id: "b", token: "tb", routines: { mesiri: { url: "https://B/fire", token: "y" } }, partners: {} },
      ],
      file: join(dir, "accounts.json"),
      now: () => T0,
      log: () => {},
    });
  const s = setup({ accounts: mk, fire: (routine) => { if (routine.url.includes("//A/")) throw new Error("usage limit reached; resets in 2 hours"); return { claude_code_session_id: "cse_B1" }; } });
  try {
    await s.say("tell 139 please also add a test for the percent correction");
    assert.deepEqual(s.fired.map((f) => f.routine.url), ["https://A/fire", "https://B/fire"]);
    assert.match(s.sent.map((m) => m.text).join("\n"), /Claude account \*A\* hit its usage limit; this group uses \*B\*[\s\S]*💬 \[139\] follow-up started: https:\/\/claude.ai\/code\/session_B1/);
  } finally {
    s.done();
  }
  const f = setup({ fire: () => { throw new Error("HTTP 500"); } });
  try {
    await f.say("tell 139 do the thing now please");
    assert.match(f.sent.at(-1).text, /Couldn't start the follow-up for \[139\] \(HTTP 500\)/);
    assert.equal(f.brain.planStore.plans[139].status, "running_in_cloud");
    assert.equal(f.brain.planStore.plans[139].followups, undefined);
  } finally {
    f.done();
  }
});

test("tell from the bot: only while the plan is in progress and the message quotes the plan; at most 3", async () => {
  const s = setup();
  try {
    const b = s.brain;
    const tell = (over = {}) => b.tellFromBot({ id: 139, message: "the 82% correction failed live (#4904)", scope: "every 'today' answer reads Day Facts", reply_chat: "M@g.us", project: "mesiri", say: async () => {}, ...over });
    let r = await tell({ scope: "totally different thing the plan never said" });
    assert.equal(r.ok, false);
    assert.match(r.text, /isn't inside plan \[139\]'s scope[\s\S]*propose a new plan/i);
    r = await tell({ scope: "short" });
    assert.equal(r.ok, false);
    assert.equal(s.fired.length, 0);
    r = await tell({ id: 555 });
    assert.match(r.text, /No plan \[555\]/);

    r = await tell();
    assert.equal(r.ok, true, r.text);
    assert.match(s.fired[0].text, /Approved by: Ilan \(in WhatsApp/); // the original approval, not "bot"
    assert.match(s.fired[0].text, /Message from the bot \(a live re-test\): the 82% correction failed live/);
    assert.equal(b.planStore.plans[139].followups[0].by, "bot");
    await tell();
    await tell();
    r = await tell();
    assert.match(r.text, /already had 3 follow-ups/);
    b.planStore.plans[139].status = "done";
    r = await tell();
    assert.match(r.text, /is done, not in progress: propose a new plan/);
    assert.equal(s.fired.length, 3);
  } finally {
    s.done();
  }
});

test("tools: status_of_work and tell_job exist only when wired, are allowed for planning turns, and tell_job refuses with an error", async () => {
  assert.ok(BRAIN_TOOL_NAMES.includes("mcp__whatsapp__status_of_work") && BRAIN_TOOL_NAMES.includes("mcp__whatsapp__tell_job"));
  const names = (srv) => Object.keys(srv.instance?._registeredTools || {});
  const base = { ctx: { chat: "c", reply_chat: "c", project: "mesiri" }, listener: {}, plans: {}, screenshotHosts: [] };
  const off = brainTools(base);
  assert.ok(!names(off).includes("status_of_work") && !names(off).includes("tell_job"));
  const on = brainTools({ ...base, workStatus: async (id) => `status ${id}`, tellJob: async () => ({ ok: false, text: "not in scope" }) });
  assert.ok(names(on).includes("status_of_work") && names(on).includes("tell_job"));
  const call = (name, args) => on.instance._registeredTools[name].handler(args, {});
  assert.equal((await call("status_of_work", { id: 139 })).content[0].text, "status 139");
  const refused = await call("tell_job", { id: 139, message: "something failed", scope: "quote of the plan that is long enough" });
  assert.equal(refused.isError, true);
  assert.match(systemAppend({ project: "mesiri", flow: "f", owner: "Ilan" }), /status_of_work\(id\)[\s\S]*tell_job\(id, message, scope\)/);
});

// ---- the payload footer --------------------------------------------------------------------------------------------

test("payload footer: heartbeats, [n] in commits, finishing with item done and a group post — on every cloud start", async () => {
  const footer = reportingFooter({ id: 139 }, "G@g.us");
  assert.match(footer, /python3 teammate\/inbox\.py item note 139 "<what you are doing/);
  assert.match(footer, /Put "\[139\]" in every commit message/);
  assert.match(footer, /item done 139 --ref <commit sha>[\s\S]*inbox\.py post --chat "G@g\.us"/);
  assert.match(reportingFooter({ id: "P3" }, "G@g.us"), /no request-log item/);

  const s = setup();
  try {
    const plan = { id: 77, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", title: "T", plan: "do it", status: "approved" };
    s.brain.planStore.plans[77] = plan;
    await s.brain.runInCloud(plan, { project: "mesiri", by: "Ilan", reply_chat: "M@g.us", say: async () => {} });
    const p = s.fired[0].text;
    assert.match(p, /^Project: mesiri\nApproved by: Ilan[\s\S]*Plan \[77\]: T\n\ndo it\n\nREPORTING[\s\S]*item note 77[\s\S]*"\[77\]"[\s\S]*item done 77 --ref/);
    assert.ok(!p.includes("FOLLOW-UP"));
    assert.ok(plan.fired_at && plan.reply_chat === "M@g.us" && plan.approved_by === "Ilan");
    assert.equal(JSON.parse(readFileSync(join(s.dir, "plans.json"), "utf8")).plans[77].status, "running_in_cloud");
  } finally {
    s.done();
  }
});
