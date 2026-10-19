import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";
import { AutoLoop, AUTO_DEFAULTS, guardWord, usageLimit, resetTimeFrom, messagesForCycle, TEST_MESSAGES, cyclePrompt } from "../src/auto.js";

const MIN = 60_000;
const ok = (text, id, extra = {}) => ({ type: "result", subtype: "success", is_error: false, result: text, session_id: id, duration_ms: 1, total_cost_usd: 0, permission_denials: [], ...extra });

/**
 * A Brain with a fake Claude and a fake clock. `answer(prompt, ctx, options)` returns the stream's messages; it gets the
 * tools' ctx so it can act like the model (save a plan, call cycle_report).
 */
function setup(answer, { fire, landed } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "auto-"));
  const sent = [];
  const fired = [];
  const calls = [];
  const items = [];
  let t = Date.parse("2026-10-19T04:00:00Z");
  const clock = { advance: (ms) => (t += ms) };
  let lastCtx = null;
  let plansApi = null;
  const brain = new Brain({
    queryFn: ({ prompt, options }) => {
      calls.push({ prompt, options });
      return (async function* () {
        for (const m of await answer(prompt, { ctx: lastCtx, plans: plansApi }, options)) yield m;
      })();
    },
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      addItem: async () => ({ item: { id: 70 + items.length } }),
      updateItem: async (id, b) => items.push({ id, ...b }),
      getItem: async () => ({ item: { status: "in_progress" } }),
    },
    tools: (ctx, plans) => ((lastCtx = ctx), (plansApi = plans), {}),
    routines: { mesiri: { url: "https://x/fire", token: "t" } },
    fireFn: async (routine, text) => {
      fired.push(text);
      if (fire) return fire(text);
      return { claude_code_session_id: `cse_${fired.length}` };
    },
    landed: landed || (async () => false),
    now: () => new Date(t),
  });
  const auto = brain.auto;
  const say = (text, extra = {}) =>
    brain.ask({ project: "mesiri", chat: "M@g.us", chat_name: "Mesiri team", chat_role: "team", reply_chat: "M@g.us", sender: "Ilan", sender_role: "owner", n: 1, text, ...extra });
  const done = () => rmSync(dir, { recursive: true, force: true });
  return { dir, sent, fired, calls, items, brain, auto, say, clock, done };
}

/** The model of one auto cycle: optionally saves a plan with an area, then reports. */
function cycleModel({ title = "Report reply names the date", area = "getting_out", plan = "Change the report reply in the composer; add a test.", outcome = "planned", verify = "fixed" } = {}) {
  return async (prompt, { ctx, plans }) => {
    if (prompt.includes("VERIFY")) {
      ctx.auto_report({ outcome: verify, summary: `live check: ${verify}` });
      return [ok("verified", "V")];
    }
    if (outcome === "planned") plans.save({ id: 61, project: "mesiri", chat_project: "mesiri", chat: ctx.chat, title, plan, by: ctx.sender, ...(ctx.auto_cycle ? { auto: area ? { area } : null, cycle: ctx.auto_cycle } : {}) });
    ctx.auto_report({ outcome, summary: "tested 5 messages", seen_not_fixed: ["labour reply is slow"] });
    return [ok("cycle summary", "A")];
  };
}

test("auto: helpers (guard words, usage limits, reset times, rotating test messages)", () => {
  assert.equal(guardWord("Fix the labour count reply"), "labour");
  assert.equal(guardWord("Rename the PDF", "x"), "rename");
  assert.equal(guardWord("edit teammate/brain"), "teammate/");
  assert.equal(guardWord("Say the report date in the reply"), null);

  const now = Date.parse("2026-10-19T04:00:00Z");
  assert.equal(usageLimit("some other error"), null);
  assert.deepEqual(usageLimit("Claude AI usage limit reached, resets in 2 hours", { now }), { resetAt: now + 120 * MIN });
  assert.deepEqual(usageLimit("x", { flagged: true, resetsAt: now + 5 }), { resetAt: now + 5 });
  assert.equal(resetTimeFrom("try again in 30 minutes", now), now + 30 * MIN);
  assert.equal(resetTimeFrom("resets 2026-10-19T06:00:00Z", now), Date.parse("2026-10-19T06:00:00Z"));
  // 04:00 UTC is 09:30 IST; 3pm IST is 5.5 h later.
  assert.equal(resetTimeFrom("Your limit resets at 3pm (Asia/Kolkata)", now), now + 330 * MIN);

  assert.deepEqual(messagesForCycle(1), TEST_MESSAGES.slice(0, 5));
  assert.deepEqual(messagesForCycle(4), TEST_MESSAGES.slice(0, 5)); // 15 messages, 5 a cycle: wraps
  const p = cyclePrompt({ cycle: 2, pending: ["[9] x"], seen: ["slow labour"] });
  assert.match(p, /AUTO CYCLE #2/);
  assert.match(p, /Already waiting for a human[\s\S]*\[9\] x/);
  assert.match(p, /seen, not fixed[\s\S]*slow labour/);
});

test("auto: commands — owners switch it on (capped hours), anyone switches it off, DMs and members can't start it", async () => {
  const { sent, auto, say, calls, done } = setup(async () => [ok("x", "S")]);
  try {
    auto.tick = async () => {}; // commands only: no cycles here
    await say("auto");
    assert.match(sent.at(-1).text, /Auto is off/);
    await say("auto on", { sender_role: "member" });
    assert.match(sent.at(-1).text, /Only an owner/);
    await say("auto on", { dm: true, chat_role: "dm" });
    assert.match(sent.at(-1).text, /team group only/);
    await say("auto on 99");
    assert.match(sent.at(-1).text, /Auto is on\* for 24 h/);
    assert.equal(auto.s.hours, 24);
    await say("auto");
    assert.match(sent.at(-1).text, /Auto is on\* until/);
    await say("stop", { sender: "Ravi", sender_role: "member" });
    assert.match(sent.at(-1).text, /Auto is off\* \(stopped by Ravi\)/);
    assert.equal(auto.enabled, false);
    await say("auto off");
    assert.match(sent.at(-1).text, /Auto isn't on/);
    assert.equal(calls.length, 0); // no Claude turn for any command
  } finally {
    done();
  }
});

test("auto: a full cycle — test, plan in scope, code approves, fire as 'auto', landed, verify fixed", async () => {
  let onMain = false;
  const { sent, fired, calls, items, brain, auto, say, clock, dir, done } = setup(cycleModel(), { landed: async (plan, since) => (assert.equal(plan.id, 61), assert.ok(since), onMain) });
  try {
    const realTick = auto.tick.bind(auto);
    auto.tick = async () => {}; // "auto on" ticks at once; the test drives the ticks itself
    await say("auto on 6");
    auto.tick = realTick;

    await auto.tick(); // TEST + PICK -> approve -> fire
    const turn = calls.at(-1);
    assert.match(turn.prompt, /AUTO CYCLE #1/);
    assert.ok(!turn.options.allowedTools.includes("Edit")); // a planning turn
    assert.equal(fired.length, 1);
    assert.match(fired[0], /Approved by: auto \(the bot's auto loop/);
    assert.equal(brain.planStore.plans[61].approved_by, "auto");
    assert.deepEqual(items.at(-2), { id: 61, status: "in_progress", note: "approved_by: auto (cycle 1, area getting_out)", project: "mesiri" });
    assert.deepEqual(items.at(-1), { id: 61, note: "cloud session https://claude.ai/code/session_1", project: "mesiri" });
    assert.match(sent.at(-1).text, /Auto cycle #1: plan \[61\].*auto-approved and started\.\nWatch it: https:\/\/claude\.ai\/code\/session_1/);
    assert.equal(auto.s.cycle.phase, "working");
    assert.deepEqual(auto.s.seen, ["labour reply is slow"]);

    await auto.tick(); // not on main yet
    assert.equal(auto.s.cycle.phase, "working");
    onMain = true;
    await auto.tick();
    assert.equal(auto.s.cycle.phase, "settling");
    await auto.tick(); // the deploy hasn't had its 5 min
    assert.equal(auto.s.cycle.phase, "settling");
    clock.advance(AUTO_DEFAULTS.verifyDelayMs);
    await auto.tick(); // VERIFY
    assert.match(calls.at(-1).prompt, /VERIFY[\s\S]*Plan \[61\]/);
    assert.equal(auto.s.cycle, null);
    assert.equal(auto.s.failures, 0);
    assert.match(auto.s.recent.at(-1), /plan \[61\] fixed/);
    assert.equal(JSON.parse(readFileSync(join(dir, "auto.json"), "utf8")).pushes.n, 1);
  } finally {
    done();
  }
});

test("auto: out-of-scope area or a guard word leaves the plan for a human ok; it isn't fired", async () => {
  for (const model of [cycleModel({ area: "labour" }), cycleModel({ area: null }), cycleModel({ plan: "Change the attendance reply" })]) {
    const { sent, fired, brain, auto, say, done } = setup(model);
    try {
      const realTick = auto.tick.bind(auto);
      auto.tick = async () => {};
      await say("auto on");
      await realTick();
      assert.equal(fired.length, 0);
      assert.match(sent.at(-1).text, /Not auto-approved: .*Reply @bot ok 61/);
      assert.equal(brain.planStore.plans[61].status, "proposed");
      assert.equal(auto.s.failures, 0); // not a failure
      assert.equal(auto.s.cycle, null);
    } finally {
      done();
    }
  }
});

test("auto: a usage limit pauses (one message), resumes at the reset time, and is not a failure", async () => {
  let limited = true;
  const { sent, calls, auto, say, clock, done } = setup(async (prompt, ctx) => {
    if (limited) return [{ type: "rate_limit_event", rate_limit_info: { status: "rejected", resetsAt: Math.floor((Date.parse("2026-10-19T04:00:00Z") + 90 * MIN) / 1000) } }, { type: "result", subtype: "error_during_execution", is_error: true, errors: ["usage limit"], session_id: "S", permission_denials: [] }];
    return cycleModel({ outcome: "no_issue_found" })(prompt, ctx);
  });
  try {
    const realTick = auto.tick.bind(auto);
    auto.tick = async () => {};
    await say("auto on");
    await realTick();
    assert.equal(auto.s.failures, 0);
    assert.ok(auto.s.paused);
    assert.equal(auto.s.paused.until, Date.parse("2026-10-19T04:00:00Z") + 91 * MIN);
    assert.match(sent.at(-1).text, /⏸ Paused: Claude usage limit, resuming ~11:01 IST/);
    const posts = sent.length;
    const turns = calls.length;
    await realTick(); // still paused: nothing runs, nothing posted
    assert.equal(calls.length, turns);
    assert.equal(sent.length, posts);

    limited = false;
    clock.advance(91 * MIN);
    await realTick();
    assert.equal(auto.s.paused, null);
    assert.ok(sent.some((s) => /Auto resumed after the usage limit/.test(s.text)));
    assert.equal(auto.s.failures, 0);
  } finally {
    done();
  }
});

test("auto: a fire refused by a limit re-fires the same plan after the pause; a stalled run is re-fired once, then fails", async () => {
  let refuse = true;
  const { fired, auto, say, clock, brain, done } = setup(cycleModel(), {
    fire: () => {
      if (refuse) throw new Error("routine fire HTTP 429 rate limit");
      return { claude_code_session_id: "cse_Z" };
    },
  });
  try {
    const realTick = auto.tick.bind(auto);
    auto.tick = async () => {};
    await say("auto on");
    await realTick();
    assert.equal(auto.s.cycle.phase, "approved");
    assert.ok(auto.s.paused);
    assert.equal(brain.planStore.plans[61].status, "approved"); // not back to proposed

    refuse = false;
    clock.advance(31 * MIN);
    await realTick(); // same plan, fired again
    assert.equal(fired.length, 2);
    assert.ok(fired.every((f) => /Plan \[61\]/.test(f)));
    assert.equal(auto.s.cycle.phase, "working");

    clock.advance(AUTO_DEFAULTS.workTimeoutMs);
    await realTick(); // not on main after the timeout: re-fired once
    assert.equal(fired.length, 3);
    assert.equal(auto.s.cycle.refired, true);
    clock.advance(AUTO_DEFAULTS.workTimeoutMs);
    await realTick(); // still not: the cycle fails
    assert.equal(auto.s.cycle, null);
    assert.equal(auto.s.failures, 1);
    assert.equal(brain.planStore.plans[61].status, "failed");
  } finally {
    done();
  }
});

test("auto: two failed cycles switch it off; a spending cap or a permission denial stops it at once", async () => {
  {
    const { sent, auto, say, clock, done } = setup(async () => [{ type: "result", subtype: "error_during_execution", is_error: true, errors: ["boom"], session_id: "S", permission_denials: [] }]);
    try {
      const realTick = auto.tick.bind(auto);
      auto.tick = async () => {};
      await say("auto on");
      await realTick();
      assert.equal(auto.s.failures, 1);
      assert.match(sent.at(-1).text, /Auto cycle failed/);
      clock.advance(AUTO_DEFAULTS.gapMs);
      await realTick();
      assert.equal(auto.enabled, false);
      assert.match(sent.at(-1).text, /Auto is off\* \(2 failed cycles in a row/);
    } finally {
      done();
    }
  }
  {
    const { sent, auto, say, done } = setup(async () => [{ type: "result", subtype: "error_max_budget_usd", is_error: true, errors: [], session_id: "S", permission_denials: [] }]);
    try {
      const realTick = auto.tick.bind(auto);
      auto.tick = async () => {};
      await say("auto on");
      await realTick();
      assert.equal(auto.enabled, false);
      assert.ok(sent.some((s) => /spending cap/.test(s.text)));
    } finally {
      done();
    }
  }
  {
    const denial = { tool_name: "Bash", tool_input: { command: "rm -rf /" } };
    const { sent, auto, say, done } = setup(async () => [ok("x", "S", { permission_denials: [denial] })]);
    try {
      const realTick = auto.tick.bind(auto);
      auto.tick = async () => {};
      await say("auto on");
      await realTick();
      assert.equal(auto.enabled, false);
      assert.match(sent.at(-1).text, /a permission was denied/);
    } finally {
      done();
    }
  }
});

test("auto: expiry switches it off; the daily push cap leaves plans for a human; auto turns skip the daily turn cap", async () => {
  const { sent, fired, auto, say, clock, brain, done } = setup(cycleModel());
  try {
    const realTick = auto.tick.bind(auto);
    auto.tick = async () => {};
    await say("auto on 2");
    auto.s.pushes = { day: "2026-10-19", n: AUTO_DEFAULTS.pushesPerDay };
    brain.today = { day: "2026-10-19", turns: 10_000 }; // over the human daily cap
    await realTick();
    assert.equal(fired.length, 0);
    assert.match(sent.at(-1).text, /Not auto-approved: today's \d+ auto pushes are used/);

    clock.advance(2 * 60 * MIN);
    await realTick();
    assert.equal(auto.enabled, false);
    assert.match(sent.at(-1).text, /time is up after 2 h/);
  } finally {
    done();
  }
});

test("auto: a restart mid-cycle carries on (planning starts again; working keeps watching)", async () => {
  const { dir, brain, auto, say, done } = setup(cycleModel());
  try {
    auto.tick = async () => {};
    await say("auto on");
    auto.s.cycle = { n: 3, phase: "planning" };
    auto.save();
    const again = new AutoLoop(brain, { dir });
    assert.equal(again.s.cycle, null);
    assert.equal(again.enabled, true);
    auto.s.cycle = { n: 3, phase: "working", planId: 61 };
    auto.save();
    assert.equal(new AutoLoop(brain, { dir }).s.cycle.phase, "working");
  } finally {
    done();
  }
});

test("brain: a human message that hits the usage limit says when it resets, not 'check the logs'", async () => {
  const { sent, say, done } = setup(async () => [{ type: "result", subtype: "error_during_execution", is_error: true, errors: ["Claude AI usage limit reached, resets in 1 hour"], session_id: "S", permission_denials: [] }]);
  try {
    await say("how is the report?");
    assert.match(sent.at(-1).text, /usage limit is reached; it resets ~\d\d:\d\d IST/);
  } finally {
    done();
  }
});
