// TM-49 (3 Nov, the team: "I don't even understand what is happening in that group, so many messages"). In 24 h the
// group got 46 bot messages and 1 from a person: each request posted 7-13 lines (started, building, resumed after a
// restart, pushed, progress, preview sent, permission blocked…) mixed with every other request's.
//
// The group now gets only what a person needs to read or decide, per request:
//   • the new request (the conversation picture + one short report with the plan)
//   • ✅ live and checked, or ❌ / ⚠️ stuck
//   • 🙋 needs you (an ok, a credential, a decision)
//   • the customer's verdict, and every reply to someone who asked the bot something
// Everything else is the request's history: it goes to that request's log (control panel → Requests, and
// `@bot status`), never to the group. Decided by code from the message itself, so no turn can forget the rule.
// 1-on-1 chats with the bot are untouched.

/** Lines that are work-in-progress, not news: they go to the request's history. */
const HISTORY = [
  /^📥 /u, // "📥 #cf124a · Ilan told Mesiri: … Looking into it now" (the report with the plan follows)
  /^▶️/u, // "▶️ Building [207] … here on the bot's server"
  /^🛠/u, // "🛠 Building [207]: …"
  /^↩️/u, // "↩️ [209] … cut off when the bot restarted. Starting it again"
  /^🔓/u, // "🔓 [210] … isn't held any more; starting it now"
  /^👀/u, // "👀 Preview sent to Ilan …"
  /^⚠️ No preview went/u,
  /^🔐 \*Needs your permission\*\s*\nWhile working I was blocked from/u, // read commands a turn was refused
  /^\[\d+\] pushed [0-9a-f]{7}/u, // "[203] pushed c1f9449 …, deploy green ✅" (the ✅ live line follows)
  /^\[\d+\] progress\b/iu,
  /^\[\d+\] landed but didn't report/u,
  /^\[\d+\] (?:is )?(?:still )?quiet for \d+/iu, // watchdog: "quiet for 30 min"
  /^☁️ Working on \[\d+\]/u,
  /^▶ /u,
];

/** A conversation picture's caption ("[207] Ilan (ADMIN) · Paraclette · …") is context for its report: kept. */
const PLAN_REF = /\[(\d{1,6})\]/u;

/**
 * Where a bot message goes: "group" (people read it) or "history" (the request's log only).
 * @param {{text?: string, caption?: string}} body  what would be sent
 */
export function destination(body) {
  const text = String(body?.text ?? body?.caption ?? "").trimStart();
  if (!text) return "group";
  if (HISTORY.some((re) => re.test(text))) return "history";
  // The production watch's report: posted when it carries a new plan; "nothing new, so no new plan" is history.
  if (/^\*?Production watch:?\*?/iu.test(text) && !/\b(?:[1-9]\d*|one|two|three) new plans?\b/iu.test(text)) return "history";
  return "group";
}

/** The request a message is about, from its "[207]", or null. */
export function planOf(text) {
  const m = String(text || "").match(PLAN_REF);
  return m ? Number(m[1]) : null;
}

/**
 * Wrap the listener's send: group messages that are history go to the request's log instead.
 * @param {(body: object) => Promise<any>} send            the listener's send
 * @param {(id: number, body: object) => Promise<any>} note  the listener's updateItem
 * @param {object} opts  { on: boolean, log: (line) => void }
 */
export function quietSend(send, note, { on = true, log = () => {} } = {}) {
  return async (body) => {
    if (!on || !String(body?.chat || "").endsWith("@g.us") || destination(body) === "group") return send(body);
    const text = String(body.text ?? body.caption ?? "");
    const id = planOf(text);
    log(`quiet: to ${id ? `[${id}]'s history` : "the bot log"}: ${text.slice(0, 160).replace(/\n/g, " ⏎ ")}`);
    if (id) await note(id, { note: `🗒 ${text.slice(0, 900)}`, project: body.project }).catch(() => {});
    return { ok: true, quiet: true };
  };
}
