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
 *   media_mime: string | null, reaction_to: string | null
 * }}
 */
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

  return {
    id: key.id,
    chat_jid: key.remoteJid,
    is_group: isGroup,
    sender_jid: isGroup ? key.participant || null : key.fromMe ? null : key.remoteJid,
    sender_pn: key.participantPn || key.senderPn || null,
    sender_name: msg.pushName || null,
    from_me: Boolean(key.fromMe),
    at: toIso(msg.messageTimestamp),
    kind,
    text: kind === "reaction" ? inner?.text || null : textOf(content, type),
    quoted_id: context?.stanzaId || null,
    quoted_text: quotedText(context?.quotedMessage),
    media_mime: MEDIA_KINDS.has(kind === "voice" ? "audio" : kind) ? inner?.mimetype || null : null,
    reaction_to: kind === "reaction" ? inner?.key?.id || null : null,
  };
}
