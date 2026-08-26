# Env Hub Analyzer (static web app)

One self-contained page (`index.html` + `sw.js`) for browsing and analysing
the hub's datasets. It is deliberately hosted **two ways**:

| Hosting | URL | Transport | Offline | web-BLE | Built-in AI |
|---|---|---|---|---|---|
| On the device (portal/captive AP) | `http://<hub-ip>/` | HTTP API (same-origin) | n/a (it *is* local) | no (insecure context) | no (insecure context) |
| GitHub Pages (HTTPS) | your Pages URL | **web-BLE** (mixed content blocks plain-http fetches) | yes, after first load | yes | yes |

## Local development over HTTPS

```sh
python tools/serve_webapp.py           # https://localhost:8443 (+ LAN IPs)
python tools/serve_webapp.py --trust   # also add the cert to the Windows
                                       # user trust store (confirmation popup)
```

Generates a reusable self-signed cert (SANs: localhost + this machine's
LAN IPs) into `tools/.localcert/`. Without `--trust`, click through
Chrome's warning (Advanced → Proceed, or type `thisisunsafe`) — note the
service worker (offline cache) only registers with a *trusted* cert.

**Built-in AI troubleshooting**: `http://localhost` is already a secure
context, so if the AI panel says *unavailable* the blocker is Chrome
itself, not TLS. The panel prints a diagnostics line. The Prompt API
(`LanguageModel`) is **stable in desktop Chrome 148+** (Windows, macOS 13+,
Linux, Chromebook Plus) — no flags — in a normal profile (not
Incognito/Guest), with ~22 GB free disk and a GPU >4 GB VRAM or 16 GB RAM.
**Chrome for Android / iOS do not have it yet** (chromestatus
`5888755098583040`, *Proposed*). The model is a one-time download managed
by Chrome; state at `chrome://on-device-internals`. See
`docs/research-web-ai-and-pyodide-query.md` for the full status check.

## Deploying

* **Device**: copy `index.html` and `sw.js` to the SD card as
  `/sd/www/index.html` (preferred) or to CIRCUITPY as `/www/index.html`.
  The collector serves it at `/` (the tiny built-in dashboard moves to `/mini`).
* **GitHub Pages**: enable Pages for this repo with the `webapp/` folder
  (or a `docs/` copy) as the source.

## Features

* **Datasets**: sync day CSVs from the device over HTTP or BLE
  (`hist <day>` streaming), or drag-drop CSV files straight off the SD
  card. Stored in the browser (IndexedDB), so old/disparate files remain
  analysable with the device offline. Duplicate rows are merged; data gaps
  (nodes asleep, hub powered off) are detected and shaded on charts.
* **Charts**: Plotly (pinned CDN version, cached by the service worker for
  offline use) with threshold lines per metric.
* **Threshold testing**: editable thresholds (prefilled from the device
  `/api/config` when connected); computes out-of-spec episodes with level,
  duration, and peak, plus a total-hours-beyond-bad summary.
* **Change testing**: Pyodide **314.0.6** (Python 3.14; numpy CUSUM
  change-point detection, cached offline after first run) with an editable
  Python cell — the script gets
  `series` (`{"src|metric": {"t": [...], "v": [...]}}`) and must define
  `analyze(series)`.
* **Ask in plain English (or by voice)**: uses Chrome's built-in AI
  ([Prompt API](https://developer.chrome.com/docs/ai/prompt-api), Gemini
  Nano — on-device, works offline once the model is downloaded). The model
  never does arithmetic over raw rows: it answers through a **tool loop**
  over the loaded data, which lives in an in-memory **sqlite3** database
  inside Pyodide (tables `readings`, `days`, `zones`, `thresholds`; rebuilt
  when *Load & merge* changes the dataset). Each turn the model returns
  constrained JSON (`responseConstraint`) — either
  `{"tool":"sql","query":...,"reason":...}` or `{"answer":...}`. The page
  validates the SQL (`ai_tools.js`: SELECT-only, single statement,
  identifier allowlist from the schema, no ATTACH/PRAGMA/writes, `LIMIT`
  clamped to 50; the db also runs `PRAGMA query_only=ON` and a ~2 s
  progress-handler timeout), runs it, feeds `{"tool_result":...}` back
  (50 rows / ~2000 chars) and repeats up to 3 times. Every executed query
  and its row count is shown under the answer in the *how I got this*
  block. The session is pre-warmed with the system prompt (domain guidance
  + live schema doc with zones and time range + 3 few-shot examples),
  cloned per question, recreated when the dataset changes or the context
  window (`contextUsage`/`contextWindow`) nears its quota, and the answer is
  rendered as plain text. Voice input via the Web Speech API.

  Example: *"my dehumidifier stopped over the last couple of days, how bad
  did the CO2 and humidity get and was it totally fucked?"* → the assistant
  queries peaks/durations vs thresholds and gives a severity verdict
  (casual phrasing is interpreted as "how far beyond acceptable, for how
  long").

  **Limits**: desktop Chrome 148+ only; Gemini Nano is small, so questions
  should be about one or two metrics/zones at a time; the model may mis-write
  SQL (the validator refuses and it gets one correction per turn); no
  function-calling API exists yet, the loop is emulated with structured
  output. **Android / no model**: the panel falls back to canned questions
  (min/mean/max, daily max, worst hours, time above/below thresholds per
  metric, zone and day range) executed through the same sqlite path.

  Tests: `node webapp/tests/sql_validator.test.mjs` (validator, reply
  parsing, prompt builder, canned queries) and
  `node webapp/tests/check_inline.mjs` (syntax check of the inline scripts).

## Future

* Optional upload of averaged subsets to online storage (e.g. Adafruit IO)
  when the hub has an internet-connected AP/STA link.
