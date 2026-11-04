// TM-83: one problem, one request, one build. The repeats of 3-4 Nov, replayed: [235]/[236]/[238] all re-opened [230]
// within minutes and two were built at once; [234] repeated [229] after it shipped.
import assert from "node:assert/strict";
import { test } from "node:test";
import { brainTools } from "../src/tools.js";
import { candidatesFor, chainOf, companyOf, coveringPlan, refsOf } from "../src/same.js";

const NOW = Date.parse("2026-11-04T08:50:00Z");
const ago = (min) => new Date(NOW - min * 60_000).toISOString();
const COR_A = "cor_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const COR_B = "cor_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

const PLANS = () => [
  { id: 229, status: "done", at: ago(35), title: "\"Press Save\" with no Save button: a 3-update voice note held", asked_by: "Ilan (ADMIN, Paraclette)", plan: "x" },
  { id: 230, status: "done", at: ago(33), title: "People see their own requests and each one's status", asked_by: "Ilan (ADMIN, Paraclette)", plan: "x" },
  { id: 235, status: "running_in_cloud", at: ago(6), title: "[230] still broken: \"Ente complaints kanikku\" answered \"can't show the list\"", asked_by: "Ilan (ADMIN, Paraclette)", asked_for: [COR_A], plan: "x" },
  { id: 199, status: "proposed", at: ago(3 * 24 * 60), title: "Labour shift correction adds instead of replacing", asked_by: "Ilan (ADMIN, Paraclette)", plan: "x" },
  { id: 237, status: "running_in_cloud", at: ago(3), title: "New material + its delivery", asked_by: "asus (ADMIN, Mesiri Test Builders)", plan: "x" },
];

test("what the code can see for certain: a follow-up of an open chain, or the same production messages", () => {
  const all = PLANS();
  assert.deepEqual([...refsOf({ title: "[230] follow-up: \"show my requests\" always uses my_requests" })], [230]);
  assert.deepEqual(chainOf(230, all).map((p) => p.id).sort(), [230, 235]);
  // [236]: "[230] follow-up" while [235] (a re-open of [230]) is being built -> it joins [235].
  assert.equal(coveringPlan({ title: "[230] follow-up: show my requests uses my_requests", plan: "p" }, all).id, 235);
  // Any re-open wording, and a re-open of the re-open, lands on the same open plan.
  assert.equal(coveringPlan({ title: "Still broken after [235]: list empty", plan: "p" }, all).id, 235);
  // The same production message, worded differently by the planner.
  assert.equal(coveringPlan({ title: "My requests list is empty", plan: "p" }, all, { asked: [COR_A] }).id, 235);
  // Guards: a re-open of a shipped request with nothing open on it is a new round, not a merge; unrelated stays new.
  assert.equal(coveringPlan({ title: "[229] still broken: Save missing", plan: "p" }, all), null);
  assert.equal(coveringPlan({ title: "Cement stock wrong", plan: "p" }, all, { asked: [COR_B] }), null);
});

test("possible repeats are recent requests from the same company (or the same group for team asks)", () => {
  assert.equal(companyOf("Ilan (ADMIN, Paraclette)"), "paraclette");
  assert.equal(companyOf("Ravi via bot"), null);
  const ids = candidatesFor({ asked_by: "Ilan (admin, Paraclette)" }, PLANS(), NOW).map((p) => p.id);
  assert.deepEqual(ids, [235, 230, 229]); // [199] is 3 days old; [237] is another company
  assert.deepEqual(candidatesFor({ chat: "T@g.us" }, [{ id: 5, status: "done", at: ago(10), chat: "T@g.us", title: "t" }, { id: 6, status: "done", at: ago(10), chat: "X@g.us", title: "t" }], NOW).map((p) => p.id), [5]);
});

function tools({ plans = PLANS(), ctx = {} } = {}) {
  const updates = [];
  const items = [];
  const sent = [];
  const listener = { send: async () => ({}), addItem: async (b) => (items.push(b), { item: { id: 241 } }), updateItem: async (id, b) => (updates.push({ id, ...b }), {}) };
  const store = Object.fromEntries(plans.map((p) => [p.id, p]));
  const planApi = {
    save: (p) => ((store[p.id] = { ...p, status: "proposed", at: new Date().toISOString() }), store[p.id]),
    get: (id) => store[id] || null,
    all: () => Object.values(store),
    update: (id, patch) => Object.assign(store[id], patch),
  };
  const base = { project: "mesiri", chat: "T@g.us", chat_name: "Team", reply_chat: "T@g.us", sender: "the production watch", autobuild: true, new_plans: [],
    watch_conversations: [{ person: "Ilan", role: "ADMIN", company: "Paraclette", who: "u1", messages: [{ correlation_id: COR_B, text: "ente complaints kanikku" }] }] };
  const server = brainTools({ ctx: { ...base, ...ctx }, listener, render: null, plans: planApi, screenshotHosts: [], sendProgress: async (b) => (sent.push(b), { sent: true }) });
  const t = server.instance._registeredTools;
  return { store, items, updates, sent, call: (name, args) => (t[name].callback || t[name].handler)(args, {}) };
}

const ARGS = { plan: "FIX: my_requests is always called for 'show my requests'.", accept: ["after the message: my_requests was called"], asked_for: [COR_B], understood: "Ningalude complaints list kaanikkunnilla ennu manassilaayi." };

test("a follow-up of an open request joins it: no new request, no new build, the person is told [n]", async () => {
  const { call, items, updates, store, sent } = tools();
  const r = await call("propose_plan", { ...ARGS, title: "[230] follow-up: \"show my requests\" always uses my_requests" });
  assert.match(r.content[0].text, /Same problem as \[235\][\s\S]*being built now[\s\S]*no second build/);
  assert.equal(items.length, 0); // nothing new in the request log
  assert.deepEqual(store[235].asked_for, [COR_A, COR_B]); // its live check covers the new person's messages too
  assert.match(updates[0].note, /same problem reported again by Ilan \(ADMIN, Paraclette\)/);
  assert.equal(updates[0].asked_ref, `${COR_A},${COR_B}`);
  assert.equal(sent[0].correlation_id, COR_B); // the person hears it is already being fixed
});

test("worded differently: the planner must rule on the recent requests; same_as merges, different_because records", async () => {
  const a = tools();
  const r1 = await a.call("propose_plan", { ...ARGS, title: "Requests list answer is wrong" });
  assert.equal(r1.isError, true);
  assert.match(r1.content[0].text, /\[235\] building[\s\S]*\[230\] shipped[\s\S]*same_as[\s\S]*different_because/);
  assert.equal(a.items.length, 0);
  const r2 = await a.call("propose_plan", { ...ARGS, title: "Requests list answer is wrong", same_as: 235 });
  assert.match(r2.content[0].text, /Same problem as \[235\]/);
  assert.equal(a.items.length, 0);

  const b = tools();
  const r3 = await b.call("propose_plan", { ...ARGS, title: "Cement left is wrong for a two-site company", different_because: "stock lookup, not the requests list" });
  assert.match(r3.content[0].text, /Plan \[241\] recorded/);
  assert.equal(b.items.length, 1);
});

test("same_as a shipped request with nothing open on it is its next round ([n] still broken), so the re-fix rules apply", async () => {
  const { call, items } = tools();
  const r = await call("propose_plan", { ...ARGS, title: "Three updates in one message lose the Save", same_as: 229 });
  assert.equal(r.isError, true); // TM-53: a second fix of the same complaint must name its root cause and failing test
  assert.match(r.content[0].text, /already had \[229\][\s\S]*Root cause/);
  const ok = await call("propose_plan", { ...ARGS, title: "Three updates in one message lose the Save", same_as: 229, plan: `${ARGS.plan}\nRoot cause: the held line drops Save.\nFailing test: test_multi_update_save.` });
  assert.match(ok.content[0].text, /Plan \[241\] recorded/);
  assert.match(items[0].title, /^\[229\] still broken: Three updates/);
});

test("a live check's own fix and the auto loop are never merged or questioned (they are the chain's next round)", async () => {
  const { call, items } = tools({ ctx: { verify_plan: 235 } });
  const r = await call("propose_plan", { ...ARGS, title: "[235] still broken after deploy", plan: `${ARGS.plan}\nRoot cause: r.\nFailing test: t.` });
  assert.match(r.content[0].text, /Plan \[241\] recorded/);
  assert.equal(items.length, 1);
});
