// TM-83: one problem, one request, one build. 4 Nov: [235], [236] and [238] were all "my requests list ([230]) doesn't
// work", logged within 4 minutes, and two were built at once; [234] repeated [229] half an hour after it shipped; on
// 3 Nov [211], [214], [216] all re-opened [207]. The only guard was a sentence in the planner's prompt. Here the code
// decides: a follow-up of a request that is still open joins it; anything else that looks like a recent request from
// the same people must be named "same as [n]" (merged) or "different because ..." before it is recorded.
import { reopens } from "./board.js";

/** A plan nobody has finished: proposed, waiting, building or built-but-not-pushed. */
export const OPEN = new Set(["proposed", "approved", "running_in_cloud", "running_here", "unpushed", "review_failed"]);
/** A plan being built right now (a second build of the same problem must wait). */
export const BUILDING = new Set(["approved", "running_in_cloud", "running_here"]);
const DAY = 86_400_000;

/** The request numbers a plan says it follows up or re-opens, plus the one it is a live-check fix of. */
export function refsOf(plan) {
  const ids = new Set(reopens({ id: plan.id ?? null, title: plan.title, summary: plan.plan }));
  if (plan.fix_of != null) ids.add(Number(plan.fix_of));
  return ids;
}

/** Every plan in the chain of request `root`: the request itself and every plan that follows it up (any depth). */
export function chainOf(root, all) {
  const chain = new Set([Number(root)]);
  for (let grew = true; grew; ) {
    grew = false;
    for (const p of all) {
      if (typeof p.id !== "number" || chain.has(p.id)) continue;
      if ([...refsOf(p)].some((r) => chain.has(r))) chain.add(p.id), (grew = true);
    }
  }
  return all.filter((p) => chain.has(p.id));
}

/**
 * The open plan this new one belongs to, by what the code can see for certain: it follows up / re-opens a request
 * whose chain still has an open plan, or it was asked in the same production messages as an open plan. The newest
 * open plan of the chain wins (it is the one being worked on). null when there is none.
 */
export function coveringPlan(plan, all, { asked = [] } = {}) {
  const others = all.filter((p) => p.id !== plan.id && OPEN.has(p.status));
  const viaRef = [...refsOf(plan)].flatMap((r) => chainOf(r, all)).filter((p) => p.id !== plan.id && OPEN.has(p.status));
  const viaAsk = asked.length ? others.filter((p) => (p.asked_for || []).some((c) => asked.includes(c))) : [];
  const hits = [...viaRef, ...viaAsk];
  if (!hits.length) return null;
  return hits.sort((a, b) => Date.parse(b.at || 0) - Date.parse(a.at || 0))[0];
}

/** "Paraclette" from "Ilan (ADMIN, Paraclette)". */
export function companyOf(askedBy) {
  const m = String(askedBy || "").match(/\(([^)]*)\)\s*$/);
  return m ? m[1].split(",").at(-1).trim().toLowerCase() || null : null;
}

/**
 * Recent requests that MAY be the same problem, for the planner to rule on: from the last 24 h, not dropped, from the
 * same company (production) or the same group (team asks). Newest first, at most 8.
 */
export function candidatesFor({ asked_by = null, chat = null }, all, now = Date.now()) {
  const company = companyOf(asked_by);
  return all
    .filter((p) => typeof p.id === "number" && p.status !== "failed" && p.status !== "stale" && now - Date.parse(p.at || 0) < DAY)
    .filter((p) => (company ? companyOf(p.asked_by) === company : p.chat === chat))
    .sort((a, b) => b.id - a.id)
    .slice(0, 8);
}

/** "[236] building · "[230] follow-up: show my requests …"" lines for the planner. */
export function candidateLines(list) {
  const what = { proposed: "planned", approved: "starting", running_in_cloud: "building", running_here: "building", unpushed: "built, not pushed", review_failed: "review failed", done: "shipped" };
  return list.map((p) => `[${p.id}] ${what[p.status] || p.status} · ${String(p.title).slice(0, 100)}`).join("\n");
}
