// Several Claude accounts behind the one bot number (TM-14). Each account brings its own Claude Code
// login and, per project, its own cloud routine and partner routine. Every WhatsApp group runs on an
// account: the one an owner picked for that group, else the default. When that account hits its usage
// limit, the group borrows the next free account until the limit resets (unless an owner turned
// automatic switching off), then goes back to its own.
//
// Account A is the original set of variables; any other account repeats them with its letter added:
//   A  CLAUDE_CODE_OAUTH_TOKEN      TEAMMATE_ROUTINE_<P>_URL / _TOKEN      TEAMMATE_PARTNER_<P>_URL / _TOKEN
//   B  CLAUDE_CODE_OAUTH_TOKEN_B    TEAMMATE_ROUTINE_<P>_URL_B / _TOKEN_B  TEAMMATE_PARTNER_<P>_URL_B / _TOKEN_B
//   C, D, … the same. An account exists once its Claude token does.
// Optional name (TM-75), for every letter A included: CLAUDE_ACCOUNT_NAME_<X>=ilan-work, shown as "B (ilan-work)".
// State (default account, each group's pick, automatic switching, limits): <dir>/accounts.json.

import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { clock } from "./auto.js";

const RETRY_MS = 30 * 60_000; // a limit with no reset time given: try that account again after this
/** TM-78: the plan windows shown and kept: the 5-hour session window and the weekly one. */
export const WINDOWS = { five_hour: "5-hour", seven_day: "weekly" };
/** TM-78: the team group is warned once per window when an account passes this share of it. */
export const WARN_PCT = 80;
const TOKEN = "CLAUDE_CODE_OAUTH_TOKEN";
const NAME = "CLAUDE_ACCOUNT_NAME";

/** A name as shown in WhatsApp: letters, digits, . _ - only, at most 40; anything else drops it. */
function cleanName(v) {
  const n = String(v || "").trim();
  return /^[A-Za-z0-9._-]{1,40}$/.test(n) ? n : null;
}

/** Every account the environment configures: [{ id: "a", token, routines: {project: {url, token}}, partners }]. */
export function parseAccounts(env, projectNames) {
  const more = Object.keys(env)
    .map((k) => k.match(new RegExp(`^${TOKEN}_([A-Z0-9]+)$`))?.[1])
    .filter((s) => s && s !== "A" && env[`${TOKEN}_${s}`]);
  return ["a", ...more.map((s) => s.toLowerCase()).sort()].map((id) => {
    const sfx = id === "a" ? "" : `_${id.toUpperCase()}`;
    const pick = (kind) => {
      const out = {};
      for (const p of projectNames) {
        const url = env[`TEAMMATE_${kind}_${p.toUpperCase()}_URL${sfx}`];
        const token = env[`TEAMMATE_${kind}_${p.toUpperCase()}_TOKEN${sfx}`];
        if (url && token) out[p] = { url, token };
      }
      return out;
    };
    const name = cleanName(env[`${NAME}_${id.toUpperCase()}`]);
    return { id, token: env[`${TOKEN}${sfx}`] || null, routines: pick("ROUTINE"), partners: pick("PARTNER"), ...(name ? { name } : {}) };
  });
}

export class Accounts {
  /** @param {{ list: Array<{id: string, token: string|null, routines: object, partners: object}>, file?: string|null, now?: () => number, log?: (m: string) => void }} opts */
  constructor({ list, file = null, now = () => Date.now(), log = () => {} }) {
    Object.assign(this, { list, file, now, log });
    let saved = {};
    try {
      saved = file ? JSON.parse(readFileSync(file, "utf8")) : {};
    } catch {
      // first start
    }
    this.state = { default: "a", groups: {}, auto: true, limited: {}, usage: {}, ...saved };
    this.state.usage ||= {};
    // An account whose login was removed: back to A.
    if (!this.get(this.state.default)) this.state.default = "a";
    for (const [chat, id] of Object.entries(this.state.groups)) if (!this.get(id)) delete this.state.groups[chat];
  }

  save() {
    if (!this.file) return;
    writeFileSync(`${this.file}.tmp`, JSON.stringify(this.state, null, 2));
    renameSync(`${this.file}.tmp`, this.file);
  }

  /** By letter, or (TM-75) by its name, ignoring case. */
  get(id) {
    const key = String(id || "").toLowerCase();
    return this.list.find((a) => a.id === key) || this.list.find((a) => a.name && a.name.toLowerCase() === key) || null;
  }

  /** The account a group picked (or the default), whether or not it's limited right now. */
  chosen(chat) {
    return this.get(this.state.groups[chat]) || this.get(this.state.default) || this.list[0];
  }

  /**
   * The account a group's turn runs on now: its chosen one, or, while that one is limited (and automatic
   * switching is on), the next free account after it in letter order. `fits` narrows the choice (e.g. an
   * account with a routine for the project); when nothing fits and is free, the chosen account.
   */
  for(chat, fits = () => true) {
    const chosen = this.chosen(chat);
    if (!this.state.auto) return chosen;
    const i = this.list.indexOf(chosen);
    const order = [...this.list.slice(i), ...this.list.slice(0, i)];
    return order.find((a) => a.token && !this.limitedUntil(a.id) && fits(a)) || order.find((a) => fits(a)) || chosen;
  }

  /** The Claude login a turn runs with: only that account's token is ever in Claude's environment. */
  env(chat) {
    const t = this.for(chat).token;
    return t ? { [TOKEN]: t } : {};
  }

  limitedUntil(id) {
    const until = this.state.limited[id] || 0;
    return until > this.now() ? until : 0;
  }

  /**
   * A group's account hit its usage limit: remember until when (it's the account that's limited, so every
   * group on it moves) and say which account the group moves to. { from, to } when there is a free one
   * (that fits), else null.
   */
  failover(limit, chat, fits = () => true) {
    const from = this.for(chat, fits).id;
    const t = this.now();
    this.state.limited[from] = limit?.resetAt && limit.resetAt > t ? limit.resetAt : t + RETRY_MS;
    this.save();
    const to = this.for(chat, fits);
    if (to.id === from || !to.token || this.limitedUntil(to.id) || !fits(to)) return null;
    this.log(`accounts: ${from} hit its limit; ${chat} moves to ${to.id}`);
    return { from, to: to.id };
  }

  /** When the first limited account frees up (ms), for "everything is limited" messages. */
  earliestReset() {
    const times = this.list.map((a) => this.limitedUntil(a.id)).filter(Boolean);
    return times.length ? Math.min(...times) : null;
  }

  /**
   * TM-78: a plan-limit reading for account `id`: { five_hour: { pct, resets_at }, seven_day: {...} } (pct 0-100,
   * resets_at ms). TM-79: between two readings of the same window, the rise in pct over the dollars the bot's turns
   * spent on that account in between is how much of the window one dollar takes (kept as a running average). Work
   * on the account that the bot doesn't see (a person's own session, a cloud routine) is in the rise too, so the
   * estimate leans high, never low.
   */
  reading(id, windows) {
    const u = (this.state.usage[id] ||= { rate: {}, spent: 0, warned: {} });
    for (const w of Object.keys(WINDOWS)) {
      const next = windows?.[w];
      if (!next || !Number.isFinite(next.pct)) continue;
      const prev = u[w];
      const sameWindow = prev && next.resets_at && prev.resets_at && Math.abs(next.resets_at - prev.resets_at) < 30 * 60_000;
      if (sameWindow && u.spent >= 0.05 && next.pct > prev.pct) {
        const r = (next.pct - prev.pct) / u.spent;
        u.rate[w] = u.rate[w] ? 0.7 * u.rate[w] + 0.3 * r : r;
      }
      u[w] = { pct: Math.round(next.pct * 10) / 10, resets_at: next.resets_at || null };
    }
    u.spent = 0;
    u.at = this.now();
    this.save();
  }

  /** TM-79: a turn on account `id` cost `usd`; returns its share of the windows, { pct_5h, pct_7d } (null: not known yet). */
  spend(id, usd) {
    const u = (this.state.usage[id] ||= { rate: {}, spent: 0, warned: {} });
    const cost = Number(usd) > 0 ? Number(usd) : 0;
    u.spent = (u.spent || 0) + cost;
    this.save();
    const share = (w) => (u.rate[w] ? Math.min(100, Math.round(cost * u.rate[w] * 10) / 10) : null);
    return { pct_5h: share("five_hour"), pct_7d: share("seven_day") };
  }

  /** "5-hour 82% (resets ~14:30) · weekly 40%", or null before the first reading (or once it is a day old). */
  usageLine(id) {
    const u = this.state.usage[id];
    if (!u?.at || this.now() - u.at > 24 * 3600_000) return null;
    const bits = Object.entries(WINDOWS)
      .filter(([w]) => u[w])
      .map(([w, name]) => {
        const r = u[w];
        const past = r.resets_at && r.resets_at <= this.now(); // the window has reset since: 0% until the next reading
        return `${name} ${past ? 0 : r.pct}%${!past && r.resets_at && w === "five_hour" ? ` (resets ~${clock(r.resets_at)})` : ""}${!past && r.pct >= WARN_PCT ? " ⚠️" : ""}`;
      });
    return bits.length ? bits.join(" · ") : null;
  }

  /** TM-78: one line for the evening digest: "• 🔑 Claude: A 5-hour 35% · weekly 20% | B (ilan-work) …", or null. */
  digestLine() {
    const parts = this.list.filter((a) => a.token).map((a) => {
      const until = this.limitedUntil(a.id);
      const used = until ? `at its limit until ~${clock(until)}` : this.usageLine(a.id);
      return used ? `${this.label(a.id)} ${used}` : null;
    }).filter(Boolean);
    return parts.length ? `• 🔑 Claude: ${parts.join(" | ")}` : null;
  }

  /** TM-78: the warning to post once per window when an account passes WARN_PCT, else null. */
  warning(id) {
    const u = this.state.usage[id];
    for (const [w, name] of Object.entries(WINDOWS)) {
      const r = u?.[w];
      if (!r || r.pct < WARN_PCT || (r.resets_at && r.resets_at <= this.now())) continue;
      const key = String(r.resets_at || "none");
      if (u.warned?.[w] === key) continue;
      (u.warned ||= {})[w] = key;
      this.save();
      const free = this.list.filter((a) => a.id !== id && a.token && !this.limitedUntil(a.id)).map((a) => this.label(a.id));
      return `⚠️ Claude account *${this.label(id)}* has used ${r.pct}% of its ${name} limit${r.resets_at ? ` (resets ~${clock(r.resets_at)})` : ""}.${free.length ? ` Free: ${free.join(", ")}.` : ""}`;
    }
    return null;
  }

  /** TM-78: every account as the listener keeps it (for the control panel): no tokens, ever. */
  snapshot() {
    return this.list.map((a) => {
      const u = this.state.usage[a.id] || {};
      const win = (w) => (u[w] ? { pct: u[w].resets_at && u[w].resets_at <= this.now() ? 0 : u[w].pct, resets_at: u[w].resets_at ? new Date(u[w].resets_at).toISOString() : null } : null);
      const until = this.limitedUntil(a.id);
      return {
        id: a.id, label: this.label(a.id), logged_in: Boolean(a.token), default: a.id === this.state.default,
        five_hour: win("five_hour"), seven_day: win("seven_day"),
        read_at: u.at ? new Date(u.at).toISOString() : null, limited_until: until ? new Date(until).toISOString() : null,
      };
    });
  }

  /** "B", or "B (ilan-work)" when the account has a name. */
  label(id) {
    const name = this.list.find((a) => a.id === id)?.name;
    return name ? `${id.toUpperCase()} (${name})` : id.toUpperCase();
  }

  /**
   * "account" (anyone approved) · owners, in a team group: "account <letter>" (this group), "account default
   * <letter>" (groups that haven't picked one), "account reset" (this group back to the default),
   * "account auto on|off". Returns a reply or null.
   */
  command(req) {
    const text = String(req.text || "").trim();
    const m = text.match(/^(?:(?:switch|use)\s+(?:to\s+)?)?(?:claude\s+)?accounts?(?:\s+(?:switch\s+)?(?:to\s+)?(.+?))?\s*$/i);
    if (!m) return null;
    const arg = (m[1] || "").toLowerCase().replace(/\s+/g, " ");
    if (!arg || arg === "list" || arg === "status") return this.show(req.chat);
    if (req.dm) return "The Claude account can be changed in a team group only.";
    if (req.sender_role !== "owner") return "Only an owner can change the Claude account.";
    const auto = arg.match(/^auto(?: (on|off))?$/);
    if (auto) {
      if (!auto[1]) return this.show(req.chat);
      this.state.auto = auto[1] === "on";
      this.save();
      this.log(`accounts: ${req.sender} turned automatic switching ${auto[1]}`);
      return this.state.auto
        ? "✅ Automatic switching is on: when a group's account hits its limit, it borrows the next free one until the limit resets."
        : "✅ Automatic switching is off: every group stays on its own account, even at a usage limit.";
    }
    if (/^(reset|default|follow default)$/.test(arg)) {
      delete this.state.groups[req.chat];
      this.save();
      return `✅ This group follows the default account again (*${this.label(this.state.default)}*).`;
    }
    const d = arg.match(/^(?:default|all|everywhere)(?: (?:to )?(\S+))$|^(\S+) (?:everywhere|for all|default)$/);
    const target = this.get(d ? d[1] || d[2] : arg);
    if (!target || !target.token) {
      const ids = this.list.filter((a) => a.token).map((a) => this.label(a.id));
      return `There's no account *${(d ? d[1] || d[2] : arg).toUpperCase()}* on this server. Set up: ${ids.join(", ") || "none"}.`;
    }
    delete this.state.limited[target.id]; // an owner's pick means "try it now"
    if (d) {
      this.state.default = target.id;
      this.save();
      this.log(`accounts: ${req.sender} set the default to ${target.id}`);
      const own = Object.keys(this.state.groups).length;
      return `🔁 Default Claude account is now *${this.label(target.id)}*${own ? ` (groups that picked their own keep it: ${own})` : ""}.`;
    }
    this.state.groups[req.chat] = target.id;
    this.save();
    this.log(`accounts: ${req.sender} set ${req.chat} to ${target.id}`);
    return `🔁 This group now runs on Claude account *${this.label(target.id)}* (from the next message). Other groups are unchanged.`;
  }

  show(chat) {
    const chosen = this.chosen(chat);
    const using = this.for(chat);
    const own = Boolean(this.get(this.state.groups[chat]));
    const lines = this.list.map((a) => {
      const bits = [];
      if (!a.token) bits.push("no Claude login");
      if (!Object.keys(a.routines).length) bits.push("no cloud routine");
      const until = this.limitedUntil(a.id);
      if (until) bits.push(`limit until ~${clock(until)}`);
      const used = !until && this.usageLine(a.id);
      if (used) bits.push(used);
      const tags = [a.id === this.state.default ? "default" : "", a.id === using.id ? "← this group" : ""].filter(Boolean).join(" ");
      return `• *${this.label(a.id)}*${tags ? `  ${tags}` : ""}${bits.length ? ` (${bits.join(", ")})` : ""}`;
    });
    const here =
      `This group: *${this.label(chosen.id)}*${own ? "" : " (the default)"}` +
      (using.id !== chosen.id ? `, borrowing *${this.label(using.id)}* while ${this.label(chosen.id)} is at its limit` : "");
    return (
      `🔑 Claude accounts:\n${lines.join("\n")}\n${here}\nAutomatic switching on a usage limit: *${this.state.auto ? "on" : "off"}*\n` +
      "Owners: @bot account <letter or name> (this group) · @bot account default <letter> · @bot account reset · @bot account auto on|off"
    );
  }
}

/** TM-78: the SDK's /usage answer (rate_limits, utilization 0-100, ISO resets_at) as a reading, or null. */
export function windowsFromUsage(res) {
  const rl = res?.rate_limits;
  if (!rl) return null;
  const out = {};
  for (const w of Object.keys(WINDOWS)) {
    const r = rl[w];
    if (r && Number.isFinite(r.utilization)) out[w] = { pct: r.utilization, resets_at: r.resets_at ? Date.parse(r.resets_at) || null : null };
  }
  return Object.keys(out).length ? out : null;
}

/**
 * TM-78: a rate_limit_event (one window, utilization when the SDK sends it, resetsAt in seconds) as a reading, or
 * null. The event's utilization is a fraction (0-1) where /usage gives percent; anything above 1 is taken as percent.
 */
export function windowsFromEvent(info) {
  const w = info?.rateLimitType;
  if (!WINDOWS[w] || !Number.isFinite(info.utilization)) return null;
  const pct = info.utilization <= 1 ? info.utilization * 100 : info.utilization;
  return { [w]: { pct, resets_at: info.resetsAt ? info.resetsAt * 1000 : null } };
}
