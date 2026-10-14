// Entry point: keep each project's repo checked out, take messages from the
// listener, answer through the listener (TM-03b).
//
//   POST /ask       {project, chat, chat_name, chat_role, reply_chat, sender, n, text, quoted_text}   a planning turn
//   POST /approve   {project, item_id?, by, reply_chat}                                             a working turn
//   GET  /health
// Both POSTs need `Authorization: Bearer <TEAMMATE_API_TOKEN>` and come from the
// listener, which has already checked that the sender is approved.
//
// Environment:
//   TEAMMATE_API_TOKEN         shared with the listener
//   TEAMMATE_API               listener URL, default http://127.0.0.1:8790
//   TEAMMATE_BRAIN_PORT        default 8791 (localhost only)
//   TEAMMATE_BRAIN_DIR         default /var/lib/teammate-brain (repos/, sessions.json, plans.json, Claude Code's home)
//   TEAMMATE_BRAIN_PROJECTS    project=owner/repo@branch, comma-separated
//   TEAMMATE_BRAIN_MODEL       default claude-opus-5-5
//   TEAMMATE_BRAIN_SCREENSHOT_HOSTS   hosts screenshot_url may open, comma-separated
//   TEAMMATE_OWNER             default Ilan
//   CLAUDE_CODE_OAUTH_TOKEN    from `claude setup-token`
//   GH_TOKEN                   GitHub token for clone / push / PRs

import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { timingSafeEqual } from "node:crypto";
import { query } from "@anthropic-ai/claude-agent-sdk";
import { Brain } from "./brain.js";
import { brainTools } from "./tools.js";
import { createRenderer } from "./render.js";

const log = (m) => console.log(`[brain] ${m}`);
const token = process.env.TEAMMATE_API_TOKEN || "";
const api = (process.env.TEAMMATE_API || "http://127.0.0.1:8790").replace(/\/$/, "");
const dir = process.env.TEAMMATE_BRAIN_DIR || "/var/lib/teammate-brain";
const port = Number(process.env.TEAMMATE_BRAIN_PORT || 8791);
const hooksDir = join(dirname(fileURLToPath(import.meta.url)), "..", "hooks");
if (token.length < 16) throw new Error("TEAMMATE_API_TOKEN missing");

// Git flow per project, as the owner set it in the group (14 Oct).
const FLOWS = {
  mercon:
    "work on branch ilan (pull first); commit and push to origin ilan; open a PR ilan -> dev with `gh pr create`; " +
    "when its CI passes, merge it into dev; then open (or update) the release PR dev -> main. Merge the release PR only when told in the group.",
  mesiri: "work on main (pull first); run the verification listed in CLAUDE.md; push to main (main deploys, so say so in the plan).",
};

function parseProjects(spec) {
  const out = {};
  for (const part of (spec || "").split(",").map((s) => s.trim()).filter(Boolean)) {
    const m = part.match(/^([a-z0-9_-]+)=([\w.-]+\/[\w.-]+)@([\w./-]+)$/);
    if (!m) throw new Error(`bad TEAMMATE_BRAIN_PROJECTS entry: ${part}`);
    const [, name, repo, branch] = m;
    out[name] = { name, repo, branch, cwd: join(dir, "repos", name), flow: FLOWS[name] || `work on branch ${branch}; open a PR; never merge to main unless told.` };
  }
  return out;
}

const git = (cwd, ...args) => execFileSync("git", ["-C", cwd, ...args], { stdio: "pipe" }).toString().trim();

/** First start: clone; every start: point hooks at the read-only folder. */
function ensureRepo({ repo, branch, cwd }) {
  if (!existsSync(join(cwd, ".git"))) {
    mkdirSync(join(dir, "repos"), { recursive: true });
    log(`cloning ${repo} (${branch})`);
    execFileSync("gh", ["repo", "clone", repo, cwd, "--", "--branch", branch], { stdio: "inherit" });
  }
  execFileSync("gh", ["auth", "setup-git"], { stdio: "inherit" });
  git(cwd, "config", "core.hooksPath", hooksDir);
}

/** Before each turn: latest code on the project's branch, without touching uncommitted work. */
function prepare({ name, cwd, branch }) {
  git(cwd, "fetch", "--quiet", "origin");
  // With a cloud routine (hybrid), all changes happen in the cloud, so this copy only mirrors GitHub:
  // set aside anything unpushed or uncommitted on a backup branch (kept, never deleted), then follow origin.
  if (routines[name]) {
    const ahead = git(cwd, "rev-list", "--count", `origin/${branch}..HEAD`);
    const dirty = git(cwd, "status", "--porcelain");
    if (ahead !== "0" || dirty) {
      const backup = `unpushed/${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "")}`;
      if (dirty) {
        git(cwd, "add", "-A");
        git(cwd, "commit", "-q", "-m", "wip: left on the bot server");
      }
      git(cwd, "branch", backup);
      log(`${name}: kept unpushed work on ${backup}`);
    }
    git(cwd, "checkout", "-q", "-B", branch, `origin/${branch}`);
    return;
  }
  if (git(cwd, "rev-parse", "--abbrev-ref", "HEAD") === branch && !git(cwd, "status", "--porcelain")) git(cwd, "merge", "--ff-only", "--quiet", `origin/${branch}`);
}

const projects = parseProjects(process.env.TEAMMATE_BRAIN_PROJECTS || "mercon=aprodac/MERCON@ilan");
for (const p of Object.values(projects)) {
  try {
    ensureRepo(p);
  } catch (e) {
    log(`could not set up ${p.repo}: ${e.message}`);
  }
}

async function call(method, path, body) {
  const res = await fetch(`${api}${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    log(`${method} ${path} failed: HTTP ${res.status} ${data.error || ""}`);
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}
const listener = {
  send: (b) => call("POST", "/send", b).catch(() => null),
  addItem: (b) => call("POST", "/items", b),
  updateItem: (id, b) => call("POST", `/items/${id}`, b),
  /** A group photo / file by message number: { data: Buffer, mime }. */
  media: async (n, project) => {
    const res = await fetch(`${api}/media/${n}?project=${encodeURIComponent(project)}`, { headers: { authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return { data: Buffer.from(await res.arrayBuffer()), mime: res.headers.get("content-type") || "" };
  },
};

let render = null;
try {
  const L = process.env;
  render = createRenderer({
    login: L.TEAMMATE_DEV_LOGIN_HOST && L.TEAMMATE_DEV_LOGIN_USER && L.TEAMMATE_DEV_LOGIN_PASSWORD
      ? { host: L.TEAMMATE_DEV_LOGIN_HOST, user: L.TEAMMATE_DEV_LOGIN_USER, password: L.TEAMMATE_DEV_LOGIN_PASSWORD }
      : null,
    stateFile: join(dir, "dev-login-state.json"),
  });
} catch (e) {
  log(`previews off: ${e.message}`);
}
const screenshotHosts = (process.env.TEAMMATE_BRAIN_SCREENSHOT_HOSTS || "").split(",").map((s) => s.trim()).filter(Boolean);

// Hybrid (TM-03b): a project with a cloud routine runs approved work there, where the owner can watch it in
// Claude Code. Per project: TEAMMATE_ROUTINE_<PROJECT>_URL (the routine's /fire URL) and _TOKEN (its API token).
const routines = {};
for (const name of Object.keys(projects)) {
  const url = process.env[`TEAMMATE_ROUTINE_${name.toUpperCase()}_URL`];
  const rtoken = process.env[`TEAMMATE_ROUTINE_${name.toUpperCase()}_TOKEN`];
  if (url && rtoken) routines[name] = { url, token: rtoken };
}
async function fireRoutine({ url, token: rtoken }, text) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${rtoken}`,
      "anthropic-beta": "experimental-cc-routine-2026-04-01",
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({ text }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`routine fire HTTP ${res.status} ${data?.error?.message || ""}`.trim());
  return data;
}

const brain = new Brain({
  routines,
  fireFn: fireRoutine,
  queryFn: query,
  projects,
  dir,
  listener,
  tools: (ctx, plans) => brainTools({ ctx, listener, render, plans, screenshotHosts }),
  prepare,
  owner: process.env.TEAMMATE_OWNER || "Ilan",
  model: process.env.TEAMMATE_BRAIN_MODEL || "claude-opus-5-5",
  // What Claude Code (and anything it runs) sees: never the dev-site password or the routine token.
  env: {
    ...Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^TEAMMATE_(DEV_LOGIN|ROUTINE)_/.test(k))),
    TEAMMATE_TOKEN: token,
    TEAMMATE_API: api,
  },
  log,
});

function authorized(req) {
  const given = Buffer.from((req.headers.authorization || "").replace(/^Bearer /, ""));
  const expected = Buffer.from(token);
  return given.length === expected.length && timingSafeEqual(given, expected);
}

createServer(async (req, res) => {
  const reply = (status, body) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  };
  if (req.method === "GET" && req.url === "/health") return reply(200, { ok: true, projects: Object.keys(projects), previews: Boolean(render) });
  if (!authorized(req)) return reply(401, { error: "unauthorized" });
  if (req.method !== "POST" || !["/ask", "/approve"].includes(req.url)) return reply(404, { error: "not found" });
  let raw = "";
  for await (const c of req) {
    raw += c;
    if (raw.length > 50_000) return reply(413, { error: "too large" });
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return reply(400, { error: "bad json" });
  }
  const required = req.url === "/ask" ? ["project", "chat", "reply_chat", "text", "sender"] : ["project", "reply_chat", "by"];
  for (const k of required) if (!body[k]) return reply(400, { error: `${k} is required` });
  if (req.url === "/ask") brain.ask(body);
  else brain.approve(body);
  return reply(202, { ok: true }); // answered asynchronously through the listener
}).listen(port, "127.0.0.1", () => log(`listening on 127.0.0.1:${port}; projects: ${Object.keys(projects).join(", ")}; previews ${render ? "on" : "off"}`));
