// HTML mockups and dev-site pages to PNG, for previews in WhatsApp (TM-03b).
// Headless Chromium via playwright-core; the browser is installed by the deploy
// workflow into PLAYWRIGHT_BROWSERS_PATH (/opt/pw-browsers).

import { chromium } from "playwright-core";

export function createRenderer({ executablePath = process.env.TEAMMATE_CHROMIUM || undefined } = {}) {
  async function withPage(viewport, fn, { javaScriptEnabled = true, blockNetwork = false } = {}) {
    const browser = await chromium.launch({ headless: true, executablePath });
    try {
      const context = await browser.newContext({ viewport, javaScriptEnabled, deviceScaleFactor: 2 });
      if (blockNetwork) await context.route("**/*", (r) => (r.request().url().startsWith("data:") ? r.continue() : r.abort()));
      const page = await context.newPage();
      return await fn(page);
    } finally {
      await browser.close();
    }
  }
  return {
    /** A mockup: scripts off, network blocked -- only what's inline shows. */
    html: (html, width) =>
      withPage({ width, height: 120 }, async (page) => {
        await page.setContent(html, { waitUntil: "load", timeout: 15_000 });
        return page.screenshot({ fullPage: true, type: "png" });
      }, { javaScriptEnabled: false, blockNetwork: true }),
    /** A real page on an allowed host (checked by the caller). */
    url: (url, width, fullPage) =>
      withPage({ width, height: 900 }, async (page) => {
        await page.goto(url, { waitUntil: "networkidle", timeout: 45_000 });
        return page.screenshot({ fullPage, type: "png" });
      }),
  };
}
