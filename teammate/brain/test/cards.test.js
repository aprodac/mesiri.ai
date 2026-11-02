// TM-32: the "what's fixed" card: every related case is shown as the real exchange the live check had.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_BUBBLES, exchanges, fixedCardHtml, splitCases } from "../src/cards.js";

const at = "2026-11-02T06:00:00Z";
const messages = [
  { n: 1, from_me: 1, text: "50 bag cement vannu, stock ethra?", at },
  { n: 2, from_me: 0, text: "Stock *176 bags*.\nReady to save: 50 bags cement", at, options: [{ title: "Save" }, { title: "Cancel" }] },
  { n: 3, from_me: 1, text: "50 ചാക്ക് സിമന്റ് വന്നു, സ്റ്റോക്ക് എത്ര?", at },
  { n: 4, from_me: 0, text: "സ്റ്റോക്ക് 176 ചാക്ക്.", at },
  { n: 5, from_me: 1, text: "20 bags used, ethra baaki?", at },
  { n: 6, from_me: 0, text: "Stock 156 bags after the usage.", at },
];

test("the test chat splits into exchanges, and each related case finds its own", () => {
  assert.equal(exchanges(messages).length, 3);
  const { main, cases } = splitCases(messages, [
    { case: "Malayalam script", sent: "50 ചാക്ക് സിമന്റ് വന്നു,  സ്റ്റോക്ക് എത്ര?" }, // spacing does not matter
    { case: "Usage + stock", sent: "20 bags used, ethra baaki?" },
    { case: "Voice note", sent: "(voice)" },
  ]);
  assert.deepEqual(main.map((e) => e.sent.n), [1]); // the reported case stays on the left
  assert.equal(cases[0].exchange.replies[0].text, "സ്റ്റോക്ക് 176 ചാക്ക്.");
  assert.equal(cases[1].exchange.sent.n, 5);
  assert.equal(cases[2].exchange, null); // never sent: not tried
});

test("the card draws every related case as messages, and says which were not tried", () => {
  const html = fixedCardHtml({ id: 81, title: "Stock with a delivery <b>", sha: "abc1234", messages,
    nowWorks: ["a delivery and a stock question in one message"],
    alsoCovered: [{ case: "Malayalam script", sent: "50 ചാക്ക് സിമന്റ് വന്നു, സ്റ്റോക്ക് എത്ര?" }, { case: "Voice note", sent: "(voice)" }],
    stillNot: ["two sites in one message"] });
  assert.match(html, /✅ \[81\] Stock with a delivery &lt;b&gt;/);
  assert.match(html, /<div class="label">➕ Malayalam script<\/div><div class="chat mini"><div class="b u">50 ചാക്ക്/);
  assert.match(html, /<div class="b m">സ്റ്റോക്ക് 176 ചാക്ക്\./);
  assert.match(html, /case missing"><div class="label">➕ Voice note<\/div><div class="nottried">⚠️ Not tried in the chat/);
  assert.match(html, /\(1 of 2 tried\)/);
  assert.match(html, /class="b m">Stock <b>176 bags<\/b>\.<br>Ready to save/);
});

test("no related cases says plainly it is a patch", () => {
  const html = fixedCardHtml({ id: 9, title: "x", messages, nowWorks: ["x"], alsoCovered: [] });
  assert.match(html, /this is a patch/);
});

test("a long test keeps only the newest bubbles on the left", () => {
  const many = Array.from({ length: 30 }, (_, i) => ({ n: i, from_me: i % 2 === 0 ? 1 : 0, text: `m${i}`, at }));
  const html = fixedCardHtml({ id: 1, title: "t", messages: many, nowWorks: ["x"] });
  const left = html.split('<div class="info">')[0];
  assert.equal((left.match(/class="b [um]"/g) || []).length, MAX_BUBBLES);
  assert.match(left, />m29</);
  assert.doesNotMatch(left, />m0</);
});

test("a voice note or photo case matches the newest message of that kind", () => {
  const withVoice = [...messages, { n: 7, from_me: 1, text: null, kind: "audio", at }, { n: 8, from_me: 0, text: "Heard: 50 bags cement. Stock 176.", at }];
  const { cases } = splitCases(withVoice, [{ case: "Voice note", sent: "(voice)" }, { case: "Photo", sent: "(photo)" }]);
  assert.equal(cases[0].exchange.replies[0].text, "Heard: 50 bags cement. Stock 176.");
  assert.equal(cases[1].exchange, null);
});
