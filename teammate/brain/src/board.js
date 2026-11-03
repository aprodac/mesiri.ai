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
  if (item.held) return { key: "waiting", text: `🙋 waiting for your ok (${String(item.held).slice(0, 80)})`, you: true };
  if (item.live_at) return { key: "live", text: "✅ live, being checked" };
  if (item.pushed_at) return { key: "deploying", text: "🚀 going live" };
  if (item.status === "in_progress" || item.started_at) return { key: "building", text: "🛠 being built" };
  return { key: "asked", text: "📝 planned, not started" };
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
