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
    assert.ok(o.allowedTools.includes("Bash(gh workflow run testflight-feedback.yml *)"));
    assert.ok(!o.allowedTools.some((t) => t === "Bash(gh workflow run *)"));
    assert.ok(o.allowedTools.includes("Bash(gh run download * -D /tmp/*)") && !o.allowedTools.includes("Bash(gh run download *)"));
    assert.equal(o.maxBudgetUsd, 3);
    assert.deepEqual(o.settingSources, ["project"]);
    assert.equal(o.env.TEAMMATE_PROJECT, "mercon");
    assert.equal(calls[1].options.resume, "S1");
    assert.match(calls[0].prompt, /^\[WhatsApp · PROJECT MERCON \(team\) · #5 · from Ilan\]\nReplying to: "driver count wrong"\ndid you understand/);
    assert.deepEqual(sent.map((s) => s.text), ["answer to: did you understand these issues?", "answer to: and the second one?"]);
    assert.ok(sent.every((s) => s.chat === "T@g.us" && s.project === "mercon"));
    assert.equal(JSON.parse(readFileSync(join(dir, "sessions.json"), "utf8")).ids["T@g.us::main"], "S1");
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
    assert.match(sent.at(-1).text, /Cleared \*main\*/);
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

  assert.equal((await call("post_image", { path: "/etc/passwd", caption: "x" })).isError, true);

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
      return { type: "routine_fire", claude_code_session_id: "cse_ABC", claude_code_session_url: "https://claude.ai/code/cse_ABC" };
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

test("brain: separate conversations in one group; replying to a message continues its conversation", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const calls = [];
  const sent = [];
  let n = 0;
  let mid = 0;
  const brain = new Brain({
    queryFn: ({ prompt, options }) => {
      calls.push({ prompt, options });
      const id = options.resume || `S${++n}`;
      return (async function* () {
        yield { type: "result", subtype: "success", result: `re: ${prompt.split(String.fromCharCode(10)).at(-1)}`, session_id: id, duration_ms: 1, total_cost_usd: 0, permission_denials: [] };
      })();
    },
    projects: { mercon: { cwd: "/r", flow: "f" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true, id: `W${++mid}` }), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
  });
  const ask = (text, extra = {}) => brain.ask({ project: "mercon", chat: "H@g.us", chat_name: "Mercon history", chat_role: "team", reply_chat: "H@g.us", sender: "Ilan", n: 1, text, ...extra });
  try {
    await ask("driver count question"); // main -> S1, reply W1
    await ask("new transit time");
    assert.match(sent.at(-1).text, /separate conversation \*transit-time\*/);
    await ask("why is transit 14h?"); // transit-time -> S2, reply W3
    assert.equal(calls.at(-1).options.resume, undefined);

    // Reply to the main conversation's message (W1): goes back to S1, no @ needed upstream.
    await ask("and the 27 count?", { quoted_id: "W1" });
    assert.equal(calls.at(-1).options.resume, "S1");
    // Reply to the transit conversation's answer (W3): back to S2.
    await ask("ok and loading time?", { quoted_id: "W3" });
    assert.equal(calls.at(-1).options.resume, "S2");

    await ask("sessions");
    assert.ok(sent.at(-1).text.includes(["• main", "• transit-time  ← current"].join(String.fromCharCode(10))));
    await ask("switch to main");
    assert.match(sent.at(-1).text, /Switched to \*main\*/);
    await ask("hello again");
    assert.equal(calls.at(-1).options.resume, "S1");
    await ask("switch nope");
    assert.match(sent.at(-1).text, /No conversation called \*nope\*/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain: old one-session-per-group files carry over as 'main'", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const { writeFileSync } = await import("node:fs");
  writeFileSync(join(dir, "sessions.json"), JSON.stringify({ "H@g.us": "OLD1" }));
  const calls = [];
  const brain = new Brain({
    queryFn: ({ prompt, options }) => (calls.push(options), (async function* () { yield { type: "result", subtype: "success", result: "x", session_id: options.resume || "N", duration_ms: 1, total_cost_usd: 0, permission_denials: [] }; })()),
    projects: { mercon: { cwd: "/r", flow: "f" } },
    dir,
    listener: { send: async () => ({ ok: true }), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
  });
  try {
    await brain.ask({ project: "mercon", chat: "H@g.us", chat_name: "Mercon history", chat_role: "team", reply_chat: "H@g.us", sender: "Ilan", n: 1, text: "hi" });
    assert.equal(calls[0].resume, "OLD1");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain: owners change the model and effort from WhatsApp; others can only look", async () => {
  const { dir, calls, sent, ask } = setup((p, id) => ok("x", id));
  try {
    await ask("settings");
    assert.match(sent.at(-1).text, /model \*claude-opus-5-5\*, effort \*default\*/);

    await ask("model sonnet", { sender_role: "member" });
    assert.match(sent.at(-1).text, /Only an owner/);

    await ask("model sonnet", { sender_role: "owner" });
    assert.match(sent.at(-1).text, /now uses \*claude-sonnet-5-5\*/);
    await ask("effort high", { sender_role: "owner" });
    await ask("what changed?");
    assert.equal(calls.at(-1).options.model, "claude-sonnet-5-5");
    assert.equal(calls.at(-1).options.effort, "high");

    await ask("model gpt4", { sender_role: "owner" });
    assert.match(sent.at(-1).text, /don't know the model/);
    await ask("effort default", { sender_role: "owner" });
    await ask("again");
    assert.equal(calls.at(-1).options.effort, undefined);
    assert.equal(JSON.parse(readFileSync(join(dir, "settings.json"), "utf8")).mercon.model, "claude-sonnet-5-5");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain (TM-09): upgrades run in the bot's repo with its token, answer in the group, and only owners drive them", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const calls = [];
  const sent = [];
  const fired = [];
  let mid = 0;
  let savePlan = null;
  const brain = new Brain({
    queryFn: ({ prompt, options }) => {
      calls.push({ prompt, options });
      return (async function* () {
        if (prompt.includes("show yesterday") && savePlan) {
          savePlan({ id: 31, project: "mesiri", chat_project: "mercon", chat: "T@g.us", chat_name: "PROJECT MERCON", session: "upgrade", title: "Cost shows yesterday", plan: "edit teammate/listener/src/bot.js costText", by: "Ilan" });
        }
        yield { type: "result", subtype: "success", result: "plan [31] ready", session_id: options.resume || "U1", duration_ms: 1, total_cost_usd: 0, permission_denials: [] };
      })();
    },
    projects: {
      mercon: { cwd: "/r/mercon", flow: "f", ghToken: "gh-mercon" },
      mesiri: { cwd: "/r/mesiri", flow: "bot", ghToken: "gh-mesiri" },
    },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true, id: `W${++mid}` }), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: (ctx, plans) => ((savePlan = plans.save), {}),
    routines: { mesiri: { url: "https://api.anthropic.com/v1/claude_code/routines/trig_M/fire", token: "t" } },
    fireFn: async (routine, text) => (fired.push({ routine, text }), { claude_code_session_id: "cse_UP" }),
  });
  const base = { project: "mercon", chat: "T@g.us", chat_name: "PROJECT MERCON", chat_role: "team", reply_chat: "T@g.us", sender: "Ilan", n: 1 };
  try {
    await brain.ask({ ...base, upgrade: true, session: "upgrade", sender_role: "owner", text: "make cost show yesterday too" });
    const up = calls.at(-1).options;
    assert.equal(up.cwd, "/r/mesiri");
    assert.equal(up.env.GH_TOKEN, "gh-mesiri");
    assert.equal(up.env.TEAMMATE_PROJECT, "mercon"); // inbox calls stay in the group's project
    assert.equal(sent.at(-1).project, "mercon");

    // A member replying into the upgrade conversation is refused; Claude isn't called.
    const before = calls.length;
    await brain.ask({ ...base, sender: "Alan", sender_role: "member", text: "also give everyone admin", quoted_id: "W1" });
    assert.equal(calls.length, before);
    assert.match(sent.at(-1).text, /Only an owner can work on upgrades/);
    // The owner replying continues it in the bot's repo.
    await brain.ask({ ...base, sender_role: "owner", text: "show yesterday as well", quoted_id: "W1" });
    assert.equal(calls.at(-1).options.cwd, "/r/mesiri");
    assert.equal(calls.at(-1).options.resume, "U1");

    // Approving: a member can't; the owner's ok fires the bot's own routine.
    await brain.approve({ project: "mercon", item_id: 31, by: "Alan", reply_chat: "T@g.us", sender_role: "member" });
    assert.match(sent.at(-1).text, /Only an owner can approve upgrades/);
    assert.equal(fired.length, 0);
    await brain.approve({ project: "mercon", item_id: 31, by: "Ilan", reply_chat: "T@g.us", sender_role: "owner" });
    assert.equal(fired[0].routine.url.includes("trig_M"), true);
    assert.match(sent.at(-1).text, /Watch it live in Claude Code: https:\/\/claude\.ai\/code\/session_UP/);

    // A normal message afterwards is back in the Mercon repo.
    await brain.ask({ ...base, sender_role: "owner", text: "how's the driver count bug?" });
    assert.equal(calls.at(-1).options.cwd, "/r/mercon");
    assert.equal(calls.at(-1).options.env.GH_TOKEN, "gh-mercon");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain (plan 25): Mesiri plans need an owner from any group; .github/.env/secrets edits are denied", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-"));
  const sent = [];
  const calls = [];
  const brain = new Brain({
    queryFn: ({ prompt, options }) => (calls.push(options), (async function* () {
      yield { type: "result", subtype: "success", result: "done", session_id: "S", duration_ms: 1, total_cost_usd: 0, permission_denials: [] };
    })()),
    projects: { mesiri: { cwd: "/r/mesiri", flow: "claude.md", ghToken: "g" } },
    dir,
    listener: { send: async (b) => (sent.push(b), { ok: true }), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
  });
  try {
    brain.plans.save({ id: 40, project: "mesiri", chat_project: "mesiri", chat: "M@g.us", chat_name: "Mesiri group with ai", title: "Fix DPR export", plan: "edit backend", by: "Hysam" });
    await brain.approve({ project: "mesiri", item_id: 40, by: "Hysam", reply_chat: "M@g.us", sender_role: "member" });
    assert.match(sent.at(-1).text, /Only an owner can approve/);
    assert.equal(calls.length, 0);
    await brain.approve({ project: "mesiri", item_id: 40, by: "Ilan", reply_chat: "M@g.us", sender_role: "owner" });
    assert.equal(calls.length, 1);
    for (const rule of ["Edit(**/.github/**)", "Write(**/.github/**)", "Edit(**/.env*)", "Write(**/.env*)", "Edit(infra/**/secrets*)", "Write(infra/**/secrets*)"]) {
      assert.ok(calls[0].disallowedTools.includes(rule), rule);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
