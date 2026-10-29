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
// State (default account, each group's pick, automatic switching, limits): <dir>/accounts.json.

import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { clock } from "./auto.js";

const RETRY_MS = 30 * 60_000; // a limit with no reset time given: try that account again after this
const TOKEN = "CLAUDE_CODE_OAUTH_TOKEN";

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
    return { id, token: env[`${TOKEN}${sfx}`] || null, routines: pick("ROUTINE"), partners: pick("PARTNER") };
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
    this.state = { default: "a", groups: {}, auto: true, limited: {}, ...saved };
    // An account whose login was removed: back to A.
    if (!this.get(this.state.default)) this.state.default = "a";
    for (const [chat, id] of Object.entries(this.state.groups)) if (!this.get(id)) delete this.state.groups[chat];
  }

  save() {
    if (!this.file) return;
    writeFileSync(`${this.file}.tmp`, JSON.stringify(this.state, null, 2));
    renameSync(`${this.file}.tmp`, this.file);
  }

  get(id) {
    return this.list.find((a) => a.id === id) || null;
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

  label(id) {
    return id.toUpperCase();
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
      const tags = [a.id === this.state.default ? "default" : "", a.id === using.id ? "← this group" : ""].filter(Boolean).join(" ");
      return `• *${this.label(a.id)}*${tags ? `  ${tags}` : ""}${bits.length ? ` (${bits.join(", ")})` : ""}`;
    });
    const here =
      `This group: *${this.label(chosen.id)}*${own ? "" : " (the default)"}` +
      (using.id !== chosen.id ? `, borrowing *${this.label(using.id)}* while ${this.label(chosen.id)} is at its limit` : "");
    return (
      `🔑 Claude accounts:\n${lines.join("\n")}\n${here}\nAutomatic switching on a usage limit: *${this.state.auto ? "on" : "off"}*\n` +
      "Owners: @bot account <letter> (this group) · @bot account default <letter> · @bot account reset · @bot account auto on|off"
    );
  }
}
