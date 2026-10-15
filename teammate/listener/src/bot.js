import { istStarts } from "./store.js";

// Tagging the bot (TM-03): approved people @-mention the linked number to ask
// for work; owners also approve / remove people from the group itself.
//
// Rules:
// - Only messages that @-mention the bot, from a chat that belongs to a project.
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
  if (/^(gemini\s+)?(cost|costs|spend|usage)(\s+(today|month|this month))?$/i.test(words)) return { verb: "cost", rest };
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
  "• @me cost: Gemini spend today and this month, in ₹",
  "• @me upgrade: <what to change in the bot> (owners): plan → @me ok <n> → it updates and redeploys itself",
  "• @me settings: Claude's model and effort · owners: @me model opus|sonnet|haiku|fable, @me effort low…max",
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
    if (rec.from_me || !rec.is_group || !(this.mentionsMe(rec) || this.repliesToMe(rec))) return;
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
      if (cmd.verb === "cost") return this.reply(replyTo, this.costText(project));
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

  costText(project) {
    const { day, month } = istStarts();
    const t = this.store.aiUsageSince(day, project);
    const mo = this.store.aiUsageSince(month, project);
    const rate = this.ai?.transcriber?.prices?.usdInr;
    return [
      `💰 Gemini spend (${project})`,
      `• Today: ₹${t.inr.toFixed(2)} · ${t.calls} call(s)`,
      `• This month: ₹${mo.inr.toFixed(2)} · ${mo.calls} call(s)`,
      rate ? `Prices: $${this.ai.transcriber.prices.priceIn} in / $${this.ai.transcriber.prices.priceOut} out per 1M tokens, ₹${rate} = $1` : "",
    ].filter(Boolean).join(String.fromCharCode(10));
  }

  whoText(project) {
    const people = this.store.listPeople(project);
    if (!people.length) return `Nobody is approved for ${project} yet.`;
    const line = (p) => `• ${p.name || "@" + (p.pn || p.jid).split("@")[0]}${p.role === "owner" ? " (owner)" : ""}`;
    return `Approved for ${project}:\n${people.map(line).join("\n")}`;
  }

  /** Replies only into team chats, at most REPLIES_PER_HOUR an hour. */
  async reply(jid, text, mentions = []) {
    const chat = this.store.findChat(jid);
    if (chat?.role !== "team") return null;
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
