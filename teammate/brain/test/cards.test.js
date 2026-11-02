// TM-32: the "what's fixed" card.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_BUBBLES, fixedCardHtml } from "../src/cards.js";

const messages = [
  { from_me: 1, text: "50 bag cement vannu, stock ethra?", at: "2026-11-02T06:00:00Z" },
  { from_me: 0, text: "Stock *176 bags*.\nReady to save: 50 bags cement", at: "2026-11-02T06:00:03Z", options: [{ title: "Save" }, { title: "Cancel" }] },
];

test("the card shows the real chat and the three lists, escaped", () => {
  const html = fixedCardHtml({ id: 81, title: "Stock with a delivery <b>", sha: "abc1234", messages,
    nowWorks: ["a delivery and a stock question in one message"], alsoCovered: ["Malayalam script", "voice note"], stillNot: ["two sites in one message"] });
  assert.match(html, /class="b u">50 bag cement vannu, stock ethra\?/);
  assert.match(html, /class="b m">Stock <b>176 bags<\/b>\.<br>Ready to save/);
  assert.match(html, /<span>Save<\/span><span>Cancel<\/span>/);
  assert.match(html, /✅ \[81\] Stock with a delivery &lt;b&gt;/);
  assert.match(html, /<li>Malayalam script<\/li><li>voice note<\/li>/);
  assert.match(html, /Live · abc1234/);
});

test("an empty 'also covered' says plainly it is a patch", () => {
  const html = fixedCardHtml({ id: 9, title: "x", messages, nowWorks: ["x"], alsoCovered: [], stillNot: [] });
  assert.match(html, /this is a patch/);
  assert.match(html, /Nothing left out/);
});

test("a long test keeps only the newest bubbles", () => {
  const many = Array.from({ length: 30 }, (_, i) => ({ from_me: i % 2, text: `m${i}`, at: "2026-11-02T06:00:00Z" }));
  const html = fixedCardHtml({ id: 1, title: "t", messages: many, nowWorks: ["x"] });
  assert.equal((html.match(/class="b [um]"/g) || []).length, MAX_BUBBLES);
  assert.match(html, />m29</);
  assert.doesNotMatch(html, />m0</);
});
