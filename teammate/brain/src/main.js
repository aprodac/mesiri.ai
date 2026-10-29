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
//   TEAMMATE_WATCH_MINUTES     how often running cloud jobs are checked (commits, deploys, silence), default 10, 0 = off
//   TEAMMATE_BOARD_MINUTES     how often the shared board (docs/agents/BOARD.md) is checked, default 30, 0 = off
//   TEAMMATE_PARTNER_<P>_URL / _TOKEN   fire the routine bound to Ilan Usman's cloud session (TM-12)
//   CLAUDE_CODE_OAUTH_TOKEN    from `claude setup-token`
//   CLAUDE_CODE_OAUTH_TOKEN_<X>, TEAMMATE_ROUTINE_<P>_URL_<X> / _TOKEN_<X>, TEAMMATE_PARTNER_<P>_URL_<X> / _TOKEN_<X>
//                              more Claude accounts B, C, … (TM-14); the unsuffixed set is account A
//   GH_TOKEN                   GitHub token for clone / push / PRs

import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { timingSafeEqual } from "node:crypto";
import { query } from "@anthropic-ai/claude-agent-sdk";
import { Brain } from "./brain.js";
import { Accounts, parseAccounts } from "./accounts.js";
import { brainTools } from "./tools.js";
import { createRenderer } from "./render.js";
import { commitPatterns, formatWorkStatus } from "./work_status.js";
import { ProdWatch, QUIET, opsSources } from "./prod_watch.js";

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
  // TM-09: in this repo the bot only upgrades itself (teammate/), for its owner.
  // Plan 25 (15 Oct, owner-approved): the whole Mesiri repo except .github/ and .env files, by CLAUDE.md.
  mesiri:
    "follow CLAUDE.md exactly. Pushing to main deploys Mesiri production (incl. alembic upgrade head), so an approved plan " +
    "IS a production deploy and only an owner can approve it. Work on main only (git checkout main; git pull origin main), no " +
    "branches, logical commits. Before every push run the CLAUDE.md verification for what you touched: backend pytest " +
    "--ignore=tests/integration + ruff on backend/src, backend/tests, backend/migrations; dashboard tsc -b --noEmit, oxlint, " +
    "vite build; platform/ai pytest; whatsapp-assistant pytest with PYTHONPATH (~9 min); teammate/ npm test in listener and " +
    "brain. Then pull, combine by hand, re-verify if the pull brought changes, push. Migrations: check the alembic head right " +
    "before writing one and confirm there's no fork. Labour / Attendance / Payroll / Workforce or a shared component: say so " +
    "plainly in the plan. Claim and mark the docs/plans/V1_TRACKER.md row with the commit hash, end with the CLAUDE.md phase " +
    "report (Executive / Technical / Git summary, verified against the remote SHA) and say plainly what wasn't verified. " +
    "Never touch .github/ or .env files. Changes under teammate/ are bot upgrades: label them so in the plan.",
};

function parseProjects(spec) {
  const out = {};
  for (const part of (spec || "").split(",").map((s) => s.trim()).filter(Boolean)) {
    const m = part.match(/^([a-z0-9_-]+)=([\w.-]+\/[\w.-]+)@([\w./-]+)$/);
    if (!m) throw new Error(`bad TEAMMATE_BRAIN_PROJECTS entry: ${part}`);
    const [, name, repo, branch] = m;
    // Each project's own GitHub token (TEAMMATE_GITHUB_TOKEN_<NAME>), else the default GH_TOKEN.
    const ghToken = process.env[`TEAMMATE_GITHUB_TOKEN_${name.toUpperCase()}`] || process.env.GH_TOKEN || "";
    out[name] = { name, repo, branch, ghToken, cwd: join(dir, "repos", name), flow: FLOWS[name] || `work on branch ${branch}; open a PR; never merge to main unless told.` };
  }
  return out;
}

const withToken = (ghToken) => ({ ...process.env, ...(ghToken ? { GH_TOKEN: ghToken } : {}) });
const gitAs = (ghToken) => (cwd, ...args) => execFileSync("git", ["-C", cwd, ...args], { stdio: "pipe", env: withToken(ghToken) }).toString().trim();

/** First start: clone; every start: point hooks at the read-only folder. */
function ensureRepo({ repo, branch, cwd, ghToken }) {
  const git = gitAs(ghToken);
  if (!existsSync(join(cwd, ".git"))) {
    mkdirSync(join(dir, "repos"), { recursive: true });
    log(`cloning ${repo} (${branch})`);
    execFileSync("gh", ["repo", "clone", repo, cwd, "--", "--branch", branch], { stdio: "inherit", env: withToken(ghToken) });
  }
  execFileSync("gh", ["auth", "setup-git"], { stdio: "inherit", env: withToken(ghToken) });
  git(cwd, "config", "core.hooksPath", hooksDir);
}

/** Before each turn: latest code on the project's branch, without touching uncommitted work. */
function prepare({ name, cwd, branch, ghToken }) {
  const git = gitAs(ghToken);
  git(cwd, "fetch", "--quiet", "origin");
  // With a cloud routine (hybrid), all changes happen in the cloud, so this copy only mirrors GitHub:
  // set aside anything unpushed or uncommitted on a backup branch (kept, never deleted), then follow origin.
  if (brain.hasRoutine(name)) { // on any Claude account (TM-14)
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
  /** Like send, but a refusal (limit, wrong chat) comes back as an error to report. */
  sendStrict: (b) => call("POST", "/send", b),
  chats: (project) => call("GET", `/chats?project=${encodeURIComponent(project)}`),
  messages: (q) => call("GET", `/messages?${new URLSearchParams(q)}`),
  addItem: (b) => call("POST", "/items", b),
  updateItem: (id, b) => call("POST", `/items/${id}`, b),
  getItem: (id, project) => call("GET", `/items/${id}?project=${encodeURIComponent(project)}`),
  /** Translate one message on request (Gemini, in the listener); returns text + cost. */
  translate: (n, project) => call("POST", `/messages/${n}/translate?project=${encodeURIComponent(project)}`),
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
  // TEAMMATE_DEV_LOGIN_HOST/_USER/_PASSWORD (Mercon dev site) and TEAMMATE_DEV_LOGIN_MESIRI_HOST/... (Mesiri
  // dashboard). All TEAMMATE_DEV_LOGIN_* are kept out of Claude's environment below.
  const logins = ["TEAMMATE_DEV_LOGIN", "TEAMMATE_DEV_LOGIN_MESIRI"]
    .map((p) => ({ host: L[`${p}_HOST`], user: L[`${p}_USER`], password: L[`${p}_PASSWORD`] }))
    .filter((l) => l.host && l.user && l.password);
  render = createRenderer({ logins, stateFile: join(dir, "login-state.json") });
} catch (e) {
  log(`previews off: ${e.message}`);
}
const screenshotHosts = (process.env.TEAMMATE_BRAIN_SCREENSHOT_HOSTS || "").split(",").map((s) => s.trim()).filter(Boolean);

// Hybrid (TM-03b): a project with a cloud routine runs approved work there, where the owner can watch it in
// Claude Code. Per project: TEAMMATE_ROUTINE_<PROJECT>_URL (the routine's /fire URL) and _TOKEN (its API token).
// The pair (TM-12): TEAMMATE_PARTNER_<PROJECT>_URL / _TOKEN fire the routine bound to Ilan Usman's cloud session,
// so Ilan Pro (this bot) can report to it. Both belong to a Claude account; with several accounts (TM-14) each
// has its own set, and each WhatsApp group uses its own account's (accounts.js).
const accounts = new Accounts({ list: parseAccounts(process.env, Object.keys(projects)), file: join(dir, "accounts.json"), log });
log(`claude accounts: ${accounts.list.map((a) => a.id.toUpperCase()).join(", ")}; default ${accounts.state.default.toUpperCase()}`);
// TEAMMATE_BOARD_MINUTES: how often the shared board is checked (0 = off).
const boardMinutes = Number(process.env.TEAMMATE_BOARD_MINUTES ?? 30);
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

// Request 139: what the project's branch and GitHub show about a plan's work. A commit since the start that names the
// request ("request 61", "[61]") or any tracker id in the plan / its notes (WA-86) is the plan's.
async function planCommits(plan, sinceIso, item = null) {
  const { cwd, branch, ghToken } = projects[plan.project];
  const git = gitAs(ghToken);
  git(cwd, "fetch", "--quiet", "origin");
  const greps = commitPatterns(plan, item).map((p) => `--grep=${p}`);
  const out = git(cwd, "log", `origin/${branch}`, `--since=${sinceIso}`, "--reverse", "-E", ...greps, "--format=%H%x09%cI%x09%s");
  return out ? out.split("\n").map((l) => { const [sha, at, ...subject] = l.split("\t"); return { sha, at, subject: subject.join("\t") }; }) : [];
}

/** Workflow runs (CI, "Deploy to Production") of those commits: GitHub REST, read-only, with the project's own token. */
async function planRuns(shas, plan) {
  const { repo, branch, ghToken } = projects[plan.project];
  const res = await fetch(`https://api.github.com/repos/${repo}/actions/runs?branch=${encodeURIComponent(branch)}&per_page=60`, {
    headers: { accept: "application/vnd.github+json", "user-agent": "teammate-brain", ...(ghToken ? { authorization: `Bearer ${ghToken}` } : {}) },
  });
  if (!res.ok) throw new Error(`GitHub runs HTTP ${res.status}`);
  const data = await res.json();
  return (data.workflow_runs || [])
    .filter((r) => shas.includes(r.head_sha))
    .map((r) => ({ sha: r.head_sha, name: r.name, status: r.status, conclusion: r.conclusion, at: r.updated_at, url: r.html_url }));
}

async function landed(plan, sinceIso) {
  let item = null;
  if (typeof plan.id === "number") item = (await listener.getItem(plan.id, plan.reply_project || plan.chat_project || plan.project).catch(() => null))?.item || null;
  return (await planCommits(plan, sinceIso, item)).length > 0;
}

const brain = new Brain({
  accounts,
  fireFn: fireRoutine,
  landed,
  work: { commits: planCommits, runs: planRuns },
  queryFn: query,
  projects,
  dir,
  listener,
  tools: (ctx, plans) => {
    const p = brain.partnerFor(ctx.chat, ctx.chat_project || ctx.project); // on this group's account, at the time of the turn
    return brainTools({
      ctx, listener, render, plans, screenshotHosts, partner: p ? (text) => fireRoutine(p, text) : null,
      workStatus: async (id) => {
        const plan = brain.planStore.plans[id];
        return plan ? formatWorkStatus(await brain.workStatus(plan), Date.now()) : `No plan [${id}].`;
      },
      tellJob: ({ id, message, scope }) =>
        brain.tellFromBot({ id, message, scope, reply_chat: ctx.reply_chat, project: ctx.chat_project || ctx.project, say: (text) => listener.send({ chat: ctx.reply_chat, project: ctx.chat_project || ctx.project, text }) }),
    });
  },
  prepare,
  owner: process.env.TEAMMATE_OWNER || "Ilan",
  model: process.env.TEAMMATE_BRAIN_MODEL || "claude-opus-5-5",
  // What Claude Code (and anything it runs) sees: never the dev-site password, a routine token, or a Claude
  // login; the brain adds only the login of the account each turn runs on (TM-14).
  env: {
    ...Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^TEAMMATE_(DEV_LOGIN|ROUTINE|PARTNER|GITHUB_TOKEN|OPS)_|^CLAUDE_CODE_OAUTH_TOKEN|^MESIRI_CLAUDE_OPS/.test(k))),
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

if (boardMinutes > 0) {
  const check = () => brain.checkBoard().catch((e) => log(`board: ${e.message}`));
  setTimeout(check, 120_000); // after start-up settles
  setInterval(check, boardMinutes * 60_000);
  log(`board: every ${boardMinutes} min; partner ${Object.keys(projects).filter((p) => accounts.list.some((a) => a.partners[p])).join(", ") || "none"}`);
}
// TM-16: the production watch. Per project TEAMMATE_OPS_<PROJECT>_URL / _TOKEN (read-only ops API, kept out of
// Claude's environment); TEAMMATE_PROD_WATCH_MINUTES, default 30, 0 = off.
const prodWatchMinutes = Number(process.env.TEAMMATE_PROD_WATCH_MINUTES ?? 30);
const opsByProject = opsSources(process.env, Object.keys(projects));
if (prodWatchMinutes > 0 && Object.keys(opsByProject).length) {
  const prodWatch = new ProdWatch({
    sources: opsByProject,
    ask: (project, text) => brain.askWatch(project, text, QUIET),
    file: join(dir, "prod-watch.json"),
    log,
    minutes: prodWatchMinutes,
  });
  const look = () => prodWatch.tick().catch((e) => log(`prod-watch: ${e.message}`));
  setTimeout(look, 240_000);
  setInterval(look, prodWatchMinutes * 60_000);
  log(`prod-watch: every ${prodWatchMinutes} min; ${Object.keys(opsByProject).join(", ")}`);
}
// Request 139: the watchdog over cloud jobs (commits, deploys, silence); TEAMMATE_WATCH_MINUTES, default 10, 0 = off.
const watchMinutes = Number(process.env.TEAMMATE_WATCH_MINUTES ?? 10);
if (watchMinutes > 0) {
  const watch = () => brain.watchdog.tick().catch((e) => log(`watchdog: ${e.message}`));
  setTimeout(watch, 180_000);
  setInterval(watch, watchMinutes * 60_000);
  log(`watchdog: every ${watchMinutes} min`);
}
setInterval(() => brain.auto.tick().catch((e) => log(`auto: ${e.message}`)), 60_000); // the auto loop (request 61)
