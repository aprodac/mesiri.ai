// TM-44 (2 Nov): Ilan said "mesiri bad ux" and got no "Is this how you want it?"; the watch turn didn't send it and
// nothing noticed. The code checks: one follow-up turn to send it; still none, the group is told why.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { Brain } from "../src/brain.js";

const CID = "cor_8fa51b0000000000";

function make(onTurn) {
  const dir = mkdtempSync(join(tmpdir(), "preview-"));
  const sent = [];
  const turns = [];
  const brain = new Brain({
    queryFn: () => {
      throw new Error("no AI turn in these tests");
    },
    projects: { mesiri: { cwd: "/r", flow: "f" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      chats: async () => ({ chats: [{ jid: "T@g.us", role: "team", project: "mesiri", name: "Mesiri group" }] }),
      addItem: async () => ({}),
      updateItem: async () => ({}),
    },
    tools: () => ({}),
  });
  brain.previewsOn = true;
  brain.turn = async (req) => {
    turns.push(req.text);
    onTurn?.(req, turns.length);
  };
  return { dir, brain, sent, turns };
}

const conv = (feedback) => ({ person: "Ilan", messages: [{ correlation_id: CID, feedback }] });

test("a bad-UX request without a preview gets one follow-up turn, then the group is told", async () => {
  const { dir, brain, sent, turns } = make();
  try {
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("bad_ux: the list came twice")]);
    assert.equal(turns.length, 2);
    assert.match(turns[1], /no "Is this how you want it\?" preview went out for conversation 1 \(Ilan, #8fa51b\)/);
    assert.match(sent.at(-1).text, /⚠️ No preview went to Ilan for #8fa51b \(the watch turn did not send one\)/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the follow-up that sends it ends the check quietly", async () => {
  const { dir, brain, sent, turns } = make((req, n) => n === 2 && req.previewed.add(CID));
  try {
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("bad_ux: the list came twice")]);
    assert.equal(turns.length, 2);
    assert.equal(sent.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("guard: a plain bug, or a preview sent in the first turn, asks for nothing more", async () => {
  const { dir, brain, sent, turns } = make((req, n) => n === 1 && req.previewed.add(CID));
  try {
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("bad_ux: x")]);
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("wrong_reply: the total is wrong")]);
    assert.equal(turns.length, 2); // one planning turn each, no follow-up
    assert.equal(sent.length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a refused preview is reported with Mesiri's reason, without another turn", async () => {
  const { dir, brain, sent, turns } = make((req) => req.preview_failed.push("#8fa51b: outside the 24-hour window"));
  try {
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("missing_feature: create a project")]);
    assert.equal(turns.length, 1);
    assert.match(sent.at(-1).text, /outside the 24-hour window/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// 3 Nov: a preview went to Ilan for #cf124a and the group was still told "No preview went": the turn's tool context
// never received the set send_preview records into (the tests above replaced the turn). Through a real turn now.
test("a preview sent by the real turn's tool is seen by the check", async () => {
  const dir = mkdtempSync(join(tmpdir(), "preview-"));
  const sent = [];
  let ctxSeen = null;
  const brain = new Brain({
    queryFn: () =>
      (async function* () {
        ctxSeen.previewed.add(CID); // what send_preview does on success (tools.js)
        yield { type: "result", subtype: "success", is_error: false, result: "QUIET", session_id: "S", duration_ms: 1, total_cost_usd: 0, permission_denials: [] };
      })(),
    projects: { mesiri: { cwd: "/r", flow: "f" } },
    dir,
    listener: {
      send: async (b) => (sent.push(b), { ok: true }),
      chats: async () => ({ chats: [{ jid: "T@g.us", role: "team", project: "mesiri", name: "Mesiri group" }] }),
      addItem: async () => ({}),
      updateItem: async () => ({}),
    },
    tools: (ctx) => ((ctxSeen = ctx), {}),
  });
  brain.previewsOn = true;
  try {
    await brain.askWatch("mesiri", "watch prompt", "QUIET", [conv("missing_feature: add a member")]);
    assert.ok(ctxSeen.previewed instanceof Set);
    assert.equal(sent.filter((m) => /No preview went/.test(m.text)).length, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
