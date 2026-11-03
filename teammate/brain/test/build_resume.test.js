// TM-43 (2 Nov): a bot deploy restarted the brain in the middle of [205]'s build on the server; the group heard
// nothing for 36 minutes, and "@bot tell 205" answered "not started in the cloud".
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";

const NOW = Date.parse("2026-11-02T17:10:00Z");

function make(plans, turn = null) {
  const dir = mkdtempSync(join(tmpdir(), "resume-"));
  const sent = [];
  const brain = new Brain({
    queryFn: () => {
      throw new Error("no AI turn in these tests");
    },
    projects: { mesiri: { cwd: "/r", buildCwd: "/b", branch: "main", flow: "f" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true }), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
    prepareBuild: () => {},
    now: () => new Date(NOW),
  });
  brain.planStore.plans = plans;
  const built = [];
  if (turn) brain.turn = turn;
  else brain.buildHere = async (plan, opts) => built.push({ id: plan.id, ...opts });
  return { dir, brain, sent, built };
}

const plan = (over) => ({ id: 205, title: "renamed project vanishes", project: "mesiri", chat: "T@g.us", reply_chat: "T@g.us",
  reply_project: "mesiri", status: "running_here", fired_at: "2026-11-02T16:24:00Z", plan: "the plan", ...over });

test("a build cut off by a restart is said in the group and started again", async () => {
  const { dir, brain, sent, built } = make({ 205: plan({ build_turn: "running" }) });
  try {
    const say = (m) => brain.listener.send(m);
    assert.deepEqual(await brain.resumeInterrupted({ say }), [205]);
    assert.match(sent[0].text, /↩️ \[205\].*cut off when the bot restarted/);
    assert.equal(built.length, 1);
    assert.match(built[0].note, /interrupted by a restart/);
    assert.equal(brain.planStore.plans[205].restarts, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("guard: a finished build, a cloud job and an old build are left alone; a third cut stops it", async () => {
  const { dir, brain, sent, built } = make({
    1: plan({ id: 1, build_turn: "finished" }), // built, the watchdog follows its deploy
    2: plan({ id: 2, status: "running_in_cloud" }),
    3: plan({ id: 3, fired_at: "2026-11-01T08:00:00Z" }), // more than 6 hours ago
    4: plan({ id: 4, build_turn: "running", restarts: 2 }),
  });
  try {
    assert.deepEqual(await brain.resumeInterrupted({ say: (m) => brain.listener.send(m) }), [4]);
    assert.equal(built.length, 0);
    assert.equal(brain.planStore.plans[4].status, "failed");
    assert.match(sent[0].text, /cut off by a restart 3 times; stopped/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("@bot tell on a plan built here continues it here with the owner's message", async () => {
  const { dir, brain, built } = make({ 205: plan({ build_turn: "finished" }) });
  try {
    const reply = await brain.tellCommand({ text: "tell 205 keep the request reference", sender: "Ilan", sender_role: "owner", reply_chat: "T@g.us", project: "mesiri" }, async () => {});
    assert.match(reply, /continues here/);
    assert.equal(built.length, 1);
    assert.match(built[0].note, /Ilan \(owner\) adds: keep the request reference/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the build turn is marked finished whatever its outcome", async () => {
  const p = plan({ status: "approved" });
  const { dir, brain } = make({ 205: p }, async () => {
    assert.equal(p.build_turn, "running"); // a restart now would find it cut off
    throw new Error("the turn crashed");
  });
  try {
    await brain.buildHere(p, { project: "mesiri", by: "autobuild", reply_chat: "T@g.us", say: async () => {} }).catch(() => {});
    assert.equal(p.build_turn, "finished");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// TM-51: the deploy waits while a build runs here; /health lists them.
test("the builds running on this server are listed for the deploy to wait on", () => {
  const { dir, brain } = make({ 205: plan({ build_turn: "running" }), 206: plan({ id: 206, build_turn: "finished" }), 207: plan({ id: 207, status: "running_in_cloud" }) });
  try {
    assert.deepEqual(brain.buildingHere(), [205]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
