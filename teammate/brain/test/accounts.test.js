import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";
import { Accounts, parseAccounts } from "../src/accounts.js";

const ok = (text, id) => ({ type: "result", subtype: "success", is_error: false, result: text, session_id: id, duration_ms: 1200, total_cost_usd: 0.01, permission_denials: [] });
const URL = (x) => `https://api.anthropic.com/v1/claude_code/routines/trig_${x}/fire`;

const ENV = {
  PATH: "/usr/bin",
  CLAUDE_CODE_OAUTH_TOKEN: "tok-a",
  TEAMMATE_ROUTINE_MESIRI_URL: URL("A"),
  TEAMMATE_ROUTINE_MESIRI_TOKEN: "rt-a",
  TEAMMATE_PARTNER_MESIRI_URL: URL("PA"),
  TEAMMATE_PARTNER_MESIRI_TOKEN: "pt-a",
  CLAUDE_CODE_OAUTH_TOKEN_C: "tok-c",
  TEAMMATE_ROUTINE_MESIRI_URL_C: URL("C"),
  TEAMMATE_ROUTINE_MESIRI_TOKEN_C: "rt-c",
  CLAUDE_CODE_OAUTH_TOKEN_B: "tok-b", // no routine on B
  CLAUDE_CODE_OAUTH_TOKEN_D: "", // empty secret: not an account
  TEAMMATE_ROUTINE_MESIRI_URL_E: URL("E"), // a routine without a Claude login: not an account
  TEAMMATE_ROUTINE_MESIRI_TOKEN_E: "rt-e",
};

test("accounts: A is the plain variables, B, C, … the same with their letter; only a Claude login makes an account", () => {
  const list = parseAccounts(ENV, ["mesiri", "mercon"]);
  assert.deepEqual(list.map((a) => a.id), ["a", "b", "c"]);
  assert.deepEqual(list[0], { id: "a", token: "tok-a", routines: { mesiri: { url: URL("A"), token: "rt-a" } }, partners: { mesiri: { url: URL("PA"), token: "pt-a" } } });
  assert.deepEqual(list[1], { id: "b", token: "tok-b", routines: {}, partners: {} });
  assert.deepEqual(list[2].routines, { mesiri: { url: URL("C"), token: "rt-c" } });
  // No extra accounts: exactly the old single-account setup.
  assert.deepEqual(parseAccounts({ CLAUDE_CODE_OAUTH_TOKEN: "x" }, ["mesiri"]).map((a) => a.id), ["a"]);
});

test("accounts: owners pick an account per group, or the default; anyone approved can look; it survives a restart", () => {
  const dir = mkdtempSync(join(tmpdir(), "acc-"));
  const file = join(dir, "accounts.json");
  const owner = (text, chat = "G1") => acc.command({ text, chat, sender_role: "owner", sender: "Ilan" });
  let acc;
  try {
    acc = new Accounts({ list: parseAccounts(ENV, ["mesiri"]), file });
    assert.equal(acc.command({ text: "what's the weather", chat: "G1" }), null);
    assert.match(acc.command({ text: "account", chat: "G1" }), /\*A\*  default ← this group[\s\S]*\*B\* \(no cloud routine\)[\s\S]*\*C\*[\s\S]*This group: \*A\* \(the default\)[\s\S]*switching on a usage limit: \*on\*/);
    assert.match(acc.command({ text: "account b", chat: "G1", sender_role: "approved" }), /Only an owner/);
    assert.match(acc.command({ text: "account b", chat: "D1", sender_role: "owner", dm: true }), /team group only/);
    assert.match(owner("account z"), /no account \*Z\*[\s\S]*A, B, C/);

    // Per group: G1 on C, G2 on B, G3 follows the default.
    assert.match(owner("account C"), /This group now runs on Claude account \*C\*[\s\S]*Other groups are unchanged/);
    assert.match(owner("switch account to b", "G2"), /This group now runs on Claude account \*B\*/);
    assert.deepEqual(acc.env("G1"), { CLAUDE_CODE_OAUTH_TOKEN: "tok-c" });
    assert.deepEqual(acc.env("G2"), { CLAUDE_CODE_OAUTH_TOKEN: "tok-b" });
    assert.deepEqual(acc.env("G3"), { CLAUDE_CODE_OAUTH_TOKEN: "tok-a" });
    assert.match(acc.command({ text: "account", chat: "G2" }), /This group: \*B\*\n/);

    // The default moves the groups that haven't picked one; "reset" puts a group back on it.
    assert.match(owner("account default c", "G3"), /Default Claude account is now \*C\* \(groups that picked their own keep it: 2\)/);
    assert.equal(acc.for("G3").id, "c");
    assert.equal(acc.for("G2").id, "b");
    assert.match(owner("account reset", "G2"), /follows the default account again \(\*C\*\)/);
    assert.equal(acc.for("G2").id, "c");
    assert.match(owner("account b everywhere", "G2"), /Default Claude account is now \*B\*/);

    assert.match(owner("account auto off"), /Automatic switching is off/);
    const again = new Accounts({ list: parseAccounts(ENV, ["mesiri"]), file });
    assert.equal(again.for("G1").id, "c");
    assert.equal(again.for("G2").id, "b");
    assert.equal(again.state.auto, false);
    // Accounts whose login was removed: those groups and the default go back to A.
    const fewer = new Accounts({ list: parseAccounts({ CLAUDE_CODE_OAUTH_TOKEN: "tok-a" }, ["mesiri"]), file });
    assert.equal(fewer.for("G1").id, "a");
    assert.equal(fewer.state.default, "a");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("accounts: at a limit a group borrows the next free account (letter order, wraps round), then goes back to its own", () => {
  let t = 1_000_000;
  const acc = new Accounts({ list: parseAccounts(ENV, ["mesiri"]), now: () => t });
  assert.deepEqual(acc.failover({ resetAt: t + 3_600_000 }, "G"), { from: "a", to: "b" });
  assert.equal(acc.for("G").id, "b");
  assert.deepEqual(acc.failover({ resetAt: null }, "G"), { from: "b", to: "c" }); // no reset time: 30 min
  assert.equal(acc.failover({ resetAt: t + 7_200_000 }, "G"), null); // all three limited
  assert.equal(acc.earliestReset(), t + 30 * 60_000); // B frees up first
  t += 31 * 60_000;
  assert.equal(acc.for("G").id, "b"); // A still limited: borrows B, now free
  t += 3 * 3_600_000; // everyone free again
  assert.equal(acc.for("G").id, "a"); // back on its own account
  // Only accounts that fit, e.g. that have a routine for the project (B has none).
  assert.deepEqual(acc.failover({ resetAt: t + 60_000 }, "G", (a) => a.routines.mesiri), { from: "a", to: "c" });
  // The limit is the account's: another group on A borrows too; a group that picked B is unaffected.
  acc.state.groups.H = "b";
  assert.equal(acc.for("G2").id, "b");
  assert.equal(acc.for("H").id, "b");
  // Automatic switching off: remembers the limit, doesn't move.
  acc.state.auto = false;
  assert.equal(acc.for("G").id, "a");
  assert.equal(acc.failover({ resetAt: t + 60_000 }, "G"), null);
});

function setup({ answer, fire } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "brain-acc-"));
  const calls = [];
  const sent = [];
  const fired = [];
  let n = 0;
  const t0 = Date.parse("2026-10-28T09:00:00Z");
  const accounts = new Accounts({ list: parseAccounts(ENV, ["mesiri"]), file: join(dir, "accounts.json"), now: () => t0 });
  const brain = new Brain({
    queryFn: ({ prompt, options }) => {
      calls.push({ prompt, options });
      const id = options.resume || `S${++n}`;
      return (async function* () {
        yield { type: "system", subtype: "init", session_id: id };
        yield* answer(options, id);
      })();
    },
    projects: { mesiri: { cwd: "/repos/mesiri", flow: "main" } },
    dir,
    listener: { send: async (b) => sent.push(b), addItem: async () => ({}), updateItem: async () => ({}) },
    tools: () => ({}),
    model: "claude-opus-5-5",
    env: { PATH: "/usr/bin" },
    accounts,
    fireFn: async (routine, text) => {
      fired.push({ routine, text });
      return fire(routine);
    },
    now: () => new Date(t0),
  });
  const ask = (text, extra = {}) => brain.ask({ project: "mesiri", chat: "T@g.us", chat_name: "Mesiri team", chat_role: "team", reply_chat: "T@g.us", sender: "Ilan", sender_role: "owner", n: 5, text, ...extra });
  return { dir, calls, sent, fired, brain, ask, accounts, t0 };
}

test("brain + accounts: each turn runs on the active account's login only; a usage limit switches and asks again there", async () => {
  const limited = new Set(["tok-a"]);
  const { dir, calls, sent, ask, accounts, t0 } = setup({
    answer: async function* (options, id) {
      if (limited.has(options.env.CLAUDE_CODE_OAUTH_TOKEN)) {
        yield { type: "rate_limit_event", rate_limit_info: { status: "rejected", resetsAt: (t0 + 2 * 3_600_000) / 1000 } };
        yield { type: "result", subtype: "error_during_execution", is_error: true, errors: ["You've hit your limit"], session_id: id };
        return;
      }
      yield ok(`answered on ${options.env.CLAUDE_CODE_OAUTH_TOKEN}`, id);
    },
  });
  try {
    await ask("why is the DPR late?");
    assert.equal(calls.length, 2);
    assert.equal(calls[0].options.env.CLAUDE_CODE_OAUTH_TOKEN, "tok-a");
    assert.equal(calls[1].options.env.CLAUDE_CODE_OAUTH_TOKEN, "tok-b");
    assert.ok(!Object.keys(calls[1].options.env).some((k) => /_B$|_C$/.test(k))); // other accounts' secrets never reach Claude
    assert.equal(calls[1].options.resume, calls[0].options.resume ?? "S1"); // same conversation
    assert.match(sent[0].text, /account \*A\* hit its usage limit; this group uses \*B\* until it resets \(~[^)]+\)/);
    assert.equal(sent[1].text, "answered on tok-b");
    assert.ok(JSON.parse(readFileSync(join(dir, "accounts.json"), "utf8")).limited.a > t0);

    // Every account limited: one retry per account, then the usual pause message, no loop.
    limited.add("tok-b").add("tok-c");
    sent.length = 0;
    calls.length = 0;
    await ask("and now?");
    assert.equal(calls.length, 2); // B, then C (A is still limited)
    assert.match(sent.at(-1).text, /Every Claude account this group can use is at its usage limit; it resets ~/);

    // An owner can force an account (e.g. after topping it up).
    limited.clear();
    sent.length = 0;
    await ask("account a");
    assert.match(sent[0].text, /This group now runs on Claude account \*A\*/);
    await ask("hello");
    assert.equal(sent.at(-1).text, "answered on tok-a");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("brain + accounts: approved work fires the active account's routine; on a limit, the next account that has one", async () => {
  const { dir, fired, sent, brain, accounts } = setup({
    answer: async function* () {},
    fire: (routine) => {
      if (routine.token === "rt-a") throw new Error("routine fire HTTP 429 usage limit reached");
      return { claude_code_session_id: "cse_C1" };
    },
  });
  try {
    brain.plans.save({ id: 7, project: "mesiri", chat: "T@g.us", chat_name: "Mesiri team", title: "Fix DPR", plan: "x", by: "Ilan" });
    await brain.approve({ project: "mesiri", item_id: 7, by: "Ilan", reply_chat: "T@g.us", sender_role: "owner" });
    assert.deepEqual(fired.map((f) => f.routine.token), ["rt-a", "rt-c"]); // B has no routine, so C
    assert.equal(accounts.for("T@g.us", (a) => a.routines.mesiri).id, "c");
    assert.match(sent[0].text, /this group uses \*C\*/);
    assert.match(sent[1].text, /Working on \[7\][\s\S]*session_C1/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
