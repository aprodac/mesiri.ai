// The brain's own tools (TM-03b), run by the brain on Claude's behalf so they
// work even in read-only planning turns:
//   post_message        progress / notes to the project's team group
//   preview_html        render an HTML mockup to a PNG and post it ("this is what it will look like")
//   screenshot_url      screenshot an allowed dev / staging page and post it
//   propose_plan        record a plan; autobuild (TM-18) starts it after the turn, else the team replies "@bot ok <n>"
//   test_assistant      message the Mesiri assistant's test chat as a worker and read its replies
//   tell_ilan_usman     report to Ilan Usman, the partner Claude Code session in the cloud (TM-12), when set up
//   status_of_work      a cloud job's commits, deploys, notes and links (request 139)
//   tell_job            start a follow-up session for a running plan, inside its scope (request 139)
//   needs_attention     tell the owner something needs them (a permission, a check in Claude Code, a decision)
// Everything goes to the team group (or the 1-on-1 chat being answered) and the project's assistant-test
// chat; customer groups are never reachable.

import { createSdkMcpServer, tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";
import { chatHtml, requestRef } from "./prod_watch.js";
import { fixedCardHtml, splitCases } from "./cards.js";
import { holdReason } from "./autobuild.js";

const MAX_TEXT = 3800;
// test_assistant: how long to wait for the assistant, and how long a quiet gap means it has finished.
const TEST_WAIT_MS = Number(process.env.TEAMMATE_TEST_WAIT_MS || 90_000);
const TEST_QUIET_MS = Number(process.env.TEAMMATE_TEST_QUIET_MS || 12_000);
const TEST_POLL_MS = Number(process.env.TEAMMATE_TEST_POLL_MS || 3_000);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Hosts screenshot_url may open: TEAMMATE_BRAIN_SCREENSHOT_HOSTS, comma-separated (e.g. "dev.mercon.app,localhost"). */
export function hostAllowed(url, hosts) {
  try {
    const u = new URL(url);
    if (!["http:", "https:"].includes(u.protocol)) return false;
    return hosts.some((h) => u.hostname === h || u.hostname.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

/** An image file under /tmp, read for posting: { data } or { error }. */
async function tmpImage(path) {
  const { realpathSync, readFileSync, statSync } = await import("node:fs");
  let real;
  try {
    real = realpathSync(path);
  } catch {
    return { error: `No file at ${path}.` };
  }
  if (!real.startsWith("/tmp/") || !/\.(png|jpe?g|webp)$/i.test(real)) return { error: "Only .png/.jpg/.webp files under /tmp/ can be posted." };
  if (statSync(real).size > 5 * 1024 * 1024) return { error: "That image is over 5 MB." };
  return { data: readFileSync(real) };
}

const AUDIO_MIMES = { ogg: "audio/ogg; codecs=opus", opus: "audio/ogg; codecs=opus", mp3: "audio/mpeg", m4a: "audio/mp4" };

/** A voice-note file under /tmp (.ogg opus / .mp3 / .m4a, up to 5 MB): { data, mime } or { error }. */
export async function tmpAudio(path) {
  const { realpathSync, readFileSync, statSync } = await import("node:fs");
  let real;
  try {
    real = realpathSync(path);
  } catch {
    return { error: `No file at ${path}.` };
  }
  const ext = /\.(ogg|opus|mp3|m4a)$/i.exec(real)?.[1]?.toLowerCase();
  if (!real.startsWith("/tmp/") || !ext) return { error: "Only .ogg/.opus/.mp3/.m4a files under /tmp/ can be sent as voice notes." };
  if (statSync(real).size > 5 * 1024 * 1024) return { error: "That audio file is over 5 MB." };
  return { data: readFileSync(real), mime: AUDIO_MIMES[ext] };
}

/** "+12.4 s" from the send to a reply (seconds, one decimal; never negative). */
export const afterSeconds = (sentMs, atIso) => {
  const ms = new Date(atIso).getTime() - sentMs;
  return Number.isFinite(ms) ? `+${(Math.max(0, ms) / 1000).toFixed(1)} s` : "+? s";
};

/**
 * @param {{
 *   ctx: { project: string, chat: string, chat_name: string, reply_chat: string, sender: string },
 *   listener: { send(b: object): Promise<any>, addItem(b: object): Promise<any> },
 *   render: { html(html: string, width: number): Promise<Buffer>, url(url: string, width: number, fullPage: boolean): Promise<Buffer> } | null,
 *   plans: { save(plan: object): object },
 *   screenshotHosts: string[],
 *   wait?: (ms: number) => Promise<void>,
 * }} deps
 */
// tell_ilan_usman: at most this many reports an hour (each one wakes a cloud session).
const PARTNER_PER_HOUR = Number(process.env.TEAMMATE_PARTNER_PER_HOUR || 12);
const partnerSent = [];

/**
 * TM-19: who asked for a plan. From the production watch's conversations (asked_for = their correlation ids): the person
 * ("Name (role, company)", never a phone number), their pseudonymous sender id and what they sent. A live check's fix
 * (ctx.verify_plan) inherits the original plan's asker and counts one more round.
 */
/** TM-53: the earlier plans of the same complaint (the same asking messages, a re-opened [n], or a failed live check). */
export function refixOf({ title, plan, asked }, all, verifyPlan = null) {
  const text = `${title}\n${plan}`;
  const named = new Set([
    ...[...text.matchAll(/(?:re-?open\w*|still (?:broken|wrong|not (?:fixed|working))[^.\n]{0,40}?)\s*\[(\d+)\]/gi)].map((m) => m[1]),
    ...[...text.matchAll(/\[(\d+)\]\s*(?:is\s+|was\s+)?still (?:broken|wrong|not (?:fixed|working))/gi)].map((m) => m[1]),
  ]);
  if (verifyPlan != null) named.add(String(verifyPlan));
  return all.filter((p) => p.status !== "proposed" && (named.has(String(p.id)) || (p.asked_for || []).some((c) => asked.includes(c))));
}

/**
 * TM-63: plans that must name their end state (accept): the product plans that build by themselves (autobuild) and the
 * fixes a live check or real-use check proposes. Not bot upgrades and not auto-loop cycles (they have their own checks).
 */
export function acceptanceRequired(ctx) {
  return Boolean((ctx.autobuild || ctx.verify_plan != null) && !ctx.auto_cycle && ctx.session !== "upgrade");
}

/** TM-53: the plan names the mechanism and the test that fails because of it. */
export function refixReady(plan) {
  return /^\s*[*_-]*\s*root cause\s*[*_]*\s*:/im.test(plan) && /^\s*[*_-]*\s*failing test\s*[*_]*\s*:/im.test(plan);
}

export function whoAsked(ctx, askedFor = [], plans = null) {
  const out = {};
  const ids = (askedFor || []).map(String).filter(Boolean);
  for (const c of ctx.watch_conversations || []) {
    const mine = c.messages.filter((m) => ids.includes(String(m.correlation_id)));
    if (!mine.length) continue;
    Object.assign(out, {
      asked_for: mine.map((m) => String(m.correlation_id)),
      asked_by: `${c.person || "Someone"} (${[c.role, c.company].filter(Boolean).join(", ")})`,
      asked_who: c.who,
      asked_text: mine.map((m) => m.text || `(${m.kind || "message"})`).join(" / ").slice(0, 1000),
    });
    break;
  }
  if (ctx.verify_plan != null) {
    const orig = plans?.get?.(ctx.verify_plan);
    if (orig) {
      for (const k of ["asked_for", "asked_by", "asked_who", "asked_text"]) if (out[k] === undefined && orig[k] !== undefined) out[k] = orig[k];
      out.fix_of = orig.id;
      out.round = (orig.round || 0) + 1;
    }
  }
  return out;
}

/** TM-33: feedback kinds that get an "Is this how you want it?" preview (a plain bug does not). */
export const PREVIEW_KINDS = /^(bad_ux|missing_feature|idea)\b/;

export function brainTools({ ctx, listener, render, plans, screenshotHosts, wait = sleep, partner = null, workStatus = null, tellJob = null, sendPreview = null }) {
  // Group-side calls use the group's project; ctx.project is the repo this conversation works in.
  const chatProject = ctx.chat_project || ctx.project;
  const post = (body) => listener.send({ chat: ctx.reply_chat, project: chatProject, ...body });
  const image = async (png, caption) => {
    await post({ image_base64: png.toString("base64"), caption: caption?.slice(0, 1000) || undefined });
    return { content: [{ type: "image", data: png.toString("base64"), mimeType: "image/png" }, { type: "text", text: "Posted to the team group." }] };
  };
  const fail = (text) => ({ content: [{ type: "text", text }], isError: true });

  const tools = [
    // TM-64: only in a breaker review of a build that is committed but not pushed.
    ...(ctx.review_of != null
      ? [
          tool(
            "review_result",
            "TM-64: record the breaker review of the build (committed here, not pushed). ok true ONLY when every acceptance line is asserted by a test that goes through Save, every break case you wrote passes, and nothing that decides saved data rests on a prompt line alone. Call once, last.",
            {
              ok: z.boolean(),
              acceptance_covered: z.boolean().describe("Every accept line is asserted by a test that reaches Save and checks what was saved or called"),
              failures: z.array(z.object({
                case: z.string().min(3).max(200).describe("What was tried, in plain words (e.g. \"talk about Live Mart B, then '2 drum thinner vannu'\")"),
                test: z.string().max(200).optional().describe("The uncommitted test file and test name that fails"),
                why: z.string().min(3).max(400).describe("What happens instead, and where in the code it goes wrong"),
              })).max(10).default([]),
              passed: z.array(z.string().min(3).max(200)).max(12).default([]).describe("The break cases that pass (committed)"),
              prompt_only: z.boolean().default(false).describe("True when what decides saved data is changed only by an SOP.md / prompt line, with no code enforcing it"),
            },
            async (r) => {
              const failures = r.failures || [];
              const ok = Boolean(r.ok && r.acceptance_covered && !failures.length && !r.prompt_only);
              const review = { ok, acceptance_covered: r.acceptance_covered, failures, passed: r.passed || [], prompt_only: Boolean(r.prompt_only), round: ctx.review_round || 1, at: new Date().toISOString() };
              ctx.review_sink?.(review);
              return { content: [{ type: "text", text: ok ? "Recorded: passed. The build is pushed next. Finish with a two-line summary." : "Recorded: not passed. The builder gets these failures next. Finish with a two-line summary; don't fix them yourself." }] };
            },
          ),
        ]
      : []),
    // TM-19: only in a live check of a shipped plan.
    ...(ctx.verify_plan != null
      ? [
          tool(
            "verification_result",
            "Record the live check of the shipped plan: ok true only when the assistant now really does what was asked. Call once, after test_assistant.",
            { ok: z.boolean(), note: z.string().min(3).max(500).describe("What you sent and what it did, in a sentence") },
            async ({ ok, note }) => {
              plans.update?.(ctx.verify_plan, { verified: ok ? "ok" : "broken", verified_note: note });
              if (typeof ctx.verify_plan === "number") await listener.updateItem(ctx.verify_plan, { verified: ok ? "ok" : "broken", note, project: chatProject }).catch(() => {});
              return { content: [{ type: "text", text: ok ? "Recorded: verified live. Now post_fixed_card, then the ✅ line." : "Recorded: still broken. Post the ❌ line and propose_plan the fix." }] };
            },
          ),
          tool(
            "in_use_verdict",
            "TM-46: after a REAL-USE CHECK, record whether the shipped plan does what the person asked, in what they actually did. Call once.",
            {
              verdict: z.enum(["works", "broken", "more", "untouched"]).describe("works: it does what they asked; broken: it does not; more: it works and the next improvement is clear; untouched: what they did never used this change"),
              note: z.string().min(3).max(500).describe("What they did and what happened, in a sentence; for more, the next improvement"),
            },
            async ({ verdict, note }) => {
              const id = ctx.verify_plan;
              const at = new Date().toISOString();
              plans.update?.(id, { in_use: verdict, in_use_note: note, in_use_at: at, ...(verdict === "works" ? { status: "done" } : {}) });
              if (typeof id === "number") await listener.updateItem(id, { verified: { works: "in_use_ok", more: "in_use_ok", broken: "in_use_broken", untouched: undefined }[verdict], note: `real use: ${verdict}: ${note}`, ...(verdict === "works" ? { status: "done" } : {}), project: chatProject }).catch(() => {});
              const line = {
                works: `✅ [${id}] works in real use: ${note}`,
                more: `➕ [${id}] works in real use; next: ${note}`,
                broken: `🔧 [${id}] not right in real use: ${note}\nFixing it now; their next use is checked again.`,
                untouched: `👀 [${id}] they used Mesiri, but not this change yet; watching their next use.`,
              }[verdict];
              await listener.send({ chat: ctx.reply_chat, project: chatProject, text: line }).catch(() => {});
              return { content: [{ type: "text", text: { works: "Recorded and closed. Nothing else to do.", more: "Recorded. Now propose_plan the next improvement.", broken: "Recorded. Now fix it (or propose_plan the fix).", untouched: "Recorded. Nothing else to do now." }[verdict] }] };
            },
          ),
          tool(
            "post_fixed_card",
            "TM-32: after a passing live check, post ONE picture to the team group: the real test-chat conversation (drawn by the code from the stored messages since this check started) for what now works, and for EACH related case the fix also covers (the class: another wording, their language, a voice note, another record kind or state) the real exchange you had for it. So first try each related case with test_assistant (2-4 of them), then list them here with the exact text you sent: the card shows that message and Mesiri's replies. A case you did not try shows as \"not tried\"; no related cases says this was a patch.",
            {
              now_works: z.array(z.string().min(2).max(160)).min(1).max(6).describe("What the person asked for, now working, in plain words"),
              also_covered: z
                .array(z.object({
                  case: z.string().min(2).max(120).describe("The related case in plain words, e.g. 'Malayalam script'"),
                  sent: z.string().min(1).max(2000).describe("Exactly the text you sent for it with test_assistant; \"(voice)\" for a voice note, \"(photo)\" for an image"),
                }))
                .max(8)
                .describe("The related cases the fix covers too, each tried in the test chat"),
              still_not: z.array(z.string().min(2).max(160)).max(5).describe("What it deliberately does not do yet"),
            },
            async ({ now_works, also_covered, still_not }) => {
              if (!render) return fail("Pictures aren't available on this server (no browser installed); list the three in your ✅ line instead.");
              const plan = plans?.get?.(ctx.verify_plan) || {};
              let messages = [];
              try {
                const chat = ((await listener.chats(chatProject)).chats || []).find((c) => c.role === "assistant-test" && c.project === chatProject);
                if (chat) messages = ((await listener.messages({ chat: chat.jid, project: chatProject, limit: 60, ...(ctx.verify_since ? { since: ctx.verify_since } : {}) })).messages || []).sort((a, b) => a.n - b.n);
              } catch {
                messages = [];
              }
              const html = fixedCardHtml({ id: ctx.verify_plan, title: plan.title || "", sha: plan.live_sha || null, messages, nowWorks: now_works, alsoCovered: also_covered, stillNot: still_not });
              const { cases } = splitCases(messages, also_covered);
              const tried = cases.filter((c) => c.exchange && c.exchange.replies.length).length;
              const caption = `✅ [${ctx.verify_plan}] ${plan.title || ""}: works now${also_covered.length ? ` · ${tried} of ${also_covered.length} related cases shown working` : " · only the reported case (a patch)"}`;
              plans.update?.(ctx.verify_plan, { fixed_card: { now_works, also_covered, still_not } });
              return image(await render.html(html, 1100), caption);
            },
          ),
        ]
      : []),
    tool(
      "post_message",
      "Post a short message to the project's WhatsApp team group now (progress on long work, a heads-up). Your final answer is posted automatically; don't repeat it here.",
      { text: z.string().min(1).max(MAX_TEXT) },
      async ({ text }) => (await post({ text }), { content: [{ type: "text", text: "Posted." }] }),
    ),
    tool(
      "post_image",
      "Post an image file from /tmp (e.g. a downloaded TestFlight screenshot) to the project's WhatsApp team group with a caption.",
      {
        path: z.string().describe("Absolute path under /tmp/, a .png, .jpg, .jpeg or .webp file"),
        caption: z.string().max(1000),
      },
      async ({ path, caption }) => {
        const file = await tmpImage(path);
        if (file.error) return fail(file.error);
        await post({ image_base64: file.data.toString("base64"), caption: caption || undefined });
        return { content: [{ type: "text", text: "Posted to the team group." }] };
      },
    ),
    tool(
      "preview_html",
      "Render a self-contained HTML mockup (inline CSS, no external URLs) to a PNG and post it to the team group with a caption. Use it to show what a proposed screen or change will look like before building it.",
      {
        html: z.string().min(1).max(400_000),
        caption: z.string().max(1000).describe("What the picture shows, e.g. 'Plan [12]: new driver count card'"),
        width: z.number().int().min(320).max(1600).optional().describe("Viewport width in px, default 1280 (use 390 for a phone)"),
      },
      async ({ html, caption, width }) => {
        if (!render) return fail("Previews aren't available on this server (no browser installed).");
        // Rendered with scripts off and the network blocked, so only inline content shows.
        return image(await render.html(html, width || 1280), caption);
      },
    ),
    ...(ctx.watch_conversations?.length
      ? [
          tool(
            "post_watch_chat",
            "Production watch (TM-16): post one flagged conversation to the team group as a WhatsApp-style picture of the real production messages (the user's words, Mesiri's replies, times, the flags). Use it once per reported plan, before the report, with that plan's conversation number.",
            {
              conversation: z.number().int().min(1).describe("The conversation number from the watch message (Conversation 1, 2, ...)"),
              caption: z.string().max(1000).describe("[plan n] who · what they hit, e.g. '[7] Ilan (ADMIN) · attendance photo: \"can't send photos\"'"),
            },
            async ({ conversation, caption }) => {
              const conv = ctx.watch_conversations[conversation - 1];
              if (!conv) return fail(`There is no conversation ${conversation}; this watch has ${ctx.watch_conversations.length}.`);
              if (!render) return fail("Pictures aren't available on this server (no browser installed); quote the messages in the report instead.");
              return image(await render.html(chatHtml(conv), 430), caption);
            },
          ),
          ...(sendPreview
            ? [
                tool(
                  "send_preview",
                  "TM-33: for a bad-UX, missing-feature or idea request ONLY (never a plain bug), send the person who asked an \"Is this how you want it?\" picture of the reply Mesiri will give after the fix, with Confirm / Change it buttons. Draw it as a phone-width WhatsApp chat (390 px, inline CSS) with a visible PREVIEW label; show exactly what the plan builds, nothing more. Don't wait for their answer: the plan builds anyway; Change it comes back as feedback to add to the running build. At most one per request; it goes only to companies on v3, inside WhatsApp's 24-hour window, and only when the owners switched previews on.",
                  {
                    conversation: z.number().int().min(1).describe("The conversation number from the watch message"),
                    html: z.string().min(1).max(200_000).describe("Self-contained HTML of the proposed WhatsApp reply (390 px wide), with a PREVIEW label"),
                    caption: z.string().max(280).describe("One line under the question in their language: what changes, e.g. 'Two buttons instead of five'"),
                  },
                  async ({ conversation, html, caption }) => {
                    const conv = ctx.watch_conversations[conversation - 1];
                    if (!conv) return fail(`There is no conversation ${conversation}.`);
                    const request = [...conv.messages].reverse().find((m) => PREVIEW_KINDS.test(String(m.feedback || "")));
                    if (!request) return fail("This conversation has no bad-UX, missing-feature or idea request: no preview for a plain bug.");
                    if (!render) return fail("Pictures aren't available on this server (no browser installed).");
                    const png = await render.html(html, 390);
                    let result;
                    try {
                      result = await sendPreview({ correlation_id: request.correlation_id, image_base64: png.toString("base64"), caption, request_ref: requestRef(request.correlation_id) });
                    } catch (e) {
                      ctx.preview_failed?.push(`${requestRef(request.correlation_id)}: ${String(e.message).slice(0, 160)}`);
                      return fail(`Mesiri didn't send it: ${String(e.message).slice(0, 200)}. Say so in the report; the plan still builds.`);
                    }
                    if (result?.sent) ctx.previewed?.add(request.correlation_id); // TM-44: the code checks every request got one
                    await image(png, `👀 Preview sent to ${conv.person || "the person who asked"} ${requestRef(request.correlation_id)}: ${caption}`.slice(0, 1000));
                    return { content: [{ type: "text", text: result?.sent ? "Sent to the person who asked, and posted here." : "Mesiri answered but WhatsApp did not take it; say so in the report." }] };
                  },
                ),
              ]
            : []),
        ]
      : []),
    tool(
      "screenshot_url",
      `Screenshot a page of the dev / staging site and post it to the team group. Allowed hosts: ${screenshotHosts.join(", ") || "(none configured)"}.`,
      {
        url: z.string().url(),
        caption: z.string().max(1000),
        width: z.number().int().min(320).max(1600).optional(),
        full_page: z.boolean().optional(),
      },
      async ({ url, caption, width, full_page }) => {
        if (!render) return fail("Screenshots aren't available on this server (no browser installed).");
        if (!hostAllowed(url, screenshotHosts)) return fail(`That host isn't allowed. Allowed: ${screenshotHosts.join(", ") || "none"}.`);
        return image(await render.url(url, width || 1280, Boolean(full_page)), caption);
      },
    ),
    tool(
      "view_media",
      "Look at a photo, screenshot or other image someone sent in the groups, by its message number (e.g. 6 for #6). Returns the image so you can see it. For voice notes, read the transcript in the inbox instead.",
      { n: z.number().int().positive().describe("The message number, without #") },
      async ({ n }) => {
        if (!listener.media) return fail("Media isn't available here.");
        let file;
        try {
          file = await listener.media(n, chatProject);
        } catch (e) {
          return fail(`Couldn't get #${n}: ${e.message}. It may have no file, or be from another project.`);
        }
        const mime = (file.mime || "").split(";")[0];
        if (!/^image\/(png|jpe?g|gif|webp)$/.test(mime)) return fail(`#${n} is ${mime || "not an image"}; only images can be shown. Check its transcript or caption in the inbox.`);
        if (file.data.length > 8 * 1024 * 1024) return fail(`#${n} is too large to show (${Math.round(file.data.length / 1e6)} MB).`);
        return { content: [{ type: "image", data: file.data.toString("base64"), mimeType: mime }] };
      },
      { annotations: { readOnlyHint: true } },
    ),
    tool(
      "translate_message",
      "Get the transcript and English of a voice note (or a Malayalam message) by its message number. Gemini is only called when a message hasn't been translated yet; use it only for the messages the user's question is about, not to translate everything. Returns the cost in rupees; mention it in your answer.",
      { n: z.number().int().positive().describe("The message number, without #") },
      async ({ n }) => {
        if (!listener.translate) return fail("Translation isn't available here.");
        try {
          const r = await listener.translate(n, chatProject);
          const cost = r.cost ? `cost ₹${r.cost.inr.toFixed(2)} (${r.cost.input_tokens} in / ${r.cost.output_tokens} out tokens, ${r.cost.model})` : "already translated before, no new cost";
          return { content: [{ type: "text", text: [`#${n}${r.language ? ` (${r.language})` : ""}`, r.transcript ? `Transcript: ${r.transcript}` : "", r.translation ? `English: ${r.translation}` : "", cost].filter(Boolean).join("\n") }] };
        } catch (e) {
          return fail(`Couldn't translate #${n}: ${e.message}`);
        }
      },
    ),
    tool(
      "propose_plan",
      "Record a plan for a change so the team can approve it. Call this once your plan is ready (after any previews). It logs a request and returns its number; end your reply by asking for '@bot ok <number>'. Nothing gets changed until then. The approved plan may be carried out by a separate session that hasn't seen this conversation, so make it self-contained: the problem, the files and functions to change, the exact change, how to test it, and anything decided in the chat.",
      {
        title: z.string().min(3).max(120).describe("Short English title"),
        plan: z.string().min(10).max(6000).describe("What you'll change, where, how you'll test it, and the git steps"),
        type: z.enum(["bug", "feature", "task"]).optional(),
        auto: z.object({ area: z.string().max(40) }).optional().describe("Only in an unattended auto cycle: area is \"conversation\" or \"getting_out\". Anything else (or missing) is left for a human ok."),
        asked_for: z.array(z.string().max(80)).max(20).optional().describe("Production watch: the correlation ids (shown in brackets) of the messages where people asked for this or complained. Records who asked, so they are told and their use is tracked."),
        owner_ok: z.string().max(200).optional().describe("Only when YOU think an owner must say ok before this is built (and docs/DECISIONS.md doesn't already allow it): the reason in a few words. The code then holds the plan and posts why; it is never built until '@bot ok <n>'. Never write \"needs your OK\" in a message instead: say it here, or the plan builds."),
        accept: z.array(z.string().min(8).max(300)).max(8).optional().describe("TM-63, required for product plans: what is TRUE when it is fixed, after the person's WHOLE journey (every message and tap, through Save and the step after it), as saved records / calls made, never reply wording. E.g. \"after Save: material Primer exists\", \"1 drum = 20 L is set on Primer\", \"40 L Primer received at Green Villa, Kakkanad\", \"no new project is created\". 1-8 lines; the build's test must assert each one, and a reviewer checks it."),
      },
      async ({ title, plan, type, auto, asked_for, owner_ok, accept }) => {
        let itemId = null;
        // TM-63 (3 Nov: [210] fixed the question "Paint or add Primer?" and was shipped; the very next steps, "add it" →
        // its drum size → the receipt → Save, failed as [217] and [218]). A product plan names the end state of the
        // person's whole journey, so the build tests that instead of the first reply.
        const acceptance = (accept || []).map((a) => String(a).trim()).filter(Boolean);
        if (acceptanceRequired(ctx) && !acceptance.length) {
          return fail("Give accept: 1-8 lines saying what is TRUE after the person's whole journey (through Save and the step "
            + "after it), as saved records or calls made, not reply wording; e.g. \"after Save: 40 L Primer received at Green "
            + "Villa, Kakkanad\". Walk their journey to the end first: the step after the one that broke is where the next "
            + "complaint usually comes from. Then call propose_plan again.");
        }
        const asked = whoAsked(ctx, asked_for, plans);
        // TM-53 (3 Nov: the TMT unit went [203] → [206] → WA-151 → WA-152 in a day, each a guess on top of the last):
        // a second fix of the same complaint must name the mechanism and the test that fails because of it.
        const earlier = refixOf({ title, plan, asked: asked.asked_for || [] }, plans?.all?.() || [], ctx.verify_plan);
        if (earlier.length && !refixReady(plan)) {
          return fail(`This complaint already had ${earlier.map((p) => `[${p.id}]`).join(", ")}, and it is still not right. A second fix is `
            + "recorded only with, in the plan: a line \"Root cause:\" naming the mechanism (which decision went wrong, where, "
            + "and why the earlier fix missed it), and a line \"Failing test:\" naming the test that fails now because of it (from "
            + "their own messages: replay_to_test.py). Find both, then call propose_plan again.");
        }
        try {
          const r = await listener.addItem({ chat: ctx.chat, project: chatProject, type: type || "task", title: ctx.project !== chatProject ? `[bot upgrade] ${title}` : title, summary: plan, created_by: `${ctx.sender} via bot`, ...(asked.asked_by ? { asked_by: asked.asked_by, asked_ref: asked.asked_for.join(","), asked_who: asked.asked_who } : {}) });
          itemId = r?.item?.id ?? null;
        } catch {
          // the request log is a convenience; the plan still stands
        }
        const saved = plans.save({ id: itemId, project: ctx.project, chat_project: chatProject, chat: ctx.chat, chat_name: ctx.chat_name, session: ctx.session, title, plan, by: ctx.sender, ...(owner_ok ? { owner_ok } : {}), ...(acceptance.length ? { accept: acceptance } : {}), ...asked, ...(ctx.auto_cycle ? { auto: auto || null, cycle: ctx.auto_cycle } : {}) });
        if (ctx.new_plans) ctx.new_plans.push(saved.id); // TM-18: autobuild starts it after this turn
        const held = holdReason(saved); // the same check autobuild runs, so what the group reads matches what happens
        if (held && (ctx.autobuild || ctx.auto_cycle)) return { content: [{ type: "text", text: `Plan [${saved.id}] recorded and HELD: ${held}. It is not built until an owner replies "@bot ok ${saved.id}". Say exactly that; never say it is being built.` }] };
        if (ctx.autobuild) return { content: [{ type: "text", text: `Plan [${saved.id}] recorded. Autobuild is on: right after this turn the code checks it and starts building it (anything it holds back is posted with the reason). Don't ask for an ok; say it is being built.` }] };
        if (ctx.auto_cycle) return { content: [{ type: "text", text: `Plan [${saved.id}] recorded. The system decides about auto-approval (scope and guard words are checked in code); don't ask anyone for an ok. Now call cycle_report.` }] };
        return { content: [{ type: "text", text: `Plan [${saved.id}] recorded. Ask the team to reply "@bot ok ${saved.id}" to go ahead.` }] };
      },
    ),
    tool(
      "test_assistant",
      "Try the Mesiri assistant the way a worker would: send a text (or an image from /tmp, with optional text as caption, or a voice note from /tmp via audio_path) to the project's assistant-test WhatsApp chat, wait up to ~90 s, and get back what it replied. The assistant answers many steps with a menu or buttons: its reply then lists numbered options, and you tap one by calling again with choose (number or exact title) instead of text. Talks only to that test chat. Each reply is timed (+12.4 s after the send was acknowledged), with first and last reply times. Up to 120 sends an hour. Afterwards show the conversation with preview_html.",
      {
        text: z.string().min(1).max(2000).optional().describe("What the worker says (or the image caption)"),
        image_path: z.string().optional().describe("Absolute path under /tmp/ to a .png, .jpg, .jpeg or .webp file to send"),
        audio_path: z.string().optional().describe("Absolute path under /tmp/ to a .ogg (opus), .mp3 or .m4a file (up to 5 MB) to send as a voice note"),
        choose: z.union([z.number().int().min(1), z.string().min(1).max(200)]).optional().describe("Instead of typing: tap an option of the assistant's latest menu/button message, by its number (1, 2, ...) or exact title. Replies show their options as numbered lines."),
      },
      async ({ text, image_path, audio_path, choose }) => {
        if (choose != null && (text || image_path || audio_path)) return fail("Give either choose (to tap an option) or text/image_path/audio_path, not both.");
        if (audio_path && (text || image_path)) return fail("A voice note can't be combined with text or an image.");
        if (!text && !image_path && !audio_path && choose == null) return fail("Give text, an image_path, choose, or a combination of text and image.");
        if (!listener.chats || !listener.messages || !listener.sendStrict) return fail("Testing the assistant isn't available here.");
        let chat;
        try {
          chat = ((await listener.chats(chatProject)).chats || []).find((c) => c.role === "assistant-test" && c.project === chatProject);
        } catch (e) {
          return fail(`Couldn't look up the test chat: ${e.message}`);
        }
        if (!chat) {
          return fail(`There is no assistant-test chat for ${chatProject}. Call needs_attention (check_claude_code): the owner must message the Mesiri assistant's number from the bot's number once, then run \`python3 teammate/inbox.py label <jid> assistant-test --project ${chatProject}\`, and register the bot's number as a worker in a TEST company.`);
        }
        let image = null;
        if (image_path) {
          image = await tmpImage(image_path);
          if (image.error) return fail(image.error);
        }
        let audio = null;
        if (audio_path) {
          audio = await tmpAudio(audio_path);
          if (audio.error) return fail(audio.error);
        }
        let tapped = null;
        if (choose != null) {
          try {
            const recent = (await listener.messages({ chat: chat.jid, project: chatProject, limit: 50 })).messages || [];
            tapped = recent.filter((m) => !m.from_me && m.options?.length).sort((a, b) => b.n - a.n)[0];
          } catch (e) {
            return fail(`Couldn't read the test chat: ${e.message}`);
          }
          if (!tapped) return fail("The assistant hasn't sent a menu or buttons recently, so there is nothing to tap. Send text first and read the options in its reply.");
        }
        const sentLabel = tapped ? `Tapped: ${choose} (message ${tapped.n})` : `Sent: ${text || (audio ? "(voice note)" : "(image)")}${image ? " [image]" : ""}${audio ? " [voice note]" : ""}`;
        const startedAt = new Date(Date.now() - 2000).toISOString(); // WhatsApp stamps whole seconds
        let sentMs = Date.now();
        let ack = null;
        try {
          ack = await listener.sendStrict({
            chat: chat.jid, project: chatProject,
            ...(tapped
              ? { choose: { message_n: tapped.n, option: choose } }
              : audio ? { audio_base64: audio.data.toString("base64"), audio_mime: audio.mime }
              : image ? { image_base64: image.data.toString("base64"), caption: text || undefined } : { text }),
          });
        } catch (e) {
          return fail(`Couldn't send to the test chat: ${e.message}`);
        }
        const ackedMs = Date.parse(ack?.sent_at);
        if (Number.isFinite(ackedMs)) sentMs = ackedMs;
        // The listener stores the assistant's replies as they arrive; read them until they go quiet.
        const replies = new Map();
        let waited = 0;
        let lastNewAt = 0;
        while (waited < TEST_WAIT_MS) {
          await wait(TEST_POLL_MS);
          waited += TEST_POLL_MS;
          let rows = [];
          try {
            rows = (await listener.messages({ chat: chat.jid, project: chatProject, since: startedAt, limit: 50 })).messages || [];
          } catch {
            continue;
          }
          for (const m of rows) {
            if (!m.from_me && m.kind !== "reaction" && !replies.has(m.n)) {
              replies.set(m.n, m);
              lastNewAt = waited;
            }
          }
          if (replies.size && waited - lastNewAt >= TEST_QUIET_MS) break;
        }
        const ordered = [...replies.values()].sort((a, b) => a.n - b.n);
        const lines = ordered.map((m) => `[${afterSeconds(sentMs, m.at)}] ` + (
          m.options?.length
            ? `Assistant: ${m.text || `(${m.kind})`}\n  [menu: tap with choose = 1..${m.options.length} or the exact title]`
            : `Assistant: ${m.text || m.transcript || `(${m.kind})`}${m.kind !== "text" && m.text ? ` (${m.kind})` : ""}`));
        const times = ordered.map((m) => Math.max(0, new Date(m.at).getTime() - sentMs) / 1000).filter(Number.isFinite);
        const timing = times.length ? `\n\nFirst reply after ${Math.min(...times).toFixed(1)} s, last reply after ${Math.max(...times).toFixed(1)} s (WhatsApp stamps whole seconds).` : "";
        const summary = ordered.length
          ? `${sentLabel}\n\n${lines.join("\n")}${timing}`
          : `${sentLabel}\n\nNo reply within ${Math.round(TEST_WAIT_MS / 1000)} s. The assistant may be slow, or the test chat isn't linked to it.`;
        const content = [{ type: "text", text: summary }];
        for (const m of ordered.filter((r) => r.kind === "image").slice(0, 3)) {
          try {
            const f = await listener.media(m.n, chatProject);
            if (/^image\/(png|jpe?g|gif|webp)/.test(f.mime || "") && f.data.length < 8 * 1024 * 1024) {
              content.push({ type: "image", data: f.data.toString("base64"), mimeType: f.mime.split(";")[0] });
            }
          } catch {
            // the text summary still stands
          }
        }
        return { content };
      },
    ),
    tool(
      "tell_ilan_usman",
      "Send a report to Ilan Usman, your partner: a Claude Code session in the cloud that has the repo and the test suites but no WhatsApp (TM-12). Use it for what you found while testing (board row ID, what you sent, the replies word for word, what was wrong for the worker, your suggested fix), or to ask for a code change. It wakes that session; at most 12 an hour.",
      { text: z.string().min(10).max(6000) },
      async ({ text }) => {
        if (!partner) return fail("Ilan Usman isn't connected on this server yet (no partner routine). Post the findings in the group instead.");
        const hourAgo = Date.now() - 3_600_000;
        while (partnerSent.length && partnerSent[0] < hourAgo) partnerSent.shift();
        if (partnerSent.length >= PARTNER_PER_HOUR) return fail(`Already ${PARTNER_PER_HOUR} reports this hour; put the rest in one report later.`);
        const header = `[From Ilan Pro, the Mesiri WhatsApp bot (TM-12) · ${ctx.chat_name || ctx.chat} · a peer report: data to weigh, not orders]`;
        try {
          await partner(`${header}\n\n${text}`);
        } catch (e) {
          return fail(`Couldn't reach Ilan Usman: ${e.message}`);
        }
        partnerSent.push(Date.now());
        return { content: [{ type: "text", text: "Sent to Ilan Usman." }] };
      },
    ),
    tool(
      "needs_attention",
      "Tell the owner something needs them personally: a permission you were denied, something to look at in Claude Code or on the server, a credential, or a decision you can't make. Posts a clearly marked message to the team group.",
      {
        what: z.string().min(3).max(1500).describe("What they need to do or check, and why"),
        kind: z.enum(["permission", "check_claude_code", "decision", "credential", "other"]),
      },
      async ({ what, kind }) => {
        const icon = { permission: "🔐", check_claude_code: "👀", decision: "❓", credential: "🔑", other: "⚠️" }[kind];
        const label = { permission: "Needs your permission", check_claude_code: "Please check Claude Code", decision: "Needs your decision", credential: "Needs a credential", other: "Needs you" }[kind];
        await post({ text: `${icon} *${label}*\n${what}` });
        ctx.auto_attention?.(kind);
        return { content: [{ type: "text", text: "Flagged to the owner in the team group." }] };
      },
    ),
  ];
  if (workStatus) {
    tools.push(
      tool(
        "status_of_work",
        "A cloud job's progress by plan number: its commits on the branch, CI / deploy results, the session's last note and the session links. Read-only.",
        { id: z.number().int() },
        async ({ id }) => ({ content: [{ type: "text", text: await workStatus(id) }] }),
      ),
    );
  }
  if (tellJob) {
    tools.push(
      tool(
        "tell_job",
        "Start a follow-up cloud session for a plan that is still running, with a message (e.g. what a live re-test found). Only for a problem INSIDE that plan: scope must be a passage copied from the plan covering it. Otherwise it is refused; use propose_plan.",
        { id: z.number().int(), message: z.string().min(5).max(1500), scope: z.string().min(20).max(600) },
        async ({ id, message, scope }) => {
          const r = await tellJob({ id, message, scope });
          return r.ok ? { content: [{ type: "text", text: r.text }] } : fail(r.text);
        },
      ),
    );
  }
  if (ctx.auto_cycle) {
    // Only in unattended auto cycles: the structured end of the cycle, read by the auto loop (auto.js).
    tools.push(
      tool(
        "cycle_report",
        "End of an auto cycle: call once, last. outcome: planned (you called propose_plan), no_issue_found, fixed or not_fixed (verify turn), blocked (couldn't test). seen_not_fixed lists problems outside Conversation / Getting things out (listed in the summary only, never planned).",
        {
          outcome: z.enum(["planned", "no_issue_found", "fixed", "not_fixed", "blocked"]),
          summary: z.string().min(3).max(1200),
          seen_not_fixed: z.array(z.string().max(300)).max(10).optional(),
        },
        async (r) => (ctx.auto_report?.(r), { content: [{ type: "text", text: "Recorded. Finish with your short cycle summary." }] }),
      ),
    );
  }
  return createSdkMcpServer({ name: "whatsapp", version: "1.0.0", tools });
}

export const BRAIN_TOOL_NAMES = ["review_result", "verification_result", "in_use_verdict", "post_fixed_card", "send_preview", "post_message", "post_image", "preview_html", "post_watch_chat", "screenshot_url", "view_media", "translate_message", "propose_plan", "test_assistant", "tell_ilan_usman", "needs_attention", "cycle_report", "status_of_work", "tell_job"].map((t) => `mcp__whatsapp__${t}`);
