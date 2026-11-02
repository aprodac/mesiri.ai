// "What's fixed" cards (TM-32, asked 2 Nov 2026: "I don't want most fixes or upgrades to be patch-ups"). After a fix
// is live, the live check posts one picture in the team group: the REAL conversation from the assistant-test chat
// (drawn by code from the stored messages, never retyped), next to what now works, the related cases the fix also
// covers (the class, docs/engineering/FIX_APPROACH.md), and what it deliberately does not. A fix whose "also covered"
// list is empty is a patch, and everyone in the group can see it.

const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const formatted = (t) => esc(t).replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|\s)_([^_\n]+)_/g, "$1<i>$2</i>").replace(/\n/g, "<br>");
const clockIst = (iso) => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? new Date(ms + 5.5 * 3600_000).toISOString().slice(11, 16) : "";
};

/** Most bubbles a card shows (the newest; a long test is cut from the top). */
export const MAX_BUBBLES = 14;

/**
 * The card's HTML. `messages` are the test chat's stored messages ({ from_me, text, kind, at, options }): from_me is
 * the tester (the bot's number), the rest are Mesiri's replies.
 */
export function fixedCardHtml({ id, title, sha = null, messages = [], nowWorks = [], alsoCovered = [], stillNot = [] }) {
  const shown = messages.filter((m) => m.text || m.kind).slice(-MAX_BUBBLES);
  const bubbles = shown.map((m) => {
    const said = m.text ? formatted(m.text) : `<i>(${esc(m.kind)})</i>`;
    const options = (m.options || []).length ? `<div class="opts">${m.options.map((o) => `<span>${esc(o.title || o)}</span>`).join("")}</div>` : "";
    return `<div class="b ${m.from_me ? "u" : "m"}">${said}${options}<span class="t">${clockIst(m.at)}</span></div>`;
  });
  const list = (items, cls, empty) =>
    items.length ? `<ul class="${cls}">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="empty">${esc(empty)}</p>`;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#fff;font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans','Noto Sans Malayalam','Noto Sans Devanagari',sans-serif;color:#111b21;font-size:15px}
.wrap{display:flex;gap:0;min-height:100vh}.chatcol{width:430px;background:#efeae2;flex:none}.info{flex:1;padding:22px 26px}
.top{background:#008069;color:#fff;padding:12px 14px;font-weight:600}.top small{display:block;font-weight:400;opacity:.85;font-size:12px}
.chat{padding:12px 10px 16px;display:flex;flex-direction:column;gap:6px}
.b{max-width:85%;padding:7px 9px 18px;border-radius:8px;position:relative;line-height:1.35;word-wrap:break-word;box-shadow:0 1px .5px rgba(0,0,0,.13)}
.u{align-self:flex-end;background:#d9fdd3}.m{align-self:flex-start;background:#fff}
.t{position:absolute;right:8px;bottom:3px;font-size:11px;color:#667781}
.opts{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.opts span{border:1px solid #c7d3d9;border-radius:12px;padding:2px 8px;font-size:12px;color:#027eb5}
h1{font-size:21px;margin:0 0 4px}.sub{color:#667781;font-size:13px;margin:0 0 18px}
h2{font-size:14px;letter-spacing:.04em;text-transform:uppercase;margin:16px 0 6px}
ul{margin:0;padding-left:20px;line-height:1.45}.ok li::marker{content:"✅ "}.also li::marker{content:"➕ "}.not li::marker{content:"⏳ "}
.empty{color:#b42318;font-weight:600;margin:0}
</style></head><body><div class="wrap"><div class="chatcol"><div class="top">Mesiri · live check<small>assistant-test chat · IST</small></div>
<div class="chat">${bubbles.join("") || '<div class="b m"><i>(no messages)</i></div>'}</div></div>
<div class="info"><h1>✅ [${esc(id)}] ${esc(title)}</h1><p class="sub">Live${sha ? ` · ${esc(sha)}` : ""} · the chat on the left is the real reply after the deploy</p>
<h2>Now works</h2>${list(nowWorks, "ok", "—")}
<h2>Also covered (the same kind of message)</h2>${list(alsoCovered, "also", "Nothing beyond the reported message: this is a patch.")}
<h2>Still not (on purpose)</h2>${list(stillNot, "not", "Nothing left out.")}
</div></div></body></html>`;
}
