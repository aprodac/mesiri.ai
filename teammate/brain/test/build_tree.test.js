// TM-31: the build worktree on the bot server, with real git in a temp folder.
import assert from "node:assert/strict";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { tmpdir } from "node:os";
import { BUILD_BRANCH, PY_EXTRAS, buildPath, prepareBuildTree, pushLeftovers } from "../src/build_tree.js";

const env = { ...process.env, GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@t", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@t" };
const git = (cwd, ...args) => execFileSync("git", ["-C", cwd, ...args], { stdio: "pipe", env }).toString().trim();

function world() {
  const dir = mkdtempSync(join(tmpdir(), "bt-"));
  const origin = join(dir, "origin.git");
  execFileSync("git", ["init", "-q", "--bare", "-b", "main", origin], { env });
  const seed = join(dir, "seed");
  execFileSync("git", ["clone", "-q", origin, seed], { env, stdio: "pipe" });
  writeFileSync(join(seed, "pyproject.toml"), "[project]\nname='x'\n");
  writeFileSync(join(seed, ".gitignore"), ".venv/\n");
  git(seed, "add", "-A");
  git(seed, "commit", "-q", "-m", "one");
  git(seed, "push", "-q", "origin", "HEAD:main");
  const cwd = join(dir, "repos", "mesiri");
  mkdirSync(join(dir, "repos"));
  execFileSync("git", ["clone", "-q", origin, cwd], { env, stdio: "pipe" });
  const project = { name: "mesiri", branch: "main", cwd, buildCwd: buildPath(dir, "mesiri") };
  return { dir, seed, project };
}

test("the build copy is a worktree named like the project, on bot-build at origin/main; packages install once", () => {
  const { dir, seed, project } = world();
  try {
    const runs = [];
    const run = (cmd, args, cwd) => {
      runs.push([cmd, ...args].join(" "));
      if (args[0] === "venv") { mkdirSync(join(cwd, ".venv", "bin"), { recursive: true }); writeFileSync(join(cwd, ".venv", "bin", "python"), ""); }
    };
    assert.equal(prepareBuildTree(project, { git, run }), "installed");
    assert.equal(basename(git(project.buildCwd, "rev-parse", "--show-toplevel")), "mesiri"); // the pre-push hook's rule
    assert.equal(git(project.buildCwd, "rev-parse", "--abbrev-ref", "HEAD"), BUILD_BRANCH);
    assert.deepEqual(runs, ["uv venv --python 3.11", `uv pip install --quiet -e ${PY_EXTRAS}`]);
    // Nothing changed: warm, no install.
    assert.equal(prepareBuildTree(project, { git, run }), "warm");
    assert.equal(runs.length, 2);
    // A new commit on origin is followed; a changed pyproject installs again (no new venv).
    writeFileSync(join(seed, "pyproject.toml"), "[project]\nname='x'\nversion='2'\n");
    git(seed, "commit", "-q", "-am", "two");
    git(seed, "push", "-q", "origin", "HEAD:main");
    assert.equal(prepareBuildTree(project, { git, run }), "installed");
    assert.equal(git(project.buildCwd, "log", "-1", "--format=%s"), "two");
    assert.equal(runs.length, 3);
    assert.ok(existsSync(join(project.buildCwd, ".venv", ".teammate-deps"))); // ignored files stay
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a previous build's leftovers are kept on a backup branch, never lost; the shared copy is untouched", () => {
  const { dir, project } = world();
  try {
    const run = () => {};
    prepareBuildTree(project, { git, run });
    writeFileSync(join(project.buildCwd, "half.txt"), "half-written");
    writeFileSync(join(project.cwd, "shared.txt"), "someone else's turn");
    prepareBuildTree(project, { git, run, now: () => new Date("2026-11-02T10:00:00Z") });
    assert.ok(!existsSync(join(project.buildCwd, "half.txt")));
    assert.equal(git(project.buildCwd, "show", "unpushed-build/20261102100000:half.txt"), "half-written");
    assert.equal(readFileSync(join(project.cwd, "shared.txt"), "utf8"), "someone else's turn");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("a failed install throws, so the brain builds in the cloud instead", () => {
  const { dir, project } = world();
  try {
    assert.throws(() => prepareBuildTree(project, { git, run: () => { throw new Error("uv: not found"); } }), /uv: not found/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// TM-56 (3 Nov: [207] built, push refused, request still marked done).
test("commits a build left behind are pushed once; a refused push is reported, not lost", () => {
  const { dir, seed, project } = world();
  try {
    prepareBuildTree(project, { git, run: () => {} });
    assert.deepEqual(pushLeftovers(project, { git }), { ahead: 0, pushed: false, error: null });
    writeFileSync(join(project.buildCwd, "a.txt"), "a");
    git(project.buildCwd, "add", "-A");
    git(project.buildCwd, "commit", "-q", "-m", "WA-153 [207]: add a member");
    // someone else pushed meanwhile: rebased first
    writeFileSync(join(seed, "b.txt"), "b");
    git(seed, "add", "-A");
    git(seed, "commit", "-q", "-m", "other");
    git(seed, "push", "-q", "origin", "HEAD:main");
    assert.deepEqual(pushLeftovers(project, { git }), { ahead: 1, pushed: true, error: null });
    git(seed, "pull", "-q", "origin", "main");
    assert.match(git(seed, "log", "-1", "--format=%s"), /WA-153 \[207\]/);
    // a remote that refuses: the error comes back, the commit stays
    writeFileSync(join(project.buildCwd, "c.txt"), "c");
    git(project.buildCwd, "add", "-A");
    git(project.buildCwd, "commit", "-q", "-m", "more");
    git(project.cwd, "remote", "set-url", "origin", join(dir, "gone.git"));
    const r = pushLeftovers(project, { git: (cwd, ...a) => (a[0] === "fetch" ? "" : git(cwd, ...a)) });
    assert.equal(r.pushed, false);
    assert.ok(r.error && r.error.length > 0);
    assert.equal(git(project.buildCwd, "log", "-1", "--format=%s"), "more");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// TM-54: the askers' real turns go into the build copy, never into a commit.
test("the real turns are saved in the build copy and ignored by git", async () => {
  const { saveReplays } = await import("../src/build_tree.js");
  const { dir, project } = world();
  try {
    prepareBuildTree(project, { git, run: () => {} });
    const paths = saveReplays(project, [{ correlation_id: "cor_ab12cd34ef", text: "Rana Mart", calls: [] }, { correlation_id: "../evil" }], { git });
    assert.deepEqual(paths, [".teammate-replays/cor_ab12cd34ef.json"]);
    assert.match(readFileSync(join(project.buildCwd, paths[0]), "utf8"), /Rana Mart/);
    assert.equal(git(project.buildCwd, "status", "--porcelain"), ""); // excluded: nothing to commit
    saveReplays(project, [], { git }); // twice: the exclude line isn't repeated
    const exclude = readFileSync(join(project.cwd, ".git", "info", "exclude"), "utf8");
    assert.equal(exclude.split("\n").filter((l) => l === ".teammate-replays/").length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
