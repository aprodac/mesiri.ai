// Turns one Baileys WAMessage into the flat record the inbox stores.
// Pure: no I/O, so it is tested directly against hand-built messages.

import { getContentType, normalizeMessageContent } from "@whiskeysockets/baileys";

// Wrapper/plumbing message types that carry nothing a person wrote.
const IGNORED_TYPES = new Set([
  "protocolMessage", // deletes, edits, ephemeral settings
  "senderKeyDistributionMessage",
  "messageContextInfo",
]);

const KIND_BY_TYPE = {
  conversation: "text",
  extendedTextMessage: "text",
  imageMessage: "image",
  videoMessage: "video",
  audioMessage: "audio",
  documentMessage: "document",
  documentWithCaptionMessage: "document",
  stickerMessage: "sticker",
  reactionMessage: "reaction",
  locationMessage: "location",
  liveLocationMessage: "location",
  contactMessage: "contact",
  contactsArrayMessage: "contact",
  pollCreationMessage: "poll",
  pollCreationMessageV2: "poll",
  pollCreationMessageV3: "poll",
  listMessage: "interactive",
  buttonsMessage: "interactive",
  interactiveMessage: "interactive",
  templateMessage: "interactive",
};

export const MEDIA_KINDS = new Set(["image", "video", "audio", "document"]);

function textOf(content, type) {
  const m = content[type];
  if (type === "conversation") return content.conversation;
  if (!m || typeof m !== "object") return null;
  if (m.text) return m.text;
  if (m.caption) return m.caption;
  if (type === "documentWithCaptionMessage") {
    const inner = m.message?.documentMessage;
    return inner?.caption || inner?.fileName || null;
  }
  if (m.fileName) return m.fileName;
  if (m.name) return m.name; // poll question, location name
  if (m.displayName) return m.displayName; // contact card
  return null;
}

const clean = (v) => (typeof v === "string" && v.trim() ? v.trim() : null);

function parseJson(raw) {
  try {
    const v = JSON.parse(raw);
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

/**
 * The menu/button shapes a business account sends: a list, reply buttons, a
 * native-flow interactive (quick_reply / single_select) or a template. Returns
 * the body lines and the options a person could tap, numbered from 1. Unknown
 * shapes give the body only (or nothing) and never throw.
 * @returns {{ body: string | null, options: Array<{n: number, id: string, title: string, type: "list"|"button"|"native_flow", name?: string}> }}
 */
export function parseInteractive(type, m) {
  const parts = [];
  const options = [];
  const add = (id, title, kind, name) => {
    const t = clean(title);
    const i = clean(String(id ?? "")) ?? t;
    if (t && i) options.push({ n: options.length + 1, id: i, title: t, type: kind, ...(name ? { name } : {}) });
  };
  try {
    if (type === "listMessage") {
      parts.push(m.title, m.description, m.footerText);
      for (const s of m.sections || []) for (const r of s?.rows || []) add(r?.rowId, r?.title, "list");
    } else if (type === "buttonsMessage") {
      parts.push(m.text, m.contentText, m.footerText);
      for (const b of m.buttons || []) add(b?.buttonId, b?.buttonText?.displayText, "button");
    } else if (type === "interactiveMessage") {
      parts.push(m.header?.title, m.header?.subtitle, m.body?.text, m.footer?.text);
      for (const b of m.nativeFlowMessage?.buttons || []) {
        const p = parseJson(b?.buttonParamsJson);
        if (b?.name === "single_select") {
          for (const s of p.sections || []) for (const r of s?.rows || []) add(r?.id, r?.title, "native_flow", b.name);
        } else if (b?.name === "quick_reply") {
          add(p.id, p.display_text, "native_flow", b.name);
        }
      }
    } else if (type === "templateMessage") {
      const t = m.hydratedTemplate || m.hydratedFourRowTemplate || {};
      parts.push(t.hydratedTitleText, t.hydratedContentText, t.hydratedFooterText);
      for (const b of t.hydratedButtons || []) {
        if (b?.quickReplyButton) add(b.quickReplyButton.id, b.quickReplyButton.displayText, "button");
      }
    }
  } catch {
    // an odd shape: fall back to whatever body was read
  }
  const body = parts.map(clean).filter(Boolean).join("\n") || null;
  return { body, options };
}

function quotedText(quoted) {
  if (!quoted) return null;
  const content = normalizeMessageContent(quoted);
  const type = content && getContentType(content);
  return type ? textOf(content, type) : null;
}

function toIso(ts) {
  // messageTimestamp is seconds, as a number or a Long.
  const seconds = typeof ts === "object" && ts !== null ? Number(ts.toString()) : Number(ts);
  return new Date((Number.isFinite(seconds) && seconds > 0 ? seconds : Date.now() / 1000) * 1000).toISOString();
}

/**
 * @returns {null | {
 *   id: string, chat_jid: string, is_group: boolean, sender_jid: string | null,
 *   sender_pn: string | null, sender_name: string | null, from_me: boolean, at: string,
 *   kind: string, text: string | null, quoted_id: string | null, quoted_text: string | null,
 *   media_mime: string | null, reaction_to: string | null, options: Array | null
 * }}
 */
// The sender's phone-number address. Senders may arrive under a privacy id
// (@lid) with the number in another field: participantAlt / remoteJidAlt in
// Baileys 7, participantPn / senderPn in 6.x.
function phoneJid(key, isGroup) {
  const candidates = isGroup
    ? [key.participantPn, key.participantAlt, key.participant]
    : [key.senderPn, key.remoteJidAlt, key.fromMe ? null : key.remoteJid];
  return candidates.find((j) => typeof j === "string" && j.endsWith("@s.whatsapp.net")) || null;
}

export function normalizeMessage(msg) {
  const key = msg?.key;
  if (!key?.id || !key.remoteJid) return null;
  if (key.remoteJid === "status@broadcast" || key.remoteJid.endsWith("@newsletter")) return null;

  const content = normalizeMessageContent(msg.message);
  if (!content) return null;
  const type = getContentType(content);
  if (!type || IGNORED_TYPES.has(type)) return null;

  const isGroup = key.remoteJid.endsWith("@g.us");
  const inner = content[type];
  const kind = type === "audioMessage" && inner?.ptt ? "voice" : KIND_BY_TYPE[type] || "other";
  const context = inner && typeof inner === "object" ? inner.contextInfo : null;

  const menu = kind === "interactive" ? parseInteractive(type, inner || {}) : null;
  const menuText = menu && [menu.body, ...menu.options.map((o) => `${o.n}) ${o.title}`)].filter(Boolean).join("\n");

  return {
    id: key.id,
    chat_jid: key.remoteJid,
    is_group: isGroup,
    sender_jid: isGroup ? key.participant || null : key.fromMe ? null : key.remoteJid,
    sender_pn: phoneJid(key, isGroup),
    sender_name: msg.pushName || null,
    from_me: Boolean(key.fromMe),
    at: toIso(msg.messageTimestamp),
    kind,
    text: menu ? menuText || null : kind === "reaction" ? inner?.text || null : textOf(content, type),
    options: menu?.options.length ? menu.options : null,
    quoted_id: context?.stanzaId || null,
    quoted_text: quotedText(context?.quotedMessage),
    media_mime: MEDIA_KINDS.has(kind === "voice" ? "audio" : kind) ? inner?.mimetype || null : null,
    reaction_to: kind === "reaction" ? inner?.key?.id || null : null,
    // Who the message @-mentions (TM-03: tagging the bot). Not stored.
    mentions: Array.isArray(context?.mentionedJid) ? context.mentionedJid.filter(Boolean) : [],
  };
}
