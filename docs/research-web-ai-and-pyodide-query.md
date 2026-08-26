# Research: Chrome built-in AI + a Pyodide query "tool" loop for the Env Hub Analyzer

**Checked: 2026-08-26.** Chrome stable at time of writing: **152** (released 2026-08-25; Chrome 152
is the last four-week release, 153 lands 2026-09-08 on a two-week cadence).
Read-only research note — no repo files were modified.

Labels below: **[verified]** = read on a primary doc/spec/chromestatus page, or measured directly
today; **[community]** = mailing-list/blog claim, not in official docs; **[inference]** = my
reasoning, not a cited fact.

## 0. What the app does today (from `webapp/index.html`, 1098 lines)

- `idb` (IndexedDB `envhub`/`files`, one record per day-CSV) → `parseCSV()` → `loadAll()` merges into
  the global `rows[]` (`{ts,src,tc,rh,co2,pm1,pm25,pm4,pm10,voc,nox,vb,flags}`), dedup on `ts|src`,
  sorted by `ts`. `METRICS` (line 202) is the metric allowlist; then `findGaps()`, `findEpisodes()`
  (thresholds line 205), `draw()` (Plotly 2.35.2, lazy).
- `ensurePyodide()` (line 499): single-flight load of **Pyodide 0.26.2** + `loadPackage("numpy")`,
  `indexURL` from `vendor/pyodide/` (hub) or jsDelivr; `runPy()` (line 516) passes `series_json` via
  `pyodide.globals.set` and reads back `result_json`.
- AI panel: `SYSTEM_PROMPT` (742), `aiContext()` (761 — a JSON **summary**), `warmAI()` (806:
  `availability()` → `create({initialPrompts, expectedInputs, expectedOutputs, monitor})`), `ask()`
  (839: `clone()` → `promptStreaming()` → `destroy()`), `mic()` (SpeechRecognition). Background
  warm-up at `load+4s` pulls Plotly + Pyodide through the SW cache (`sw.js`, `CACHE="envhub-v12"`).

The plumbing you need already exists. What is missing is a **table inside Pyodide** and a
**decide → query → answer loop** around the existing session.

---

# Part 1 — Chrome built-in AI, current state (2026-08-26)

## 1.1 Naming and shipping status

- The API is a **global `LanguageModel`** (static `availability()`, `create()`; instances are
  sessions). `window.ai.*` / `ai.assistant` / `ai.languageModel` are the **2024 dev-preview names and
  are gone** — reference `LanguageModel` directly. **[verified]**
- **The Prompt API shipped stable on desktop in Chrome 148** (stable 2026-05-05): "direct access to a
  browser-provided on-device AI language model", with text/image/audio input and regex/JSON-schema
  response constraints. chromestatus `5134603979063296`: shipped desktop **148**, first enterprise
  notification 137, Android **not shipped**, WebView n/a. Before that: extensions-only from Chrome
  138 and, on the web, origin trial `AIPromptAPIMultimodalInput` (M139–144, extended to M147). **[verified]**
- Still trial-only: **`samplingMode`** ("Prompt API Sampling Parameters", chromestatus
  `6325545693478912`) is a **web origin trial from Chrome 148, extended through M159**. **[verified]**
- Firefox and WebKit have **negative standards positions** (MDN); Edge/Firefox/Safari unsupported. **[verified]**

## 1.2 API surface (what to code against)

```js
await LanguageModel.availability({ expectedInputs, expectedOutputs });
//   -> "unavailable" | "downloadable" | "downloading" | "available"
const s = await LanguageModel.create({
  initialPrompts: [{ role: "system", content: SYSTEM_PROMPT }, /* + user/assistant pairs */],
  expectedInputs:  [{ type: "text"|"image"|"audio", languages: ["en"] }],
  expectedOutputs: [{ type: "text", languages: ["en"] }],
  monitor(m) { m.addEventListener("downloadprogress", e => e.loaded /* 0..1 */); },
  signal: ac.signal,
  // samplingMode: "most-predictable" ... "most-creative"  -> WEB: origin trial only
  // temperature / topK + LanguageModel.params()           -> Chrome EXTENSIONS only
});
await s.prompt(input, { signal, responseConstraint, omitResponseConstraintInput });
       s.promptStreaming(input, { /* same options */ });   // ReadableStream of text chunks
await s.append(messages);          // add context without generating
await s.clone({ signal });         // copy, including context
       s.destroy();
s.contextUsage / s.contextWindow;  // tokens used / total
await s.measureContextUsage(input, { responseConstraint });
s.addEventListener("contextoverflow", ...);
```

- **Renamed properties — worth updating our mental model.** MDN's `LanguageModel` page lists only
  **`contextUsage` / `contextWindow` / `measureContextUsage()`**; `inputUsage`, `inputQuota` and
  `measureInputUsage()` are the superseded spec names. **[verified]** For robustness across builds:
  `s.contextWindow ?? s.inputQuota`. **[inference]**
- **Overflow semantics:** the oldest prompt/response *pairs* are evicted one at a time (system prompt
  preserved) and a `contextoverflow` event fires; if enough tokens still cannot be freed, the call
  **rejects with `QuotaExceededError`** carrying `requested` and `contextWindow`, and nothing is
  removed. **[verified]** Chrome does **not** publish a token count; community reports for Nano in
  Chrome are 6,144 tokens (early) and ~9,216 shared input+output more recently. **[community]** →
  read `contextWindow` at runtime; never hard-code.
- `temperature`/`topK` and `LanguageModel.params()` are **Extensions-only** on current builds; stated
  rationale is that raw numeric knobs "do not translate consistently across different underlying
  models", hence the enum `samplingMode` origin trial for the web. **[verified]**

## 1.3 Structured output (`responseConstraint`)

- Available since **Chrome 137**; accepts a **JSON Schema object or a `RegExp`**, passed per call to
  `prompt()`/`promptStreaming()`; the result is parseable JSON with no prose chatter. **[verified]**
- The schema **is sent to the model and counts against the context window**; measure with
  `measureContextUsage(input, {responseConstraint})`, and use **`omitResponseConstraintInput: true`**
  when you have already described the format in your own prompt text. **[verified that the option
  exists in spec + Chrome docs; the actual saving is unmeasured here]**
- Chrome's docs do not enumerate the supported JSON Schema keyword subset. Stick to
  `type/properties/required/enum/items/pattern/description` and validate the parse yourself. **[inference]**

## 1.4 Tool / function calling — **not shipped; you must emulate it**

- The WebML explainer (`webmachinelearning/prompt-api`) **does specify** a `tools` option on
  `create()`: `{name, description, inputSchema, async execute()}`, with model-initiated invocation.
  **[verified — present in the explainer]**
- **Chrome has not shipped it.** It is absent from `developer.chrome.com/docs/ai/prompt-api`, from
  the Chrome 148 release notes, and from the chromestatus entry; Chromium's own extension docs note
  the explainer "differs from the current implementation" and that function calling is being
  *explored*. **[verified by absence + the Chromium docs statement]**
- **So for this app: tools = `responseConstraint` (JSON) + a page-side loop.** That is the design in
  Part 2, and it is forward-compatible: if `tools` lands, your validator/executor becomes the
  `execute()` body unchanged.

## 1.5 Requirements — and the Android problem

All **[verified]** unless noted:

| Requirement | Value |
|---|---|
| Context / activation | **Secure context** (HTTPS/localhost); **transient user activation** for `create()`, at least when a download is needed ("meaningful interaction": click/tap/keypress) |
| Iframes / workers | Top-level + same-origin; cross-origin needs `allow="language-model"` / `Permissions-Policy: language-model` (if disallowed, `availability()` → `unavailable`). **Not available in Web Workers** |
| OS | Windows 10/11; macOS 13+ (Ventura+); Linux; ChromeOS **Chromebook Plus only** (platform 16389.0.0+) |
| Hardware | **≥22 GB free** on the Chrome-profile volume (headroom, not the model size); **>4 GB VRAM** or 16 GB RAM + ≥4 CPU cores; **audio input requires a GPU**; unmetered network for the one-time download |
| Languages | Chrome 149+: en, es, ja, de, fr (input and output) |
| **Mobile** | **"Chrome for Android, iOS, and ChromeOS on non-Chromebook Plus devices are not yet supported."** |
| Model size | Chrome declines to state a number ("significantly smaller" than 22 GB; check `chrome://on-device-internals`); ~2 GB and ~4 GB figures circulate **[community]** |
| Enterprise kill-switches | `GenAILocalFoundationalModelSettings`, `BuiltInAIAPIsEnabled` |

**Headline for you: the Prompt API does not exist in Chrome for Android today.** There is a
chromestatus entry **"Prompt API on Android" (`5888755098583040`), status *Proposed*, created
2026-07-30, no origin trial configured, security and privacy reviews pending** — so there isn't even
a flag to flip. The Chrome team's public line has been "stay tuned in 2026". On-device Nano on
Android is currently reachable only from **native** apps via ML Kit GenAI / AICore, not from the web.
**[verified]**

Consequences for this app **[inference]**: `warmAI()` on your phone will hit
`!("LanguageModel" in self)` or `availability() == "unavailable"`. The diagnostics block is
structurally right but its **advice is stale** — it mentions Chrome 131,
`chrome://flags/#prompt-api-for-gemini-nano`, `#optimization-guide-on-device-model`,
`chrome://components`. On desktop 148+ none of that is needed; on Android none of it helps. Suggested
text: "desktop Chrome 148+ only; Android not supported yet (chromestatus 5888755098583040)". The
existing HTTP→HTTPS handoff is also the right shape for a phone→desktop handoff.

## 1.6 Multimodal, and the sibling APIs

- **Multimodal input is shipped** with the Chrome 148 stable Prompt API: `expectedInputs` may be
  `text`, `image`, `audio`; **output is text only**. Image values: `HTMLImageElement`,
  `SVGImageElement`, `HTMLVideoElement`, `HTMLCanvasElement`, `ImageBitmap`, `OffscreenCanvas`,
  `VideoFrame`, `Blob`, `ImageData`. Audio: `AudioBuffer`, `ArrayBuffer(View)`, `Blob`. These go in
  content objects for `prompt()`/`promptStreaming()`/`append()`/`initialPrompts`. **Audio input
  requires a GPU.** **[verified]**
- Two cheap ideas for later: audio input as a fully-offline replacement for `SpeechRecognition`
  (cloud-backed in Chrome), and image input over a Plotly `toImage()` PNG so the model can "look at"
  a chart. **[inference]**

| API | Status (2026-08-26) |
|---|---|
| Translator | **Stable, Chrome 138** |
| Language Detector | **Stable, Chrome 138** |
| Summarizer | **Stable, Chrome 138** |
| Prompt (`LanguageModel`) | **Stable desktop, Chrome 148**; sampling-params OT → M159 |
| Proofreader | **Origin trial** |
| Writer / Rewriter | **Developer trial (experimental / EPP)** |

All sit behind the same hardware gate, and the get-started platform matrix marks mobile ✗ across the
board. **[verified — but see Open Questions: Translator on Android deserves a re-check; it's a
smaller model with a different history.]**

## 1.7 Grounding a small on-device model on local data — practical rules

1. **Never let Nano do arithmetic.** Sums, durations, percentiles and unit conversions over 10⁵ rows
   are exactly what a small quantised model gets wrong. Compute in SQL/numpy; let it only *narrate*.
   **[inference, strongly held]**
2. **Budget tokens against `contextWindow` at runtime.** System prompt + schema doc + question + tool
   results must fit; with a ~6–9k window keep a turn under ~2,500 tokens (≈10 kB of text).
   **[inference from verified overflow semantics]**
3. **Constrain every machine-readable step** with `responseConstraint`, then **validate and retry
   once**, appending the validator error. Small models drift into prose otherwise.
4. **Chunk by asking, not by stuffing.** Let the model request aggregates (`GROUP BY day`, `MAX`,
   `SUM`) — one to two orders of magnitude smaller than raw rows.
5. **Cap iterations** (N = 2–3); Nano will happily loop on a bad query. **`clone()` per question**
   (already done) so tool chatter never pollutes the pre-warmed session; `destroy()` in a `finally`.
6. **Catch `QuotaExceededError` explicitly** and degrade to today's summary-only path.
7. **Keep the model outside the trust boundary**: it emits a *query proposal*; the page decides. Model
   output is untrusted — the app's use of `textContent` is correct; never `innerHTML`.

---

# Part 2 — Pyodide as the query engine (the "tool")

## 2.1 Options for SQL-like querying, with measured numbers

Sizes measured today with `curl` against `cdn.jsdelivr.net/pyodide/...` (raw bytes / brotli
on-the-wire, since jsDelivr recompresses):

| Option | Download | Verdict for a phone-class browser |
|---|---|---|
| **`sqlite3` in Pyodide 0.26.2** | `sqlite3-1.0.0.zip` **1,454,039 B raw / 540,250 B br** | **Recommended.** Pyodide is already loaded and SW-cached; this is a rounding error on top. |
| Already paid for by the app | `pyodide.asm.wasm` **10,087,885 B / 2,992,037 B br**; `python_stdlib.zip` **2,341,761 B**; `numpy` **11,959,233 B / 2,456,456 B br** | baseline |
| **pandas** | **23,759,070 B** + deps (`numpy`, `python-dateutil`, `pytz`) | **No.** Doubles the download, and pandas import in wasm costs seconds; buys nothing over SQL here. |
| **DuckDB-wasm** | ~9.6 MB gzipped bundle (wasm variants ~6.4 MB to >18 MB); a *separate* runtime, not a Pyodide package | **No.** Great engine, but a second multi-MB WASM VM plus its own worker/COOP-COEP plumbing, for queries over ≤10⁵ rows. |
| Pure JS (hand-rolled filter/group-by, or a mini DSL) | 0 B | Viable **fallback**, and safest if you distrust free-form SQL — but you re-implement `GROUP BY`/time bucketing/percentiles by hand. |

**Important version gotcha [verified]:** in **Pyodide 0.22.0 `sqlite3` was unvendored** from the
stdlib ("Now it needs to be loaded with `pyodide.loadPackage` or `micropip.install`"), and it was
**restored to the bundled stdlib only in Pyodide 314.0.0 (2026-06-09)** ("We do not unvendor stdlibs
anymore. sqlite3 and lzma are now bundled into Pyodide by default"). The app pins **0.26.2**, so
`await py.loadPackage("sqlite3")` is **required** — plain `import sqlite3` fails without it. The
package is in the 0.26.2 lockfile (`sqlite3` 1.0.0, `install_dir: "stdlib"`, `package_type:
"cpython_module"`, `shared_library: true`), so it resolves from the same `indexURL` and lands in the
same SW cache. **[verified by reading `pyodide-lock.json` for v0.26.2]** Upgrading to 314.x would
make it free (and `pyodide.asm.wasm` is slightly smaller: 9,597,831 B) but is a much bigger change —
Python 3.14, new Emscripten ABI, every pinned URL and the hub's `vendor/pyodide/` move. **[verified sizes]**

**Memory [inference]:** an in-memory SQLite table of 100k rows × 12 REAL columns is roughly
100k × ~100 B ≈ 10 MB of wasm heap plus indexes — comfortably inside Pyodide's default heap. The
larger transient cost is the JSON hand-off, so build the table once and keep it.

## 2.2 The schema to expose (compact, ~200 tokens)

Give the model *one* small schema doc, with units and enumerated zones. This is the single biggest
quality lever.

```
TABLES (SQLite, read-only):
samples(ts INT epoch-UTC, t TEXT 'YYYY-MM-DD HH:MM' local, day TEXT local,
        hour INT 0-23 local, src TEXT zone,
        tc REAL degC, rh REAL %, co2 REAL ppm,
        pm1 REAL, pm25 REAL, pm4 REAL, pm10 REAL ug/m3,
        voc REAL Sensirion INDEX baseline 100, nox REAL INDEX baseline 1,
        vb REAL node battery volts)     -- NULL where a zone lacks that sensor
episodes(src TEXT, metric TEXT, level TEXT 'warn'|'bad',
         start TEXT local, hours REAL, peak REAL)
gaps(src TEXT, start TEXT local, hours REAL)
zones: hub, bed1, shed            -- actual values of src
range: 2026-08-19 .. 2026-08-26   -- 41231 rows
Rules: SELECT only, one statement, always aggregate or LIMIT<=40.
Use day/hour/t for time; ts is UTC epoch, t/day/hour are LOCAL.
```

Materialising the JS-side `episodes[]`/`gaps[]` into SQLite is worth it: "how bad did it get and for
how long" becomes one trivial query instead of an aggregate the model has to invent. **[inference]**

## 2.3 The tool loop

Two phases, max N = 2 tool calls.

**Phase A — decide (constrained JSON).**

```js
const PLAN_SCHEMA = {
  type: "object", required: ["action"], additionalProperties: false,
  properties: {
    action: { type: "string", enum: ["sql", "answer"] },
    query:  { type: "string", description: "a single read-only SELECT, only when action=sql" },
    why:    { type: "string", description: "<=12 words, shown to the user" }
  }
};
```

Prompt (target < ~450 tokens):

```
You may query the user's data with SQLite before answering.
{SCHEMA_DOC}
QUESTION: {q}
{PRIOR_RESULTS_IF_ANY}
Reply with JSON only:
  {"action":"sql","query":"SELECT ...","why":"..."}   to fetch numbers you still need
  {"action":"answer"}                                 when you have enough to answer
Prefer ONE aggregate query (MIN/MAX/AVG/COUNT/SUM, GROUP BY day or src).
Never SELECT raw rows without LIMIT.
```

**Phase B — answer (prose, streamed).** Re-prompt the *same clone* with the existing
`SYSTEM_PROMPT` context plus:

```
TOOL RESULTS (authoritative - do not recompute, quote these numbers):
{tool_results_json}
CONTEXT (summary): {aiContext()}
QUESTION: {q}
Now answer in prose. Use only the numbers above. If a data gap overlaps the
period, say the record is incomplete.
```

**Validation gate (page-side, non-negotiable):**

- strip trailing `;`, reject if any `;` remains (single statement only); must match `/^\s*(select|with)\b/i`;
- word-boundary blocklist: `attach|detach|pragma|insert|update|delete|drop|create|alter|replace|vacuum|reindex|load_extension|readfile|writefile|sqlite_master`;
- identifier allowlist: every word token outside string literals must be a known table, column or SQL keyword;
- append `LIMIT 40` if absent, clamp any larger `LIMIT`; cap the serialised result by **rows and
  chars** (40 / 2,000); wall-clock guard via SQLite's `set_progress_handler` so a cartesian join
  cannot hang the tab.

Belt and braces beyond the validator: run `PRAGMA query_only = ON` once after loading, so even a
validator miss cannot write. **[inference — `query_only` is standard SQLite; untested in Pyodide]**

**Token budget [inference]:** system 300 + schema 200 + question 30 + results 600 + summary 400
≈ 1,530 tokens in — well inside a 6k window. Guard it with
`const need = await s.measureContextUsage(text); if (need > s.contextWindow - 512) { /* drop the
summary first, then shrink results */ }`.

## 2.4 Session and DB lifecycle

- `ensurePyodide()` already single-flights. Add `ensureSqlDb()` that (a) awaits it, (b)
  `loadPackage("sqlite3")` once, (c) runs the Python setup module once, (d) rebuilds the table when a
  `dataVersion` counter changes.
- `dataVersion++` at the end of `loadAll()` (and after `findEpisodes()`/`findGaps()`); the next
  question rebuilds lazily. Rebuild = `DROP TABLE` + recreate + one `executemany`. Keeping the
  connection avoids re-paying `loadPackage`. One module-level `pyodide` (already true) and one
  Python-side `_ENV` dict holding the connection — never re-create the VM.
- Warm-up: the existing `load+4s` block already calls `ensurePyodide()`; add `loadPackage("sqlite3")`
  there so the 540 kB lands in the SW cache while online. Bump `CACHE` in `sw.js` when adding a CDN URL.

## 2.5 Transparency line

Show every executed query. Suggested UI: below `#answer`, a `<details>` labelled "queries used (2)"
containing, per step: the model's `why`, the **post-validation** SQL in a `<code>`, row count, elapsed
ms, and a small result table — all via `textContent`. Also surface rejections ("model asked for a
non-SELECT statement — refused") so failures are legible rather than silent.

## 2.6 Fallback when the Prompt API is unavailable (i.e. your Android phone)

Ranked by effort/value **[inference]**:

1. **Deterministic query UI (do this first).** The executor half of the tool loop is model-free: ship
   6–10 canned questions as buttons ("worst CO2 day", "hours above bad per zone", "last 24 h vs
   previous week", "battery sag by node") mapped to fixed parameterised SQL, rendered as a table plus
   a template sentence. Works in every browser, no download, and doubles as the golden-test suite.
2. **Voice → canned intent.** `SpeechRecognition` works on Chrome Android (cloud-backed) even though
   `LanguageModel` does not; a keyword matcher over the metric/zone/time vocabulary can select one of
   the canned queries. Cheap, no LLM.
3. **Phone → desktop handoff.** Reuse the existing `handoff()` fragment trick (`#import=gz.…`) to move
   today's days to a desktop Chrome 148+ where the AI works; add a QR of that URL.
4. **Remote model, same loop.** Transport-agnostic — swap Phase A/B for a `fetch` to a remote API and
   everything else stands. It costs the "nothing leaves the device" property, so make it explicit
   per-question opt-in and show the exact JSON before sending (schema doc + aggregate results are far
   less sensitive than raw rows).

## 2.7 Concrete code sketch (illustrative — nothing was edited)

Python side, run once (a `const SQL_SETUP_PY = String.raw` template next to `DEFAULT_PY`):

```python
import sqlite3, json, time
_ENV = {}
COLS = ["tc","rh","co2","pm1","pm25","pm4","pm10","voc","nox","vb"]

def env_build(rows_json):
    """rows_json: [{ts,src,t,day,hour, <metrics>}] - JS precomputes local t/day/hour."""
    rows = json.loads(rows_json)
    db = _ENV.get("db") or sqlite3.connect(":memory:")
    db.execute("DROP TABLE IF EXISTS samples")
    db.execute("CREATE TABLE samples (ts INTEGER, t TEXT, day TEXT, hour INTEGER,"
               " src TEXT, " + ", ".join(c + " REAL" for c in COLS) + ")")
    keys = ["ts","t","day","hour","src"] + COLS
    db.executemany("INSERT INTO samples VALUES (" + ",".join("?" * len(keys)) + ")",
                   ([r.get(k) for k in keys] for r in rows))
    db.execute("CREATE INDEX ix_ts  ON samples(ts)")
    db.execute("CREATE INDEX ix_src ON samples(src, ts)")
    db.commit()
    _ENV["db"] = db
    return json.dumps({"rows": len(rows)})

def env_aux(episodes_json, gaps_json):
    # same shape: DROP/CREATE episodes(src,metric,level,start,hours,peak) and
    # gaps(src,start,hours), executemany from the JSON, commit, then lock it down:
    db = _ENV["db"]
    ...
    db.execute("PRAGMA query_only = ON")   # cannot write from here on, validator or not
    return "ok"

def env_query(sql, max_rows=40, budget_s=3.0):
    db = _ENV["db"]
    t0 = time.time()
    db.set_progress_handler(lambda: 1 if time.time() - t0 > budget_s else 0, 10000)
    try:
        cur = db.execute(sql)
        cols = [d[0] for d in cur.description or []]
        out = cur.fetchmany(max_rows + 1)
    finally:
        db.set_progress_handler(None, 0)
    cell = lambda v: round(v, 3) if isinstance(v, float) else v
    return json.dumps({"cols": cols,
                       "rows": [[cell(v) for v in r] for r in out[:max_rows]],
                       "truncated": len(out) > max_rows,
                       "ms": int((time.time() - t0) * 1000)})
```

JS side:

```js
let sqlReady = null, sqlStamp = -1, dataVersion = 0;      // dataVersion++ in loadAll()

function ensureSqlDb() {                                   // single-flight, like ensurePyodide
  if (sqlReady && sqlStamp === dataVersion) return sqlReady;
  sqlStamp = dataVersion;
  sqlReady = (async () => {
    const py = await ensurePyodide();
    if (!py._sqlLoaded) {                                  // Pyodide 0.26.x: sqlite3 is unvendored
      await py.loadPackage("sqlite3");
      await py.runPythonAsync(SQL_SETUP_PY);
      py._sqlLoaded = true;
    }
    const lt = ts => {                                     // LOCAL time parts for the model
      const d = new Date(ts * 1000), p = n => String(n).padStart(2, "0");
      const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
      return { t: `${day} ${p(d.getHours())}:${p(d.getMinutes())}`, day, hour: d.getHours() };
    };
    py.globals.set("rows_json", JSON.stringify(rows.map(r => ({ ...r, ...lt(r.ts) }))));
    await py.runPythonAsync("_r = env_build(rows_json)");
    py.globals.set("rows_json", null);                      // free the big string
    if (!episodes.length) findEpisodes();
    // episodes/gaps reuse the exact shapes aiContext() already builds
    py.globals.set("epi_json", JSON.stringify(episodes.map(e => ({
      zone: e.src, metric: e.metric, level: e.level === 2 ? "bad" : "warn",
      start: iso(e.start), hours: +((e.end - e.start) / 3600).toFixed(2), peak: e.peak }))));
    py.globals.set("gap_json", JSON.stringify(gaps.map(g => ({
      zone: g.src, from: iso(g.from), hours: +((g.to - g.from) / 3600).toFixed(2) }))));
    await py.runPythonAsync("_r = env_aux(epi_json, gap_json)");
    return py;
  })().catch(e => { sqlReady = null; throw e; });
  return sqlReady;
}

const SQL_TABLES = { samples: ["ts","t","day","hour","src", ...METRICS],
                     episodes: ["src","metric","level","start","hours","peak"],
                     gaps: ["src","start","hours"] };
const SQL_BAD = /\b(attach|detach|pragma|insert|update|delete|drop|create|alter|replace|vacuum|reindex|load_extension|readfile|writefile|sqlite_master)\b/i;
const SQL_WORDS = ("select with from where group by order having limit offset as and or not null is"
  + " in between like case when then else end distinct count sum avg min max abs round cast integer"
  + " real text strftime datetime date julianday asc desc union all on join left inner using").split(" ");

function validateSql(sql) {
  let q = String(sql || "").trim().replace(/;+\s*$/, "");
  if (!q) throw new Error("empty query");
  if (q.includes(";")) throw new Error("only one statement allowed");
  if (!/^\s*(select|with)\b/i.test(q)) throw new Error("SELECT only");
  if (SQL_BAD.test(q)) throw new Error("read-only queries only");
  const known = new Set([...Object.keys(SQL_TABLES), ...Object.values(SQL_TABLES).flat(),
                         ...SQL_WORDS]);
  const bare = q.replace(/'[^']*'/g, " ").replace(/"[^"]*"/g, " ");
  for (const w of bare.match(/[A-Za-z_][A-Za-z0-9_]*/g) || [])
    if (!known.has(w.toLowerCase())) throw new Error("unknown identifier: " + w);
  if (!/\blimit\s+\d+/i.test(q)) q += " LIMIT 40";
  else q = q.replace(/\blimit\s+(\d+)/i, (m, n) => "LIMIT " + Math.min(+n, 40));
  return q;
}

async function sqlTool(sql) {
  const safe = validateSql(sql);
  const py = await ensureSqlDb();
  py.globals.set("q_sql", safe);
  await py.runPythonAsync("_out = env_query(q_sql)");
  return { sql: safe, ...JSON.parse(py.globals.get("_out")) };
}

async function askWithTools(q, s) {              // s = the pre-warmed clone from ask()
  const steps = [];
  for (let i = 0; i < 2; i++) {
    let plan;
    try {
      plan = JSON.parse(await s.prompt(planPrompt(q, steps),
        { responseConstraint: PLAN_SCHEMA, omitResponseConstraintInput: true }));
    } catch (e) { break; }                       // bad JSON / quota -> go straight to prose
    if (plan.action !== "sql" || !plan.query) break;
    setStatus("aistatus", "querying your data...", true);
    try { steps.push({ why: plan.why, ...(await sqlTool(plan.query)) }); }
    catch (e) { steps.push({ why: plan.why, sql: plan.query, error: String(e.message || e) }); }
  }
  showQueries(steps);                            // the <details> transparency block
  return steps;
}
```

`ask()` changes minimally: after `const s = await aiSession.clone();`, insert
`const steps = await askWithTools(q, s);` and build the Phase-B prompt from `steps` + `aiContext()`
before `s.promptStreaming(...)`. Everything else — streaming into `#answer` via `textContent`,
`s.destroy()`, timing status — stays. Roughly **+130 lines JS, +55 lines Python**; no changes to
`idb`, charts, or transports; `sw.js` needs a `CACHE` bump.

---

## Sources (all fetched/measured 2026-08-26)

**Chrome docs:** `developer.chrome.com/docs/ai/prompt-api` · `/docs/ai/get-started` ·
`/docs/ai/built-in-apis` · `/docs/ai/structured-output-for-prompt-api` · `/release-notes/148` ·
`/release-notes/152`
**chromestatus:** `/api/v0/features/5134603979063296` (Prompt API) ·
`/api/v0/features/5888755098583040` (Prompt API on Android — *Proposed*) ·
`/api/v0/features?q=Prompt%20API` (sampling parameters, OT → M159)
**MDN:** `/Web/API/LanguageModel` · `/Web/API/Prompt_API` · `/Web/API/Prompt_API/Multimodal`
**Spec / Chromium:** https://github.com/webmachinelearning/prompt-api (explainer, incl. the
unshipped `tools` option) ·
https://chromium.googlesource.com/chromium/src/+/main/docs/experiments/prompt-api-for-extension.md ·
https://github.com/GoogleChrome/modern-web-guidance/blob/main/skills/modern-web-guidance/guides/built-in-ai/language-model.md
**Community:** `groups.google.com/a/chromium.org/g/chrome-ai-dev-preview-discuss/c/WO2NIK_9Ue4`
(token limits) · `.../c/HKIndTczlPM` (Android) ·
https://developers.google.com/ml-kit/genai/prompt/android/get-started (native Android path)
**Pyodide:** https://pyodide.org/en/stable/project/changelog.html (sqlite3 unvendored 0.22.0;
re-bundled 314.0.0) · https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide-lock.json (`sqlite3`
1.0.0 entry) plus asset sizes measured directly from `cdn.jsdelivr.net/pyodide/v0.26.2/full/`
**Other:** https://duckdb.org/docs/current/clients/wasm/overview and
https://github.com/duckdb/duckdb-wasm/discussions/1241 (bundle size / memory) ·
https://chromereleases.googleblog.com/2026/ (Chrome 152 stable, 2026-08-25)

## Open questions for tomorrow's review

1. **Android is a hard no for the Prompt API today.** Do we (a) ship the deterministic canned-query UI
   as the phone experience, (b) add a phone→desktop QR handoff, or (c) add an opt-in remote model?
   Recommendation: (a) now, (b) cheap, (c) only behind explicit per-question consent.
2. **Adopt `contextUsage`/`contextWindow`** (not `inputUsage`/`inputQuota`) and add a pre-flight
   `measureContextUsage()` budget check? The app reads neither today.
3. **Pin decision: stay on Pyodide 0.26.2 + `loadPackage("sqlite3")` (+540 kB br), or jump to 314.x**
   where sqlite3 is bundled? The jump means Python 3.14, a new numpy pin, and re-vendoring
   `vendor/pyodide/` for the hub. I'd stay on 0.26.2.
4. **Free-form SQL vs a constrained query DSL.** The allowlist validator is decent but SQL is a big
   surface. Alternative: `responseConstraint` a *structured* query object
   (`{metric, zone, from, to, agg, group_by}`) that the page compiles to SQL — safer, less expressive.
5. **Measure `omitResponseConstraintInput`** on the real device: how many tokens does the schema cost
   with and without it? It sets the whole budget.
6. **Verified-numbers guardrail:** force Phase B through a template (page-rendered numbers, model
   writes only connective prose) so a hallucination can't restate a wrong peak? Cheap insurance.
7. **Does the hub's `vendor/pyodide/` copy include the `sqlite3` package?** If not, the hub-hosted
   (offline, plain-http) copy fails on `loadPackage("sqlite3")` while GitHub Pages works.
8. **`sw.js` inconsistency spotted in passing:** `CACHE = "envhub-v12"`, but the post-registration
   check opens `caches.open("envhub-v3")`, so the "offline: ready" chip can never match. Unrelated to
   this work; a one-word fix.
9. **Timezone contract:** JS precomputes local `t`/`day`/`hour` columns (SQLite has no tz database)
   and the schema doc says "ts is UTC epoch, t/day/hour are local" — agree?
10. **Materialise `episodes`/`gaps`/`change_points` as SQL tables?** Yes for the first two, I think;
    change points are few enough to stay in the prose summary. And do the canned fallback queries
    become a golden-test harness for the AI loop ("does it pick the right query for these 10?").

## Implementation note (branch `ai-tool-loop`, 2026-08-26)

Implemented per Part 2 with these decisions: **Pyodide pinned to 314.0.6** (latest on jsDelivr,
2026-08-25; `sqlite3/` verified inside its `python_stdlib.zip`, numpy 2.4.6 in `pyodide-lock.json`,
no `sqlite3` package entry — i.e. bundled) instead of 0.26.2 + `loadPackage("sqlite3")`; the app
still calls `loadPackage("sqlite3")` when an older vendored tree reports a non-314 version. Tables
are `readings(ts,src,<METRICS>,flags)`, `days`, `zones`, `thresholds` (episodes/gaps stay in JS).
The flat `TOOL_SCHEMA` (tool/query/reason/answer) is used for `responseConstraint` rather than
`anyOf`, since Chrome does not document its JSON-Schema keyword subset. Validator + prompt builder
+ canned fallback queries live in `webapp/ai_tools.js` with Node tests in `webapp/tests/`. Open
questions 2, 3, 8 above are resolved by this branch; 4, 5, 6 remain for manual Chrome testing.
