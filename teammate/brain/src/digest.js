// Weekly digest (TM-26, asked 2 Nov 2026): once a week, in the project's team group, how Mesiri did with the people
// who use it: the top complaints, which tools get cancelled or taken back most, the slowest step of a v3 reply, and how
// many requests shipped and what the testers said about them. `@bot digest` posts one now (any approved person).
//
// One SELECT through the project's read-only ops API (the production watch's token, which stays in this process), and
// the request log from the listener. No AI, no Claude turn: free. Customer names never appear; complaints are Mesiri's
// own one-line summaries of what was asked (tell_the_team `about`), never the person's words.

import { readFileSync, writeFileSync } from "node:fs";
import { asObjects, TAKE_BACK_TOOLS } from "./prod_watch.js";
import { firstTimeRightLine } from "./board.js";

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
const DAY = 86_400_000;
const IST = 330 * 60_000;
/** Monday, from this hour (India time): the digest goes out on the first check after it. */
export const SEND_HOUR_IST = 9;

const calls = (col = "calls") =>
  `jsonb_array_elements(CASE WHEN jsonb_typeof(jt.stage_payload::jsonb->'${col}') = 'array' THEN jt.stage_payload::jsonb->'${col}' ELSE '[]'::jsonb END)`;

/** The week's numbers as rows of (section, name, n, ms). `since` is a checked ISO time. */
export function digestSql(since) {
  if (!ISO.test(since)) throw new Error("bad period");
  const take = TAKE_BACK_TOOLS.map((t) => `'${t}'`).join(", ");
  return `SELECT * FROM (
  SELECT 'complaint' AS section, (c->'args'->>'kind') || ': ' || left(coalesce(c->'args'->>'about', ''), 110) AS name,
         count(DISTINCT jt.correlation_id)::int AS n, NULL::float AS ms
  FROM journey_traces jt, ${calls()} c
  WHERE jt.created_at >= '${since}' AND jt.stage IN ('agent_v2_live', 'agent_api_turn', 'release_feedback') AND c->>'tool' = 'tell_the_team'
  GROUP BY 2 ORDER BY 3 DESC LIMIT 5) a
UNION ALL SELECT * FROM (
  SELECT 'cancelled', x->>'tool', count(*)::int, NULL::float
  FROM journey_traces jt, ${calls("cancelled")} x
  WHERE jt.created_at >= '${since}' AND jt.stage = 'agent_api_turn' AND NOT jt.stage_payload::jsonb ? 'cancel_reason'
  GROUP BY 2 ORDER BY 3 DESC LIMIT 6) b
UNION ALL SELECT * FROM (
  SELECT 'reason', jt.stage_payload::jsonb->>'cancel_reason', count(*)::int, NULL::float
  FROM journey_traces jt
  WHERE jt.created_at >= '${since}' AND jt.stage = 'agent_api_turn' AND jt.stage_payload::jsonb ? 'cancel_reason'
  GROUP BY 2) c
UNION ALL SELECT * FROM (
  SELECT 'took_back', c->>'tool', count(*)::int, NULL::float
  FROM journey_traces jt, ${calls()} c
  WHERE jt.created_at >= '${since}' AND jt.stage = 'agent_api_turn' AND c->>'tool' IN (${take})
  GROUP BY 2 ORDER BY 3 DESC LIMIT 6) d
UNION ALL SELECT * FROM (
  SELECT 'step', e.key, count(*)::int, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY e.value::float)::numeric, 0)::float
  FROM journey_traces jt, jsonb_each_text(jt.stage_payload::jsonb) e
  WHERE jt.created_at >= '${since}' AND jt.stage = 'prepipeline' AND e.key LIKE 'v3\\_%' AND e.value ~ '^[0-9.]+$'
  GROUP BY 2) e
UNION ALL SELECT * FROM (
  SELECT 'turns', CASE WHEN jt.succeeded THEN 'ok' ELSE 'failed' END, count(*)::int,
         round(percentile_cont(0.5) WITHIN GROUP (ORDER BY jt.duration_ms)::numeric, 0)::float
  FROM journey_traces jt WHERE jt.created_at >= '${since}' AND jt.stage = 'agent_api_turn' GROUP BY 2) f
UNION ALL SELECT * FROM (
  SELECT 'verdict', jt.stage_payload::jsonb->>'verdict', count(*)::int, NULL::float
  FROM journey_traces jt WHERE jt.created_at >= '${since}' AND jt.stage = 'release_feedback' GROUP BY 2) g`;
}

const REASONS = { site: "wrong site", amount: "wrong amount", other: "something else" };
const secs = (ms) => (ms == null ? "?" : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`);

/** The digest message (WhatsApp formatting). `items` is the listener's request log; `since` a Date. */
export function digestText({ rows, items = [], since, until = new Date() }) {
  const of = (section) => rows.filter((r) => r.section === section);
  const n = (section, name) => of(section).find((r) => r.name === name)?.n || 0;
  const day = (d) => new Date(d.getTime() + IST).toISOString().slice(0, 10);
  const lines = [`📊 *Mesiri this week* (${day(since)} → ${day(until)})`];

  const turns = n("turns", "ok") + n("turns", "failed");
  const median = of("turns").find((r) => r.name === "ok")?.ms;
  if (turns) lines.push(`v3 replies: ${turns}, ${n("turns", "failed")} failed · median ${secs(median)}`);

  const complaints = of("complaint");
  lines.push("", "*Top complaints*");
  if (complaints.length) complaints.forEach((r, i) => lines.push(`${i + 1}. ${String(r.name).replace(/_/g, " ")} (${r.n})`));
  else lines.push("None this week.");

  const cancelled = of("cancelled");
  const tookBack = of("took_back");
  const reasons = of("reason").map((r) => `${REASONS[r.name] || r.name} ${r.n}`).join(", ");
  lines.push("", "*Cancelled or taken back most*");
  if (cancelled.length || tookBack.length) {
    if (cancelled.length) lines.push(`Cancelled: ${cancelled.map((r) => `${r.name} ${r.n}`).join(", ")}${reasons ? ` · why: ${reasons}` : ""}`);
    if (tookBack.length) lines.push(`Taken back / corrected: ${tookBack.map((r) => `${r.name} ${r.n}`).join(", ")}`);
  } else lines.push("Nothing cancelled or taken back.");

  const steps = of("step").filter((r) => r.name !== "v3_before").sort((a, b) => (b.ms || 0) - (a.ms || 0));
  lines.push("", "*Slowest step of a v3 reply*");
  if (steps.length) {
    const [top, ...rest] = steps;
    lines.push(`${top.name.replace(/^v3_/, "")}: median ${secs(top.ms)}${rest.length ? ` (then ${rest.slice(0, 2).map((r) => `${r.name.replace(/^v3_/, "")} ${secs(r.ms)}`).join(", ")})` : ""}`);
  } else lines.push("No v3 timings this week.");

  const from = since.getTime();
  const at = (v) => (v ? Date.parse(v) : NaN);
  const shipped = items.filter((i) => at(i.live_at) >= from);
  const fromUsers = shipped.filter((i) => i.asked_by).length;
  const checked = items.filter((i) => at(i.verified_at) >= from);
  lines.push("", "*Requests*");
  lines.push(
    `Shipped: ${shipped.length} (${fromUsers} asked by users) · live check ${checked.filter((i) => i.verified === "ok").length} ok, ${checked.filter((i) => i.verified === "broken").length} broken`,
  );
  lines.push(`Testers said: ${n("verdict", "works")} Works ✅ · ${n("verdict", "still_wrong")} Still wrong ❌`);
  // TM-67: the number the loop is trusted on: fixed in one round, nobody had to come back.
  const ftr = firstTimeRightLine(items, from);
  if (ftr) lines.push(`🎯 ${ftr}`);
  // TM-27: where a request's time went this week (median minutes per stage, requests from users).
  const mid = (xs) => (xs.length ? xs.sort((a, b) => a - b)[Math.floor(xs.length / 2)] : null);
  const span = (a, b) => shipped.filter((i) => i.asked_by && at(i[a]) <= at(i[b])).map((i) => (at(i[b]) - at(i[a])) / 60_000);
  const parts = [["plan", "created_at", "started_at"], ["build", "started_at", "pushed_at"], ["deploy", "pushed_at", "live_at"]]
    .map(([name, a, b]) => [name, mid(span(a, b))])
    .filter(([, m]) => m != null);
  if (parts.length) lines.push(`Time per request (median): ${parts.map(([name, m]) => `${name} ${Math.round(m)} min`).join(" · ")}`);
  return lines.join("\n");
}

/** Monday (India time) at or after SEND_HOUR_IST, as "YYYY-MM-DD" of that Monday; else null. */
export function sendDay(now) {
  const local = new Date(now + IST);
  if (local.getUTCDay() !== 1 || local.getUTCHours() < SEND_HOUR_IST) return null;
  return local.toISOString().slice(0, 10);
}

export class Digest {
  /**
   * @param sources {project: {url, token}} the ops API per project (opsSources)
   * @param items async (project) => the listener's request log items
   * @param notify async (project, text) => posted in the project's team group
   */
  constructor({ sources, items, notify, file, log = () => {}, fetchFn = fetch, now = () => Date.now() }) {
    Object.assign(this, { sources, items, notify, file, log, fetchFn, now });
  }

  state() {
    try {
      return JSON.parse(readFileSync(this.file, "utf8"));
    } catch {
      return {};
    }
  }

  async rows(project, since) {
    const source = this.sources[project];
    const res = await this.fetchFn(`${source.url}/claude-ops/sql`, {
      method: "POST",
      headers: { authorization: `Bearer ${source.token}`, "content-type": "application/json" },
      body: JSON.stringify({ sql: digestSql(since.toISOString().replace(/\.\d+Z$/, "Z")) }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) throw new Error(`ops API HTTP ${res.status}`);
    return asObjects(await res.json());
  }

  /** The digest text for the last 7 days. */
  async build(project) {
    const until = new Date(this.now());
    const since = new Date(until.getTime() - 7 * DAY);
    const rows = await this.rows(project, since);
    let items = [];
    try {
      items = await this.items(project);
    } catch (e) {
      this.log(`digest ${project}: request log unavailable: ${e.message}`);
    }
    return digestText({ rows, items, since, until });
  }

  /** Called every hour: on Monday morning (India time), each project's digest once. Never throws. */
  async maybeSend() {
    const day = sendDay(this.now());
    if (!day) return 0;
    const state = this.state();
    let sent = 0;
    for (const project of Object.keys(this.sources)) {
      if (state[project] === day) continue;
      try {
        await this.notify(project, await this.build(project));
        state[project] = day;
        writeFileSync(this.file, JSON.stringify(state));
        sent += 1;
        this.log(`digest ${project}: sent for the week to ${day}`);
      } catch (e) {
        this.log(`digest ${project}: ${e.message}`);
      }
    }
    return sent;
  }

  /** "@bot digest": this week's numbers now. undefined when the message is something else. */
  async command(req) {
    if (!/^(?:weekly\s+)?digest$/i.test(String(req.text || "").trim())) return undefined;
    if (!this.sources[req.project]) return "There is no production data for this project.";
    try {
      return await this.build(req.project);
    } catch (e) {
      return `⚠️ Couldn't build the digest (${String(e.message).slice(0, 100)}).`;
    }
  }
}
