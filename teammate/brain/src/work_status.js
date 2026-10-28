// What happened to a plan after "@bot ok n" (request 139).
//
// Approved work runs in a Claude Code cloud session and the routine API only returns its link, so the bot is blind
// afterwards. This module answers "what is this job doing?" from what can be seen from outside: commits on the
// project's branch, the CI / deploy runs of those commits, the request-log item (status, notes = heartbeats) and the
// session link. Pure functions plus injected lookups (git, GitHub), so it is testable without either.

const MIN = 60_000;
// "WA-86", "TM-12": a tracker id. Words that look like one but aren't (UTF-8, SHA-256…) are skipped.
const NOT_TRACKER = new Set(["UTF", "SHA", "ISO", "HTTP", "TLS", "AES", "MD", "RFC", "PNG", "GPT", "TS", "ES", "H"]);
// Notes the bot writes itself; they are not the session's heartbeats.
const BOT_NOTE = /^(OK from |cloud session|watchdog:)/i;

/** Tracker ids named in some text, upper-cased, once each. */
export function trackerIds(...texts) {
  const out = new Set();
  for (const t of texts) for (const m of String(t || "").matchAll(/\b([A-Z]{1,5})-(\d{1,5})\b/g)) if (!NOT_TRACKER.has(m[1])) out.add(`${m[1]}-${m[2]}`);
  return [...out];
}

/** The text a commit message has to contain for it to count as this plan's: "request n", "[n]" or a tracker id. */
export function commitPatterns(plan, item) {
  const id = String(plan.id);
  const notes = (item?.log || []).map((l) => l.note).join("\n");
  const ids = trackerIds(plan.title, plan.plan, notes);
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return [`request ${esc(id)}([^0-9]|$)`, `\\[${esc(id)}\\]`, ...ids.map((t) => `${esc(t)}([^0-9]|$)`)];
}

/** Deploy state of one commit from its workflow runs: green | red | running | none. */
export function deployState(runs) {
  const deploys = runs.filter((r) => /deploy/i.test(r.name || "")).sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const r = deploys[0];
  if (!r) return { state: "none", at: null, url: null };
  if (r.status !== "completed") return { state: "running", at: r.at, url: r.url };
  return { state: r.conclusion === "success" ? "green" : "red", at: r.at, url: r.url };
}

/** CI state of one commit (every run that isn't a deploy): green | red | running | none. */
export function ciState(runs) {
  const ci = runs.filter((r) => !/deploy/i.test(r.name || ""));
  if (!ci.length) return "none";
  if (ci.some((r) => r.status === "completed" && !["success", "skipped", "neutral"].includes(r.conclusion))) return "red";
  if (ci.some((r) => r.status !== "completed")) return "running";
  return "green";
}

/** The session's last heartbeat: the newest request-log note that the bot didn't write itself, after `sinceIso`. */
export function lastHeartbeat(item, sinceIso) {
  const notes = (item?.log || []).filter((l) => l.note && !BOT_NOTE.test(String(l.note)) && (!sinceIso || String(l.at) >= sinceIso));
  const n = notes.at(-1);
  return n ? { at: n.at, note: String(n.note) } : null;
}

/** When the plan's cloud session was started (ISO). */
export function startedAt(plan) {
  return plan.fired_at || plan.approved_at || plan.at || null;
}

/**
 * Everything known about one plan's work.
 * @param {{ plan: object, item?: object|null, commits: (plan, sinceIso, item) => Promise<{sha: string, subject: string, at: string}[]>,
 *           runs: (shas: string[], plan: object) => Promise<{sha: string, name: string, status: string, conclusion: string|null, at: string, url?: string}[]> }} deps
 */
export async function collectWorkStatus({ plan, item = null, commits, runs }) {
  const since = startedAt(plan);
  let found = [];
  try {
    found = since ? await commits(plan, since, item) : [];
  } catch {
    // git is unreachable: report what the request log says
  }
  let all = [];
  try {
    all = found.length ? await runs(found.map((c) => c.sha), plan) : [];
  } catch {
    // GitHub unreachable or no token: commits are shown without a deploy state
  }
  const list = found.map((c) => {
    const mine = all.filter((r) => r.sha === c.sha || c.sha.startsWith(r.sha) || r.sha.startsWith(c.sha));
    return { ...c, short: c.sha.slice(0, 7), deploy: deployState(mine), ci: ciState(mine) };
  });
  const hb = lastHeartbeat(item, since);
  const times = [since, hb?.at, ...list.map((c) => c.at)].filter(Boolean).map((t) => Date.parse(t)).filter(Number.isFinite);
  return {
    id: plan.id,
    title: plan.title,
    planStatus: plan.status,
    item: item ? { status: item.status, ref: item.done_ref || null, notes: (item.log || []).filter((l) => l.note).slice(-3).map((l) => ({ at: l.at, note: String(l.note) })) } : null,
    commits: list,
    heartbeat: hb,
    session_url: plan.session_url || null,
    followups: plan.followups || [],
    startedAt: since,
    lastActivityAt: times.length ? Math.max(...times) : null,
  };
}

export const ago = (ms) => {
  const m = Math.max(0, Math.round(ms / MIN));
  return m < 1 ? "just now" : m < 90 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
};

const DEPLOY_ICON = { green: "deploy ✅", red: "deploy ❌", running: "deploying…", none: "no deploy run yet" };

/** One job as WhatsApp text. `now` is ms. */
export function formatWorkStatus(ws, now, { short = false } = {}) {
  const lines = [`*[${ws.id}] ${ws.title}* — ${ws.item?.status || ws.planStatus}`];
  if (ws.commits.length) {
    for (const c of ws.commits.slice(short ? -1 : -5)) lines.push(`• ${c.short} ${String(c.subject).slice(0, 70)} — ${DEPLOY_ICON[c.deploy.state]}${c.ci === "red" ? ", CI ❌" : ""}`);
  } else lines.push("• no commit on main yet");
  if (ws.heartbeat) lines.push(`• last note ${ago(now - Date.parse(ws.heartbeat.at))}: ${ws.heartbeat.note.slice(0, 140)}`);
  else lines.push("• no note from the session yet");
  if (!short && ws.item?.notes?.length && !ws.heartbeat) lines.push(`• request log: ${ws.item.notes.at(-1).note.slice(0, 100)}`);
  if (ws.startedAt) lines.push(`• started ${ago(now - Date.parse(ws.startedAt))}`);
  if (ws.session_url) lines.push(`• session: ${ws.session_url}`);
  for (const f of ws.followups) lines.push(`• follow-up (${ago(now - Date.parse(f.at))}): ${f.url}`);
  return lines.join("\n");
}
