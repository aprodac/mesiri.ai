// 3 Nov: a line using `opsByProject` before its declaration crash-looped the team bot all night (ReferenceError at
// start-up, thousands of restarts, no request picked up). Unit tests import modules, never main.js, so none saw it.
// This starts the real entry point with a dummy setup and requires it to come up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const MAIN = fileURLToPath(new URL("../src/main.js", import.meta.url));

test("the team bot starts: main.js comes up with a minimal setup and says it is listening", async () => {
  const dir = mkdtempSync(join(tmpdir(), "brain-start-"));
  const port = String(20000 + Math.floor(Math.random() * 20000));
  const child = spawn(process.execPath, [MAIN], {
    env: {
      PATH: process.env.PATH, HOME: dir,
      TEAMMATE_API_TOKEN: "x".repeat(32), TEAMMATE_API: "http://127.0.0.1:9", TEAMMATE_BRAIN_DIR: dir,
      TEAMMATE_BRAIN_PORT: port, TEAMMATE_BRAIN_PROJECTS: "mesiri=aprodac/mesiri.ai@main",
      // a production-watch source, so every start-up path that reads it runs
      TEAMMATE_OPS_MESIRI_URL: "http://127.0.0.1:9", TEAMMATE_OPS_MESIRI_TOKEN: "y".repeat(32),
    },
  });
  let out = "";
  child.stdout.on("data", (b) => (out += b));
  child.stderr.on("data", (b) => (out += b));
  try {
    const up = await new Promise((resolve) => {
      let check = null;
      const finish = (ok) => {
        clearInterval(check);
        clearTimeout(timer);
        resolve(ok);
      };
      const timer = setTimeout(() => finish(false), 15000);
      child.on("exit", () => finish(/listening on 127\.0\.0\.1:/.test(out)));
      check = setInterval(() => /listening on 127\.0\.0\.1:/.test(out) && finish(true), 50);
    });
    assert.ok(up, `the bot did not come up:\n${out.slice(-1500)}`);
    assert.doesNotMatch(out, /ReferenceError|TypeError|SyntaxError/);
  } finally {
    child.kill("SIGKILL");
    rmSync(dir, { recursive: true, force: true });
  }
});
