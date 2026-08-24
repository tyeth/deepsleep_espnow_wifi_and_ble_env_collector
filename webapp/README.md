# Env Hub Analyzer (static web app)

One self-contained page (`index.html` + `sw.js`) for browsing and analysing
the hub's datasets. It is deliberately hosted **two ways**:

| Hosting | URL | Transport | Offline | web-BLE | Built-in AI |
|---|---|---|---|---|---|
| On the device (portal/captive AP) | `http://<hub-ip>/` | HTTP API (same-origin) | n/a (it *is* local) | no (insecure context) | no (insecure context) |
| GitHub Pages (HTTPS) | your Pages URL | **web-BLE** (mixed content blocks plain-http fetches) | yes, after first load | yes | yes |

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
* **Change testing**: Pyodide (numpy CUSUM change-point detection, cached
  offline after first run) with an editable Python cell — the script gets
  `series` (`{"src|metric": {"t": [...], "v": [...]}}`) and must define
  `analyze(series)`.
* **Ask in plain English (or by voice)**: uses Chrome's built-in AI
  ([Prompt API](https://developer.chrome.com/docs/ai/prompt-api), Gemini
  Nano — on-device, works offline once the model is downloaded). The model
  is given *computed statistics only* (ranges, episodes, gaps, change
  points — never raw CSVs), per the
  [built-in AI do's & don'ts](https://developer.chrome.com/docs/ai/built-in-ai-dos-donts):
  the session is pre-warmed with the system prompt, cloned per question,
  streamed, and rendered as plain text. Voice input via the Web Speech API.

  Example: *"my dehumidifier stopped over the last couple of days, how bad
  did the CO2 and humidity get and was it totally fucked?"* → the assistant
  reports peaks/durations vs thresholds and gives a severity verdict
  (casual phrasing is interpreted as "how far beyond acceptable, for how
  long").

## Future

* Optional upload of averaged subsets to online storage (e.g. Adafruit IO)
  when the hub has an internet-connected AP/STA link.
