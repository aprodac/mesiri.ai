// HTML mockups and dev-site pages to PNG, for previews in WhatsApp (TM-03b).
// Headless Chromium via playwright-core; the browser is installed by the deploy
// workflow into PLAYWRIGHT_BROWSERS_PATH (/opt/pw-browsers).
//
// Site logins (optional): one test account per host (Mercon dev site, Mesiri dashboard). A page on that host
// that redirects to /login is signed in with that account, and the session is kept in a per-host state file
// next to `stateFile` so later screenshots don't log in again. The credentials stay in this process; Claude
// only ever gets the picture.

import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { chromium } from "playwright-core";

export function createRenderer({
  executablePath = process.env.TEAMMATE_CHROMIUM || undefined,
  logins = [], // [{ host, user, password, path? }]
  stateFile = null, // a file in the state folder; each host gets its own "<host>.login-state.json" beside it
} = {}) {
  const loginFor = (url) => logins.find((l) => l.host === new URL(url).hostname) || null;
  const stateFor = (url) => (stateFile ? join(dirname(stateFile), `${new URL(url).hostname}.login-state.json`) : null);

  async function withPage(viewport, fn, { javaScriptEnabled = true, blockNetwork = false, stateFrom = null } = {}) {
    const browser = await chromium.launch({ headless: true, executablePath });
    try {
      const state = stateFrom && stateFor(stateFrom);
      const storageState = state && existsSync(state) ? state : undefined;
      const context = await browser.newContext({ viewport, javaScriptEnabled, deviceScaleFactor: 2, storageState });
      if (blockNetwork) await context.route("**/*", (r) => (r.request().url().startsWith("data:") ? r.continue() : r.abort()));
      const page = await context.newPage();
      return await fn(page, context);
    } finally {
      await browser.close();
    }
  }

  async function signInIfAsked(page, context, url) {
    const login = loginFor(url);
    if (!login) return;
    if (!new URL(page.url()).pathname.startsWith(login.path || "/login")) return;
    // Mercon's form names its fields; Mesiri's dashboard uses an email input.
    await page.locator('input[name="username"], input[name="email"], input[type="email"]').first().fill(login.user);
    await page.locator('input[type="password"]').first().fill(login.password);
    await Promise.all([
      page.waitForURL((u) => !new URL(u).pathname.startsWith(login.path || "/login"), { timeout: 30_000 }),
      page.click('button[type="submit"]'),
    ]);
    if (stateFor(url)) await context.storageState({ path: stateFor(url) });
    await page.goto(url, { waitUntil: "networkidle", timeout: 45_000 });
  }

  return {
    /** A mockup: scripts off, network blocked -- only what's inline shows. */
    html: (html, width) =>
      withPage({ width, height: 120 }, async (page) => {
        await page.setContent(html, { waitUntil: "load", timeout: 15_000 });
        return page.screenshot({ fullPage: true, type: "png" });
      }, { javaScriptEnabled: false, blockNetwork: true }),
    /** A real page on an allowed host (checked by the caller); signs in when the site asks and has an account. */
    url: (url, width, fullPage) =>
      withPage({ width, height: 900 }, async (page, context) => {
        await page.goto(url, { waitUntil: "networkidle", timeout: 45_000 });
        await signInIfAsked(page, context, url);
        return page.screenshot({ fullPage, type: "png" });
      }, { stateFrom: url }),
  };
}
