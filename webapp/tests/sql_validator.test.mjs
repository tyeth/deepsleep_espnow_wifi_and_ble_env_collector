// Unit tests for the SQL gate + reply parsing in ai_tools.js. Run: node webapp/tests/sql_validator.test.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const T = createRequire(import.meta.url)(path.join(here, "..", "ai_tools.js"));
let n = 0;
const ok = (name, fn) => { fn(); n++; console.log("ok -", name); };
const rejects = (sql, re) => assert.throws(() => T.validateSql(sql), re, sql);

ok("accepts a plain aggregate and appends LIMIT", () => {
  const q = T.validateSql("SELECT src, MAX(co2) AS peak FROM readings GROUP BY src");
  assert.equal(q, "SELECT src, MAX(co2) AS peak FROM readings GROUP BY src LIMIT 50");
});
ok("strips a trailing semicolon", () => {
  assert.match(T.validateSql("SELECT COUNT(*) AS n FROM readings;"), /^SELECT COUNT\(\*\) AS n FROM readings LIMIT 50$/);
});
ok("clamps an oversized LIMIT and keeps a small one", () => {
  assert.match(T.validateSql("SELECT ts, co2 FROM readings ORDER BY co2 DESC LIMIT 500"), /LIMIT 50$/);
  assert.match(T.validateSql("SELECT ts, co2 FROM readings LIMIT 5"), /LIMIT 5$/);
});
ok("accepts strftime bucketing, string literals with date modifiers, aliases and joins", () => {
  T.validateSql("SELECT strftime('%Y-%m-%d %H', ts, 'unixepoch') AS hour, src, ROUND(AVG(pm25),1) AS avg_pm25 FROM readings WHERE pm25 IS NOT NULL GROUP BY hour, src ORDER BY avg_pm25 DESC LIMIT 3");
  T.validateSql("SELECT r.src, COUNT(*) AS n, SUM(r.co2 >= t.warn) AS n_warn FROM readings r JOIN thresholds t ON t.metric='co2' WHERE r.co2 IS NOT NULL GROUP BY r.src");
  T.validateSql("WITH d AS (SELECT date(ts,'unixepoch') AS day, MAX(rh) AS peak FROM readings GROUP BY day) SELECT day, peak FROM d ORDER BY peak DESC");
  T.validateSql("SELECT * FROM readings WHERE src = 'shed' AND ts BETWEEN 1787356800 AND 1787443200 AND tc < 1.5e1");
});
ok("rejects non-SELECT statements", () => {
  rejects("DELETE FROM readings", /SELECT only/);
  rejects("INSERT INTO readings VALUES (1)", /SELECT only/);
  rejects("PRAGMA table_info(readings)", /SELECT only/);
  rejects("", /empty/);
});
ok("rejects multiple statements and comments", () => {
  rejects("SELECT 1; DROP TABLE readings", /one statement/);
  rejects("SELECT co2 FROM readings -- hidden", /comments/);
});
ok("rejects write/meta keywords even inside a SELECT", () => {
  rejects("SELECT name FROM sqlite_master", /read-only/);
  rejects("SELECT load_extension('x')", /read-only/);
  rejects("SELECT 1 FROM readings WHERE 1 IN (SELECT 1 FROM x ATTACH DATABASE)", /read-only/);
});
ok("rejects unknown tables, columns and functions", () => {
  rejects("SELECT * FROM users", /unknown identifier: users/);
  rejects("SELECT temperature FROM readings", /unknown identifier: temperature/);
  rejects("SELECT randomblob(10) FROM readings", /unknown identifier: randomblob/);
  rejects("SELECT co2 FROM readings WHERE src = 'a' OR '1'='1' AND x", /unknown identifier: x/);
  rejects("SELECT co2 FROM readings WHERE src = 'unterminated", /unbalanced quote/);
});
ok("parses strict and lenient JSON replies and classifies them", () => {
  assert.deepEqual(T.classifyReply(T.parseToolReply('{"tool":"sql","query":"SELECT 1","reason":"r"}')),
    {kind: "sql", query: "SELECT 1", reason: "r"});
  assert.deepEqual(T.classifyReply(T.parseToolReply('Sure! {"answer":"CO2 peaked at 2310 ppm."} hope that helps')),
    {kind: "answer", text: "CO2 peaked at 2310 ppm."});
  assert.throws(() => T.classifyReply({}), /neither/);
});
ok("caps tool results by rows and characters", () => {
  const big = {cols: ["a"], rows: Array.from({length: 400}, (_, i) => ["x".repeat(40) + i])};
  const c = T.capToolResult(big);
  assert.ok(c.rows.length <= 50 && c.truncated && c.row_count === 400);
  assert.ok(JSON.stringify(c).length <= 2000, "under char budget");
});
ok("schema doc and system prompt mention every table and the zones", () => {
  const meta = {sources: ["local", "bedroom"], from: "2026-08-22 00:00", to: "2026-08-24 23:55",
    rows: 1234, days: 3, tzOffsetMin: 60};
  const p = T.buildSystemPrompt(meta);
  for (const t of Object.keys(T.SQL_TABLES)) assert.ok(p.includes(t + "("), "mentions " + t);
  assert.ok(p.includes("local, bedroom") && p.includes("UTC+01:00") && p.includes("tool_result"));
});
ok("canned fallback queries all pass the validator", () => {
  for (const c of T.CANNED)
    T.validateSql(c.sql("co2", " AND src = 'local'", 1787356800, 1787443200));
  for (const c of T.CANNED) T.validateSql(c.sql("rh", "", 0, 1));
});
console.log(`\n${n} test groups passed`);
