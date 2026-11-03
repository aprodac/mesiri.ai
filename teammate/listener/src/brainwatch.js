// 3 Nov: the team bot (brain) crash-looped all night and nobody knew; the GitHub uptime check that was meant to see it
// runs "every 10 minutes" on paper but GitHub ran it every few hours (8 runs in 2 days). The listener is a separate
// process that stayed up all night, and it can post in the team groups itself: it looks at the brain every minute and
// says so once when the brain has been down (or restarting in a loop) for DOWN_AFTER_MS, and once when it is back.

export const DOWN_AFTER_MS = 3 * 60_000;
/** Up this long counts as up; a crash loop restarts every few seconds and never gets here. */
export const STABLE_S = 30;

export class BrainWatch {
  /**
   * @param o.health  () => Promise<{state: "up"|"down", up_s?: number}>
   * @param o.post    (text) => Promise<void>   posts in every team group
   */
  constructor({ health, post, now = () => Date.now(), log = () => {}, downAfterMs = DOWN_AFTER_MS }) {
    Object.assign(this, { health, post, now, log, downAfterMs });
    this.badSince = null;
    this.alerted = false;
  }

  /** One look. Never throws. */
  async tick() {
    let h;
    try {
      h = await this.health();
    } catch {
      h = { state: "down" };
    }
    const ok = h.state === "up" && (h.up_s == null || h.up_s >= STABLE_S);
    const now = this.now();
    if (ok) {
      if (this.alerted) {
        const mins = Math.round((now - this.badSince) / 60_000);
        this.log(`brainwatch: the team bot is back after ${mins} min`);
        await this.post(`✅ The team bot is back (it was down about ${mins} min). Requests made meanwhile are being read now.`).catch(() => {});
      }
      this.badSince = null;
      this.alerted = false;
      return "up";
    }
    if (this.badSince == null) this.badSince = now;
    if (!this.alerted && now - this.badSince >= this.downAfterMs) {
      this.alerted = true;
      const since = new Date(this.badSince + 330 * 60_000).toISOString().slice(11, 16);
      const how = h.state === "up" ? "keeps restarting" : "is not answering";
      this.log(`brainwatch: the team bot ${how} since ${since} IST`);
      await this.post(`🙋 *Needs you:* the team bot ${how} since ${since}. What customers report is kept and is handled once it is back, but nobody is looking at it now. Check the bot server (\`journalctl -u teammate-brain\`).`).catch(() => {});
    }
    return "down";
  }
}
