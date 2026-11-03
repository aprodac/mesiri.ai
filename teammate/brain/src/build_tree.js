// The build worktree (TM-31, asked 2 Nov 2026): a second copy of a project's repository on this server, used only
// for builds that run here ("@bot build here"). The shared copy is reset to GitHub before every turn (prepare in
// main.js), which would set aside a build's half-written changes; this copy is touched only by builds, one at a time.
//
//   <dir>/build/<project>   git worktree of the shared clone, local branch bot-build following origin/<branch>
//
// The folder is named like the project, because the read-only pre-push hook (hooks/pre-push) picks the branch a
// repository may push to from the folder name; builds push with `git push origin HEAD:<branch>`. The Python packages
// live in its .venv and are installed again only when pyproject.toml changes (uv), so a build starts warm.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const BUILD_BRANCH = "bot-build";
/** The extras CI installs (.github/workflows/ci-python.yml). */
export const PY_EXTRAS = ".[dev,infra,providers,reports,workflow,receipt]";
const STAMP = ".teammate-deps";

export function buildPath(dir, name) {
  return join(dir, "build", name);
}

/** The worktree exists (made once from the shared clone). */
export function ensureBuildTree({ cwd, buildCwd, branch }, git) {
  if (existsSync(join(buildCwd, ".git"))) return false;
  git(cwd, "fetch", "--quiet", "origin");
  git(cwd, "worktree", "prune");
  git(cwd, "worktree", "add", "--quiet", "-f", "-B", BUILD_BRANCH, buildCwd, `origin/${branch}`);
  return true;
}

/**
 * Before a build: the worktree follows origin/<branch>; anything a previous build left (unpushed commits, edits) is kept
 * on a backup branch, never lost. Ignored files (.venv, node_modules) stay, so the packages stay installed.
 * `run(cmd, args, cwd)` runs a program (uv); a failure throws, and the caller builds in the cloud instead.
 */
export function prepareBuildTree(project, { git, run, log = () => {}, now = () => new Date() }) {
  const { buildCwd, branch } = project;
  const made = ensureBuildTree(project, git);
  if (made) log(`build copy for ${project.name}: created at ${buildCwd}`);
  git(buildCwd, "fetch", "--quiet", "origin");
  const ahead = git(buildCwd, "rev-list", "--count", `origin/${branch}..HEAD`);
  const dirty = git(buildCwd, "status", "--porcelain");
  if (ahead !== "0" || dirty) {
    const backup = `unpushed-build/${now().toISOString().slice(0, 19).replace(/[-:T]/g, "")}`;
    if (dirty) {
      git(buildCwd, "add", "-A");
      git(buildCwd, "commit", "-q", "-m", "wip: left in the build copy");
    }
    git(buildCwd, "branch", backup);
    log(`build copy for ${project.name}: kept unpushed work on ${backup}`);
  }
  git(buildCwd, "checkout", "-q", "-B", BUILD_BRANCH, `origin/${branch}`);
  git(buildCwd, "clean", "-fdq"); // untracked files go; ignored ones (.venv, node_modules) stay
  return installPython(buildCwd, { run, log, name: project.name });
}

/** Python packages into <buildCwd>/.venv, only when pyproject.toml changed since the last install. */
export function installPython(buildCwd, { run, log = () => {}, name = "" }) {
  const pyproject = join(buildCwd, "pyproject.toml");
  if (!existsSync(pyproject)) return "no-python";
  const hash = createHash("sha256").update(readFileSync(pyproject)).digest("hex");
  const stamp = join(buildCwd, ".venv", STAMP);
  if (existsSync(stamp) && readFileSync(stamp, "utf8").trim() === hash) return "warm";
  log(`build copy for ${name}: installing Python packages (pyproject.toml changed)`);
  if (!existsSync(join(buildCwd, ".venv", "bin", "python"))) run("uv", ["venv", "--python", "3.11"], buildCwd);
  run("uv", ["pip", "install", "--quiet", "-e", PY_EXTRAS], buildCwd);
  mkdirSync(join(buildCwd, ".venv"), { recursive: true });
  writeFileSync(stamp, hash);
  return "installed";
}

/**
 * TM-56 (3 Nov: [207] was built, its push refused (403), and the request was still marked done; it never reached
 * main). After a build turn: what the build copy holds that origin/<branch> doesn't. Commits left behind are pushed
 * once (a rebase on the latest first); what still can't go is reported with git's own words.
 * @returns {{ ahead: number, pushed: boolean, error: string|null }}
 */
export function pushLeftovers(project, { git, log = () => {} }) {
  const { buildCwd, branch } = project;
  git(buildCwd, "fetch", "--quiet", "origin");
  const ahead = Number(git(buildCwd, "rev-list", "--count", `origin/${branch}..HEAD`)) || 0;
  if (!ahead) return { ahead: 0, pushed: false, error: null };
  try {
    git(buildCwd, "rebase", "--quiet", `origin/${branch}`);
    git(buildCwd, "push", "--quiet", "origin", `HEAD:${branch}`);
    log(`build copy for ${project.name}: pushed ${ahead} commit(s) the build left behind`);
    return { ahead, pushed: true, error: null };
  } catch (e) {
    try {
      git(buildCwd, "rebase", "--abort");
    } catch {
      // no rebase in progress
    }
    const why = String(e.stderr || e.message || e).split("\n").filter(Boolean).slice(-2).join(" ").slice(0, 240);
    return { ahead, pushed: false, error: why };
  }
}

/**
 * TM-54 (3 Nov: not one complaint had become a replay test; builds here have no production access, so
 * `replay_to_test.py <cor>` always failed and they wrote invented cases instead). The bot, which can read production,
 * saves each asker's real v3 turn into the build copy as .teammate-replays/<cor>.json (never committed), and the build
 * makes it a test with `replay_to_test.py --from-json`. Returns the relative paths written.
 * @param turns  [{ correlation_id, ...the turn as replay_to_test.py's fetch() returns it }]
 */
export function saveReplays(project, turns, { git }) {
  const dir = join(project.buildCwd, ".teammate-replays");
  mkdirSync(dir, { recursive: true });
  const exclude = git(project.buildCwd, "rev-parse", "--git-path", "info/exclude");
  const excludePath = exclude.startsWith("/") ? exclude : join(project.buildCwd, exclude);
  let current = "";
  try {
    current = readFileSync(excludePath, "utf8");
  } catch {
    mkdirSync(join(excludePath, ".."), { recursive: true });
  }
  if (!current.split("\n").includes(".teammate-replays/")) writeFileSync(excludePath, `${current}${current && !current.endsWith("\n") ? "\n" : ""}.teammate-replays/\n`);
  const paths = [];
  for (const t of turns) {
    if (!/^cor_[0-9a-f]{8,40}$/.test(String(t?.correlation_id))) continue;
    writeFileSync(join(dir, `${t.correlation_id}.json`), JSON.stringify(t, null, 2));
    paths.push(`.teammate-replays/${t.correlation_id}.json`);
  }
  return paths;
}
