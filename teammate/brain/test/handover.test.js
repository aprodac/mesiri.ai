// TM-84: a cloud build that is about to hit its Claude account's limit hands over (finished work pushed, the rest as a
// patch with a note), and the bot continues it on another account, or by itself at the reset. Never just sits there.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain, reportingFooter } from "../src/brain.js";
import { Accounts } from "../src/accounts.js";
import { Watchdog } from "../src/watchdog.js";

const T0 = Date.parse("2026-11-04T09:00:00Z");
const MIN = 60_000;
const iso = (ms) => new Date(ms).toISOString();

function setup({ withB = true } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "handover-"));
  let t = T0;
  const sent = [];
  const fired = [];
  const updates = [];
  const state = { item: { status: "in_progress", log: [], paused: null } };
  const accounts = new Accounts({
    list: [
      { id: "a", token: "ta", routines: { mesiri: { url: "https://A/fire", token: "x" } }, partners: {} },
      ...(withB ? [{ id: "b", token: "tb", routines: { mesiri: { url: "https://B/fire", token: "y" } }, partners: {}, name: "ilan-work" }] : []),
    ],
    file: join(dir, "accounts.json"),
    now: () => t,
  });
  const brain = new Brain({
    queryFn: () => (async function* () {})(),
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      updateItem: async (id, b) => (updates.push({ id, ...b }), state.item),
      getItem: async () => ({ item: state.item }),
    },
    tools: () => ({}),
    accounts,
    fireFn: async (routine, text) => (fired.push({ routine, text }), { claude_code_session_id: `cse_${fired.length}` }),
    work: { commits: async () => [], runs: async () => [] },
    now: () => new Date(t),
  });
  brain.planStore.plans[240] = { id: 240, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", reply_chat: "M@g.us", reply_project: "mesiri", title: "Company requests page", plan: "p", status: "running_in_cloud", session_url: "https://claude.ai/code/session_1", fired_at: iso(T0), approved_by: "autobuild", at: iso(T0), account: "a" };
  const wd = new Watchdog(brain, { dir });
  return { brain, accounts, wd, sent, fired, updates, state, advance: (ms) => (t += ms), now: () => t, done: () => rmSync(dir, { recursive: true, force: true }) };
}

test("every cloud job is told its account and the handover rule; never half-done code on main", () => {
  const f = reportingFooter({ id: 240 }, "M@g.us", "B (ilan-work)");
  assert.match(f, /USAGE LIMIT \(TM-84\): this session runs on Claude account B \(ilan-work\)/);
  assert.match(f, /inbox\.py limits --account "B \(ilan-work\)"[\s\S]*exits 3 and says HAND OVER/);
  assert.match(f, /item handover 240 --note[\s\S]*never push half-done code to main/);
  assert.doesNotMatch(reportingFooter({ id: "P3" }, "M@g.us"), /USAGE LIMIT/); // no request number, nowhere to hand over
});

test("an account near its limit is passed over for new work while another has room", () => {
  const { accounts, done } = setup();
  try {
    accounts.reading("a", { five_hour: { pct: 92, resets_at: T0 + 2 * 60 * MIN } });
    assert.equal(accounts.near("a"), true);
    assert.equal(accounts.for("M@g.us").id, "b");
    assert.equal(accounts.roomAt("a"), T0 + 2 * 60 * MIN);
    accounts.reading("b", { five_hour: { pct: 95, resets_at: T0 + 60 * MIN } });
    assert.equal(accounts.for("M@g.us").id, "a"); // both near: the group's own account, as before
  } finally {
    done();
  }
});

test("a handover is picked up at once on another account, starting with item pickup", async () => {
  const s = setup();
  try {
    s.accounts.reading("a", { five_hour: { pct: 93, resets_at: T0 + 90 * MIN } });
    s.state.item.paused = "handed over (account A): done: test added / left: the fix / next step: run it";
    s.state.item.log = [{ at: iso(T0 + 5 * MIN), note: "step 2" }];
    s.advance(10 * MIN);
    await s.wd.tick();
    assert.equal(s.fired.length, 1);
    assert.equal(s.fired[0].routine.url, "https://B/fire");
    assert.match(s.fired[0].text, /FOLLOW-UP[\s\S]*item pickup 240[\s\S]*this session runs on Claude account B \(ilan-work\)/);
    assert.match(s.sent.at(-2).text, /⏸→▶️ \[240\] handed over before its Claude account's limit\. Continuing on Claude account \*B \(ilan-work\)\*/);
    assert.equal(s.brain.planStore.plans[240].account, "b");
    assert.ok(s.updates.some((u) => u.paused === null)); // the pause ends on the board
    await s.wd.tick(); // the same handover is not picked up twice
    assert.equal(s.fired.length, 1);
  } finally {
    s.done();
  }
});

test("no account has room: it waits, says when once, and continues by itself at the reset", async () => {
  const s = setup({ withB: false });
  try {
    s.accounts.reading("a", { five_hour: { pct: 99, resets_at: T0 + 60 * MIN } });
    s.state.item.log = [{ at: iso(T0), note: "step 1" }];
    s.advance(15 * MIN); // silent for 15 min on an account at its limit (no handover was made)
    await s.wd.tick();
    assert.equal(s.fired.length, 0);
    assert.match(s.sent.at(-1).text, /⏸ \[240\] stopped: Claude account A is at its limit\. No Claude account has room now: it continues by itself at ~\d\d:\d\d IST/);
    assert.ok(s.updates.some((u) => /continues by itself/.test(u.paused || "")));
    const said = s.sent.length;
    s.advance(10 * MIN);
    await s.wd.tick();
    assert.equal(s.sent.length, said); // said once
    s.advance(40 * MIN); // past the reset; the next reading shows room
    s.accounts.reading("a", { five_hour: { pct: 3, resets_at: T0 + 6 * 60 * MIN } });
    await s.wd.tick();
    assert.equal(s.fired.length, 1);
    assert.match(s.fired[0].text, /item pickup 240/);
    assert.equal(s.brain.planStore.plans[240].resume_at, null);
  } finally {
    s.done();
  }
});
