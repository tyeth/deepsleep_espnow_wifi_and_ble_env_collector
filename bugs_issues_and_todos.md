# Bugs, upstream issues & TODOs

Findings from the 2026-08-24 hardware bring-up (Feather ESP32-C6 +
CircuitPython **10.3.0-alpha.4** + eInk Feather Friend #4446 + 3.52" quad
JD79667; node = Feather ESP32-S3 No PSRAM, same CP version).

## Suspected CircuitPython core bugs (worth filing upstream)

### 1. C6: `wifi.radio.start_ap()` hard-faults when called after heavy imports
* **Symptom**: `Hard fault: memory access or instruction error` → safe
  mode, immediately at the `start_ap` call. 100% reproducible in a normal
  boot once `adafruit_httpserver`/`displayio` etc. are imported; the same
  call works in safe-mode REPL, in a fresh-VM REPL, and at the very top of
  `code.py` before any heavy imports.
* **Hypothesis**: softAP init needs large contiguous internal-heap
  allocations; when they fail the port hard-faults instead of raising
  `MemoryError`/`espidf.IDFError`.
* **Workaround**: "EARLY AP START" block at the top of `collector/code.py`.
* **Repro**: flash CP 10.3.0-a4 on `adafruit_feather_esp32c6_4mbflash_nopsram`;
  `import adafruit_httpserver, displayio; import wifi; wifi.radio.start_ap(ssid="X")`
  in code.py (not REPL).

### 2. C6: wifi/socket bring-up corrupts the shared `busio.SPI` lock flag
* **Symptom**: after constructing a `socketpool.SocketPool` + UDP socket
  (captive-portal DNS) with the AP active, the SPI bus used by the eInk
  reads LOCKED forever: `spi.try_lock()` returns False with **no Python
  owner**, and every `EPaperDisplay.refresh()` fails `"Refresh too soon"`
  (misleading message — it's the `displayio_display_bus_is_free` check)
  while `time_to_refresh == 0.0` and `busy == False`.
* **Evidence**: staged `spi.try_lock()` probes: free after ESP-NOW init,
  LOCKED immediately after `CaptivePortal` construction (wifi/socket code
  that never touches SPI).
* **Workaround**: call `spi.unlock()` (ignoring errors) before each
  refresh (`collector/code.py refresh_display`).

### 3. `sdcardio.SDCard()` leaves the SPI bus locked when card-init fails
* **Symptom**: with no card inserted, the failed constructor
  (`OSError: no SD card`) leaves the shared SPI locked → all display
  refreshes blocked (same misleading "Refresh too soon").
* **Workaround**: `spi.unlock()` in the except branch.
* Probably a genuine upstream bug regardless of the C6 flag corruption.

### 4. e-paper + console splash: supervisor auto-refresh starves user refreshes
* **Symptom**: if an `EPaperDisplay` is left showing the splash/console,
  the supervisor auto-refreshes it in the background; user `refresh()`
  calls then collide indefinitely. `root_group = None` re-shows the
  splash, restarting the cycle.
* **Workaround**: assign a real (white) group immediately at construction
  and never set `root_group = None`.
* Docs could warn about this; also `"Refresh too soon"` is raised for
  three unrelated causes (timer, busy, bus-not-free) — separate messages
  would have saved hours.

### 5. C6: BLE alongside softAP — **UNDER TEST, see below**
* Observed once as a clean `_bleio` error `Unknown system firmware error:
  519` (graceful), and one boot with BLE re-enabled ended in a hard fault
  (location not confirmed — needs the retest documented below).
* esptool note: `--after watchdog-reset` is not supported for C6 by
  esptool 5.2.dev4, and RTS reset is a no-op on USB-Serial/JTAG, so a
  flashed C6 sits in download mode until the physical reset button.

### BLE + AP coexistence retest (C6)
Procedure: boot the full collector with `ble_enabled=true`, AP active;
vary WHERE BLE is initialised. Watch for (a) success, (b) clean error,
(c) hard fault.

| Configuration | Boots | Result |
|---|---|---|
| BLE **workflow** (pre-boot) + early AP + late user BLE init | 1 | AP + workflow coexist; user BLE init fails **cleanly** (`Unknown system firmware error: 519`) |
| workflow OFF, early AP, **late** user BLE init (after all imports) | 2 | **HARD FAULT** both boots, exactly at BLE init (last breadcrumb `mem[after http portal]`) |
| workflow OFF, early AP **then** early BLE (before heavy imports) | 1 | catastrophic: USB-Serial/JTAG **wedged** (port opens but blocks; needs physical reset) |
| workflow OFF, early **BLE then AP** (mirrors the workflow ordering) | 3 | **BLE advertises + AP coexists, no crash** — but the resident BLE stack costs ~64 KB gc heap **and enough IDF internal heap that the HTTP server can no longer create sockets** (`Cannot start server on 0.0.0.0:<any port>`, tried 80 and 999); remaining gc heap ~14 KB then OOMs later init |

**Conclusion**: on C6/CP10.3-a4 the working orderings are settled —
early-BLE-then-early-AP is the only sequence where both come up — but the
C6 does not have enough memory (gc + IDF internal) to run
**BLE + softAP + HTTP portal + eInk dashboard** together. Pick per
deployment: `ble_enabled=false` (default; AP + captive portal + dashboard
all work, ~90 KB free) or `ap_enabled=false` for a BLE-centric hub.
Boards with PSRAM (Feather S3 w/ PSRAM) should manage all of it.

### 0. **PARKED**: C6 softAP unconnectable from phones (2026-08-24)
Despite fixing the ESP-NOW ordering (issue 6) and explicitly starting the
DHCP server (`start_dhcp_ap()`), phones still associate with `BASE{mac}`
and immediately drop. Everything server-side *looks* healthy
(`ap_active=True`, DHCP started without error, DNS+HTTP listening).
NOT a DHCP bug per se: the **node's** portal AP accepts phones and hands
out leases using the very same `start_ap`+`start_dhcp_ap` calls — the
difference is the collector has ESP-NOW (and sometimes BLE) resident, so
this is radio coexistence breaking the host AP, not the DHCP server.
**Decision: park it.** Resume plan: two dev boards with no sensors and a
self-compiled CircuitPython (debug logging in the espressif port's softAP
/ DHCP glue) another day. Until then the collector runs
`ap_enabled=false, ble_enabled=true` — BLE + ESP-NOW verified as the
access/transport pair (HTTP portal available whenever STA WiFi creds are
set in settings.toml).

### 6. C6: `espnow.ESPNow()` kills an active user softAP (and can wedge USB)
* **Symptom**: boot order "start_ap → espnow.ESPNow()" completes without
  error, but `wifi.radio.ap_active` is later False — the AP beacon is
  gone and phones can never associate (looks like DHCP failure). Running
  the same two calls interactively wedged USB-Serial/JTAG entirely
  (serial write timeout, physical reset required).
* **Contrast**: the S3 node's portal AP (no ESP-NOW running) accepts
  phone connections fine.
* **Workaround**: initialise ESP-NOW BEFORE `start_ap` in the early radio
  block and keep the object alive forever (`net_espnow.EspNowHub`
  accepts the pre-built object); main loop logs if the AP still drops.

### 7. **RESOLVED 2026-08-24 (Pi bench)**: C6 BLE-mode starvation — eInk
### "SPI configuration failed" AND GATT connects timing out
Both had one root cause: in BLE mode the collector still imported and
started the whole HTTP stack (`net_wifi`/`adafruit_httpserver` + captive
DNS) that could serve nothing (no AP, no STA creds), leaving ~15 KB gc
free with BLE resident. At that level (a) eInk refreshes fail
`SPI configuration failed`, and (b) **incoming GATT connections never
complete** — WinRT, Android nRF Connect, and BlueZ/bleak all timed out
identically; a minimal BLE-only code.py (fresh VM, 227 KB free) accepted
BlueZ connections instantly, proving the C6 BLE core is fine.
**Fix**: `HTTP_WANTED` gate in `collector/code.py` — the HTTP/captive
stack is only imported/started when the AP is enabled or STA creds
exist. BLE mode now runs at ~71-73 KB free, the eInk dashboard refreshes
fine, and the full BLE command matrix works from BlueZ on the Pi.
Take-away for upstream: a failed GATT connect for lack of memory is
totally silent on the device side — no exception, no console output.

### 8. C6: `_bleio` silently DROPS outgoing notifications (TX queue ~5 deep)
* **Symptom**: any UART reply longer than ~100 bytes truncates: exactly
  100 bytes (5 x 20-byte notifications at the default ATT 23 MTU) arrive
  at the client, the rest vanish. `UARTService.write` neither blocks nor
  raises — the data is simply gone. Measured with a raw byte-counting
  bleak client on the Pi (BlueZ).
* **Partial workaround**: pace TX at one 20-byte notification per write
  with a 50 ms gap (`net_ble._write_paced`). Long replies then complete
  *most* of the time, but the occasional notification still disappears
  even fully paced — suspicion: drops coincide with the ~20 s eInk SPI
  refresh window and/or ESP-NOW activity.
* **Client-side mitigation**: replies are newline-framed, so
  `tools/ble_smoke.py` resends a command (up to 3x) when no complete
  line arrives; `hist` framing (#BEGIN/#END) makes streamed days
  verifiable the same way.
* Upstream-worthy: TX overflow should block or raise, not drop.

### 9. C6: `_bleio.PacketBuffer.write` blocks FOREVER after client disconnect
* Tried the proper fix for issue 8: wrap the UART TX characteristic
  (`uart._server_tx.bound_characteristic`) in a
  `_bleio.PacketBuffer(ch, buffer_size=8)` and send via its `write()` —
  flow control works (no more drops) **but when the client disconnects
  mid-reply the pending `write()` never returns**, freezing the whole
  main loop (found wedged at `net_ble._write_paced` minutes later; only
  Ctrl-C recovered it). Supervision timeout has long expired by then —
  the port should abort blocked writes on disconnect.
* So PacketBuffer TX is opt-in (`"ble_tx_pktbuf": true` in config.json,
  default off) with a connected-check + bounded retry guard; the default
  path remains paced `UARTService.write` + client-side line retries.

## Library bugs
* `adafruit_jd79667` ships **debug prints**: the start-sequence hex dump
  and a stray `AttributeError:` line on every init.
* `adafruit_jd79667` passes no `refresh_time`/`seconds_per_frame`; the
  quad panel takes ~20 s per refresh; the inherited defaults (refresh_time=40, seconds_per_frame=180) are wrong for it, and `time_to_refresh` did not
  reflect the enforced minimum in all states.
* `mpremote fs cp` to a **new** file on CP 10.3-alpha fails with a
  device-side `ENOENT` (overwrites of existing files work) — CP or
  mpremote raw-REPL helper incompatibility.

### 10. C6: resident BLE starves ESP-NOW **TX** (ESP_ERR_ESPNOW_NO_MEM 0x3067)
* In BLE mode the collector RECEIVES espnow fine (node `dsc` broadcasts
  logged every cycle) but **every send fails `IDFError: ESP-NOW error
  0x3067`** (= ESP_ERR_ESPNOW_NO_MEM, IDF internal heap). Retries don't
  help; **`deinit()` + fresh `espnow.ESPNow()` doesn't help either**
  (reinit succeeds, next send still 0x3067). Nodes therefore never get
  cfg replies → discovery can't complete → no data flows.
* Control: identical build with `ble_enabled=false` — discovery, data,
  time push, config push, and 36-reading stash retransmit all pass
  immediately.
* **Consequence: on the C6 the collector is EITHER a BLE hub OR an
  ESP-NOW hub, not both** (mirrors the BLE-vs-HTTP-sockets finding,
  issue 5). config.json ships `ble_enabled=false` so the node mesh works;
  flip it for a BLE-access hub. PSRAM boards should manage both.
* `net_espnow.EspNowHub.send` now retries then deinit/re-inits and logs
  loudly instead of failing silently.

### Fixed along the way (our bugs, 2026-08-24 evening)
* `node/envproto.py` was a stale copy (no `at`/`t` fields) → node crashed
  `TypeError: unexpected keyword argument 'at'` before ever transmitting.
  Also: that crash happened OUTSIDE the guarded transport path, so the
  node hit "Code done running" instead of sleeping — consider wrapping
  packet build too.
* Node `_try_send` read `send_success` immediately after `send()` — the
  ACK callback is async, so every send looked failed: the node
  re-discovered every wake and stashed readings it had actually
  delivered. Now polls the counters for up to 0.2 s.
* Node `_listen_cfg` windows were 0.25-0.5 s; the collector replies from
  its main loop which can be seconds away (eInk SPI refresh) → raised to
  1.5 s.
* Node config had `configured: false` → every power-on sat 180 s in the
  setup portal before reporting (looked like dead ESP-NOW).

## Devkit validation matrix (C6 + S3 devkits, dual USB, debug CP builds)

Every finding above rests on black-box observation of release builds on
Feathers. Before filing upstream, validate each on **devkits with both
USB ports** (native + UART bridge: console stays up through resets and
radio crashes) running **self-compiled CircuitPython with debug logging**
(WSL tree `~/dev-projects/python/circuitpython/circuitpython`, main;
`cd ports/espressif && . ./esp-idf/export.sh && make
BOARD=adafruit_feather_esp32c6_4mbflash_nopsram V=1`; enable IDF
logging + `CIRCUITPY_DEBUG`, esp_log for wifi/dhcp/nimble/espnow).

| # | Claim to validate | Debug evidence wanted |
|---|---|---|
| 0 | softAP associates then drops clients | wpa/hostapd + DHCP server logs during a phone associate |
| 1 | `start_ap` after heavy imports hard-faults (alloc fail → fault, not MemoryError) | backtrace at fault; heap_caps trace of the failing alloc |
| 2 | wifi/socket bring-up corrupts the shared SPI lock flag | watchpoint on the lock word; find the writer |
| 3 | failed `sdcardio.SDCard()` leaves SPI locked | confirm on both chips; simple fix PR |
| 4 | splash auto-refresh starves user refreshes | supervisor refresh scheduling trace |
| 5 | BLE+AP orderings matrix (only BLE-then-AP coexists) | nimble + wifi init logs per ordering; internal-heap watermarks |
| 6 | `espnow.ESPNow()` kills an active softAP | wifi event log at espnow init (channel/iface change?) |
| 7 | GATT connect fails silently under low memory | nimble log at connect when gc/IDF heap is starved |
| 8 | `_bleio` TX notify queue ~5 deep, overflow drops silently | nimble notify path; confirm queue depth + drop site |
| 9 | `PacketBuffer.write` never returns after client disconnect | nimble conn-state at the blocked write; should abort on disconnect event |
| — | DHCP itself is fine for user APs (the node's portal AP serves phone leases with the same `start_ap`+`start_dhcp_ap` calls); the **collector's** AP fails because BLE and/or ESP-NOW are resident alongside it — a radio-coexistence conflict, not missing DHCP | wifi/dhcp logs on the host AP with espnow/BLE up vs. without |
| 10 | BLE resident → every espnow send fails 0x3067 NO_MEM (RX unaffected; deinit/reinit no help) | heap_caps_get_free/largest for MALLOC_CAP_INTERNAL with vs. without nimble; find the espnow TX alloc that fails |
| — | node S3 wedged unresponsive (no console, no Ctrl-C) after repeated fake-sleep + espnow cycles; needed 1200bps-touch → bootloader → hard reset | reproduce with dual-USB console attached |

## TODOs
* [ ] Fill in the BLE retest table above; file upstream issues 1–4 (and 5
      if confirmed) at adafruit/circuitpython + the jd79667 debug prints.
* [ ] Node ↔ collector: verify ESP-NOW discovery end-to-end on the bench
      (S3 node with SCD41 → BASE597BE4), incl. stash retransmission after
      a collector outage and hub-time retro-adjustment.
* [ ] Battery watermark test (unplug).
* [x] Calibration: two-step scheduled reference cal built + hub dry-run
      verified over BLE (2 min window, ref 568/spread 8, no FRC written).
      Node-side window still needs an end-to-end run (needs espnow TX +
      a trigger path: STA-WiFi HTTP, or a PSRAM hub) -- see README.
* [ ] QT Py S3 + 2.9" tri-color HIL rig bring-up (profile `tri_2in9`).
* [ ] GitHub Pages deploy of `webapp/` + web-BLE against the S3 node/hub.
* [ ] Adafruit IO upload of averaged subsets (future).
* [ ] Wire the eInk BUSY line (D7?) on a future revision — with no busy
      pin the driver flies blind through 20 s refreshes.

## 2026-08-26 devkit bench session (C6 + S3 devkits, self-built CircuitPython)

Bench: ESP32-C6-DevKitC-1-N8 (muselab nano, NeoPixel GPIO8) as the **hub**,
ESP32-S3-DevKitC-1-N8 (no PSRAM) as station/node client; both dual-USB
(UART bridge COM13/COM14 for esptool + IDF logs, native COM17/COM21 for the
REPL). CircuitPython built in WSL from `tyeth/circuitpython` (`wifi-ap-debug`
branch = bench firmware with ESP_LOGW instrumentation; `espressif-radio-heap-
reserve` = clean upstream-candidate branch). Tools/logs: `C:\dev\python\
circuitpython\cp-debug-tools\` (bench.py, repro_code.py, cleanlog.py, probes).

### Root cause found (issues 0, 5, 6, 10)
CircuitPython's espressif port lets the auto-growing Python heap take the
**entire** largest free IDF block (`gc_get_max_new_split()` ->
`heap_caps_get_largest_free_block()`, no reserve). With the collector running,
the wifi driver had ~8 KB left:
* `esp_now_send` -> `0x3067 ESP_ERR_ESPNOW_NO_MEM` with `idf_free=7884
  largest=7680` (issue 10, reproduced **without BLE**).
* phone associates, DHCP server builds the ACK, `udp_sendto result -1` ->
  "obtaining IP address" forever (issue 0).
* `start_ap` hard fault instead of MemoryError when the blob's alloc fails
  (issue 1, same mechanism).
Bare radio scripts with ~180 KB free never failed: AP + DHCP + ESP-NOW + BLE
coexisted in every ordering, so issues 5/6 were symptoms, not radio bugs.
**Fix (firmware)**: reserve IDF heap while wifi/BLE are enabled
(`CIRCUITPY_ESP_RADIO_HEAP_RESERVE`, 32 KB default in the clean branch, 40 KB
on the bench build). Also: softAP DHCP server auto-starts (`start_dhcp_ap()`
returns `ESP_ERR_ESP_NETIF_DHCP_ALREADY_STARTED`); the collector's call is a
harmless no-op.

### Collector memory (probe `mem_probe.py`, C6)
`import wifi` 41 KB; `bitmap_label` 17 KB; dashboard 24 KB gc + 65 KB IDF;
helper modules 24 KB; **`adafruit_httpserver` 46 KB**. Replaced the latter
with a ~300-line non-blocking socketpool server (`net_wifi.py`): collector
went from OOM to 54 KB free (32 KB reserve). `.mpy` shipping saves ~6 KB.
`label.Label` instead of `bitmap_label` was WORSE (more gc) - reverted.

### HTTPS on the hub (secure context for the built-in AI / web-BLE)
Public Let's Encrypt cert for `192dot168dot4dot1.gundryconsultancy.com`
(files SD `/sd/certs` first, then flash `/certs`; `certstore.py` parses
`notAfter` from the PEM, `POST /api/cert` installs, renewal from
gundryconsultancy.com when online). Findings on CircuitPython server TLS:
* `CONFIG_MBEDTLS_SSL_OUT_CONTENT_LEN=2048` (CP default) cannot send a 3.7 KB
  chain -> `PSA_ERROR_BUFFER_TOO_SMALL` surfaces as `OSError(138)`; bench
  firmware uses OUT=4096, IN=4096.
* `ssl.SSLContext()` attaches the CA bundle -> as a *server* it demands a
  client certificate (`MBEDTLS_ERR_SSL_NO_CLIENT_CERTIFICATE`); clear with
  `ctx.load_verify_locations(cadata="")`.
* handshake only happens in `accept()` on a wrapped listener, or implicitly on
  first recv of a wrapped accepted socket; a wrapped *listener* keeps a full
  mbedTLS context resident and starved DHCP again -> wrap per connection.
* RSA-2048 handshake ~1.3 s of blocking CPU on the C6 (HW MPI is already on);
  phone Chrome opens several connections and abandons the slow ones
  (`MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE`, `EPIPE 141`).
Status at end of day: phone reached the secure page (isSecureContext true)
several times but not reliably; the last regression was self-inflicted (a
2.5 s "no request yet" timeout killing sessions mid-handshake - raised to
10 s at e881526, untested). Session tickets + HW SHA/AES firmware commit was
reverted on the bench build pending a controlled retest. Captive portal now
lands on plain http (fast); https is a header link.

### Web app
Header: enable AI (user activation), speak/Ask, http<->https switch, hub->
hosted handoff via URL fragment; cert sync/upload; default base URL = hub
https hostname; CO2 calibration collapsed at the end. Pages (HTTPS) can call
the hub over HTTPS (CORS) - needs the hub cert; plain-http hub is blocked.

### Open items
* [ ] **Cert sync CORS fallback** (web app `certSync()`): the direct
      `fetch("https://www.gundryconsultancy.com/ssl.combined")` only works if
      that server sends CORS headers. Supplement with a CORS-fixer proxy
      fallback, e.g. allorigins (`GET https://api.allorigins.win/get?url=<enc>`
      -> JSON `{contents}`), used only when the direct fetch throws; verify the
      PEM parses (`-----BEGIN CERTIFICATE-----` x2 + PRIVATE KEY) before
      pushing to the hub, and keep the file-upload path as the last resort.
      Note the proxy sees the private key in transit -- acceptable only because
      the key is already published on that site; prefer fixing CORS on the
      server. Suggested shape:
      ```js
      async function fetchViaCors(url){
        const r=await fetch(`https://api.allorigins.win/get?url=${encodeURIComponent(url)}`);
        if(!r.ok)throw new Error("proxy "+r.status);
        return (await r.json()).contents;
      }
      // in certSync(): try direct fetch; on TypeError (CORS) -> fetchViaCors(url)
      ```
* HTTPS reliability on the C6 (retest e881526; then bisect tickets / HW crypto).
* `node packet error: OverflowError overflow converting long int to machine
  word` in the collector's node packet parsing.
* Plotly/Pyodide from `/sd/www/vendor` before CDN.
* BLE + ESP-NOW coexistence retest under the new heap headroom.
* Upstream: PR from `espressif-radio-heap-reserve` (reserve + server session
  tickets; builds on stock C6 layout), issue for the PSA/`errno 138` mapping
  and the 2 KB out-buffer.
* Tomorrow: HITL host SBC with Ethernet uplink so the agent can join the hub
  AP itself and drive the browser tests.
