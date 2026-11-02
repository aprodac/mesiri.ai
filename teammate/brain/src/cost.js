// TM-20: what production's AI calls cost, for `@bot cost`. One SELECT through the project's read-only ops API
// (the production watch's token, which stays here: the listener only gets the totals). Each row is one line of the
// reply: `section` is work | company | day | unpriced, `name` the thing inside it.
import { asObjects } from "./prod_watch.js";

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

const totals = "count(*)::int AS calls, COALESCE(round(sum(cost_inr), 2), 0)::float AS inr, (count(*) FILTER (WHERE cost_inr IS NULL))::int AS unpriced";

/** The company rule is `_ORG` in usage_costs.py. `since` and `until` are checked ISO times, never message text. */
export function costSql({ since, until = null }) {
  if (!ISO.test(since) || (until && !ISO.test(until))) throw new Error("bad period");
  return `WITH c AS (
  SELECT pe.provider, pe.model, pe.cost_inr, COALESCE(pe.purpose, pe.operation) AS work, o.name AS company,
         (pe.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day
  FROM provider_executions pe
  LEFT JOIN organizations o ON o.id = COALESCE(pe.organization_id,
    (SELECT im.organization_id FROM inbound_messages im WHERE im.correlation_id = pe.correlation_id LIMIT 1))
  WHERE pe.metered AND pe.provider <> 'whatsapp' AND pe.created_at >= '${since}'
    ${until ? `AND pe.created_at < '${until}'` : ""}
)
SELECT 'work' AS section, CASE WHEN provider = 'gemini' THEN work ELSE provider END AS name, ${totals} FROM c GROUP BY 2
UNION ALL SELECT 'company', company, ${totals} FROM c WHERE provider = 'gemini' GROUP BY 2
UNION ALL SELECT 'day', day::text, ${totals} FROM c WHERE provider = 'gemini' GROUP BY 2
UNION ALL SELECT 'unpriced', model, ${totals} FROM c WHERE provider = 'gemini' AND cost_inr IS NULL GROUP BY 2`;
}

/** @param source {url, token} from opsSources */
export async function costRows(source, period, fetchFn = fetch) {
  const res = await fetchFn(`${source.url}/claude-ops/sql`, {
    method: "POST",
    headers: { authorization: `Bearer ${source.token}`, "content-type": "application/json" },
    body: JSON.stringify({ sql: costSql(period) }),
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`ops API HTTP ${res.status}`);
  return asObjects(await res.json());
}
