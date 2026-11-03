// TM-69 (3 Nov 2026: "from the user's side, they should feel understood: the problem I faced is being fixed"). The
// person who asked hears their own problem said back when the fix is planned, what was found when a fix came back
// wrong (never a question), and once, honestly, when it takes longer. Mesiri checks and sends each message.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";
import { brainTools, tellAsker } from "../src/tools.js";

const COR = "cor_754851efd77446bc8326a1fc2e44d52c";
const LINE = "Primer-um drum size-um add aayi, pakshe Green Villa-il vanna 2 drum save aayilla: avide stock 40 L kuravaanu.";

function tools({ ctx = {}, earlierPlans = [], sendProgress } = {}) {
  const saved = [];
  const listener = { send: async () => ({}), addItem: async () => ({ item: { id: 240 } }), updateItem: async () => ({}) };
  const base = { project: "mesiri", chat: "T@g.us", chat_name: "Team", reply_chat: "T@g.us", sender: "the production watch", autobuild: true, new_plans: [],
    watch_conversations: [{ person: "asus", role: "ADMIN", company: "Mesiri Test Builders", who: "u1", messages: [{ correlation_id: COR, text: "2 drum primer vannu" }] }] };
  const server = brainTools({ ctx: { ...base, ...ctx }, listener, render: null, plans: { save: (p) => (saved.push(p), p), all: () => earlierPlans }, screenshotHosts: [], sendProgress });
  const t = Object.fromEntries(Object.entries(server.instance._registeredTools));
  return { saved, call: (name, args) => (t[name].callback || t[name].handler)(args, {}) };
}

const PLAN = { title: "Primer, its drum size and the receipt in one Save", plan: "FIX: Save runs dependent lines in order.", accept: ["after Save: 40 L Primer received at Green Villa"] };

test("TM-69: a plan for someone who asked says their problem back to them at once, in their words", async () => {
  const sent = [];
  const { call, saved } = tools({ sendProgress: async (b) => (sent.push(b), { sent: true }) });
  const r = await call("propose_plan", { ...PLAN, asked_for: [COR], understood: LINE });
  assert.match(r.content[0].text, /Plan \[240\] recorded[\s\S]*was told \(in their language\) what you understood/);
  assert.deepEqual(sent[0], { correlation_id: COR, stage: "understood", line: LINE, request_ref: "#754851", round: 1 });
  assert.equal(saved[0].told.stage, "understood");
});

test("TM-69: without understood the plan is refused and told what to write", async () => {
  const { call, saved } = tools({ sendProgress: async () => ({ sent: true }) });
  const r = await call("propose_plan", { ...PLAN, asked_for: [COR] });
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /understood: one or two sentences in THEIR language[\s\S]*Never a question/);
  assert.equal(saved.length, 0);
});

test("TM-69: a fix of a fix tells them what was found this time (stage again, next round)", async () => {
  const sent = [];
  const earlier = [{ id: 210, status: "done", asked_for: [COR] }];
  const { call } = tools({ earlierPlans: earlier, sendProgress: async (b) => (sent.push(b), { sent: true }) });
  await call("propose_plan", { ...PLAN, plan: `${PLAN.plan}\nRoot cause: conversion ran first.\nFailing test: test_x.`, asked_for: [COR], understood: "Primer save aayi, pakshe receipt list-il varaathe poyi." });
  assert.equal(sent[0].stage, "again");
  assert.equal(sent[0].round, 2);
});

test("TM-69: a plan held for an owner says honestly that it takes longer", async () => {
  const sent = [];
  const saved = { id: 7, title: "Attendance totals", plan: "FIX: attendance replaces the shift." };
  const out = await tellAsker({ sendProgress: async (b) => (sent.push(b), { sent: true }), saved, asked: { asked_for: [COR] }, understood: LINE, held: "it touches Attendance" });
  assert.match(out, /was told/);
  assert.equal(sent[0].stage, "slow");
});

test("guard TM-69: nobody asked, or Mesiri can't be reached: no message, the plan still stands", async () => {
  const quiet = tools({ ctx: { watch_conversations: [] }, sendProgress: async () => assert.fail("nobody to tell") });
  const r = await quiet.call("propose_plan", { ...PLAN });
  assert.match(r.content[0].text, /recorded/);
  const down = tools({ sendProgress: async () => { throw new Error("HTTP 409: outside the 24-hour window"); } });
  const d = await down.call("propose_plan", { ...PLAN, asked_for: [COR], understood: LINE });
  assert.match(d.content[0].text, /recorded[\s\S]*Telling them didn't work \(HTTP 409/);
  const none = tools({}); // no Mesiri API: understood isn't asked for
  assert.match((await none.call("propose_plan", { ...PLAN, asked_for: [COR] })).content[0].text, /recorded/);
});

// ---------- the slow note ----------

const NOW = Date.parse("2026-11-03T15:00:00Z");
const hoursAgo = (h) => new Date(NOW - h * 3600_000).toISOString();

function brainWith(plans) {
  const dir = mkdtempSync(join(tmpdir(), "slow-"));
  const told = [];
  const brain = new Brain({
    queryFn: () => { throw new Error("no AI turn"); },
    projects: { mesiri: { cwd: "/r", flow: "f" } },
    dir,
    listener: { send: async () => ({}), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
    progress: async (project, body) => (told.push([project, body]), { sent: true }),
    now: () => new Date(NOW),
  });
  brain.planStore.plans = plans;
  return { dir, brain, told };
}

const P = (id, over) => ({ id, title: "t", project: "mesiri", chat: "T@g.us", asked_for: [COR], status: "running_here", at: hoursAgo(3), ...over });

test("TM-69: not live after 2 hours, or stuck after 30 min: one honest note, once", async () => {
  const { dir, brain, told } = brainWith({
    1: P(1), // 3 h, still building
    2: P(2, { at: hoursAgo(0.75), status: "review_failed" }), // stuck after the breaker review
    3: P(3, { at: hoursAgo(0.75), status: "proposed", held: "it touches Attendance" }), // waiting for an owner
  });
  try {
    assert.deepEqual(await brain.tellSlow(), [1, 2, 3]);
    assert.deepEqual(told[0], ["mesiri", { correlation_id: COR, stage: "slow", line: "", request_ref: "#754851" }]);
    assert.deepEqual(await brain.tellSlow(), []); // never twice
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("guard TM-69: live, deployed, quick, nobody asked, dropped, old, or already told slow: no note", async () => {
  const { dir, brain, told } = brainWith({
    1: P(1, { live_at: hoursAgo(1) }),
    2: P(2, { deployed_at: hoursAgo(1) }),
    3: P(3, { at: hoursAgo(1) }), // 1 h, building normally
    4: P(4, { asked_for: [] }),
    5: P(5, { status: "wont_do" }),
    6: P(6, { at: hoursAgo(72) }),
    7: P(7, { told: { stage: "slow" } }), // held at planning: its first message already said so
    8: P(8, { session: "upgrade" }),
  });
  try {
    assert.deepEqual(await brain.tellSlow(), []);
    assert.equal(told.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
