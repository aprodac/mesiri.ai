// The watchdog over cloud jobs (request 139). Called on a timer (main.js, every 10 min) for each plan whose status is
// running_in_cloud. It posts to the group when something happens and never twice for the same event:
//   • a new commit on the branch, once its deploy has a result: "[n] pushed <sha>, deploy green/red"
//   • 30 min with no note and no commit: "quiet for 30 min", once per stretch of silence, with the session link
//   • deploy green for 20 min, the session never reported: "landed but didn't report", item marked done with the sha

import { readFileSync, writeFileSync, renameSync, existsSync } from "node:fs";

const MIN = 60_000;
export const WATCH_DEFAULTS = { stallMs: 30 * MIN, reportAfterMs: 20 * MIN, deployWaitMs: 30 * MIN };

function readJson(path, fallback) {
  try {
    return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : fallback;
  } catch {
    return fallback;
  }
}

export class Watchdog {
  /** @param {object} brain the Brain (planStore, listener, workStatus, savePlans, now, log) */
  constructor(brain, { dir, cfg = WATCH_DEFAULTS }) {
    this.brain = brain;
    this.file = `${dir}/watch.json`;
    this.cfg = cfg;
    this.s = readJson(this.file, {});
    this.busy = false;
  }

  save() {
    writeFileSync(`${this.file}.tmp`, JSON.stringify(this.s, null, 2));
    renameSync(`${this.file}.tmp`, this.file);
  }

  /** One pass over every running cloud job. */
  async tick() {
    if (this.busy) return;
    this.busy = true;
    try {
      const running = Object.values(this.brain.planStore.plans).filter((p) => p.status === "running_in_cloud");
      for (const plan of running) {
        try {
          await this.check(plan);
        } catch (e) {
          this.brain.log(`watchdog: [${plan.id}] ${e.message}`);
        }
      }
    } finally {
      this.busy = false;
    }
  }

  async check(plan) {
    const b = this.brain;
    const now = b.now().getTime();
    const ws = await b.workStatus(plan);
    const st = (this.s[plan.id] ||= { posted: [], stallFor: null });
    const say = (text) => b.listener.send({ chat: plan.reply_chat || plan.chat, project: plan.reply_project || plan.chat_project || plan.project, text }).catch(() => null);
    const tag = `[${plan.id}]`;

    // The session reported by itself (item done / dropped): nothing for the watchdog to say.
    if (ws.item?.status === "done" || ws.item?.status === "wont_do") {
      plan.status = ws.item.status === "done" ? "done" : "failed";
      b.savePlans();
      delete this.s[plan.id];
      this.save();
      return;
    }

    for (const c of ws.commits) {
      if (st.posted.includes(c.sha)) continue;
      const decided = c.deploy.state === "green" || c.deploy.state === "red";
      if (!decided && now - Date.parse(c.at) < this.cfg.deployWaitMs) continue; // wait for the deploy's result
      st.posted.push(c.sha);
      this.save();
      const how = { green: "deploy green ✅", red: "deploy red ❌", running: "deploy still running", none: "no deploy run seen" }[c.deploy.state];
      const link = c.deploy.state === "red" && c.deploy.url ? `\n${c.deploy.url}` : "";
      await say(`${tag} pushed ${c.short} “${String(c.subject).slice(0, 80)}”, ${how}.${link}`);
    }

    // Deployed, then silence: the session finished (or died) without its ✅.
    const last = ws.commits.at(-1);
    if (last?.deploy.state === "green" && now - Date.parse(last.deploy.at) >= this.cfg.reportAfterMs) {
      const after = ws.heartbeat && Date.parse(ws.heartbeat.at) > Date.parse(last.deploy.at);
      if (!after) {
        plan.status = "done";
        b.savePlans();
        if (typeof plan.id === "number") await b.listener.updateItem(plan.id, { status: "done", ref: last.short, note: `watchdog: landed ${last.short}, deploy green, the session did not report`, project: plan.reply_project || plan.chat_project || plan.project }).catch(() => {});
        delete this.s[plan.id];
        this.save();
        await say(`${tag} landed but didn't report: ${last.short} is deployed (green) and the session said nothing for ${Math.round(this.cfg.reportAfterMs / MIN)} min. Marked done with ${last.short}.`);
        return;
      }
    }

    // No sign of life.
    const quiet = ws.lastActivityAt ? now - ws.lastActivityAt : 0;
    if (ws.lastActivityAt && quiet >= this.cfg.stallMs && st.stallFor !== ws.lastActivityAt) {
      st.stallFor = ws.lastActivityAt;
      this.save();
      await say(`${tag} quiet for ${Math.round(quiet / MIN)} min: no note and no commit from the session.\nCheck it: ${ws.session_url || "(no link)"}\n@bot status ${plan.id} shows the details; @bot tell ${plan.id} <message> starts a follow-up.`);
    }
  }
}
