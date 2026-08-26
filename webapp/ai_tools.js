/* Env Hub Analyzer - AI tool-loop helpers (pure, no DOM).
 * Loaded by index.html as a plain script (window.EnvAiTools) and by
 * tests/sql_validator.test.mjs via require(). Everything here is
 * deterministic so the SQL gate can be unit-tested without a browser.
 * See docs/research-web-ai-and-pyodide-query.md for the design brief. */
(function (root) {
  "use strict";

  // metric columns in the readings table, same order as index.html METRICS
  const METRICS = ["tc","rh","co2","pm1","pm25","pm4","pm10","voc","nox","vb"];
  // units per metric for the schema doc shown to the model
  const UNITS = {tc:"degC",rh:"%",co2:"ppm",pm1:"ug/m3",pm25:"ug/m3",pm4:"ug/m3",
    pm10:"ug/m3",voc:"index(base 100)",nox:"index(base 1)",vb:"volts"};
  // tables + columns the model may reference (identifier allowlist)
  const SQL_TABLES = {
    readings: ["ts","src", ...METRICS, "flags"],
    days: ["day","rows","sources"],
    zones: ["src","rows","first_ts","last_ts"],
    thresholds: ["metric","lo_bad","lo_warn","warn","bad"],
  };
  // SQL keywords / functions allowed outside string literals
  const SQL_WORDS = ("select with from where group by order having limit offset as and or not"
    + " null is in between like glob case when then else end distinct count sum avg min max total"
    + " abs round cast integer real text coalesce ifnull nullif length substr lower upper printf"
    + " group_concat strftime datetime date time julianday unixepoch localtime asc desc union all"
    + " on join left inner cross using exists over partition rows unbounded preceding following"
    + " current row row_number rank dense_rank lag lead first_value last_value true false"
    + " recursive filter escape collate nocase").split(" ");
  // statements/functions that must never reach SQLite
  const SQL_BAD = /\b(attach|detach|pragma|insert|update|delete|drop|create|alter|replace|vacuum|reindex|load_extension|readfile|writefile|sqlite_master|sqlite_schema|sqlite_temp_master|zipfile|fts\w*|json_\w*)\b/i;

  // structured reply the model must return each turn (Nano prefers a flat schema; the
  // page enforces the either/or: tool+query for a query, answer for the final prose)
  const TOOL_SCHEMA = {
    type: "object",
    properties: {
      tool: {type: "string", enum: ["sql"], description: "set to sql to request one query"},
      query: {type: "string", description: "one read-only SELECT (only with tool)"},
      reason: {type: "string", description: "<=12 words why (only with tool)"},
      answer: {type: "string", description: "final plain-prose answer with numbers+units"},
    },
  };

  // aliases declared in the query (AS x, FROM t x, JOIN t x) so they pass the allowlist
  function aliasesOf(q) {
    const out = new Set();
    for (const m of q.matchAll(/\bas\s+([A-Za-z_]\w*)/gi)) out.add(m[1].toLowerCase());
    for (const m of q.matchAll(/\b(?:with|,)\s*([A-Za-z_]\w*)\s+as\s*\(/gi)) out.add(m[1].toLowerCase());
    for (const m of q.matchAll(/\b(?:from|join)\s+([A-Za-z_]\w*)\s+(?!as\b)([A-Za-z_]\w*)/gi))
      if (!SQL_WORDS.includes(m[2].toLowerCase())) out.add(m[2].toLowerCase());
    return out;
  }

  // gate a model-proposed query: SELECT-only, single statement, known identifiers,
  // LIMIT clamped to maxRows; returns the SQL to execute or throws a reason
  function validateSql(sql, tables = SQL_TABLES, maxRows = 50) {
    let q = String(sql || "").trim().replace(/;+\s*$/, "").trim();
    if (!q) throw new Error("empty query");
    if (q.includes(";")) throw new Error("only one statement allowed");
    if (/--|\/\*/.test(q)) throw new Error("comments are not allowed");
    if (!/^(select|with)\b/i.test(q)) throw new Error("SELECT only");
    if (SQL_BAD.test(q)) throw new Error("read-only queries only");
    const known = new Set([...Object.keys(tables), ...Object.values(tables).flat(),
      ...SQL_WORDS, ...aliasesOf(q)]);
    const bare = q.replace(/'(?:[^']|'')*'/g, " ").replace(/"[^"]*"/g, " ");
    if (bare.includes("'")) throw new Error("unbalanced quote");
    const toks = bare.match(/\d+(?:\.\d*)?(?:e[+-]?\d+)?|[A-Za-z_]\w*/gi) || [];
    for (const w of toks) {
      if (/^\d/.test(w)) continue;
      if (!known.has(w.toLowerCase())) throw new Error("unknown identifier: " + w);
    }
    if (/\blimit\s+\d+/i.test(q))
      q = q.replace(/\blimit\s+(\d+)/i, (m, n) => "LIMIT " + Math.min(+n, maxRows));
    else q += " LIMIT " + maxRows;
    return q;
  }

  // parse the model's JSON reply leniently (first {...} block if it added prose)
  function parseToolReply(text) {
    const s = String(text || "");
    try { return JSON.parse(s); } catch (e) { /* fall through */ }
    const a = s.indexOf("{"), b = s.lastIndexOf("}");
    if (a < 0 || b <= a) throw new Error("no JSON object in reply");
    return JSON.parse(s.slice(a, b + 1));
  }

  // decide what the reply asks for: {kind:"sql",query,reason} | {kind:"answer",text}
  function classifyReply(r) {
    if (r && typeof r.query === "string" && r.query.trim() && (r.tool === "sql" || !r.answer))
      return {kind: "sql", query: r.query, reason: r.reason || ""};
    if (r && typeof r.answer === "string" && r.answer.trim()) return {kind: "answer", text: r.answer};
    throw new Error("reply had neither a query nor an answer");
  }

  // shrink a query result to the token budget: <=maxRows rows and ~maxChars of JSON
  function capToolResult(res, maxRows = 50, maxChars = 2000) {
    const out = {cols: res.cols || [], rows: (res.rows || []).slice(0, maxRows),
      row_count: res.row_count != null ? res.row_count : (res.rows || []).length,
      truncated: !!res.truncated || (res.rows || []).length > maxRows};
    while (JSON.stringify(out).length > maxChars && out.rows.length > 1) {
      out.rows.pop(); out.truncated = true;
    }
    return out;
  }

  // compact schema description (~100 tokens) filled from the loaded dataset
  function schemaDoc(meta) {
    const cols = METRICS.map(m => `${m} ${UNITS[m]}`).join(", ");
    const off = meta.tzOffsetMin || 0, sign = off >= 0 ? "+" : "-", ah = Math.abs(off);
    const tz = `${sign}${String(Math.floor(ah / 60)).padStart(2, "0")}:${String(ah % 60).padStart(2, "0")}`;
    return `SQLite tables (read-only):
readings(ts INT epoch-s UTC, src TEXT zone, ${cols}, flags INT) - NULL where a zone lacks a sensor
days(day TEXT 'YYYY-MM-DD', rows INT, sources TEXT)
zones(src, rows, first_ts, last_ts)
thresholds(metric, lo_bad, lo_warn, warn, bad) - warn/bad = too high, lo_* = too low
zones present: ${(meta.sources || []).join(", ")}
data range: ${meta.from} .. ${meta.to} UTC, ${meta.rows} rows over ${meta.days} day(s); local time is UTC${tz}
bucket by hour: strftime('%Y-%m-%d %H', ts, 'unixepoch'); by day: date(ts, 'unixepoch')`;
  }

  // the domain guidance kept from the original assistant prompt
  const DOMAIN_PROMPT = `You are the analyst for a home environmental monitoring hub (CO2 ppm,
temperature degC, relative humidity %, particulates ug/m3, VOC and NOx index, node battery
volts). Out-of-spec runs BOTH ways: values below the normal range are also warn/bad - low
temperature, low humidity, low battery volts, and CO2 below ~400 ppm (physically implausible
indoors: a sensor/calibration fault, not good air). VOC and NOx are Sensirion INDEX values, not
concentrations: VOC settles to a baseline of 100 (higher = worse than the recent norm), NOx to 1
and is rarely relevant indoors. Users speak casually: "totally fucked" / "how bad" mean "how far
beyond acceptable limits and for how long". A good answer gives 1) what happened with numbers,
peaks and durations, 2) a verdict: fine / briefly out of range / bad / severely out of range for
an excessive period, 3) anything to check. If gaps overlap the period say the record is incomplete.`;

  // tool-protocol rules + few-shot examples the model sees at session creation
  function buildSystemPrompt(meta) {
    return `${DOMAIN_PROMPT}

TOOL: you have a Python/Pyodide tool holding the user's data in an in-memory sqlite3 database.
${schemaDoc(meta)}
Rules: reply with JSON only. To look something up reply {"tool":"sql","query":"SELECT ...","reason":"..."}
- at most ONE query per turn, SELECT only, prefer aggregates (MIN/MAX/AVG/COUNT, GROUP BY src or
day/hour), never raw rows without LIMIT (results are capped at 50 rows / ~2000 chars). The next
turn gives you {"tool_result":{"cols":[...],"rows":[...],"row_count":n}} plus the original question.
When you have the numbers reply {"answer":"..."}: brief plain prose with numbers and units. Never
guess values you have not queried; if a query errors, fix it or say what you could not get.

Example 1
Q: what was the worst CO2 and where?
A: {"tool":"sql","query":"SELECT src, MAX(co2) AS peak, COUNT(*) AS n FROM readings WHERE co2 IS NOT NULL GROUP BY src ORDER BY peak DESC","reason":"peak CO2 per zone"}
{"tool_result":{"cols":["src","peak","n"],"rows":[["bedroom",2310,4100],["local",1480,4200]],"row_count":2}}
A: {"answer":"Worst CO2 was in bedroom: peak 2310 ppm (bad, threshold 2000). The hub (local) peaked at 1480 ppm - warn level."}

Example 2
Q: how long was humidity above 70% yesterday in the shed?
A: {"tool":"sql","query":"SELECT COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts, MAX(rh) AS peak FROM readings WHERE src='shed' AND rh>70 AND date(ts,'unixepoch')='2026-08-23'","reason":"count samples above 70% on that day"}
{"tool_result":{"cols":["n","first_ts","last_ts","peak"],"rows":[[52,1787428800,1787444100,81.5]],"row_count":1}}
A: {"answer":"Shed humidity was above 70% for about 4.3 h on 2026-08-23 (52 five-minute samples, 08:00-12:15 UTC), peaking at 81.5% - bad (threshold 70%). Check the dehumidifier."}

Example 3
Q: which hour had the highest PM2.5?
A: {"tool":"sql","query":"SELECT strftime('%Y-%m-%d %H',ts,'unixepoch') AS hour, src, ROUND(AVG(pm25),1) AS avg_pm25 FROM readings WHERE pm25 IS NOT NULL GROUP BY hour, src ORDER BY avg_pm25 DESC LIMIT 3","reason":"worst hours by mean PM2.5"}
{"tool_result":{"cols":["hour","src","avg_pm25"],"rows":[["2026-08-22 18","local",41.2],["2026-08-22 19","local",33.8],["2026-08-22 17","local",22.5]],"row_count":3}}
A: {"answer":"The worst hour was 2026-08-22 18:00 UTC at the hub (local): mean PM2.5 41.2 ug/m3, above the bad threshold of 35 ug/m3 - probably cooking or an open window near traffic."}`;
  }

  // canned questions for the no-model fallback: {label, sql(metric, zone, from, to)}
  // from/to are epoch seconds (UTC); zone "" means all zones
  const CANNED = [
    {id: "stats", label: "min / mean / max per zone",
      sql: (m, z, a, b) => `SELECT src, ROUND(MIN(${m}),2) AS min, ROUND(AVG(${m}),2) AS mean, ROUND(MAX(${m}),2) AS max, COUNT(*) AS n FROM readings WHERE ${m} IS NOT NULL AND ts BETWEEN ${a} AND ${b}${z} GROUP BY src ORDER BY max DESC`},
    {id: "daily", label: "daily max per zone",
      sql: (m, z, a, b) => `SELECT date(ts,'unixepoch') AS day, src, ROUND(MAX(${m}),2) AS max, ROUND(AVG(${m}),2) AS mean FROM readings WHERE ${m} IS NOT NULL AND ts BETWEEN ${a} AND ${b}${z} GROUP BY day, src ORDER BY day, src`},
    {id: "worst_hour", label: "worst hours (highest hourly mean)",
      sql: (m, z, a, b) => `SELECT strftime('%Y-%m-%d %H',ts,'unixepoch') AS hour, src, ROUND(AVG(${m}),2) AS mean, MAX(${m}) AS peak FROM readings WHERE ${m} IS NOT NULL AND ts BETWEEN ${a} AND ${b}${z} GROUP BY hour, src ORDER BY mean DESC LIMIT 10`},
    {id: "above", label: "samples at/above the 'warn' and 'bad' thresholds",
      sql: (m, z, a, b) => `SELECT r.src, COUNT(*) AS n, SUM(r.${m} >= t.warn) AS n_warn, SUM(r.${m} >= t.bad) AS n_bad, MAX(r.${m}) AS peak FROM readings r JOIN thresholds t ON t.metric='${m}' WHERE r.${m} IS NOT NULL AND r.ts BETWEEN ${a} AND ${b}${z.replace(/\bsrc\b/g, "r.src")} GROUP BY r.src`},
    {id: "below", label: "samples at/below the low thresholds",
      sql: (m, z, a, b) => `SELECT r.src, COUNT(*) AS n, SUM(r.${m} <= t.lo_warn) AS n_lo_warn, SUM(r.${m} <= t.lo_bad) AS n_lo_bad, MIN(r.${m}) AS low FROM readings r JOIN thresholds t ON t.metric='${m}' WHERE r.${m} IS NOT NULL AND r.ts BETWEEN ${a} AND ${b}${z.replace(/\bsrc\b/g, "r.src")} GROUP BY r.src`},
  ];

  const api = {METRICS, UNITS, SQL_TABLES, SQL_WORDS, SQL_BAD, TOOL_SCHEMA, CANNED,
    validateSql, parseToolReply, classifyReply, capToolResult, schemaDoc, buildSystemPrompt};
  root.EnvAiTools = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof self !== "undefined" ? self : globalThis);
