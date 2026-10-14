// HTML mockups and dev-site pages to PNG, for previews in WhatsApp (TM-03b).
// Headless Chromium via playwright-core; the browser is installed by the deploy
// workflow into PLAYWRIGHT_BROWSERS_PATH (/opt/pw-browsers).
//
// Dev-site login (optional): with TEAMMATE_DEV_LOGIN_HOST / _USER / _PASSWORD set, a page on that host that
// redirects to /login is signed in with that test account, and the session is kept in `stateFile` so later
// screenshots don't log in again. The credentials stay in this process; Claude only ever gets the picture.

import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

export function createRenderer({
  executablePath = process.env.TEAMMATE_CHROMIUM || undefined,
  login = null, // { host, user, password, path? }
  stateFile = null,
} = {}) {
  async function withPage(viewport, fn, { javaScriptEnabled = true, blockNetwork = false, keepState = false } = {}) {
    const browser = await chromium.launch({ headless: true, executablePath });
    try {
      const storageState = keepState && stateFile && existsSync(stateFile) ? stateFile : undefined;
      const context = await browser.newContext({ viewport, javaScriptEnabled, deviceScaleFactor: 2, storageState });
      if (blockNetwork) await context.route("**/*", (r) => (r.request().url().startsWith("data:") ? r.continue() : r.abort()));
      const page = await context.newPage();
      return await fn(page, context);
    } finally {
      await browser.close();
    }
  }

  async function signInIfAsked(page, context, url) {
    if (!login || new URL(url).hostname !== login.host) return;
    if (!new URL(page.url()).pathname.startsWith(login.path || "/login")) return;
    await page.fill('input[name="username"]', login.user);
    await page.fill('input[name="password"]', login.password);
    await Promise.all([
      page.waitForURL((u) => !new URL(u).pathname.startsWith(login.path || "/login"), { timeout: 30_000 }),
      page.click('button[type="submit"]'),
    ]);
    if (stateFile) await context.storageState({ path: stateFile });
    await page.goto(url, { waitUntil: "networkidle", timeout: 45_000 });
  }

  return {
    /** A mockup: scripts off, network blocked -- only what's inline shows. */
    html: (html, width) =>
      withPage({ width, height: 120 }, async (page) => {
        await page.setContent(html, { waitUntil: "load", timeout: 15_000 });
        return page.screenshot({ fullPage: true, type: "png" });
      }, { javaScriptEnabled: false, blockNetwork: true }),
    /** A real page on an allowed host (checked by the caller); signs in to the dev site when it asks. */
    url: (url, width, fullPage) =>
      withPage({ width, height: 900 }, async (page, context) => {
        await page.goto(url, { waitUntil: "networkidle", timeout: 45_000 });
        await signInIfAsked(page, context, url);
        return page.screenshot({ fullPage, type: "png" });
      }, { keepState: true }),
  };
}
