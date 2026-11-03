// TM-59 (3 Nov): every alarm went through the team's WhatsApp link, an unofficial linked number that can log out or
// be blocked; then every alarm stops at once and the group looks calm. A second way out that doesn't need WhatsApp:
// TEAMMATE_ALERT_URL (the deploy fills it from the NOTIFY_WEBHOOK_URL secret, the one the uptime check already uses).
//   • an ntfy.sh topic URL (push to a phone, no account: install the ntfy app and subscribe to the topic): plain text
//   • any other URL (Slack / Discord / Google Chat incoming webhook): JSON { text, content }
// Alarms only, never customer data: what is down and since when.

export async function sendAlarm(url, text, { fetchFn = fetch, log = () => {} } = {}) {
  if (!url) return false;
  try {
    const ntfy = /(^|\.)ntfy\./i.test(new URL(url).hostname);
    const res = await fetchFn(url, ntfy
      ? { method: "POST", headers: { title: "Mesiri team bot", tags: "rotating_light" }, body: text, signal: AbortSignal.timeout(10_000) }
      : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, content: text }), signal: AbortSignal.timeout(10_000) });
    if (!res.ok) log(`alarm: the alert URL answered HTTP ${res.status}`);
    return res.ok;
  } catch (e) {
    log(`alarm: ${e.message}`);
    return false;
  }
}

export const LINK_DOWN_AFTER_MS = 5 * 60_000;

/** The WhatsApp link itself: when it isn't connected for 5 minutes, only the second channel can say so. */
export class LinkWatch {
  constructor({ status, alarm, now = () => Date.now(), downAfterMs = LINK_DOWN_AFTER_MS }) {
    Object.assign(this, { status, alarm, now, downAfterMs });
    this.badSince = null;
    this.alerted = false;
  }

  async tick() {
    const state = String(this.status()?.state || "unknown");
    const now = this.now();
    if (state === "connected") {
      if (this.alerted) await this.alarm(`✅ The team's WhatsApp link is connected again (it was down about ${Math.round((now - this.badSince) / 60_000)} min).`);
      this.badSince = null;
      this.alerted = false;
      return "up";
    }
    if (this.badSince == null) this.badSince = now;
    if (!this.alerted && now - this.badSince >= this.downAfterMs) {
      this.alerted = true;
      const since = new Date(this.badSince + 330 * 60_000).toISOString().slice(11, 16);
      const fix = state === "logged_out" || state === "waiting_for_pairing" ? " It must be paired again: `python3 teammate/inbox.py pair <phone>`." : "";
      await this.alarm(`🚨 The team's WhatsApp link is ${state.replace(/_/g, " ")} since ${since} IST: no request, update or alarm reaches the team group until it's back.${fix}`);
    }
    return "down";
  }
}

/**
 * TM-61 (3 Nov): a full disk stops the app, the bot and its builds at once, and nothing watched it (`vps-check` only
 * runs by hand). Every 10 min the listener reads free space on the paths it is given; under 10 % or 3 GB free it says
 * so once in the team groups and by the second way, again a day later if still low, and once when it is fine again.
 */
export class DiskWatch {
  constructor({ paths, statfs, post, now = () => Date.now(), minFree = 0.1, minBytes = 3 * 2 ** 30, againMs = 86_400_000 }) {
    Object.assign(this, { paths, statfs, post, now, minFree, minBytes, againMs });
    this.low = new Map(); // path -> last alert time
  }

  async tick() {
    const out = [];
    const seen = new Set(); // paths on the same disk are said once
    for (const path of this.paths) {
      let s;
      try {
        s = await this.statfs(path);
      } catch {
        continue; // a path not on this server
      }
      const disk = `${s.type}:${s.blocks}:${s.bsize}`;
      if (seen.has(disk)) continue;
      seen.add(disk);
      const total = Number(s.blocks) * Number(s.bsize);
      const free = Number(s.bavail) * Number(s.bsize);
      const gb = (free / 2 ** 30).toFixed(1);
      const pct = total ? Math.round((free / total) * 100) : 0;
      const isLow = free < this.minBytes || (total && free / total < this.minFree);
      const last = this.low.get(path);
      if (isLow && (last == null || this.now() - last >= this.againMs)) {
        this.low.set(path, this.now());
        out.push(`🙋 *Needs you:* the server's disk is nearly full at ${path}: ${gb} GB free (${pct} %). When it fills, Mesiri, the team bot and its builds stop. Clear old build copies, logs or backups.`);
      } else if (!isLow && last != null) {
        this.low.delete(path);
        out.push(`✅ Disk space is fine again at ${path}: ${gb} GB free (${pct} %).`);
      }
    }
    for (const text of out) await this.post(text);
    return out.length;
  }
}
