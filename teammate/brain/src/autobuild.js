// Autobuild (TM-18, Ilan 1 Nov 2026): "a tester's WhatsApp message should reach production with no human in the loop.
// If we need correction, we will tell. Just report what it is developing; it should develop fast."
//
// With autobuild on (the default; owners: "@bot autobuild off" / "on"), a plan that a planning turn records for the
// project (the production watch's plans, and plans from approved people in the team group or a 1-on-1 chat) starts
// building in the cloud right after that turn, exactly as if an owner had replied "@bot ok <n>". The group sees
// "▶️ Working on [n] …" with the session link, then the job's own progress, and the people who hit it get the release
// note once it is live.
//
// Code decides, not the model, and holds back for a human ok only what CLAUDE.md still reserves for the owner:
// Labour / Attendance / Payroll / Workforce, migrations that drop or rename data, secrets and tokens, tenant
// isolation, login, CI / deploy files, the bot itself (teammate/), and the daily cap. Roles and permissions inside the
// product (who may create a project, admin vs site engineer) are NOT held: Ilan, 1 Nov: "those you can do; report it".
// A held plan is posted with the reason and waits for "@bot ok <n>" as before.

import { readFileSync, writeFileSync, renameSync } from "node:fs";

export const AUTOBUILD_PER_DAY = Number(process.env.TEAMMATE_AUTOBUILD_PER_DAY || 12);

/** What keeps a plan on "@bot ok". Each entry: [pattern, reason in plain words]. */
const HOLD = [
  [/\blabou?r\b/i, "Labour"],
  [/\battendance\b/i, "Attendance"],
  [/\bpayroll\b|\bwages?\b|\bsalar(?:y|ies)\b/i, "Payroll"],
  [/\bworkforce\b/i, "Workforce"],
  [/\bdrop(?:s|ped|ping)?\s+(?:the\s+)?(?:table|column|index|constraint)\b|\brenam\w*\s+(?:the\s+)?(?:table|column)\b|\bdelete[sd]?\s+(?:existing\s+)?(?:rows|data|records)\b|\bbackfill\w*\b|\brewrit\w*\s+(?:existing\s+)?data\b/i, "a migration that changes existing data"],
  [/\bsecrets?\b|\bapi[ _-]?keys?\b|\b(?:access|auth|bearer|oauth|api)[ _-]?tokens?\b|\bcredentials?\b/i, "secrets or tokens"],
  [/\btenant\w*\b|\brow[ -]level security\b|\bRLS\b/, "tenant isolation"],
  [/\blogin\b|\bpasswords?\b|\botp\b|\bsign[ -]?in\b|\bauthenticat\w*\b/i, "login / authentication"],
  [/\.github\b|\bdeploy\.yml\b|\.env\b/i, "CI / deploy files"],
  [/\bteammate\//i, "the bot itself (teammate/)"],
];

/** A sentence that says what the plan does NOT touch ("Labour untouched", "no migration") is not a reason to hold. */
const NOT_TOUCHED = /\b(?:untouched|not touched|unchanged|not changed|no changes? to|nothing (?:in|to)|(?:does|do|will) not (?:touch|change)|doesn'?t (?:touch|change)|never touch\w*|without touching|stays? (?:the same|as it is)|no migration|out of scope|not in scope)\b/i;

/** The plan's text without the sentences (and lines) that only say what stays untouched. */
export function touchedText(...texts) {
  return texts
    .filter(Boolean)
    .join("\n")
    .split(/\n+|(?<=[.;!?])\s+/)
    .filter((part) => !NOT_TOUCHED.test(part))
    .join("\n");
}

/** Why this plan must wait for a human ok, or null when autobuild may start it. */
export function holdReason(plan) {
  if (plan?.session === "upgrade") return "it changes the bot itself";
  const text = touchedText(plan?.title, plan?.plan);
  for (const [re, why] of HOLD) if (re.test(text)) return `it touches ${why}`;
  return null;
}

export class AutoBuild {
  /** @param file  where the per-project setting and today's count are kept */
  constructor({ file, now = () => Date.now(), perDay = AUTOBUILD_PER_DAY, defaultOn = process.env.TEAMMATE_AUTOBUILD !== "0" }) {
    Object.assign(this, { file, now, perDay, defaultOn });
    try {
      this.s = JSON.parse(readFileSync(file, "utf8"));
    } catch {
      this.s = {};
    }
  }

  save() {
    const tmp = `${this.file}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.s, null, 2));
    renameSync(tmp, this.file);
  }

  isOn(project) {
    const p = this.s.projects?.[project];
    return p ? Boolean(p.on) : this.defaultOn;
  }

  /** Builds started today (India day) for this project. */
  today(project) {
    const day = new Date(this.now() + 5.5 * 3600_000).toISOString().slice(0, 10);
    const c = this.s.count?.[project];
    return c && c.day === day ? c : { day, n: 0 };
  }

  /** Why autobuild won't start this plan (null: start it). Not started means it waits for "@bot ok". */
  decide(plan, project) {
    if (!this.isOn(project)) return "autobuild is off";
    const why = holdReason(plan);
    if (why) return why;
    if (this.today(project).n >= this.perDay) return `today's ${this.perDay} automatic builds are used`;
    return null;
  }

  started(project) {
    const c = this.today(project);
    c.n += 1;
    (this.s.count ||= {})[project] = c;
    this.save();
  }

  /**
   * "@bot autobuild" (anyone approved: the state) and, for owners in the team group, "autobuild on" / "off".
   * Returns the reply, or undefined when the text isn't an autobuild command.
   */
  command(req) {
    const m = String(req.text || "").trim().match(/^auto[\s-]?build(?:\s+(.*))?$/i);
    if (!m) return undefined;
    const project = req.reply_project || req.project;
    const arg = String(m[1] || "").trim().toLowerCase();
    const show = (head = "") => {
      const on = this.isOn(project);
      return `${head}🛠 *Autobuild*: ${on ? "*on*: plans from the production watch and from your messages start building by themselves; Labour / Attendance / Payroll / Workforce, data-changing migrations, secrets, tenant isolation, login and the bot itself still wait for @bot ok" : "*off*: every plan waits for @bot ok <n>"}\n` +
        `Today: ${this.today(project).n} of ${this.perDay} started\nOwners: @bot autobuild on | off`;
    };
    if (!arg || /^(status|\?)$/.test(arg)) return show();
    if (req.dm) return "Autobuild can be switched in the team group only.";
    if (req.sender_role !== "owner") return "Only an owner can switch autobuild.";
    if (!/^(on|off|start|stop|pause|resume)$/.test(arg)) return `I didn't understand "${arg}". Try: @bot autobuild on, off, or just @bot autobuild.`;
    const on = /^(on|start|resume)$/.test(arg);
    (this.s.projects ||= {})[project] = { on, by: req.sender || "an owner", at: new Date(this.now()).toISOString() };
    this.save();
    return show(on ? "▶️ " : "⏸️ ");
  }
}
