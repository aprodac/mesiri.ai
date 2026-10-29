// Auto loop (request 61, replaces 60): with "@bot auto on [hours]" (owners) the bot works through small cycles by itself
//
//   TEST     a planning turn sends a few messages to the assistant's test chat (test_assistant)
//   PICK     it picks ONE issue in scope (Conversation, Getting things out) and calls propose_plan with auto.area
//   APPROVE  code decides, not the model: area in scope, no guard word, under the daily push cap, nothing in flight
//   WORK     the plan is fired as the cloud routine (like an "@bot ok"), approved_by "auto"
//   VERIFY   after the push has deployed, a planning turn re-sends the failing messages and reports fixed / not_fixed
//
// Anyone approved can say "@bot auto off" / "@bot stop"; "@bot auto" shows the state.
// Stops by itself: expiry (12 h default, 24 h max), 2 failed cycles in a row, the spending cap, a permission denial.
// A usage / rate limit (the 5-hour window) is NOT a failure: auto pauses, posts once, resumes at the reset time
// (retrying every 30 min when no reset time is known). The expiry clock keeps running while paused.
// State is kept in <dir>/auto.json, so a restart carries on where it was.

import { readFileSync, writeFileSync, renameSync, existsSync } from "node:fs";

const MIN = 60_000;
const env = (k, d) => Number(process.env[k] || d);
export const AUTO_DEFAULTS = {
  hours: 12,
  maxHours: 24,
  pushesPerDay: env("TEAMMATE_AUTO_PUSHES_PER_DAY", 6),
  cyclesPerDay: env("TEAMMATE_AUTO_CYCLES_PER_DAY", 16),
  gapMs: env("TEAMMATE_AUTO_GAP_MIN", 15) * MIN, // between cycles
  quietGapMs: env("TEAMMATE_AUTO_QUIET_GAP_MIN", 60) * MIN, // after a cycle that found nothing
  retryMs: 30 * MIN, // usage limit with no reset time given
  verifyDelayMs: env("TEAMMATE_AUTO_VERIFY_DELAY_MIN", 5) * MIN, // the push redeploys production first
  workTimeoutMs: env("TEAMMATE_AUTO_WORK_TIMEOUT_MIN", 120) * MIN,
  maxFailures: 2,
};

/** Areas auto may touch. propose_plan's auto.area must be one of these, else a human has to say "@bot ok". */
export const AUTO_AREAS = ["conversation", "getting_out"];

/** Words that keep a plan on "@bot ok" (CLAUDE.md module isolation, migrations, security, the bot itself). */
const GUARD = [
  /labou?r/i, /attendance/i, /payroll/i, /workforce/i, /migration/i, /alembic/i, /\bdrop(s|ped|ping)?\b/i, /\brenam\w*/i,
  /\bauth\w*/i, /\btokens?\b/i, /\bpermissions?\b/i, /\btenant\w*/i, /\bsecurity\b/i, /\.github/i, /\.env\b/i, /teammate\//i,
  /shared[- ]component/i,
];

/** The first guard word found in the plan's text, or null. */
export function guardWord(...texts) {
  const text = texts.filter(Boolean).join("\n");
  for (const re of GUARD) {
    const m = text.match(re);
    if (m) return m[0].toLowerCase();
  }
  return null;
}

/**
 * Is this a usage / rate limit (the 5-hour window)? `signals` may carry resetsAt (ms) from the SDK's rate_limit_event.
 * Returns { resetAt: ms | null } or null.
 */
export function usageLimit(text, { resetsAt = null, flagged = false, now = Date.now() } = {}) {
  const t = String(text || "");
  const looksLike = flagged || /usage limit|rate[ _-]?limit|limit reached|too many requests|\b429\b|quota|you(?:'|’)ve hit your limit|credit balance|overloaded/i.test(t);
  if (!looksLike) return null;
  return { resetAt: resetsAt || resetTimeFrom(t, now) };
}

/** A reset time given in an error text ("resets in 2 hours", "resets at 3pm (Asia/Kolkata)", an ISO time), as ms; else null. */
export function resetTimeFrom(text, now = Date.now()) {
  const t = String(text || "");
  let m = t.match(/(?:reset|retry|try again|available)[^.\n]{0,30}?in\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b/i);
  if (m) return now + Number(m[1]) * (/^h/i.test(m[2]) ? 60 : 1) * MIN;
  m = t.match(/\b(\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:?\d{2}))/);
  if (m && Date.parse(m[1]) > now) return Date.parse(m[1]);
  m = t.match(/(?:reset|retry|try again|available)[^.\n]{0,20}?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(([A-Za-z_]+\/[A-Za-z_]+)\)/i);
  if (m) {
    const at = nextClockTime(Number(m[1]) % 12 + (/pm/i.test(m[3]) ? 12 : 0), Number(m[2] || 0), m[4], now);
    if (at) return at;
  }
  return null;
}

/** The next moment it is hh:mm in an IANA time zone (null when the zone is unknown). */
function nextClockTime(hh, mm, tz, now) {
  try {
    const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    const parts = fmt.formatToParts(new Date(now));
    const h = Number(parts.find((p) => p.type === "hour").value);
    const mi = Number(parts.find((p) => p.type === "minute").value);
    let delta = (hh * 60 + mm) - (h * 60 + mi);
    if (delta <= 0) delta += 24 * 60;
    return now + delta * MIN;
  } catch {
    return null;
  }
}

/** "HH:MM" in the team's time zone (TEAMMATE_AUTO_TZ, default India), with its name. */
export function clock(ms, tz = process.env.TEAMMATE_AUTO_TZ || "Asia/Kolkata") {
  const t = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(ms));
  return `${t}${tz === "Asia/Kolkata" ? " IST" : ` (${tz})`}`;
}

// The fixed fallback list: used when docs/qa/CONVERSATION_SCORECARD.md isn't readable. Each cycle uses a rotating slice.
export const TEST_MESSAGES = [
  "6 mason, 10 helper vannu",
  "Plastering 2nd floor 40% aayi",
  "plastering finished 2nd floor",
  "25 bags cement vannu",
  "6 mason, 10 helper vannu. Nale slab concrete cheyyan pattumo?",
  "can we pour the slab tomorrow?",
  "what did I log today?",
  "how many workers today?",
  "how much cement is left?",
  "today's summary",
  "Send me today's report",
  "send yesterday's report",
  "send me the report for last friday",
  "paid 4500 for tipper hire (a module that is off should be a short natural line, not a robotic one)",
  "hi",
];
const PER_CYCLE = 5;

/** The messages this cycle sends: a rotating slice, so successive cycles cover the whole list. */
export function messagesForCycle(n) {
  const start = ((Number(n) - 1) * PER_CYCLE) % TEST_MESSAGES.length;
  return Array.from({ length: PER_CYCLE }, (_, i) => TEST_MESSAGES[(start + i) % TEST_MESSAGES.length]);
}

const SCOPE = [
  "SCOPE: only these two areas. Nothing else is ever planned by an auto cycle.",
  "1. Conversation: replies say what was saved; questions are answered or acknowledged; the worker's language and script;",
  "   natural, non-robotic wording (e.g. the AI's \"I'm sorry, I cannot… right now\" rewording of the module-off line);",
  "   one message per input; no repeated text; sensible follow-up questions.",
  "2. Getting things out: report / DPR on demand (today, any date); summaries (\"today's summary\", \"how many workers today\",",
  "   \"cement stock\"); PDFs actually delivered; the receipt card present and correct.",
];

/** The prompt of one TEST + PICK planning turn. */
export function cyclePrompt({ cycle, pending = [], recent = [], seen = [] }) {
  return [
    `AUTO CYCLE #${cycle}. Unattended: nobody is reading along live, and nobody will answer a question. Do not ask for an ok.`,
    "Keep this cycle small: one issue at most, and at most 15 test_assistant sends.",
    "",
    ...SCOPE,
    "",
    "1) TEST. Read the conversation and report parts of docs/qa/CONVERSATION_SCORECARD.md (what scores 2 / 1 / 0), then send these",
    "   messages to the assistant with test_assistant (if that file can't be read, these are the fixed list), and judge each reply like a site worker would:",
    ...messagesForCycle(cycle).map((m, i) => `   ${i + 1}. ${m}`),
    "2) PICK at most ONE real problem in scope, the most useful to fix. A problem outside the scope is NOT planned: put it in the",
    "   cycle summary as \"seen, not fixed: …\" and in cycle_report.seen_not_fixed.",
    "3) If you picked one: investigate the code read-only, then call propose_plan ONCE with auto: { area: \"conversation\" } or",
    "   { area: \"getting_out\" }. The plan must be small, self-contained (problem, files, exact change, tests, tracker row) and",
    "   must not touch Labour, Attendance, Payroll, Workforce, migrations, auth / tokens / permissions / tenants / security,",
    "   .github, .env, teammate/ or a shared component: code checks for those words and sends such a plan to a human instead.",
    "4) ALWAYS finish with cycle_report (outcome planned | no_issue_found | blocked), then a summary of at most 8 lines:",
    "   what you tested, what you found, and \"seen, not fixed: …\" for anything out of scope. Plain WhatsApp style.",
    "   If you can't test at all (no test chat), call needs_attention and use outcome blocked.",
    ...(pending.length ? ["", "Already waiting for a human (don't plan these again):", ...pending.map((t) => `- ${t}`)] : []),
    ...(recent.length ? ["", "Recent cycles (don't repeat their work):", ...recent.map((t) => `- ${t}`)] : []),
    ...(seen.length ? ["", "Already listed as seen, not fixed (list again only if new):", ...seen.map((t) => `- ${t}`)] : []),
  ].join("\n");
}

/** The prompt of the VERIFY planning turn, after the push has deployed. */
export function verifyPrompt({ cycle, plan }) {
  return [
    `AUTO CYCLE #${cycle}, VERIFY. Unattended; do not ask for an ok. The fix below was pushed by an auto run and the bot has redeployed.`,
    "Re-send, with test_assistant, the message(s) that showed the problem (at most 4 sends) and check the replies the way a site worker would.",
    "Then call cycle_report with outcome fixed or not_fixed and say what you saw, in at most 5 lines (WhatsApp style).",
    "Fixing anything else is out of scope; list other problems as \"seen, not fixed: …\".",
    "",
    `Plan [${plan.id}] ${plan.title}`,
    String(plan.plan || "").slice(0, 2500),
  ].join("\n");
}

function readJson(path, fallback) {
  try {
    return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : fallback;
  } catch {
    return fallback;
  }
}

export class AutoLoop {
  /**
   * @param {object} brain the Brain (turn, plans, listener, routines, fireFn, now, log)
   * @param {{ dir: string, landed?: (plan: object, sinceIso: string) => Promise<boolean> }} opts
   *   landed: is this plan's work on main? (git: a commit that names the request.) Default: unknown (false).
   */
  constructor(brain, { dir, landed = async () => false, settings = AUTO_DEFAULTS }) {
    this.brain = brain;
    this.file = `${dir}/auto.json`;
    this.landed = landed;
    this.cfg = settings;
    this.s = readJson(this.file, null) || { enabled: false };
    this.busy = false;
    // Whatever was mid-turn when the process stopped is simply started again; that is not a failure.
    if (this.s.cycle && ["planning", "verifying"].includes(this.s.cycle.phase)) {
      this.s.cycle.phase = this.s.cycle.phase === "planning" ? "idle" : "settling";
      if (this.s.cycle.phase === "idle") this.s.cycle = null;
    }
  }

  now() {
    return this.brain.now().getTime();
  }
  save() {
    writeFileSync(`${this.file}.tmp`, JSON.stringify(this.s, null, 2));
    renameSync(`${this.file}.tmp`, this.file);
  }
  say(text) {
    return this.brain.listener.send({ chat: this.s.chat, project: this.s.project, text }).catch(() => null);
  }
  log(m) {
    this.brain.log(`auto: ${m}`);
  }
  get enabled() {
    return Boolean(this.s.enabled);
  }

  // ---- commands ---------------------------------------------------------------------------------------------------

  /** "auto", "auto on [hours]", "auto off", "stop": returns the reply ("" when already posted), or undefined when the text isn't an auto command. */
  command(req) {
    const text = String(req.text || "").trim();
    let m = text.match(/^auto(?:\s+(on|off|stop|status))?(?:\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)?)?\s*$/i);
    const stop = /^(?:stop|stop auto|auto stop)$/i.test(text);
    if (!m && !stop) return undefined;
    const verb = stop ? "off" : (m[1] || "status").toLowerCase() === "stop" ? "off" : (m[1] || "status").toLowerCase();
    if (verb === "status") return this.statusText();
    if (verb === "off") {
      if (!this.enabled) return "Auto isn't on.";
      this.turnOff(`stopped by ${req.sender}`);
      return ""; // turnOff posts the summary
    }
    // on
    if (req.dm) return "Auto can be switched on in the team group only.";
    if (req.sender_role !== "owner") return "Only an owner can switch auto on. Anyone approved can say @bot auto off.";
    const project = req.reply_project || req.project;
    if (!this.brain.hasRoutine(project) || !this.brain.fireFn) return `Auto needs the cloud routine for ${project}, which isn't set up on this server.`;
    const hours = Math.min(this.cfg.maxHours, Math.max(1, m[2] ? Number(m[2]) : this.cfg.hours));
    const t = this.now();
    this.s = {
      ...this.s, enabled: true, project, chat: req.reply_chat, chat_name: req.chat_name, by: req.sender, hours,
      startedAt: t, expiresAt: t + hours * 3_600_000, failures: 0, paused: null, limitNotified: false, nextAt: t,
      cycle: this.s.cycle?.phase && !["idle"].includes(this.s.cycle.phase) ? this.s.cycle : null,
      seq: this.s.seq || 0, pushes: this.s.pushes || { day: "", n: 0 }, cyclesToday: this.s.cyclesToday || { day: "", n: 0 },
      recent: this.s.recent || [], seen: this.s.seen || [],
    };
    this.save();
    this.log(`on for ${hours} h by ${req.sender} (${project})`);
    setImmediate(() => this.tick());
    return (
      `🤖 *Auto is on* for ${hours} h (until ${clock(this.s.expiresAt)}). Small cycles: test → pick one issue in Conversation or Getting things out → ` +
      `work → verify live, at most ${this.cfg.pushesPerDay} pushes a day, one at a time. Plans that touch Labour, Attendance, Payroll, Workforce, ` +
      "migrations, auth / security, .github, .env, teammate/ or a shared component still wait for @bot ok.\n" +
      "Stop it: @bot auto off (or @bot stop). It also stops after 2 failed cycles in a row, at the spending cap, or on a permission denial. " +
      "A Claude usage limit only pauses it."
    );
  }

  statusText() {
    const s = this.s;
    if (!s.enabled) return "🤖 Auto is off. An owner can start it: @bot auto on [hours].";
    const lines = [`🤖 *Auto is on* until ${clock(s.expiresAt)}, started by ${s.by}.`];
    if (s.paused) lines.push(`⏸ Paused: Claude usage limit, resuming ~${clock(s.paused.until)}.`);
    const c = s.cycle;
    if (c) {
      const where = { planning: "testing and picking", approved: "waiting to start the work", working: `work running for plan [${c.planId}]`, settling: `plan [${c.planId}] landed, waiting for the deploy`, verifying: "verifying live" }[c.phase] || c.phase;
      lines.push(`Cycle #${c.n}: ${where}.`);
    } else lines.push(`Idle until ${clock(s.nextAt || this.now())}.`);
    lines.push(`Pushes today: ${this.todays(s.pushes).n}/${this.cfg.pushesPerDay} · failed cycles in a row: ${s.failures || 0}/${this.cfg.maxFailures}`);
    return lines.join("\n");
  }

  turnOff(why) {
    if (!this.s.enabled) return;
    const c = this.s.cycle;
    this.s.enabled = false;
    this.s.paused = null;
    this.save();
    this.log(`off: ${why}`);
    const flight = c && ["approved", "working", "settling", "verifying"].includes(c.phase) ? `\nPlan [${c.planId}] was already started and is not cancelled: watch its Claude Code session.` : "";
    return this.say(`🛑 *Auto is off* (${why}). Cycles this run: ${this.s.seq || 0}, pushes started today: ${this.todays(this.s.pushes).n}.${flight}\nTo start again: @bot auto on [hours].`);
  }

  todays(counter) {
    const day = new Date(this.now()).toISOString().slice(0, 10);
    return counter?.day === day ? counter : { day, n: 0 };
  }
  bump(name) {
    const c = this.todays(this.s[name]);
    this.s[name] = { day: c.day, n: c.n + 1 };
  }

  // ---- usage limit ------------------------------------------------------------------------------------------------

  /** A usage limit is not a failure: pause, say so once, resume at the reset time (else retry in 30 min). */
  pause(limit) {
    const t = this.now();
    // Several Claude accounts (TM-14): the brain already moved to any free one, so this means all are limited;
    // resume when the first frees up.
    const accounts = this.brain.accounts;
    if (accounts?.list.length > 1 && accounts.earliestReset()) limit = { resetAt: accounts.earliestReset() };
    const until = limit?.resetAt && limit.resetAt > t ? limit.resetAt + MIN : t + this.cfg.retryMs;
    const first = !this.s.limitNotified;
    this.s.paused = { reason: "usage limit", until, since: this.s.paused?.since || t };
    this.s.limitNotified = true;
    this.save();
    this.log(`paused (usage limit) until ${new Date(until).toISOString()}`);
    if (first) return this.say(`⏸ Paused: Claude usage limit, resuming ~${clock(until)}`);
  }

  // ---- the loop ---------------------------------------------------------------------------------------------------

  /** Called every minute (and when switched on). Does at most one step; never overlaps itself. */
  async tick() {
    if (!this.enabled || this.busy) return;
    this.busy = true;
    try {
      await this.step();
    } catch (e) {
      this.log(`step failed: ${e.stack || e}`);
      await this.cycleFailed(`internal error: ${String(e.message || e).slice(0, 120)}`);
    } finally {
      this.busy = false;
    }
  }

  async step() {
    const s = this.s;
    const t = this.now();
    if (t >= s.expiresAt) return this.turnOff(`time is up after ${s.hours} h`);
    const paused = s.paused && t < s.paused.until;
    if (s.paused && !paused) {
      s.paused = null; // the reset time came (or the 30 min retry): carry on
      this.save();
    }
    const c = s.cycle;
    if (c?.phase === "working") return this.watchWork(c, paused);
    if (paused) return;
    if (c?.phase === "approved") return this.fire(c); // the fire was refused by a limit: same plan, once the pause ends
    if (c?.phase === "settling") return t >= c.settleAt ? this.verify(c) : undefined;
    if (c?.phase === "verifying") return this.verify(c);
    if (c) return;
    if (t < (s.nextAt || 0)) return;
    if (this.todays(s.cyclesToday).n >= this.cfg.cyclesPerDay) {
      s.nextAt = t + 60 * MIN;
      return this.save();
    }
    return this.startCycle();
  }

  async startCycle() {
    const s = this.s;
    s.seq = (s.seq || 0) + 1;
    this.bump("cyclesToday");
    const n = s.seq;
    s.cycle = { n, phase: "planning", startedAt: this.now() };
    this.save();
    const pending = Object.values(this.brain.planStore.plans).filter((p) => p.status === "proposed" && (p.chat_project || p.project) === s.project).map((p) => `[${p.id}] ${p.title}`);
    const prompt = cyclePrompt({ cycle: n, pending, recent: (s.recent || []).slice(-4), seen: (s.seen || []).slice(-8) });
    const r = await this.runTurn(n, prompt);
    if (!this.enabled) return; // switched off while it ran: nothing is approved or started
    const out = r.outcome;
    if (!this.afterTurn(out, n)) return;
    // The model's own plan(s) from this cycle: the first is the one issue; code decides whether it may go.
    const plan = Object.values(this.brain.planStore.plans).filter((p) => p.cycle === n).sort((a, b) => String(a.at).localeCompare(String(b.at)))[0];
    this.noteSeen(r.report);
    if (!plan) {
      this.s.recent = [...(s.recent || []), `#${n}: ${r.report?.outcome || "no plan"} — ${String(r.report?.summary || "nothing to fix").slice(0, 140)}`].slice(-8);
      return this.cycleDone({ quiet: true });
    }
    return this.decide(plan, n);
  }

  /** Runs one planning turn for the auto session (a fresh conversation each time, so a cycle stays small). */
  async runTurn(n, text) {
    const s = this.s;
    const report = { current: null };
    const flags = { attention: null };
    this.brain.sessions.ids[`${s.chat}::auto`] = null;
    const req = {
      project: s.project, reply_project: s.project, chat: s.chat, chat_name: s.chat_name || s.project, chat_role: "team", reply_chat: s.chat,
      sender: "the auto loop", sender_role: "owner", n: null, text, session: "auto", auto: true, auto_cycle: n,
      auto_report: (r) => (report.current = r),
      auto_attention: (kind) => (flags.attention = kind),
      budget: Number(process.env.TEAMMATE_AUTO_PLAN_USD || 0) || undefined,
    };
    const outcome = (await this.brain.enqueue(`${s.chat}::auto`, () => this.brain.turn(req, "planning"))) || { ok: false, error: "turn crashed" };
    outcome.attention = flags.attention;
    return { outcome, report: report.current };
  }

  /** Common checks after a planning turn. Returns true when the cycle may go on. */
  afterTurn(out, n) {
    if (out.limit) {
      this.s.cycle = null; // this cycle is lost, not failed
      this.s.nextAt = this.now();
      this.pause(out.limit);
      return false;
    }
    if (out.budget) {
      this.s.cycle = null;
      this.turnOff("spending cap reached");
      return false;
    }
    if (out.denied?.length || out.attention === "permission") {
      this.s.cycle = null;
      this.turnOff("a permission was denied; a human has to look");
      return false;
    }
    if (!out.ok || out.attention) {
      this.cycleFailed(out.attention ? "the cycle needed a human" : `the planning turn failed (${String(out.error || "no result").slice(0, 80)})`);
      return false;
    }
    this.resumed();
    return true;
  }

  /** Once a call gets through again after a usage-limit pause. */
  resumed() {
    if (!this.s.limitNotified) return;
    this.s.limitNotified = false;
    this.save();
    this.say("▶️ Auto resumed after the usage limit.");
  }

  noteSeen(report) {
    const add = (report?.seen_not_fixed || []).filter(Boolean);
    if (add.length) this.s.seen = [...new Set([...(this.s.seen || []), ...add])].slice(-20);
  }

  /** The code-checked approval. Not approved is not a failure: the plan simply waits for a human "@bot ok". */
  async decide(plan, n) {
    const s = this.s;
    const why = !plan.auto || !AUTO_AREAS.includes(String(plan.auto.area || "").toLowerCase())
      ? `outside Conversation / Getting things out (area: ${plan.auto?.area || "not given"})`
      : guardWord(plan.title, plan.plan)
        ? `it mentions "${guardWord(plan.title, plan.plan)}"`
        : this.todays(s.pushes).n >= this.cfg.pushesPerDay
          ? `today's ${this.cfg.pushesPerDay} auto pushes are used`
          : null;
    if (why) {
      this.log(`plan [${plan.id}] not auto-approved: ${why}`);
      await this.say(`✋ Plan [${plan.id}] ${plan.title}\nNot auto-approved: ${why}. Reply @bot ok ${plan.id} if you want it done.`);
      s.recent = [...(s.recent || []), `#${n}: plan [${plan.id}] waits for a human (${why})`].slice(-8);
      return this.cycleDone({ quiet: false });
    }
    plan.status = "approved";
    plan.approved_by = "auto";
    plan.approved_at = this.brain.now().toISOString();
    this.brain.savePlans();
    this.bump("pushes");
    s.cycle = { n, phase: "approved", planId: plan.id, area: plan.auto.area, approvedAt: this.now(), refired: false };
    this.save();
    if (typeof plan.id === "number") {
      this.brain.listener.updateItem(plan.id, { status: "in_progress", note: `approved_by: auto (cycle ${n}, area ${plan.auto.area})`, project: s.project }).catch(() => {});
    }
    return this.fire(s.cycle);
  }

  /** Fires the plan's cloud routine. A refused fire because of a limit pauses (same plan fires later); other errors fail the cycle. */
  async fire(c) {
    const s = this.s;
    const plan = this.brain.planStore.plans[c.planId];
    if (!plan) return this.cycleFailed("the plan disappeared");
    const r = await this.brain.runInCloud(plan, { project: s.project, by: "auto", reply_chat: s.chat, say: (t) => this.say(t), quiet: true });
    if (r.ok) {
      this.resumed();
      c.phase = "working";
      c.firedAt = this.now();
      this.save();
      this.say(`🤖 Auto cycle #${c.n}: plan [${plan.id}] ${plan.title} (${c.area}) was auto-approved and started.\nWatch it: ${plan.session_url || "(link not returned)"}`);
      return;
    }
    const limit = usageLimit(r.error, { flagged: r.limit });
    if (limit) {
      c.phase = "approved";
      this.save();
      return this.pause(limit);
    }
    return this.cycleFailed(`the cloud routine didn't start (${String(r.error).slice(0, 100)})`);
  }

  /** While the routine works: done when its request-log item is done or its commit is on main. A stall is re-fired once. */
  async watchWork(c, paused) {
    const s = this.s;
    const plan = this.brain.planStore.plans[c.planId];
    let item = null;
    if (typeof c.planId === "number") {
      try {
        item = (await this.brain.listener.getItem(c.planId, s.project))?.item;
      } catch {
        // the request log is a convenience; git below is the proof
      }
    }
    if (item?.status === "wont_do") return this.cycleFailed(`plan [${c.planId}] was dropped (wont_do)`);
    const since = new Date(c.approvedAt).toISOString();
    const onMain = await this.landed(plan, since).catch(() => false);
    if (onMain || item?.status === "done") {
      if (plan) plan.status = "done";
      this.brain.savePlans();
      c.phase = "settling";
      c.settleAt = this.now() + this.cfg.verifyDelayMs;
      this.save();
      return;
    }
    if (this.now() - (c.firedAt || c.approvedAt) < this.cfg.workTimeoutMs || paused) return;
    // The routine stopped before pushing (typically the 5-hour limit hit mid-work): nothing half-done is on main, so
    // re-fire the SAME plan, once, instead of picking a new issue.
    if (!c.refired) {
      c.refired = true;
      this.log(`plan [${c.planId}] is not on main after ${Math.round(this.cfg.workTimeoutMs / MIN)} min: re-fired once`);
      const r = await this.brain.runInCloud(plan, { project: s.project, by: "auto", reply_chat: s.chat, say: (t) => this.say(t), quiet: true });
      const limit = !r.ok && usageLimit(r.error, { flagged: r.limit });
      if (limit) {
        c.refired = false;
        c.firedAt = this.now(); // the clock restarts after the pause
        return this.pause(limit);
      }
      if (!r.ok) return this.cycleFailed(`re-firing plan [${c.planId}] failed (${String(r.error).slice(0, 100)})`);
      c.firedAt = this.now();
      this.save();
      this.say(`🔁 Plan [${c.planId}] wasn't on main after ${Math.round(this.cfg.workTimeoutMs / MIN)} min (probably stopped by a limit). Started it again once.\n${plan.session_url || ""}`.trim());
      return;
    }
    if (plan) plan.status = "failed";
    this.brain.savePlans();
    return this.cycleFailed(`plan [${c.planId}] still isn't on main after the second try`);
  }

  async verify(c) {
    const s = this.s;
    const plan = this.brain.planStore.plans[c.planId];
    c.phase = "verifying";
    this.save();
    const r = await this.runTurn(c.n, verifyPrompt({ cycle: c.n, plan: plan || { id: c.planId, title: "", plan: "" } }));
    if (!this.enabled) return;
    if (!this.afterTurn(r.outcome, c.n)) {
      if (r.outcome.limit) {
        // the work is on main; only the check is waiting for the pause to end
        s.cycle = { ...c, phase: "settling", settleAt: 0 };
        this.save();
      }
      return;
    }
    this.noteSeen(r.report);
    const fixed = r.report?.outcome === "fixed";
    s.recent = [...(s.recent || []), `#${c.n}: plan [${c.planId}] ${fixed ? "fixed" : "not fixed"} — ${String(r.report?.summary || "").slice(0, 120)}`].slice(-8);
    if (!fixed) return this.cycleFailed(`plan [${c.planId}] pushed, but the live check says it isn't fixed`);
    return this.cycleDone({ quiet: false });
  }

  cycleDone({ quiet }) {
    const s = this.s;
    s.failures = 0;
    s.cycle = null;
    s.nextAt = this.now() + (quiet ? this.cfg.quietGapMs : this.cfg.gapMs);
    this.save();
  }

  /** Two failed cycles in a row switch auto off. */
  async cycleFailed(why) {
    const s = this.s;
    s.failures = (s.failures || 0) + 1;
    s.cycle = null;
    s.nextAt = this.now() + this.cfg.gapMs;
    this.save();
    this.log(`cycle failed (${s.failures}/${this.cfg.maxFailures}): ${why}`);
    if (s.failures >= this.cfg.maxFailures) return this.turnOff(`${s.failures} failed cycles in a row; last: ${why}`);
    return this.say(`⚠️ Auto cycle failed: ${why}. One more failure and it switches itself off.`);
  }
}
