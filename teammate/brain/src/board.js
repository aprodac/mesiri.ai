// TM-49: the whole picture in one message, from the request log (no AI turn, so it works under a usage limit).
//   "@bot status"  every open request: where it is and whether it waits for someone
//   every evening (19:00 IST) the day in four lines, in each team group: what came in, what is live and confirmed,
//   what is being built, what needs you.
// The group no longer gets each step (quiet.js); this is where a person sees them all at once.

import { readFileSync, writeFileSync } from "node:fs";

const IST = 330 * 60_000;
export const EVENING_HOUR_IST = 19;

/** Where a request is, in plain words, and whether a person must act. */
export function stageOf(item) {
  if (item.status === "wont_do") return { key: "dropped", text: "dropped" };
  if (item.verified === "broken") return { key: "broken", text: "❌ live but still broken", you: false };
  if (item.status === "done" || item.verified === "ok") {
    return item.verified === "ok" ? { key: "confirmed", text: "✅ live and checked" } : { key: "live", text: "✅ live" };
  }
  // TM-60: a cap is not a question for anyone: it waits until tomorrow, or an ok builds it now.
  if (item.held && /automatic builds are used|autobuild is off|usage limit|daily limit/i.test(item.held)) {
    return { key: "waiting", text: `⏸ waiting: ${String(item.held).slice(0, 80)} (@bot ok ${item.id} builds it now)`, you: false, capped: true };
  }
  if (item.held) return { key: "waiting", text: `🙋 waiting for you (${String(item.held).slice(0, 100)})`, you: true };
  if (item.live_at) return { key: "live", text: "✅ live, being checked" };
  if (item.pushed_at) return { key: "deploying", text: "🚀 going live" };
  if (item.status === "in_progress" || item.started_at) return { key: "building", text: "🛠 being built" };
  return { key: "asked", text: "📝 planned, not started" };
}

/**
 * TM-67: the requests that re-open an earlier one ("[213] still broken", "[210] follow-up", "RE-OPENS [209]",
 * "[212] never reached main", "[207]/[211] were never built"): the numbers of the earlier requests they re-open.
 */
const REOPEN = /(?:\[(\d+)\](?:\s*\/\s*\[\d+\])*\s*(?:is\s+|was\s+|were\s+)?(?:still\b|follow[- ]?up|never\b|closed without|marked done but|not (?:fixed|working|live))|(?:re-?opens?|follow[- ]?up to|still broken after|still wrong after)\s*\[(\d+)\])/gi;
export function reopens(item) {
  const text = `${item.title || ""}\n${String(item.summary || "").slice(0, 400)}`;
  const ids = new Set();
  for (const m of text.matchAll(REOPEN)) {
    const lead = m[0].match(/^((?:\[\d+\]\s*\/?\s*)+)/);
    for (const n of lead ? lead[1].match(/\d+/g) : [m[2]]) if (n && Number(n) !== item.id) ids.add(Number(n));
  }
  return [...ids];
}

/**
 * TM-67: "fixed in one round". Of the requests first made since `from` (not bot upgrades, not themselves a re-open)
 * that went live or were re-opened, those nobody had to re-open and no live or real-use check found broken.
 * @returns {{ right: number, total: number, missed: number[] }}
 */
export function firstTimeRight(items, from) {
  const reopened = new Set(items.flatMap(reopens));
  const at = (v) => (v ? Date.parse(v) : NaN);
  const base = items.filter((i) => at(i.created_at) >= from && !/^\[bot upgrade\]/i.test(i.title || "") && !reopens(i).length
    && (i.live_at || reopened.has(i.id)) && !(i.status === "wont_do" && !reopened.has(i.id)));
  const wrong = base.filter((i) => reopened.has(i.id) || i.verified === "broken" || i.verified === "in_use_broken");
  return { right: base.length - wrong.length, total: base.length, missed: wrong.map((i) => i.id) };
}

/** "First time right: 3 of 5 (60%) · re-opened: [207] [210]" or null when nothing shipped. */
export function firstTimeRightLine(items, from) {
  const f = firstTimeRight(items, from);
  if (!f.total) return null;
  return `First time right: ${f.right} of ${f.total} (${Math.round((100 * f.right) / f.total)}%)${f.missed.length ? ` · needed another round: ${f.missed.slice(0, 8).map((n) => `[${n}]`).join(" ")}` : ""}`;
}

const day = (iso, now) => Boolean(iso) && new Date(new Date(iso).getTime() + IST).toISOString().slice(0, 10) === new Date(now + IST).toISOString().slice(0, 10);
const who = (item) => (item.asked_by ? ` · asked by ${String(item.asked_by).split(/[,(]/)[0].trim()}` : "");
const title = (item) => String(item.title || "").replace(/^\[bot upgrade\]\s*/i, "bot: ").slice(0, 90);

/** "@bot status": open requests first those that need someone, then the rest by number. */
export function boardText(items, now = Date.now()) {
  const open = items.filter((i) => i.status === "open" || i.status === "in_progress" || i.verified === "broken");
  const doneToday = items.filter((i) => (i.status === "done" || i.verified === "ok") && i.verified !== "broken" && day(i.updated_at, now));
  if (!open.length && !doneToday.length) return "Nothing open. Every request is done.";
  const order = { waiting: 0, broken: 1, building: 2, deploying: 3, live: 4, asked: 5 };
  const rows = open
    .map((i) => ({ i, s: stageOf(i) }))
    .sort((a, b) => (order[a.s.key] ?? 9) - (order[b.s.key] ?? 9) || a.i.id - b.i.id)
    .slice(0, 15)
    .map(({ i, s }) => `• [${i.id}] ${title(i)}${who(i)}\n   ${s.text}`);
  const needs = open.filter((i) => stageOf(i).you).length;
  return [
    `*Open requests: ${open.length}*${needs ? ` · 🙋 ${needs} need${needs === 1 ? "s" : ""} you` : ""}`,
    ...rows,
    ...(doneToday.length ? [`\n_Done today:_ ${doneToday.map((i) => `[${i.id}]`).join(" ")}`] : []),
    "\n@bot status <n> shows one request's whole story.",
  ].join("\n");
}

/** The evening summary: today's requests in four lines. null when nothing happened today. */
export function eveningText(items, now = Date.now()) {
  const came = items.filter((i) => day(i.created_at, now));
  const live = items.filter((i) => day(i.live_at, now) || (i.status === "done" && day(i.updated_at, now)));
  const confirmed = live.filter((i) => i.verified === "ok");
  const building = items.filter((i) => ["building", "deploying"].includes(stageOf(i).key));
  const needs = items.filter((i) => (i.status === "open" || i.status === "in_progress") && stageOf(i).you);
  const broken = items.filter((i) => i.verified === "broken" && i.status !== "done" && i.status !== "wont_do");
  if (!came.length && !live.length && !needs.length && !broken.length) return null;
  const ids = (list) => (list.length ? ` (${list.slice(0, 8).map((i) => `[${i.id}]`).join(" ")})` : "");
  return [
    "*Today with Mesiri*",
    `• ${came.length} new request${came.length === 1 ? "" : "s"}${ids(came)}`,
    `• ✅ ${live.length} went live${ids(live)}, ${confirmed.length} confirmed by a real use`,
    `• 🛠 ${building.length} being built${ids(building)}`,
    needs.length || broken.length
      ? `• 🙋 Needs you: ${[...needs.map((i) => `[${i.id}] ${title(i)} (reply @bot ok ${i.id})`), ...broken.map((i) => `[${i.id}] still broken`)].join("; ")}`
      : "• 🙋 Nothing needs you",
    ...(() => {
      // TM-67: the last 7 days, so one day's two requests don't swing it.
      const line = firstTimeRightLine(items, now - 7 * 86_400_000);
      return line ? [`• 🎯 ${line} (7 days)`] : [];
    })(),
    "@bot status for the details.",
  ].join("\n");
}

export class Evening {
  /** @param {{projects: string[], items: (p) => Promise<object[]>, notify: (p, text) => Promise<any>, file: string, now?: () => number, log?: Function}} o */
  constructor({ projects, items, notify, file, now = () => Date.now(), log = () => {}, loopLine = () => null }) {
    Object.assign(this, { projects, items, notify, file, now, log, loopLine });
  }

  state() {
    try {
      return JSON.parse(readFileSync(this.file, "utf8"));
    } catch {
      return {};
    }
  }

  /** Called every 10 min: from 19:00 IST, once a day per project. Never throws. */
  async maybeSend() {
    const t = new Date(this.now() + IST);
    if (t.getUTCHours() < EVENING_HOUR_IST) return 0;
    const today = t.toISOString().slice(0, 10);
    const state = this.state();
    let sent = 0;
    for (const project of this.projects) {
      if (state[project] === today) continue;
      try {
        const text = eveningText(await this.items(project), this.now());
        const loop = this.loopLine(project); // TM-37: this morning's check of the feedback loop
        if (text) await this.notify(project, loop ? text.replace(/\n@bot status/, `\n${loop}\n@bot status`) : text);
        state[project] = today;
        writeFileSync(this.file, JSON.stringify(state));
        sent += text ? 1 : 0;
      } catch (e) {
        this.log(`evening ${project}: ${e.message}`);
      }
    }
    return sent;
  }
}

/**
 * TM-60 (3 Nov: a 🙋 is posted once; unanswered, it sinks under everything else). Every 10 min, between 09:00 and
 * 21:00 IST: at 09:00 the morning list of what waits on someone (if anything does), and once more for any request that
 * has waited on someone for 3 hours since the last reminder. Never at night, never twice in 6 hours for one request.
 */
export class Reminders {
  constructor({ projects, items, notify, file, now = () => Date.now(), log = () => {}, afterMs = 3 * 3600_000, againMs = 6 * 3600_000 }) {
    Object.assign(this, { projects, items, notify, file, now, log, afterMs, againMs });
  }

  state() {
    try {
      return JSON.parse(readFileSync(this.file, "utf8"));
    } catch {
      return {};
    }
  }

  async tick() {
    const t = new Date(this.now() + IST);
    const hour = t.getUTCHours();
    if (hour < 9 || hour >= 21) return 0;
    const today = t.toISOString().slice(0, 10);
    const state = this.state();
    let sent = 0;
    for (const project of this.projects) {
      try {
        const waiting = (await this.items(project)).filter((i) => (i.status === "open" || i.status === "in_progress") && stageOf(i).you);
        const s = (state[project] ||= { morning: null, reminded: {} });
        if (s.morning !== today) {
          s.morning = today;
          if (waiting.length) {
            await this.notify(project, `*Good morning. Waiting on you:*\n${waiting.map((i) => `• [${i.id}] ${title(i)}: ${String(i.held).slice(0, 120)}`).join("\n")}\n@bot status for everything open.`);
            for (const i of waiting) s.reminded[i.id] = this.now();
            sent += 1;
          }
        }
        const due = waiting.filter((i) => this.now() - Date.parse(i.updated_at || i.created_at) >= this.afterMs
          && this.now() - (s.reminded[i.id] || 0) >= this.againMs);
        if (due.length) {
          await this.notify(project, `🙋 *Still waiting on you:*\n${due.map((i) => `• [${i.id}] ${title(i)}: ${String(i.held).slice(0, 120)}`).join("\n")}`);
          for (const i of due) s.reminded[i.id] = this.now();
          sent += 1;
        }
        writeFileSync(this.file, JSON.stringify(state));
      } catch (e) {
        this.log(`reminders ${project}: ${e.message}`);
      }
    }
    return sent;
  }
}
