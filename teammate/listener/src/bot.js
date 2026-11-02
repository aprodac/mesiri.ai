import { istStarts } from "./store.js";

// Tagging the bot (TM-03): approved people @-mention the linked number to ask
// for work; owners also approve / remove people from the group itself.
//
// Rules:
// - Only messages that @-mention the bot, from a chat that belongs to a project.
// - 1-on-1 chats (DMs): an approved person needs no @; unapproved senders are ignored. The project is
//   the one they're approved for, or, if several, the one they name ("mesiri" / "mercon"), remembered
//   for that chat. Replies go back to that DM only; owner-only commands stay in the team group.
// - Commands and replies only in that project's team chat. In customer chats
//   the bot never answers; an approved person's tag there is logged as a
//   request and announced in the team chat instead.
// - Senders who aren't approved are ignored (logged on the server only).
// - Owners approve / remove; members request work and say OK. The first owner
//   is set on the server (inbox.py allow ... --role owner), never by a message.
// - At most REPLIES_PER_HOUR replies, so two bots tagging each other can't loop.
//
// Message text is data: it is stored as the request's title / summary for a
// person to plan from, never executed.

const REPLIES_PER_HOUR = Number(process.env.TEAMMATE_BOT_REPLIES_PER_HOUR || 20);
const TITLE_MAX = 120;

const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
const COST_PERIOD = new RegExp(`\\b(?:today|yesterday|this week|week|this month|last month|month|last \\d{1,3} days|${MONTHS.join("|")})\\b`, "i");
const DAY_MS = 86_400_000;
const IST_MS = 330 * 60_000;

/** "october", "last 7 days", "" (this month) -> { label, since, until } in India days; until null = up to now. */
export function costPeriod(text = "", now = Date.now()) {
  const { day, month } = istStarts(now);
  const today = Date.parse(day);
  const iso = (ms) => new Date(ms).toISOString();
  const local = new Date(now + IST_MS);
  const monthStart = (year, m) => iso(Date.UTC(year, m, 1) - IST_MS);
  const t = String(text).toLowerCase();
  const days = t.match(/last (\d+) days/)?.[1];
  if (t === "today") return { label: "today", since: day, until: null };
  if (t === "yesterday") return { label: "yesterday", since: iso(today - DAY_MS), until: day };
  if (days) return { label: `last ${Number(days)} days`, since: iso(today - (Math.max(Number(days), 1) - 1) * DAY_MS), until: null };
  if (t.endsWith("week")) return { label: "last 7 days", since: iso(today - 6 * DAY_MS), until: null };
  if (t === "last month") return { label: "last month", since: monthStart(local.getUTCFullYear(), local.getUTCMonth() - 1), until: month };
  const named = MONTHS.indexOf(t);
  if (named >= 0) {
    // The most recent such month: in November, "december" is last year's.
    const year = local.getUTCFullYear() - (named > local.getUTCMonth() ? 1 : 0);
    const name = t[0].toUpperCase() + t.slice(1);
    return named === local.getUTCMonth() ? { label: name, since: month, until: null } : { label: `${name} ${year}`, since: monthStart(year, named), until: monthStart(year, named + 1) };
  }
  return { label: "this month", since: month, until: null };
}

const COST_LABELS = {
  run_tools: "Assistant replies",
  extract: "Reading messages",
  decompose: "Splitting messages",
  analyze_image: "Reading photos",
  understand_voice: "Voice notes",
  transcribe: "Voice notes",
  translate: "Translation",
  generate_json: "Structured answers",
  dpr_summary: "DPR summaries",
};
const BOT_LABELS = { translate: "Team bot: voice notes and translation", watch_screen: "Team bot: production watch screen", ci_tests: "Testing: CI runs and evals (estimate)" };
const OTHER_AI = new Set(["deepseek", "sarvam"]);
const COMPANIES_SHOWN = 6;
const DAYS_SHOWN = 7;

const rupees = (n) => `₹${Number(n).toFixed(2)}`;
const calls = (n) => `${n} call${n === 1 ? "" : "s"}`;

/** "@919544376072 approve @9198…" -> { verb: "approve", rest: "…" }; leading mentions dropped. */
export function parseCommand(text) {
  const words = String(text || "").replace(/@\S+/g, " ").trim();
  const [first = "", ...others] = words.split(/\s+/);
  const verb = first.toLowerCase().replace(/[^a-z]/g, "");
  const rest = others.join(" ").trim();
  // Commands only when the whole message is the command (people are @-tagged, so they vanish above):
  // "add a filter to trips" or "ok but change the colour" are requests for Claude, not commands.
  if (verb === "make" && /^owner$/i.test(rest)) return { verb: "owner", rest: "" };
  if (["approve", "allow", "add"].includes(verb) && !rest) return { verb: "approve", rest };
  if (["remove", "disallow", "revoke"].includes(verb) && !rest) return { verb: "remove", rest };
  if (["who", "list"].includes(verb) && !rest) return { verb: "who", rest };
  // TM-19: the request list (counts + numbered), answered by code. "list requests" / "send the list of requests" too.
  if (["requests", "request", "features", "feature", "fixes"].includes(verb) && /^(list|all|open|done|users|asked|waiting|building|live|verified|broken|dropped)?$/i.test(rest)) {
    return { verb: "requests", rest: rest === "list" ? "" : rest.toLowerCase() };
  }
  if (/^(?:send\s+(?:me\s+)?(?:the\s+)?)?list\s+(?:of\s+)?(?:all\s+)?(?:the\s+)?(?:requests|features|fixes)$/i.test(words)) return { verb: "requests", rest: "" };
  if (["help", "commands"].includes(verb) && !rest) return { verb: "help", rest };
  if (["ok", "okay", "approved", "go", "yes"].includes(verb) && /^(\[?#?\d+\]?)?$/.test(rest)) {
    const id = rest.match(/(\d+)/)?.[1];
    return { verb: "ok", id: id ? Number(id) : null, rest };
  }
  // Gemini, on request only: "translate" (reply to the voice note / message, or "translate #123"), "cost".
  if (["translate", "transcribe", "translation"].includes(verb) && /^(this|it|that)?\s*(#?\d+)?$/i.test(rest)) {
    const id = rest.match(/(\d+)/)?.[1];
    return { verb: "translate", id: id ? Number(id) : null, rest };
  }
  // TM-20: "cost", "cost october", "gemini spend last 7 days"; or a question about Gemini spend, not any cost ("cost of steel").
  const period = words.match(COST_PERIOD)?.[0].toLowerCase() || "";
  const bare = new RegExp(`^(?:(?:gemini|ai)\\s+)?(?:cost|costs|spend|spent|usage)(?:\\s+(?:for|in|of))?(?:\\s+${COST_PERIOD.source})?$`, "i");
  const asked = /^(?:how much|what|where|which)\b/i.test(words) && /\b(?:gemini|ai)\b/i.test(words) && /\b(?:cost|costs|spend|spent|spending|bill)\b/i.test(words);
  if (bare.test(words) || asked) return { verb: "cost", rest, period };
  // Upgrading the bot itself (TM-09): "upgrade: make the cost command show yesterday too".
  const up = words.match(/^upgrade\b[\s:,-]*([\s\S]*)$/i);
  if (up) return { verb: "upgrade", rest: up[1].trim() };
  if (!words) return { verb: "help", rest: "" };
  return { verb: "request", rest: words };
}

const HELP = [
  "I pass your messages to Claude Code.",
  "• @me <question or request>, or just reply to one of my messages (no @ needed)",
  "• @me ok <number>: approve a plan",
  "• @me new <name>: start a separate conversation (the others are kept)",
  "• @me sessions / @me switch <name> / @me reset",
  "• send a voice note as a reply to me: it's transcribed (Gemini, ~₹0.10-0.50) and answered",
  "• reply to a voice note with @me translate (or @me translate #123): transcript + English + what it cost",
  "• @me cost: Gemini spend in ₹ by work, company and day · also @me cost today | yesterday | last 7 days | last month | october",
  "• @me upgrade: <what to change in the bot> (owners): plan → @me ok <n> → it updates and redeploys itself",
  "• @me settings: Claude's model and effort · owners: @me model opus|sonnet|haiku|fable, @me effort low…max",
  "• @me account: which Claude account this group runs on (A, B, C…) · owners: @me account <letter> (this group), @me account default <letter>, @me account reset, @me account auto on|off",
  "• @me auto on [hours] (owners): test, fix and verify small Conversation / report issues by itself · @me auto: its state · @me auto off or @me stop (anyone)",
  "• @me watch: the production watch (how often, what it found today) · owners: @me watch 5m|30m|1h|2h, @me watch off|on, @me watch now",
  "• @me requests: everything asked for and where it is (asked, building, live, verified, broken), numbered, with who asked · @me requests open | done | users | all",
  "• @me autobuild: plans start building by themselves, no ok needed (TM-18; Attendance, Payroll, Workforce, data-changing migrations, secrets, tenant isolation, login and the bot itself still wait for @me ok) · owners: @me autobuild on|off",
  "• @me status: the jobs running in the cloud · @me status <n>: one job (commits, deploy, last note) · owners: @me tell <n> <message> starts a follow-up session for job n",
  "• @me who: who is approved here",
  "Owners: @me approve @person · @me remove @person · @me make owner @person",
].join(String.fromCharCode(10));

export class Bot {
  /**
   * @param {{ store: import('./store.js').Store, wa: { ownIds(): string[], pnFor(jid: string): Promise<string|null>, send(jid: string, c: object): Promise<string|null> }, log?: (m: string) => void, onRequest?: (item: object) => void, onApproved?: (item: object, by: string) => void }} opts
   */
  constructor({ store, wa, log = () => {}, onRequest = null, onApproved = null, brain = null, ai = null }) {
    this.ai = ai; // Gemini translation, on request (translate / cost)
    this.store = store;
    this.brain = brain; // TM-03b: { ask(req) } -- Claude Code answers; null = log requests only
    this.wa = wa;
    this.log = log;
    this.onRequest = onRequest;
    this.onApproved = onApproved;
    this.sentAt = [];
  }

  mentionsMe(rec) {
    const mine = new Set(this.wa.ownIds());
    return rec.mentions?.some((j) => mine.has(j)) ?? false;
  }

  /** A reply to one of the bot's own messages counts as talking to it, no @ needed. */
  repliesToMe(rec) {
    return Boolean(rec.quoted_id && this.store.isOwnMessage?.(rec.chat_jid, rec.quoted_id));
  }

  /** Called for every live (not history) message once it is stored as number `n`. */
  async handle(rec, n) {
    if (rec.from_me) return;
    if (!rec.is_group) return this.handleDm(rec, n);
    if (!(this.mentionsMe(rec) || this.repliesToMe(rec))) return;
    const chat = this.store.findChat(rec.chat_jid);
    if (!chat?.project || !["team", "customer"].includes(chat.role)) return;
    const project = chat.project;
    const who = rec.sender_name || (rec.sender_pn || rec.sender_jid || "?").split("@")[0];
    const person = this.store.findPerson(project, [rec.sender_jid, rec.sender_pn]);
    if (!person) {
      this.log(`bot: ignored a tag from ${who} in ${chat.name} (not approved for ${project})`);
      return;
    }
    // A voice note in a team group is never parsed as a command: it can only become a question for Claude.
    const isVoice = (rec.kind === "voice" || rec.kind === "audio") && chat.role === "team" && Boolean(this.brain);
    const cmd = isVoice ? { verb: "request", rest: "" } : parseCommand(rec.text);
    const team = this.store.teamChat(project);
    const owners = ["approve", "remove", "owner"];
    // Answer in the group where it was asked when that's a team group; from a
    // customer group, in the project's team group instead.
    const replyTo = chat.role === "team" ? chat.jid : team?.jid;

    // Translation and its cost: handled here (fast, no Claude), answered in the team group.
    if (cmd.verb === "translate" || cmd.verb === "cost") {
      if (!replyTo) return;
      if (cmd.verb === "cost") {
        this.wa.typing?.(replyTo);
        return this.reply(replyTo, await this.costReply(project, cmd.period));
      }
      const target = cmd.id ?? (rec.quoted_id ? this.store.messageNumber(rec.chat_jid, rec.quoted_id) : null);
      if (!target) return this.reply(replyTo, "Reply to the voice note (or message) with @bot translate, or write @bot translate #123.");
      if (!this.ai?.translate) return this.reply(replyTo, "Translation is off (no Gemini key on the server).");
      if (this.store.getMessage(target)?.chat_project !== project) return this.reply(replyTo, `#${target} isn't in this project.`);
      this.wa.typing?.(replyTo);
      try {
        const r = await this.ai.translate(target);
        return this.reply(replyTo, this.translationText(r));
      } catch (e) {
        return this.reply(replyTo, `⚠️ Couldn't translate #${target}: ${String(e.message || e).slice(0, 200)}`);
      }
    }

    // TM-19: the request list, by code (no Claude turn), in the team group.
    if (cmd.verb === "requests") {
      if (!replyTo) return;
      return this.reply(replyTo, this.store.requestsText(project, cmd.rest));
    }

    // TM-09: owners plan upgrades to the bot itself, in the bot's own repo.
    if (cmd.verb === "upgrade") {
      if (!this.brain || !replyTo) return this.reply(replyTo, "Upgrades from WhatsApp aren't switched on.");
      if (person.role !== "owner") return this.reply(replyTo, "Only an owner can upgrade the bot.");
      this.wa.typing?.(replyTo);
      this.log(`bot: ${who} asked for a bot upgrade in ${chat.name}`);
      return this.brain.ask({
        project, upgrade: true, session: "upgrade", chat: chat.jid, chat_name: chat.name, chat_role: chat.role, reply_chat: replyTo,
        sender: who, sender_role: person.role, n, text: cmd.rest || "What could be improved in the bot? Suggest a few upgrades.",
        quoted_text: rec.quoted_text || null, quoted_id: null,
      });
    }

    // TM-03b: everything except the approval commands goes to Claude Code, whose
    // answer lands in the team group. Customer groups still never get a reply.
    // An ok approves a plan: only in the team group, and the brain runs that plan's working turn.
    if (this.brain && team && cmd.verb === "ok") {
      if (chat.role !== "team") return;
      this.wa.typing?.(replyTo);
      this.log(`bot: ${who} approved ${cmd.id ?? "the pending plan"} in ${chat.name}`);
      return this.brain.approve({ project, item_id: cmd.id, by: who, reply_chat: replyTo, sender_role: person.role });
    }
    if (isVoice) {
      if (!this.ai?.translate) return this.reply(replyTo, "Voice notes need translation, which is off on the server.");
      this.wa.typing?.(replyTo);
      let r;
      try {
        r = await this.ai.translate(n);
      } catch (e) {
        return this.reply(replyTo, `⚠️ Couldn't understand the voice note: ${String(e.message || e).slice(0, 200)}`);
      }
      const english = String(r.translation || r.transcript || "").trim();
      if (!english) return this.reply(replyTo, "⚠️ Couldn't understand the voice note: nothing was heard.");
      const inr = r.cost ? ` · ₹${r.cost.inr.toFixed(2)}` : "";
      await this.reply(replyTo, `🗣 Heard: "${english.slice(0, 500)}"${inr}`);
      const original = r.transcript && r.translation && r.transcript !== r.translation
        ? ` (original${r.language ? `, ${r.language}` : ""}: ${r.transcript})` : "";
      this.log(`bot: ${who} in ${chat.name} -> Claude (voice note)`);
      return this.brain.ask({
        project, chat: chat.jid, chat_name: chat.name, chat_role: chat.role, reply_chat: replyTo,
        sender: who, sender_role: person.role, n, text: english + original, quoted_text: rec.quoted_text || null, quoted_id: rec.quoted_id || null,
      });
    }
    if (this.brain && team && ![...owners, "who", "help"].includes(cmd.verb)) {
      const text = String(rec.text || "").replace(/@\S+/g, " ").replace(/\s+/g, " ").trim() || "help";
      this.wa.typing?.(replyTo);
      this.log(`bot: ${who} in ${chat.name} -> Claude`);
      return this.brain.ask({
        project, chat: chat.jid, chat_name: chat.name, chat_role: chat.role, reply_chat: replyTo,
        sender: who, sender_role: person.role, n, text, quoted_text: rec.quoted_text || null, quoted_id: rec.quoted_id || null,
      });
    }

    if (chat.role === "customer") {
      // Never answer in a customer group: log it, tell the team.
      if (cmd.verb !== "request") return;
      const item = this.logRequest(rec, n, chat, cmd.rest, who);
      if (team) await this.reply(team.jid, `📝 Request [${item.id}] from ${who} in ${chat.name}: ${item.title}`);
      return;
    }

    if (owners.includes(cmd.verb) && person.role !== "owner") {
      return this.reply(chat.jid, `Only an owner can ${cmd.verb === "owner" ? "make owners" : `${cmd.verb} people`}.`);
    }
    if (owners.includes(cmd.verb)) return this.changePeople(rec, chat, cmd.verb, who);
    if (cmd.verb === "who") return this.reply(chat.jid, this.whoText(project));
    if (cmd.verb === "help") return this.reply(chat.jid, HELP);
    if (cmd.verb === "ok") return this.approve(chat, cmd.id, who);
    const item = this.logRequest(rec, n, chat, cmd.rest, who);
    const next = this.onRequest ? "Claude Code will post a plan here; reply @me ok " + item.id + " to go ahead." : "Logged for Claude Code (automatic start isn't switched on yet).";
    return this.reply(chat.jid, `📝 Request [${item.id}]: ${item.title}\n${next}`);
  }

  /** A 1-on-1 message: answered only when the sender is approved, only in that chat. */
  async handleDm(rec, n) {
    if (!this.brain) return;
    const chat = this.store.findChat(rec.chat_jid);
    // Only plain, unlabelled chats: never the assistant-test chat, customers or ignored chats.
    if (!chat || chat.is_group || chat.role !== "unlabelled") return;
    if (!["text", "image"].includes(rec.kind)) return;
    const ids = [rec.sender_jid, rec.sender_pn];
    const approvals = this.store.personProjects(ids);
    const who = rec.sender_name || (rec.sender_pn || rec.sender_jid || "?").split("@")[0];
    if (!approvals.length) {
      this.log(`bot: ignored a direct message from ${who} (not approved for any project)`);
      return;
    }
    const text = String(rec.text || "").replace(/\s+/g, " ").trim();
    const known = this.store.teamProjects();
    // Projects this person may use: their own, or every project with a team chat for '*'.
    const mine = approvals.some((a) => a.project === "*") ? known : approvals.map((a) => a.project).filter((p) => known.includes(p));
    if (!mine.length) {
      this.log(`bot: ignored a direct message from ${who} (no team chat for their projects)`);
      return;
    }
    const say = (t) => this.reply(chat.jid, t, [], true);
    const wanted = text.toLowerCase().match(/^(?:(?:project|use|switch to)\s+)?([a-z0-9][a-z0-9_-]*)$/)?.[1];
    if (wanted && mine.includes(wanted) && (mine.length > 1 || chat.project !== wanted)) {
      this.store.setChatProject(chat.jid, wanted);
      return say(`👍 Using *${wanted}* in this chat. Go ahead. (Say "project <name>" to change it.)`);
    }
    let project = mine.length === 1 ? mine[0] : mine.includes(chat.project) ? chat.project : null;
    if (!project) return say(`Which project is this about? Reply with one of: ${mine.map((p) => `"${p}"`).join(" / ")}.`);
    if (chat.project !== project) this.store.setChatProject(chat.jid, project);

    const person = this.store.findPerson(project, ids);
    const team = this.store.teamChat(project);
    const cmd = parseCommand(text);
    if (["approve", "remove", "owner", "upgrade", "translate", "cost"].includes(cmd.verb)) {
      return say("That one works in the team group only.");
    }
    if (cmd.verb === "who") return say(this.whoText(project));
    if (cmd.verb === "help") return say(HELP);
    if (cmd.verb === "requests") return say(this.store.requestsText(project, cmd.rest)); // TM-19
    // 'ok <n>' approves a plan of the project this person is approved for; the working turn reports back here.
    if (cmd.verb === "ok") {
      if (!team) return;
      this.wa.typing?.(chat.jid);
      this.log(`bot: ${who} approved ${cmd.id ?? "the pending plan"} in a direct message (${project})`);
      return this.brain.approve({ project, item_id: cmd.id, by: who, reply_chat: chat.jid, sender_role: person.role, dm: true });
    }
    this.wa.typing?.(chat.jid);
    this.log(`bot: ${who} in a direct message (${project}) -> Claude`);
    return this.brain.ask({
      project, chat: chat.jid, chat_name: chat.name || who, chat_role: "dm", reply_chat: chat.jid, dm: true,
      sender: who, sender_role: person.role, n, text: text || "help", quoted_text: rec.quoted_text || null, quoted_id: rec.quoted_id || null,
    });
  }

  logRequest(rec, n, chat, text, who) {
    const quoted = rec.quoted_id ? this.store.messageNumber(rec.chat_jid, rec.quoted_id) : null;
    const title = text.length > TITLE_MAX ? `${text.slice(0, TITLE_MAX - 1)}…` : text;
    const id = this.store.addItem({
      chat_jid: chat.jid,
      type: "task",
      title,
      summary: [text.length > TITLE_MAX ? text : null, rec.quoted_text ? `About: "${rec.quoted_text.slice(0, 300)}"` : null]
        .filter(Boolean)
        .join("\n") || null,
      source: [quoted, n].filter(Boolean).join(","),
      created_by: `${who} (WhatsApp)`,
    });
    const item = this.store.getItem(id);
    this.log(`bot: request [${id}] from ${who} in ${chat.name}`);
    this.onRequest?.(item);
    return item;
  }

  async changePeople(rec, chat, verb, who) {
    const mine = new Set(this.wa.ownIds());
    const targets = (rec.mentions || []).filter((j) => !mine.has(j));
    if (!targets.length) return this.reply(chat.jid, "Tag the person too, e.g. @me approve @Name.");
    const done = [];
    for (const jid of targets) {
      const pn = jid.endsWith("@s.whatsapp.net") ? jid : await this.wa.pnFor(jid).catch(() => null);
      const label = `@${(pn || jid).split("@")[0]}`;
      if (verb === "remove") {
        const removed = this.store.removePerson(chat.project, [jid, pn], who);
        done.push(removed ? `removed ${label}` : `${label} wasn't approved`);
      } else {
        this.store.allowPerson({ project: chat.project, jid, pn, role: verb === "owner" ? "owner" : "member", added_by: who });
        done.push(verb === "owner" ? `${label} is now an owner` : `approved ${label}`);
      }
    }
    this.log(`bot: ${who} in ${chat.name}: ${done.join("; ")}`);
    return this.reply(chat.jid, `✅ ${done.join("; ")} (${chat.project})`, targets);
  }

  approve(chat, id, who) {
    const open = this.store.listItems({ project: chat.project }).filter((i) => i.status === "open" || i.status === "in_progress");
    const item = id ? open.find((i) => i.id === id) : open.length === 1 ? open[0] : null;
    if (!item) {
      const hint = open.length ? `Which one? ${open.slice(0, 5).map((i) => `[${i.id}]`).join(" ")}` : "Nothing is waiting.";
      return this.reply(chat.jid, `Say @me ok <number>. ${hint}`);
    }
    const updated = this.store.updateItem(item.id, { status: "in_progress", note: `OK from ${who} in ${chat.name}` });
    this.onApproved?.(updated, who);
    return this.reply(chat.jid, `👍 [${item.id}] approved by ${who}. ${this.onApproved ? "Starting." : "Logged; a Claude Code session will pick it up."}`);
  }

  translationText(r) {
    const lines = [`🗣 #${r.n}${r.language ? ` (${r.language})` : ""}`];
    if (r.transcript) lines.push(`"${r.transcript}"`);
    if (r.translation && r.translation !== r.transcript) lines.push(`⇒ EN: ${r.translation}`);
    if (!r.transcript && !r.translation) lines.push("(it's already in English)");
    lines.push(r.cost
      ? `💰 ₹${r.cost.inr.toFixed(2)} · ${r.cost.input_tokens.toLocaleString("en-IN")} in / ${r.cost.output_tokens.toLocaleString("en-IN")} out tokens · ${r.cost.model}`
      : "💰 already translated before, no new cost");
    return lines.join(String.fromCharCode(10)).slice(0, 3900);
  }

  /** TM-20: production's spend (through the brain) plus the bot's own. A production read failing still shows the bot's. */
  async costReply(project, text) {
    const period = costPeriod(text);
    let rows = null;
    let failed = null;
    if (this.brain?.cost) {
      try {
        rows = await this.brain.cost({ project, since: period.since, until: period.until });
      } catch (e) {
        failed = String(e.message || e).slice(0, 120);
      }
    }
    return this.costText(project, period, rows, failed);
  }

  costText(project, period, rows, failed = null) {
    const nl = String.fromCharCode(10);
    const section = (name) => (rows || []).filter((r) => r.section === name);
    const bot = this.store.aiUsageByKind(period.since, project, period.until || undefined);
    const work = section("work").filter((r) => !OTHER_AI.has(r.name));
    const lines = [
      ...work.map((r) => ({ label: COST_LABELS[r.name] || r.name, inr: r.inr, calls: r.calls })),
      ...bot.map((r) => ({ label: BOT_LABELS[r.kind] || `Team bot: ${r.kind}`, inr: r.inr, calls: r.calls })),
    ];
    // Two operations can share a label (the voice ones).
    const merged = new Map();
    for (const l of lines) {
      const have = merged.get(l.label) || { label: l.label, inr: 0, calls: 0 };
      merged.set(l.label, { ...have, inr: have.inr + Number(l.inr), calls: have.calls + Number(l.calls) });
    }
    const byWork = [...merged.values()].sort((a, b) => b.inr - a.inr);
    const total = byWork.reduce((sum, l) => sum + l.inr, 0);
    const out = [`💰 Gemini spend · ${project} · ${period.label}`, `Total: ${rupees(total)} · ${calls(byWork.reduce((sum, l) => sum + l.calls, 0))}`];
    if (byWork.length) out.push("", "*By work*", ...byWork.map((l) => `• ${l.label}: ${rupees(l.inr)} · ${calls(l.calls)}`));
    const companies = section("company").sort((a, b) => b.inr - a.inr);
    if (companies.length) {
      const name = (r) => r.name || "No company (signups, scheduled jobs)";
      out.push("", "*By company (production)*", ...companies.slice(0, COMPANIES_SHOWN).map((r) => `• ${name(r)}: ${rupees(r.inr)} · ${calls(r.calls)}`));
      if (companies.length > COMPANIES_SHOWN) out.push(`• and ${companies.length - COMPANIES_SHOWN} more`);
    }
    const days = section("day").sort((a, b) => String(b.name).localeCompare(String(a.name)));
    if (days.length > 1) {
      out.push("", "*By day (production)*", ...days.slice(0, DAYS_SHOWN).map((r) => `• ${r.name}: ${rupees(r.inr)}`));
      if (days.length > DAYS_SHOWN) out.push(`• and ${days.length - DAYS_SHOWN} earlier days`);
    }
    const other = section("work").filter((r) => OTHER_AI.has(r.name));
    if (other.length) out.push("", `Other AI, not in the total: ${other.map((r) => `${r.name} ${rupees(r.inr)}`).join(" · ")}`);
    const unpriced = section("unpriced");
    if (unpriced.length) {
      const n = unpriced.reduce((sum, r) => sum + Number(r.calls), 0);
      out.push("", `⚠️ ${calls(n)} on ${unpriced.map((r) => r.name || "an unknown model").join(", ")} ${n === 1 ? "has" : "have"} no price yet, so the total is short.`);
    }
    if (failed) out.push("", `⚠️ Couldn't read production (${failed}): this is the team bot's spend only.`);
    else if (rows === null) out.push("", "Production isn't connected for this project: this is the team bot's spend only.");
    out.push("", "Not counted: tests run on people's own computers. Google's billing page is the exact bill.");
    return out.join(nl).slice(0, 3900);
  }

  whoText(project) {
    const people = this.store.listPeople(project);
    if (!people.length) return `Nobody is approved for ${project} yet.`;
    const line = (p) => `• ${p.name || "@" + (p.pn || p.jid).split("@")[0]}${p.role === "owner" ? " (owner)" : ""}`;
    return `Approved for ${project}:\n${people.map(line).join("\n")}`;
  }

  /** Replies only into team chats (and, when `dm`, an approved person's own chat), at most REPLIES_PER_HOUR an hour. */
  async reply(jid, text, mentions = [], dm = false) {
    const chat = this.store.findChat(jid);
    if (chat?.role !== "team" && !(dm && chat && !chat.is_group && chat.role === "unlabelled")) return null;
    const hourAgo = Date.now() - 3_600_000;
    while (this.sentAt.length && this.sentAt[0] < hourAgo) this.sentAt.shift();
    if (this.sentAt.length >= REPLIES_PER_HOUR) {
      this.log("bot: reply limit reached; not answering");
      return null;
    }
    this.sentAt.push(Date.now());
    try {
      return await this.wa.send(jid, { text, mentions });
    } catch (e) {
      this.log(`bot: reply failed: ${e.message || e}`);
      return null;
    }
  }
}
