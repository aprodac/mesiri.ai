// "What's fixed" cards (TM-32, asked 2 Nov 2026: "I don't want most fixes or upgrades to be patch-ups"). After a fix
// is live, the live check posts one picture in the team group: the REAL conversation from the assistant-test chat
// (drawn by code from the stored messages, never retyped) for what now works, and for every related case the fix also
// covers (the class, docs/engineering/FIX_APPROACH.md) the real exchange the check had for it: what it sent and what
// Mesiri answered. A related case the check never tried shows as "not tried"; a card with no related cases says
// "this is a patch". So everyone in the group sees what was proven, not just claimed.

const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const formatted = (t) => esc(t).replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|\s)_([^_\n]+)_/g, "$1<i>$2</i>").replace(/\n/g, "<br>");
const clockIst = (iso) => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? new Date(ms + 5.5 * 3600_000).toISOString().slice(11, 16) : "";
};
const norm = (t) => String(t ?? "").trim().replace(/\s+/g, " ").toLowerCase();

/** Most bubbles the main conversation shows (the newest; a long test is cut from the top). */
export const MAX_BUBBLES = 12;
/** Most bubbles one related case shows (what was sent and the first replies). */
export const MAX_CASE_BUBBLES = 4;

/**
 * The test chat as exchanges: each message the check sent (from_me, a text or a tap) with Mesiri's replies after it.
 * `messages` are the listener's stored messages ({ n, from_me, text, kind, at, options }).
 */
export function exchanges(messages) {
  const out = [];
  for (const m of [...messages].sort((a, b) => (a.n ?? 0) - (b.n ?? 0))) {
    if (!(m.text || m.kind)) continue;
    if (m.from_me) out.push({ sent: m, replies: [] });
    else if (out.length) out.at(-1).replies.push(m);
  }
  return out;
}

/**
 * Splits the exchanges: for each related case, the LAST exchange whose sent text is the case's `sent` (as given to
 * test_assistant); everything else is the main conversation. A case with no such exchange was not tried.
 */
export function splitCases(messages, alsoCovered) {
  const all = exchanges(messages);
  const used = new Set();
  const cases = alsoCovered.map((c) => {
    const want = norm(c.sent);
    // A voice note or photo has no text to match: "(voice)" / "(photo)" match the newest one of that kind.
    const kind = /^\((voice|audio)/.test(want) ? /audio|ptt|voice/ : /^\((photo|image)/.test(want) ? /image|photo/ : null;
    const matches = (e) => (kind ? kind.test(String(e.sent.kind || "")) || (e.sent.has_media && /image|photo/.test(String(e.sent.media_mime || "")) && kind.test("image")) : norm(e.sent.text) === want);
    let idx = -1;
    for (let i = all.length - 1; i >= 0; i--) {
      if (!used.has(i) && want && matches(all[i])) {
        idx = i;
        break;
      }
    }
    if (idx >= 0) used.add(idx);
    return { label: c.case, sent: c.sent, exchange: idx >= 0 ? all[idx] : null };
  });
  const main = all.filter((_, i) => !used.has(i));
  return { main, cases };
}

const bubble = (m) => {
  const said = m.text ? formatted(m.text) : `<i>(${esc(m.kind)})</i>`;
  const options = (m.options || []).length ? `<div class="opts">${m.options.map((o) => `<span>${esc(o.title || o)}</span>`).join("")}</div>` : "";
  return `<div class="b ${m.from_me ? "u" : "m"}">${said}${options}<span class="t">${clockIst(m.at)}</span></div>`;
};
const flat = (exs) => exs.flatMap((e) => [e.sent, ...e.replies]);

/** The card's HTML: the main conversation on the left, the related cases as their own small chats on the right. */
export function fixedCardHtml({ id, title, sha = null, messages = [], nowWorks = [], alsoCovered = [], stillNot = [] }) {
  const { main, cases } = splitCases(messages, alsoCovered);
  const mainBubbles = flat(main).slice(-MAX_BUBBLES).map(bubble);
  const tried = cases.filter((c) => c.exchange).length;
  const caseHtml = cases.length
    ? cases
        .map((c) => {
          if (!c.exchange) {
            return `<div class="case missing"><div class="label">➕ ${esc(c.label)}</div><div class="nottried">⚠️ Not tried in the chat (“${esc(c.sent)}”): not proven</div></div>`;
          }
          const bubbles = [c.exchange.sent, ...c.exchange.replies].slice(0, MAX_CASE_BUBBLES).map(bubble).join("");
          const answered = c.exchange.replies.length ? "" : '<div class="nottried">⚠️ No reply from Mesiri</div>';
          return `<div class="case"><div class="label">➕ ${esc(c.label)}</div><div class="chat mini">${bubbles}</div>${answered}</div>`;
        })
        .join("")
    : '<p class="empty">Nothing beyond the reported message: this is a patch.</p>';
  const list = (items, cls, empty) =>
    items.length ? `<ul class="${cls}">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="none">${esc(empty)}</p>`;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#fff;font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans','Noto Sans Malayalam','Noto Sans Devanagari',sans-serif;color:#111b21;font-size:15px}
.wrap{display:flex}.chatcol{width:430px;background:#efeae2;flex:none}.info{flex:1;padding:20px 22px;min-width:0}
.top{background:#008069;color:#fff;padding:12px 14px;font-weight:600}.top small{display:block;font-weight:400;opacity:.85;font-size:12px}
.chat{padding:12px 10px 16px;display:flex;flex-direction:column;gap:6px}
.b{max-width:85%;padding:7px 9px 18px;border-radius:8px;position:relative;line-height:1.35;word-wrap:break-word;box-shadow:0 1px .5px rgba(0,0,0,.13)}
.u{align-self:flex-end;background:#d9fdd3}.m{align-self:flex-start;background:#fff}
.t{position:absolute;right:8px;bottom:3px;font-size:11px;color:#667781}
.opts{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.opts span{border:1px solid #c7d3d9;border-radius:12px;padding:2px 8px;font-size:12px;color:#027eb5}
h1{font-size:20px;margin:0 0 4px}.sub{color:#667781;font-size:13px;margin:0 0 14px}
h2{font-size:13px;letter-spacing:.04em;text-transform:uppercase;margin:14px 0 6px}
ul{margin:0;padding-left:20px;line-height:1.45}.ok li::marker{content:"✅ "}.not li::marker{content:"⏳ "}
.cases{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.case{background:#efeae2;border-radius:10px;overflow:hidden}.case .label{background:#dfe5e7;padding:6px 10px;font-size:13px;font-weight:600}
.chat.mini{padding:8px;gap:5px}.chat.mini .b{font-size:13px;padding:6px 8px 16px}
.case.missing{background:#fdecea}.nottried{color:#b42318;font-size:13px;padding:6px 10px 8px;font-weight:600}
.empty{color:#b42318;font-weight:600;margin:0}.none{color:#667781;margin:0}
</style></head><body><div class="wrap"><div class="chatcol"><div class="top">Mesiri · live check<small>assistant-test chat · IST</small></div>
<div class="chat">${mainBubbles.join("") || '<div class="b m"><i>(no messages)</i></div>'}</div></div>
<div class="info"><h1>✅ [${esc(id)}] ${esc(title)}</h1><p class="sub">Live${sha ? ` · ${esc(sha)}` : ""} · every chat on this card is the real reply after the deploy</p>
<h2>Now works</h2>${list(nowWorks, "ok", "—")}
<h2>Also covered: the same kind of message (${tried} of ${cases.length} tried)</h2><div class="cases">${caseHtml}</div>
<h2>Still not (on purpose)</h2>${list(stillNot, "not", "Nothing left out.")}
</div></div></body></html>`;
}
