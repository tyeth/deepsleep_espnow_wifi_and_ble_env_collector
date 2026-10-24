# Updated portal rollout — 22 October 2026

Portal revision `83526b03c034fee9452505069aded739b55d5dcb` is now installed on
the C5, after independent verification of all three eight-hour runs and the
separate Pico two-hour run. The transaction backed up, replaced and read back
`index.html`, `prompt_backend.js` and `sw.js`, then resumed the collector.
Firmware remains `cb5301b6fb`; certificates, configuration and stored data were
preserved. [Exact evidence](portal-rx-rollout-2026-10-22.json).

Trusted HTTPS verification passed at 19:49 UTC: all seven served web assets
matched the release hashes, normal system CA and hostname checks succeeded,
the expected certificate was served, the measurement API returned valid JSON,
and the wrong hostname was rejected specifically as a hostname mismatch.

A fresh isolated Chromium 155 context loaded the actual C5 page with TLS error
bypass disabled. With the experimental WebMCP flags enabled, the browser exposed
`document.modelContext.registerTool`; both native tools registered. The page
used application cache `envhub-v21` and loaded 697 device readings.

Native WebMCP verification passed at 19:59 UTC:

- Dataset summary: one UTC day, 697 rows, sources `bench-c61-sim` and `local`.
- Grouped query: 497 node rows and 200 local rows, each with peak CO2 616 ppm.
- A DELETE request returned `SELECT only`; the following count remained 697.

The optional mobile-model checkbox stayed off. Native `LanguageModel` was
present, but this check did not run model inference. Android fallback inference
and model retention have separate emulator evidence; the two integrations are
not being conflated.

The original browser-startup job exceeded its caller timeout, but the isolated
browser remained alive. Later fresh snapshots and native tool calls completed
normally; no root cause is asserted. Four initial local-vendor 404s were followed
by successful CDN fallback, loaded NumPy and `offline: ready`. These diagnostics
remain retained instead of being relabelled as a clean startup.

The completed overnight runs used the preceding portal assets. Their results
remain valid for those exact inputs; this rollout is a separate functional
qualification, with subsequent firmware/application checks still required.
