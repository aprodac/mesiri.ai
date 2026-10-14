import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain, chunk, systemAppend } from "../src/brain.js";
import { brainTools, hostAllowed } from "../src/tools.js";

const ok = (text, id, extra = {}) => ({ type: "result", subtype: "success", is_error: false, result: text, session_id: id, duration_ms: 1200, total_cost_usd: 0.01, permission_denials: [], ...extra });

function setup(answer) {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const calls = [];
  const sent = [];
  const items = [];
  let n = 0;
  const listener = {
    send: async (b) => sent.push(b),
    addItem: async (b) => (items.push(b), { item: { id: 40 + items.length } }),
    updateItem: async (id, b) => items.push({ update: id, ...b }),
  };
  // A fake Claude: calls the mcp tool handlers it is given when the prompt asks it to.
  const queryFn = ({ prompt, options }) => {
    calls.push({ prompt, options });
    const id = options.resume || `S${++n}`;
    return (async function* () {
      yield { type: "system", subtype: "init", session_id: id };
      yield await answer(prompt, id, options);
    })();
  };
  const plansSeen = [];
  const brain = new Brain({
    queryFn,
    projects: { mercon: { cwd: "/repos/mercon", flow: "work on ilan" } },
    dir,
    listener,
    tools: (ctx, plans) => (plansSeen.push(plans), { ctx, plans }),
    model: "claude-opus-5-5",
    env: { PATH: "/usr/bin" },
  });
  const ask = (text, extra = {}) =>
    brain.ask({ project: "mercon", chat: "T@g.us", chat_name: "PROJECT MERCON", chat_role: "team", reply_chat: "T@g.us", sender: "Ilan", n: 5, text, ...extra });
  return { dir, calls, sent, items, brain, ask, plansSeen };
}

test("brain: planning turns are read-only, keep one session per group, answer in the team group", async () => {
  const { dir, calls, sent, ask } = setup((p, id) => ok(`answer to: ${p.split("\n").at(-1)}`, id));
  try {
    await ask("did you understand these issues?", { quoted_text: "driver count wrong" });
    await ask("and the second one?");
    const o = calls[0].options;
    assert.equal(o.permissionMode, "dontAsk");
    assert.ok(o.allowedTools.includes("Read") && o.allowedTools.includes("mcp__whatsapp__preview_html"));
    assert.ok(!o.allowedTools.includes("Edit") && !o.allowedTools.some((t) => t.startsWith("Bash(git *)")));
    assert.ok(o.disallowedTools.includes("Bash(git push --force*)") && o.disallowedTools.includes("Read(**/.env)"));
    assert.equal(o.maxBudgetUsd, 3);
    assert.deepEqual(o.settingSources, ["project"]);
    assert.equal(o.env.TEAMMATE_PROJECT, "mercon");
    assert.equal(calls[1].options.resume, "S1");
    assert.match(calls[0].prompt, /^\[WhatsApp · PROJECT MERCON \(team\) · #5 · from Ilan\]\nReplying to: "driver count wrong"\ndid you understand/);
    assert.deepEqual(sent.map((s) => s.text), ["answer to: did you understand these issues?", "answer to: and the second one?"]);
    assert.ok(sent.every((s) => s.chat === "T@g.us" && s.project === "mercon"));
    assert.deepEqual(JSON.parse(readFileSync(join(dir, "sessions.json"), "utf8")), { "T@g.us": "S1" });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain: a plan, then an ok, runs one working turn with edit permissions", async () => {
  let plansApi;
  const { dir, calls, sent, items, brain, ask, plansSeen } = setup(async (p, id, options) => {
    if (p.includes("fix the transit time")) {
      plansApi = plansSeen.at(-1);
      plansApi.save({ id: 41, project: "mercon", chat: "T@g.us", chat_name: "PROJECT MERCON", title: "Transit from loading time", plan: "1. change calc 2. test", by: "Ilan" });
      return ok("Plan [41] ready. Reply @bot ok 41.", id);
    }
    return ok(options.allowedTools.includes("Edit") ? "Done: PR #300" : "plain", id);
  });
  try {
    await ask("fix the transit time");
    await brain.approve({ project: "mercon", item_id: 99, by: "Ilan", reply_chat: "T@g.us" });
    assert.match(sent.at(-1).text, /Which plan\?[\s\S]*\[41\] Transit from loading time/);

    await brain.approve({ project: "mercon", item_id: 41, by: "Alan", reply_chat: "T@g.us" });
    const work = calls.at(-1);
    assert.ok(work.options.allowedTools.includes("Edit") && work.options.allowedTools.includes("Bash(git *)"));
    assert.equal(work.options.maxBudgetUsd, 25);
    assert.equal(work.options.resume, "S1"); // same conversation as the plan
    assert.match(work.prompt, /Alan approved plan \[41\] "Transit from loading time"[\s\S]*1\. change calc/);
    assert.equal(sent.at(-1).text, "Done: PR #300");
    assert.deepEqual(items.at(-1), { update: 41, status: "in_progress", note: "OK from Alan in WhatsApp", project: "mercon" });

    // Used up: a second ok finds nothing waiting.
    await brain.approve({ project: "mercon", by: "Ilan", reply_chat: "T@g.us" });
    assert.match(sent.at(-1).text, /no plan waiting/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain: refusals while working are flagged to the owner; while planning only logged", async () => {
  const denial = { tool_name: "Bash", tool_input: { command: "sudo systemctl restart nginx" } };
  const { dir, sent, brain, ask, plansSeen } = setup(async (p, id, options) => {
    if (p.includes("plan it")) {
      plansSeen.at(-1).save({ id: 7, project: "mercon", chat: "T@g.us", chat_name: "PROJECT MERCON", title: "t", plan: "p", by: "Ilan" });
    }
    return ok("ok", id, { permission_denials: [denial] });
  });
  try {
    await ask("plan it");
    assert.equal(sent.length, 1); // planning: answer only
    await brain.approve({ project: "mercon", item_id: 7, by: "Ilan", reply_chat: "T@g.us" });
    assert.match(sent.at(-1).text, /Needs your permission[\s\S]*sudo systemctl restart nginx[\s\S]*check Claude Code/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain: order per group, customer questions, reset, failures, long replies, daily cap", async () => {
  const order = [];
  let mode = "ok";
  const long = "line\n".repeat(1500);
  const { dir, calls, sent, ask } = setup((p, id) => {
    order.push(p.split("\n").at(-1));
    if (mode === "fail") return { type: "result", subtype: "error_max_budget_usd", is_error: true, errors: [], session_id: id, permission_denials: [] };
    return ok(p.includes("long") ? long : "fine", id);
  });
  try {
    await Promise.all([ask("one"), ask("two"), ask("three")]);
    assert.deepEqual(order, ["one", "two", "three"]);

    await ask("what did they ask?", { chat: "C@g.us", chat_name: "Mercon history", chat_role: "customer" });
    assert.match(calls.at(-1).prompt, /Mercon history \(customer; answer goes to the team group\)/);
    assert.equal(sent.at(-1).chat, "T@g.us");

    const before = sent.length;
    await ask("long please");
    assert.ok(sent.length - before >= 2 && sent.slice(before).every((s) => s.text.length <= 3800));

    await ask("reset");
    assert.match(sent.at(-1).text, /fresh conversation/);
    await ask("hi again");
    assert.equal(calls.at(-1).options.resume, undefined);

    mode = "fail";
    await ask("expensive");
    assert.match(sent.at(-1).text, /spending cap/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("tools: team group only, plan recording, attention flags, allowed screenshot hosts", async () => {
  const sent = [];
  const added = [];
  const media = { 6: { data: Buffer.from([0xff, 0xd8, 0xff]), mime: "image/jpeg" }, 7: { data: Buffer.from("OggS"), mime: "audio/ogg" } };
  const asked = [];
  const listener = {
    send: async (b) => sent.push(b),
    addItem: async (b) => (added.push(b), { item: { id: 12 } }),
    media: async (n, project) => (asked.push([n, project]), media[n] || Promise.reject(new Error("HTTP 404"))),
  };
  const saved = [];
  const ctx = { project: "mercon", chat: "C@g.us", chat_name: "Mercon history", reply_chat: "T@g.us", sender: "Ilan" };
  const png = Buffer.from([0x89, 0x50, 0x4e, 0x47]);
  const render = { html: async () => png, url: async () => png };
  const server = brainTools({ ctx, listener, render, plans: { save: (p) => (saved.push(p), p) }, screenshotHosts: ["dev.mercon.app"] });
  const tools = Object.fromEntries(server.instance._registeredTools ? Object.entries(server.instance._registeredTools) : []);
  const call = async (name, args) => {
    const t = tools[name];
    assert.ok(t, `tool ${name} registered`);
    return (t.callback || t.handler)(args, {});
  };

  await call("post_message", { text: "working on it" });
  assert.deepEqual(sent.at(-1), { chat: "T@g.us", project: "mercon", text: "working on it" });

  const img = await call("preview_html", { html: "<h1>Driver count</h1>", caption: "Plan [12]: new card" });
  assert.equal(sent.at(-1).image_base64, png.toString("base64"));
  assert.equal(img.content[0].type, "image");

  const refused = await call("screenshot_url", { url: "https://evil.example.com/x", caption: "x" });
  assert.equal(refused.isError, true);
  await call("screenshot_url", { url: "https://app.dev.mercon.app/trips", caption: "current trips page" });
  assert.equal(sent.at(-1).caption, "current trips page");

  const plan = await call("propose_plan", { title: "New driver count card", plan: "Count only active drivers.", type: "bug" });
  assert.match(plan.content[0].text, /Plan \[12\] recorded/);
  assert.equal(added[0].chat, "C@g.us");
  assert.equal(saved[0].id, 12);

  await call("needs_attention", { what: "Approve the widget in Claude Code", kind: "check_claude_code" });
  assert.match(sent.at(-1).text, /👀 \*Please check Claude Code\*\nApprove the widget/);

  const seen = await call("view_media", { n: 6 });
  assert.deepEqual(seen.content[0], { type: "image", data: Buffer.from([0xff, 0xd8, 0xff]).toString("base64"), mimeType: "image/jpeg" });
  assert.deepEqual(asked[0], [6, "mercon"]);
  assert.match((await call("view_media", { n: 7 })).content[0].text, /audio\/ogg; only images/);
  assert.equal((await call("view_media", { n: 99 })).isError, true);

  assert.equal(hostAllowed("http://dev.mercon.app/a", ["dev.mercon.app"]), true);
  assert.equal(hostAllowed("file:///etc/passwd", ["dev.mercon.app"]), false);
  assert.equal(hostAllowed("https://dev.mercon.app.evil.com/", ["dev.mercon.app"]), false);
});

test("brain: chunk and system prompt", () => {
  assert.deepEqual(chunk("a\n\nb", 3), ["a", "b"]);
  assert.equal(chunk("x".repeat(10), 4).join(""), "x".repeat(10));
  const sys = systemAppend({ project: "mercon", flow: "F", owner: "Ilan" });
  assert.match(sys, /Git flow: F/);
  assert.match(sys, /needs_attention/);
  assert.match(sys, /preview_html/);
});

test("brain (hybrid): with a routine, an ok starts a cloud session and posts its link", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const sent = [];
  const fired = [];
  let fail = false;
  const brain = new Brain({
    queryFn: () => {
      throw new Error("no local working turn expected");
    },
    projects: { mercon: { cwd: "/repos/mercon", flow: "work on ilan" } },
    dir,
    listener: { send: async (b) => sent.push(b), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
    routines: { mercon: { url: "https://api.anthropic.com/v1/claude_code/routines/trig_X/fire", token: "t" } },
    fireFn: async (routine, text) => {
      if (fail) throw new Error("routine fire HTTP 429");
      fired.push({ routine, text });
      return { type: "routine_fire", claude_code_session_url: "https://claude.ai/code/session_ABC" };
    },
  });
  try {
    brain.plans.save({ id: 41, project: "mercon", chat: "H@g.us", chat_name: "Mercon history", title: "Driver count", plan: "Count active drivers only; test with 25+5.", by: "Ilan" });
    brain.plans.save({ id: 42, project: "mercon", chat: "H@g.us", chat_name: "Mercon history", title: "Other", plan: "x", by: "Ilan" });

    await brain.approve({ project: "mercon", item_id: 41, by: "Ilan", reply_chat: "H@g.us" });
    assert.equal(fired.length, 1);
    assert.match(fired[0].text, /Approved by: Ilan[\s\S]*Request log item: 41[\s\S]*Reply group jid: H@g\.us[\s\S]*Count active drivers only/);
    assert.match(sent.at(-1).text, /▶️ Working on \[41\] Driver count\nWatch it live in Claude Code: https:\/\/claude\.ai\/code\/session_ABC/);
    assert.equal(sent.at(-1).chat, "H@g.us");

    fail = true;
    await brain.approve({ project: "mercon", item_id: 42, by: "Ilan", reply_chat: "H@g.us" });
    assert.match(sent.at(-1).text, /Couldn't start the cloud session for \[42\][\s\S]*ok 42/);
    fail = false;
    await brain.approve({ project: "mercon", item_id: 42, by: "Ilan", reply_chat: "H@g.us" }); // retry works
    assert.equal(fired.length, 2);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
