// The brain's own tools (TM-03b), run by the brain on Claude's behalf so they
// work even in read-only planning turns:
//   post_message        progress / notes to the project's team group
//   preview_html        render an HTML mockup to a PNG and post it ("this is what it will look like")
//   screenshot_url      screenshot an allowed dev / staging page and post it
//   propose_plan        record a plan for approval; the team replies "@bot ok <n>"
//   needs_attention     tell the owner something needs them (a permission, a check in Claude Code, a decision)
// Everything goes to the team group only; customer groups are never reachable.

import { createSdkMcpServer, tool } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";

const MAX_TEXT = 3800;

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

/**
 * @param {{
 *   ctx: { project: string, chat: string, chat_name: string, reply_chat: string, sender: string },
 *   listener: { send(b: object): Promise<any>, addItem(b: object): Promise<any> },
 *   render: { html(html: string, width: number): Promise<Buffer>, url(url: string, width: number, fullPage: boolean): Promise<Buffer> } | null,
 *   plans: { save(plan: object): object },
 *   screenshotHosts: string[],
 * }} deps
 */
export function brainTools({ ctx, listener, render, plans, screenshotHosts }) {
  const post = (body) => listener.send({ chat: ctx.reply_chat, project: ctx.project, ...body });
  const image = async (png, caption) => {
    await post({ image_base64: png.toString("base64"), caption: caption?.slice(0, 1000) || undefined });
    return { content: [{ type: "image", data: png.toString("base64"), mimeType: "image/png" }, { type: "text", text: "Posted to the team group." }] };
  };
  const fail = (text) => ({ content: [{ type: "text", text }], isError: true });

  const tools = [
    tool(
      "post_message",
      "Post a short message to the project's WhatsApp team group now (progress on long work, a heads-up). Your final answer is posted automatically; don't repeat it here.",
      { text: z.string().min(1).max(MAX_TEXT) },
      async ({ text }) => (await post({ text }), { content: [{ type: "text", text: "Posted." }] }),
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
      "propose_plan",
      "Record a plan for a change so the team can approve it. Call this once your plan is ready (after any previews). It logs a request and returns its number; end your reply by asking for '@bot ok <number>'. Nothing gets changed until then.",
      {
        title: z.string().min(3).max(120).describe("Short English title"),
        plan: z.string().min(10).max(6000).describe("What you'll change, where, how you'll test it, and the git steps"),
        type: z.enum(["bug", "feature", "task"]).optional(),
      },
      async ({ title, plan, type }) => {
        let itemId = null;
        try {
          const r = await listener.addItem({ chat: ctx.chat, project: ctx.project, type: type || "task", title, summary: plan, created_by: `${ctx.sender} via bot` });
          itemId = r?.item?.id ?? null;
        } catch {
          // the request log is a convenience; the plan still stands
        }
        const saved = plans.save({ id: itemId, project: ctx.project, chat: ctx.chat, chat_name: ctx.chat_name, title, plan, by: ctx.sender });
        return { content: [{ type: "text", text: `Plan [${saved.id}] recorded. Ask the team to reply "@bot ok ${saved.id}" to go ahead.` }] };
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
        return { content: [{ type: "text", text: "Flagged to the owner in the team group." }] };
      },
    ),
  ];
  return createSdkMcpServer({ name: "whatsapp", version: "1.0.0", tools });
}

export const BRAIN_TOOL_NAMES = ["post_message", "preview_html", "screenshot_url", "propose_plan", "needs_attention"].map((t) => `mcp__whatsapp__${t}`);
