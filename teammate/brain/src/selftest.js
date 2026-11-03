// TM-37 (asked 2 Nov; 3 Nov: the bot was down all night and a request reached nobody): every morning the whole
// feedback loop is tried for real. The bot's own number sends "mesiri fix it: SELFTEST-…" in the assistant-test chat
// (the team's test company), exactly like a customer would, and the code checks each step:
//   1. Mesiri answers in the chat                          (WhatsApp in, Mesiri up, reply out)
//   2. the team bot receives the request                    (tell_the_team → poke → production watch reads it)
// The watch recognises the SELFTEST token and stops there: no plan, no build, nothing in the group. Only a broken
// step is posted ("🙋 Needs you: … step 2 broken"); a passing check is one line in the evening summary.
// "@bot selftest" runs it now.

import { readFileSync, writeFileSync } from "node:fs";

const IST = 330 * 60_000;
export const SELFTEST_HOUR_IST = 8;
export const TOKEN = /SELFTEST-[0-9]{8}-[a-z0-9]{4}/;
const MS = { reply: 90_000, team: 5 * 60_000 };

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** The SELFTEST conversations taken out of the watch's list (their token is reported as seen); the rest go on. */
export function takeSelfTests(convs, seen) {
  return convs.filter((c) => {
    const m = JSON.stringify(c.messages || c).match(TOKEN);
    if (m) seen(m[0]);
    return !m;
  });
}

export class SelfTest {
  /**
   * @param o.listener  { chats, messages, sendStrict }
   * @param o.notify    (project, text) => post in the team group
   */
  constructor({ listener, projects, notify, file, now = () => Date.now(), log = () => {}, pollMs = 5_000, limits = MS }) {
    Object.assign(this, { listener, projects, notify, file, now, log, pollMs, limits });
    this.arrived = new Map(); // token -> when the team bot received it
  }

  state() {
    try {
      return JSON.parse(readFileSync(this.file, "utf8"));
    } catch {
      return {};
    }
  }

  save(state) {
    writeFileSync(this.file, JSON.stringify(state));
  }

  /** Called by the production watch when a SELFTEST request reaches it. */
  seen(token) {
    if (!this.arrived.has(token)) this.arrived.set(token, this.now());
  }

  /** One check for one project: the result, also kept for the evening summary. Never throws. */
  async run(project) {
    const day = new Date(this.now() + IST).toISOString().slice(0, 10).replace(/-/g, "");
    const token = `SELFTEST-${day}-${Math.random().toString(36).slice(2, 6).padEnd(4, "0")}`;
    const result = { at: new Date(this.now()).toISOString(), token, steps: [] };
    const step = (name, ok, ms, why = "") => result.steps.push({ name, ok, ms, why });
    try {
      const chat = ((await this.listener.chats(project)).chats || []).find((c) => c.role === "assistant-test" && c.project === project);
      if (!chat) {
        step("test chat", false, null, "there is no assistant-test chat for this project");
        return this.finish(project, result);
      }
      const since = new Date(this.now() - 2000).toISOString();
      const sentAt = this.now();
      await this.listener.sendStrict({ chat: chat.jid, project, text: `mesiri fix it: ${token} (the team bot's daily check, please ignore)` });
      let replyAt = null;
      while (this.now() - sentAt < this.limits.team) {
        if (!replyAt) {
          const rows = (await this.listener.messages({ chat: chat.jid, project, since, limit: 20 }).catch(() => ({})))?.messages || [];
          if (rows.some((m) => !m.from_me && m.kind !== "reaction")) replyAt = this.now();
        }
        if (replyAt && this.arrived.has(token)) break;
        if (!replyAt && this.now() - sentAt > this.limits.reply) break; // no answer at all: step 2 can't happen
        await wait(this.pollMs);
      }
      step("Mesiri answered in WhatsApp", Boolean(replyAt), replyAt ? replyAt - sentAt : null,
        replyAt ? "" : `no reply in ${Math.round(this.limits.reply / 1000)} s: Mesiri may be down or not answering this number`);
      const teamAt = this.arrived.get(token) || null;
      if (replyAt) {
        step("the team bot received the request", Boolean(teamAt), teamAt ? teamAt - sentAt : null,
          teamAt ? "" : `not received in ${Math.round(this.limits.team / 60_000)} min: the hand-over from Mesiri (poke) or the production watch is broken`);
      }
    } catch (e) {
      step("sending the test message", false, null, String(e.message).slice(0, 160));
    }
    return this.finish(project, result);
  }

  async finish(project, result) {
    result.ok = result.steps.length > 0 && result.steps.every((s) => s.ok);
    const state = this.state();
    state[project] = result;
    this.save(state);
    this.log(`selftest ${project}: ${result.ok ? "ok" : "BROKEN"} ${result.steps.map((s) => `${s.name}=${s.ok ? `${Math.round((s.ms || 0) / 1000)}s` : "no"}`).join(", ")}`);
    if (!result.ok) {
      const bad = result.steps.find((s) => !s.ok);
      await this.notify(project, `🙋 *Needs you:* the daily check of the feedback loop failed.\n❌ ${bad.name}: ${bad.why}\nUntil it's fixed, what customers report may not reach the team. @bot selftest runs it again.`).catch(() => {});
    }
    return result;
  }

  /** The last result, as one line for the evening summary (or null). */
  line(project) {
    const r = this.state()[project];
    if (!r) return null;
    const when = new Date(Date.parse(r.at) + IST).toISOString().slice(11, 16);
    if (!r.ok) return `• ❌ Feedback loop check (${when}): ${r.steps.find((s) => !s.ok)?.name || "failed"}`;
    return `• ✅ Feedback loop checked at ${when}: ${r.steps.map((s) => `${s.name.replace(/^the /, "")} ${Math.round(s.ms / 1000)} s`).join(", ")}`;
  }

  /** Every 10 min: from 08:00 IST, once a day per project. */
  async maybeRun() {
    const t = new Date(this.now() + IST);
    if (t.getUTCHours() < SELFTEST_HOUR_IST) return 0;
    const today = t.toISOString().slice(0, 10);
    const state = this.state();
    let ran = 0;
    for (const project of this.projects) {
      if (state._ran?.[project] === today) continue;
      (state._ran ||= {})[project] = today;
      this.save(state);
      await this.run(project);
      ran += 1;
    }
    return ran;
  }

  /** "@bot selftest": run it now and answer with the result. */
  async command(req) {
    if (!/^self[\s-]?test$/i.test(String(req.text || "").trim())) return undefined;
    const r = await this.run(req.reply_project || req.project);
    return r.ok ? `✅ Feedback loop works: ${r.steps.map((s) => `${s.name} in ${Math.round(s.ms / 1000)} s`).join("; ")}.` : ""; // a failure is posted by finish()
  }
}
