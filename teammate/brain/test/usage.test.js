// TM-78 / TM-79: each Claude account's 5-hour and weekly use, and what each request used of it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";
import { Accounts, parseAccounts, windowsFromEvent, windowsFromUsage } from "../src/accounts.js";
import { usageText, boardText, Evening } from "../src/board.js";

const T0 = Date.parse("2026-11-04T09:00:00Z");
const H = 3600_000;
const ENV = { CLAUDE_CODE_OAUTH_TOKEN: "tok-a", CLAUDE_CODE_OAUTH_TOKEN_B: "tok-b", CLAUDE_ACCOUNT_NAME_B: "ilan-work" };

function accounts(now = () => T0) {
  return new Accounts({ list: parseAccounts(ENV, ["mesiri"]), now });
}

test("readings: /usage percent and rate_limit_event fractions both land as percent; unknown shapes are ignored", () => {
  assert.deepEqual(windowsFromUsage({ rate_limits: { five_hour: { utilization: 42, resets_at: "2026-11-04T12:00:00Z" }, seven_day: { utilization: 10, resets_at: null } } }), {
    five_hour: { pct: 42, resets_at: Date.parse("2026-11-04T12:00:00Z") },
    seven_day: { pct: 10, resets_at: null },
  });
  assert.equal(windowsFromUsage({ rate_limits: null }), null); // an API-key login: no plan limits
  assert.equal(windowsFromUsage(undefined), null);
  assert.deepEqual(windowsFromEvent({ status: "allowed_warning", rateLimitType: "five_hour", utilization: 0.82, resetsAt: 1762257600 }), { five_hour: { pct: 82, resets_at: 1762257600_000 } });
  assert.equal(windowsFromEvent({ status: "allowed", rateLimitType: "five_hour" }), null); // no utilization sent
  assert.equal(windowsFromEvent({ status: "allowed", rateLimitType: "overage", utilization: 0.5 }), null);
});

test("a dollar's share of a window is learned between readings; each turn's share follows from its cost", () => {
  const acc = accounts();
  const resets = T0 + 3 * H;
  assert.deepEqual(acc.spend("a", 1), { pct_5h: null, pct_7d: null }); // nothing learned yet
  acc.reading("a", { five_hour: { pct: 10, resets_at: resets }, seven_day: { pct: 5, resets_at: T0 + 100 * H } });
  acc.spend("a", 2);
  acc.spend("a", 2); // two turns, $4 in all
  acc.reading("a", { five_hour: { pct: 30, resets_at: resets }, seven_day: { pct: 7, resets_at: T0 + 100 * H } });
  assert.deepEqual(acc.spend("a", 1), { pct_5h: 5, pct_7d: 0.5 }); // 20% per $4, 2% per $4
  // A new window (it reset): no rate from the jump down, the old rate stays.
  acc.reading("a", { five_hour: { pct: 2, resets_at: resets + 5 * H } });
  assert.equal(acc.spend("a", 2).pct_5h, 10);
  // Account B learned nothing: its share is unknown, never borrowed from A.
  assert.equal(acc.spend("b", 1).pct_5h, null);
});

test("@bot account and the digest show the windows; the group is warned once per window past 80%", () => {
  let now = T0;
  const acc = accounts(() => now);
  acc.reading("b", { five_hour: { pct: 82, resets_at: T0 + 2 * H }, seven_day: { pct: 40, resets_at: T0 + 50 * H } });
  assert.match(acc.show("G"), /\*B \(ilan-work\)\*.*5-hour 82% \(resets ~\d\d:\d\d IST\) ⚠️ · weekly 40%/);
  assert.match(acc.digestLine(), /🔑 Claude: B \(ilan-work\) 5-hour 82%/);
  assert.match(acc.warning("b"), /account \*B \(ilan-work\)\* has used 82% of its 5-hour limit.*Free: A/);
  assert.equal(acc.warning("b"), null); // once per window
  assert.equal(acc.warning("a"), null); // no reading, no warning
  const snap = acc.snapshot();
  assert.deepEqual(snap.map((a) => [a.id, a.label, a.five_hour?.pct ?? null]), [["a", "A", null], ["b", "B (ilan-work)", 82]]);
  assert.ok(!JSON.stringify(snap).includes("tok-")); // never a login token
  now = T0 + 3 * H; // the 5-hour window has reset since the reading
  assert.match(acc.usageLine("b"), /^5-hour 0% · weekly 40%$/);
  now = T0 + 30 * H; // a day-old reading isn't shown as current
  assert.equal(acc.usageLine("b"), null);
});

test("a turn reads the account's windows once, charges its request, sends the readings, and warns the group", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-usage-"));
  const sent = [];
  const usage = [];
  const snapshots = [];
  let reads = 0;
  let pct = 50;
  const acc = new Accounts({ list: parseAccounts(ENV, ["mesiri"]), file: join(dir, "accounts.json"), now: () => T0 });
  const brain = new Brain({
    queryFn: ({ options }) => {
      const stream = (async function* () {
        yield { type: "system", subtype: "init", session_id: options.resume || "S1" };
        yield { type: "result", subtype: "success", result: "done", session_id: "S1", duration_ms: 10, total_cost_usd: 2, usage: { input_tokens: 1000, output_tokens: 500, cache_creation_input_tokens: 100 }, permission_denials: [] };
      })();
      stream.usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET = async () => {
        reads += 1;
        return { rate_limits: { five_hour: { utilization: pct, resets_at: new Date(T0 + 2 * H).toISOString() } } };
      };
      return stream;
    },
    projects: { mesiri: { cwd: "/repos/mesiri", flow: "main" } },
    dir,
    listener: {
      send: async (b) => sent.push(b), addItem: async () => ({}), updateItem: async () => ({}),
      addUsage: async (id, b) => usage.push({ id, ...b }), setAccounts: async (list) => snapshots.push(list),
    },
    tools: () => ({}),
    model: "claude-opus-5-5",
    env: { PATH: "/usr/bin" },
    accounts: acc,
    now: () => new Date(T0),
  });
  try {
    const req = { project: "mesiri", chat: "T@g.us", chat_name: "Mesiri team", chat_role: "team", reply_chat: "T@g.us", sender: "Ilan", sender_role: "owner", n: 5, text: "check [7] live" };
    await brain.turn({ ...req, verify_plan: 7 }, "reading");
    assert.equal(reads, 1); // one reading per turn
    assert.deepEqual(usage[0], { id: 7, account: "A", by: "team bot", cost_usd: 2, tokens: 1600, pct_5h: null, pct_7d: null, project: "mesiri" });
    assert.equal(snapshots.at(-1)[0].five_hour.pct, 50);
    pct = 85; // the next reading sees the rise: 35% for the $2 spent since
    await brain.turn({ ...req, verify_plan: 7 }, "reading");
    assert.equal(usage[1].pct_5h, 35);
    assert.ok(sent.some((m) => /account \*A\* has used 85% of its 5-hour limit/.test(m.text)));
    // A turn for no request (plain chat) charges nobody, but the readings still go out.
    await brain.turn(req, "reading");
    assert.equal(usage.length, 2);
    assert.equal(snapshots.length, 3);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("@bot status and the evening digest carry the usage", async () => {
  const item = { id: 227, title: "Tap on an old card", status: "in_progress", stage: "building", usage_usd: 2.1, usage_5h: 14, usage_7d: 3, usage_turns: 5, usage_accounts: "B (ilan-work)" };
  assert.equal(usageText(item), "Claude usage: ~14% of a 5-hour window, ~3% of the week · $2.10 · 5 turns on B (ilan-work)");
  assert.equal(usageText({ id: 1 }), null);
  assert.equal(usageText({ usage_turns: 1, usage_usd: 0.5, usage_5h: null, usage_7d: null }), "Claude usage: $0.50 · 1 turn");
  assert.match(boardText([item], T0), /\[227\] Tap on an old card\n {3}🛠 being built · ~14% 5h · \$2\.10/);
  const notes = [];
  const ev = new Evening({ projects: ["mesiri"], items: async () => [{ ...item, created_at: new Date(T0 + 5 * H).toISOString() }], notify: async (p, t) => notes.push(t), file: join(mkdtempSync(join(tmpdir(), "ev-")), "e.json"), now: () => T0 + 5 * H, accountsLine: () => "• 🔑 Claude: A 5-hour 35%" });
  await ev.maybeSend();
  assert.match(notes[0], /• 🔑 Claude: A 5-hour 35%\n@bot status/);
});
