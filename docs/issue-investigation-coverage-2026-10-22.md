## Pico application integration and silent MSC writes — 24 October

## Pico 2 actual hub scan follow-up (24 October)

Actual hub boot now reaches AP, HTTP/HTTPS listeners, BLE UART advertising and
the collector loop with 85,424 bytes free after scanner creation. It exposes a
positional `_bleio.start_scan` API bug, fixed by `prefixes=`; three new host
regressions pass versus two failures/one error before, and 50 protocol checks pass.
The initial physical rerun removes that TypeError but reports scan OSError22:
that run remains **failed**, with no API request made. All four
attempts preserve their failures and restore the exact original 4 MiB image.
Separate raw scan matrices pass 24/24 on each of original9e153 and candidate5f731,
including AP plus connectable advertising. All filtered counts are zero, so
node delivery is not implied. A later trace and minimal ordering reproduction narrow the error as described below.
A fifth instrumented boot identifies `start_scan` itself with the expected
arguments. Twelve HTTP JSON checks pass and latest consistently reports the
scan error. The job remains failed (also a network cleanup assertion); exact
original flash/runtime/radios/port restoration pass, then a separate read-only
postflight verifies disconnected Wi-Fi, removed test profile and baseline state.

The sixth run traces the error to controller LE Set Scan Enable status0x12;
it separately fails AP association and needs separate successful full-image
recovery after a USB descriptor-read error. A minimal MCU-boot reproduction
without Wi-Fi/GATT imports fails when connectable advertising precedes the
first scan (both .1/.05 windows), then passes after scanning once with
advertising stopped. The earlier raw controls had already primed scanning.
[Zephyr #12](https://github.com/tyeth/zephyr/issues/12) records this eighth new
issue. At that stage the implicit-identity/address-selection mismatch was
unpatched; the subsequent fix and passing comparison follow. Both later tests end with exact original flash/runtime/port restoration
and independent postflights. Diagnostic completion is distinct from the two
deliberately recorded scan failures.
The identity fix is now in Zephyr PR #11 at `5bf4230`: track implicit
connectable identity use and select the actual advertiser identity. A new
nondefault-identity unit case fails baseline; five configurations yield
19 pass/1 fail/35 skip before and 20 pass/0 fail/35 skip after. The revised
diagnostic full-hub run passes 44-file readback, MCU boot, twelve public-address
scan starts and twelve HTTP JSON checks. All scanner API samples have ble_rx=0
and no ble_err: node delivery remains unverified. Full original flash is
restored byte-exact, original files/identity/radios pass, networking/imports/power
are restored and independent postflights pass. The earlier preflash timeout and
minimal diagnostic missing its BEGIN marker remain failures. CP #32 now pins Zephyr5bf4230 at CP3254e272; both normal Pico builds pass
with matching clean dependencies, normal BLE workflows and no diagnostic hooks.
The normal Pico 2 image now has actual-node reception evidence below;
normal Pico W3254 remains build-only here. Production remains restored9e153. The diagnostic bounded pass is not a long-soak claim.
See [hub scan evidence and controls](pico2-hub-scan-2026-10-24.md).


PR #11 is integrated locally with the C5 I2C guard and full-chain certificate
fix retained. The actual Pico W node entry point passes two MCU-reset boots,
five simulated-sensor advertising cycles each, stable identity and exact full-disk
restoration. Startup free heap is 77,616 bytes. Over-air receipt and real sensors remain unverified. Pico 2 hub startup and
its corrected scan startup and bounded HTTP behavior now pass as described
above; end-to-end node delivery and real peripheral qualification remain open.
[Report, transcript and scope](picow-node-application-2026-10-24.md).

New [CP #43](https://github.com/tyeth/circuitpython/issues/43) records physically
reproduced silent rejection of a multi-sector MSC write starting at synthetic
MBR LBA 0. Source ignores the block-device error. Partition-only recovery and
exact full-disk verification pass. The first test and intermediate recovery
wrapper failures remain failed; a corrected application transaction passes.
Firmware fix `5f73172d46` now propagates the rejection as SCSI CHECK CONDITION:
the direct Pico W before/after comparison, valid partition write and three
free-sector write/restore controls pass with complete disk verification.
Original code/full expected flash and radio checks are restored. Native
fault/bounds/cache checks pass 56/56 versus 34 failures on the preceding source;
both Pico builds pass. Pico 2 physical MSC subtests now pass too, including
three free-sector spans and complete disk restoration. Its original job remains
failed at a later ROM reattachment identity guard; separate recovery verifies
original code/full expected flash, three radio cycles and baseline port state.
The #42 stall and Pico 2 64 KiB read latency remain open.
[Exact reproduction, preserved guard failure and limits](zephyr-msc-errors-2026-10-24.md).
This remains one issue in the seven-new-issue tally, not a new issue or closure.

## Pico 2 forced BLE retry — 24 October

The current HAL ready guard now passes the Pico 2 three-software-error/retry
control: expected errno after each forced successful-operation return, usable
Wi-Fi after each, one download across four attempts, stable BLE identity and
three successful BLE scans. Original production code, full expected flash,
three radio checks and port/import cleanup all pass. Natural electrical
faults and workflow client transfers remain unqualified. This supersedes older
Pico 2 forced-error-pending statements below. [Report and exact reproduction](pico2-bt-forced-retry-2026-10-24.md).

## S31 HCD timing follow-up — 24 October

Temporary instrumentation narrows the 64 KiB delay to channel activation →
HCD retirement, with microsecond submission/callback overhead. Four complete
network replies match all 64 UART segments. The original job **failed** on
a separate final 4 KiB response with no captured payload; offline analysis
retains that boundary. Original bridge app/full expected flash/API/topology
restoration and a separate read-only postflight pass. No host-versus-device
root cause or fix is claimed. [Evidence](pico2-s31-hcd-timing-2026-10-24.md).

Certificate failure injection is now tracked by [application #38](https://github.com/tyeth/deepsleep_espnow_wifi_and_ble_env_collector/issues/38):
mismatched live pair after second rename failure and abandoned `.new` files
after rejected end/abort. These remain application defects, not CP defects.

# Issue investigation coverage — updated 23 October 2026, 23:19 UTC

## Pico 2 long-read comparison: independent failure remains

Both original `9e153ad624` and latest normal `0d545efdcf74` pass 4 KiB and 64 KiB
reads with CDC checks but fail the full-disk 64 KiB-request read through S31. USBmon records
successful 64 KiB READ(10) completions delayed by about 10, 14 and 14 seconds
on each revision, with zero capture drops. The candidate's paired USB fixes
therefore do not resolve this workload. Original code was restored with whole
expected-flash verification and three radio checks; imports and port state were
restored without a bridge restart. Runtime data was retained, so restored flash
is not identical to the pretest backup. No raw-sector write test was attempted.
This is independent evidence for Pico 2; its cause is not established as the
same as direct Pico W #42. Earlier UART-reset and capture-cleanup fixture
failures remain preserved. [Comparison, minimal reproduction and exact limits](pico2-msc-long-read-comparison-2026-10-23.md).


**No: the work is not fully investigated or physically verified.** This ledger
reconciles the original `bugs_issues_and_todos.md` with the CP #15 escalation
index. More soak time is now lower priority than these specific gaps. A source
fix, a native fault-injection test and a physical-board test are separate kinds
of evidence. Historical notes below are not new reproductions.

A simultaneous USB/IP network/USBmon capture now places the long interval
before the first reply arrives at the host: 10.037/14.024/14.024 seconds, followed
by complete 64 KiB reply delivery in under 10 ms. A tested out-of-order-aware
decoder confirms these timings. This does not yet distinguish request delivery,
bridge admission/completion queuing, or device USB processing. The full-read job
remains failed and all cleanup passes. [Timing and decoder boundaries](pico2-msc-long-read-comparison-2026-10-23.md#simultaneous-network-and-usb-timing).

A new original-firmware size control reads the entire 2,617,856-byte disk twice
using 4 KiB requests in 6.881/6.478 seconds with exact content equality, surrounding
a 256 KiB prefix read using 64 KiB requests that takes 24.307 seconds. A separate
quiet/active-console/quiet prefix control takes 24.311/56.260/56.210 seconds;
20 print probes complete but do not remove the delay. These diagnostic jobs
PASS with clean capture/port/import restoration; prior full-disk 64 KiB failures
remain failures. No writes or latest-candidate 4 KiB full-disk qualification are
claimed. [Reproduction, capture boundary review and limits](pico2-msc-long-read-comparison-2026-10-23.md#transfer-size-and-console-activity-controls).

The direct Pico W open-console timing control reads its entire 520,704-byte
disk in 1.117/1.019/1.120 seconds using 4 KiB/64 KiB/4 KiB requests, with exact
content equality. Seven 64 KiB READ(10) commands complete in 116–120 ms; all
298 target MSC commands have successful status wrappers. This different-board
comparison does not isolate the bridge or disprove the closed-console issue.
[Direct-board timings and scope](pico2-msc-long-read-comparison-2026-10-23.md#direct-pico-w-timing-control).

The temporary S31 per-segment diagnostic now localizes the Pico 2 W large-read
pause to host-submit-call → client-completion-callback time: ten and fourteen
segments each take approximately one second, while application queueing and
reply delivery take milliseconds. Original bridge firmware was restored and
whole expected flash verified. This is new localization, not a fix or host/device
causal attribution. [Measurements and minimal instrumentation](pico2-s31-segment-timing-2026-10-24.md).

## Certificate-sync coverage correction (24 October)

The original application issue #25 (distinct from CircuitPython warm-reset #25)
records the oversized BLE upload, receive-line discard and missing-dispatch
failures. Chunked `cert begin` / `c` / `k` / `end` support and historical C6
hardware verification are present. Current host checks now pass: 20 JavaScript
test groups (`node webapp/tests/cert_sync.test.mjs`) and all parser/receiver checks
(`python3 tools/test_cert_ble.py`), including bounded chunks, exact reassembly,
missing handler, oversize-line recovery and disconnect cleanup. These do not
constitute fresh 11.0.0-alpha.2 physical certificate installation.

Targeted POSIX host failure injection now reproduces two separate application
defects: a failed second rename leaves a new live chain paired with the old key;
and a rejected `end` clears the receiver, so a subsequent abort leaves both
`.new` files. Synthetic fixtures and mocked expiry isolate these paths; this is
not physical filesystem or power-loss qualification. No cryptographic key/cert
match validation is claimed by the protocol tests. [Reproduction and limits](cert-install-failure-paths-2026-10-24.md).

## Pico USB production rollout: console-close storage blocker

The actual `6839890534` Pico W rollout fails its initial capacity read before
the repeated-configuration tests. A second temporary run reproduces it with
USBmon: a TEST UNIT READY completes after 10.126 seconds as the console reopens,
with no missing MSC status wrappers or reported capture drops. The first
automatic restore stalls on host storage unbind; a separate CDC ROM recovery
restores original firmware, full expected image, three radios and bindings.
The traced run also restores successfully. Both production Picos remain `9e153ad624`;
The later temporary latest-build Pico 2 comparison above also fails its
full-disk 64 KiB read and restores original code; permanent rollout remains blocked.

Matched no-flash controls on the older build show 31 ms reads with the console
open or DTR off, but 2.068/4.066 seconds when a closed console is reopened after
2/4 seconds. One closed-port attempt with a one-second reopen does not stall;
the trigger is intermittent. Sleep/busy/sleep reads stay 31/32/60 ms, so no
thread-priority fix is justified by these controls. Root cause remains open in
[fork #42](https://github.com/tyeth/circuitpython/issues/42). See
[minimal steps, failed rollout and recovery](picow-console-storage-stall-2026-10-23.md).
Earlier bounded USB-fix passes retain their scope; they do not prove production
reliability with the console closed.

## Follow-up: runtime power, control endpoint and interpreter progress

Further no-flash controls on the older firmware narrow the fault:

- The Pico and both parent hubs already have runtime power policy on. Reapplying
  and restoring it still gives three closed-console reads around 3.074 seconds,
  alongside fast non-reproductions. Supported sampled ancestors remain active
  with zero suspended time, including immediately before reopening during stalls.
  Linux runtime autosuspend does not explain these reproductions.
- Device GET_STATUS succeeds with the console open. In two closed-console
  reproductions it times out (ETIMEDOUT) while disk reads wait 4.066 seconds for
  reopening. A third attempt passes both operations. The fault therefore affects
  control traffic as well as storage. Direct interface line-state requests return
  Linux EBUSY because the CDC driver owns the interface; those are inconclusive.
- Python continues executing during the USB stall. Of three closed-console busy
  runs, two disk reads wait 3.133/3.067 seconds, while maximum gaps between Python
  iterations are only 8.06/7.81 milliseconds. A sleeping-loop reproduction waits
  3.068 seconds with a maximum iteration gap of 15.87 milliseconds. This evidence
  does not support a whole-MCU freeze or a fault limited to the REPL prompt.
- Leaving the console closed also led to kernel USB reset/descriptor timeouts,
  followed by a host-initiated port power cycle and same-device re-enumeration.
  Two later probes stopped at missing-device guards; another hit an enumeration
  race before its first test. These failed attempts remain preserved.

All successful reads retain the same 4 KiB hash; completed comparisons restore
host bindings and power settings and leave the S31 unchanged. The initial PM
fixture failed before changes when an ancestor sysfs attribute returned EIO;
the corrected fixture records unsupported attributes. A first strict control
fixture records the GET_STATUS timeout as a failed job, with cleanup passing.
The completed diagnostic means evidence collection passed, not that USB is fixed.

Root cause and production rollout remain open in
[CircuitPython fork #42](https://github.com/tyeth/circuitpython/issues/42).
The [sanitized measurements](picow-console-followup-2026-10-23.json) retain every
comparison, including non-reproductions. USB thread/queue and controller-state
instrumentation is still needed before selecting a source fix.

## Passive USB and thread snapshots

A temporary diagnostic build on CircuitPython `6839890534556b06b8b3d7c491e36fd2005b2483`
and Zephyr `c6200e80ea6973b092da3c30c672901cc1951fc2` captures controller registers,
endpoint state and Zephyr thread waits into RAM. It makes no USB requests and
prints the captured data only after the console reopens. Each round contains
20 snapshots approximately 300 ms apart; each snapshot is 816 bytes and contains
17 threads. The temporary source edits were removed and original source hashes
verified after building.

Five open/closed/closed/closed/open rounds read the same 4 KiB disk data in
0.031, 0.061, **3.126**, **3.067**, and 0.060 seconds. Reopening was scheduled
three seconds after closing. Both long stalls therefore occurred with the
instrumentation installed; the fast closed round preserves the intermittence.

At the sampled points, including both long stalls:

- The UDC mutex has no owner and depth zero. Driver event, new-transfer,
  finished-transfer, buffer-status, interrupt-status and abort bits are zero.
- UDC, USBD and MSC threads wait on their normal event/message queues. The
  exact diagnostic ELF resolves those wait-queue addresses.
- The USB SOF frame counter advances during the stall. The MSC OUT endpoint
  has an available receive buffer, is not halted, and has no received bytes in
  its queued buffer. The separate HID OUT buffer is not a second MSC buffer.
- Actual runtime priorities are UDC/USBD **-8**, MSC **-1**, and Python main
  **14**. The configured UDC value 8 is passed through `K_PRIO_COOP`; it must
  not be read as preemptive priority 8 or used to infer starvation by main.

These samples do not show a held UDC mutex, stranded completion event, stopped
frame clock or whole-interpreter freeze. They do not establish which side of
the USB link is responsible. Sampling can miss short transitions, and host
USBmon completion timing cannot reveal electrical packets or DATA0/DATA1 state.
Host-controller/hub behavior versus device endpoint protocol remains the next
discriminator; no erratum or source fix is claimed.

The original `9e153` code was restored, the complete expected 2 MiB image was
verified, and three Wi-Fi/BLE scan cycles passed (76/64, 75/73, 80/70 results).
The full restored image is not bit-identical to the pretest backup because
runtime version metadata changed. Console bindings were restored and the S31
was untouched. Both production Picos remain on the previous firmware; rollout
remains blocked by [fork issue #42](https://github.com/tyeth/circuitpython/issues/42).

[Sanitized grouped measurements](picow-usb-passive-snapshot-2026-10-23.json) and
[the temporary instrumentation and decoder](../tools/repro_picow_usb_snapshot/README.md)
make this result reviewable. Six decoder controls and eight flash-transaction
fault controls passed. Raw flash images and USB captures remain private.

## Host HID binding control

The older production `9e153` image also reproduces the console-close stall
with the host HID driver unbound. CDC and MSC stay bound throughout this
comparison. Closed-console reads before unbinding take 3.128, 0.034 and 3.068
seconds; with HID unbound they take 3.068, 0.058 and 3.140 seconds. Three after
rebinding are fast (0.031/0.035/0.060 seconds). Open controls before and after
take 0.032/0.061 seconds. All eleven reads have the same hash; Python keeps
progressing with maximum iteration gaps below 18 ms.

A bound host HID driver is therefore not required for this reproduction.
Three attempts per phase do not estimate failure rates, and the final fast
rounds do not establish that rebinding fixes this intermittent problem. Device
HID endpoint configuration, hub behavior and host-controller behavior were not
independently removed by this comparison. Root cause remains open.

No firmware or filesystem writes were made. Original bindings were restored
while the console remained open, and the S31 was untouched. The
[sanitized timing record](picow-console-hid-control-2026-10-23.json) retains
all reproductions and non-reproductions.

## USB/IP reconnect: endpoint reconfiguration isolated

The Pico 2 single-import MSC failure now has packet evidence and matched
controls: CLEAR_FEATURE on both MSC endpoints passes 4/4, GET_STATUS with the
same extra session passes only the first import, then CLEAR_FEATURE passes
4/4 again. CDC survives all baseline/workaround cases. A one-function Zephyr
reconfiguration candidate instead fails its first CDC raw-REPL write, before
MSC; it is rejected from rollout and production is restored exactly. A second
combined candidate adds cancelled-OUT CDC rearming and passes all four ordinary
imports with correct first-INQUIRY exchanges and exact disk reads; production
is again restored. The fixes are carried by Zephyr `c6200e80` and CP pin
`6839890534`, with production rollout still pending. A later direct Pico W comparison now
reproduces failure on the second baseline configuration selection, while the
actual `6839890534` build passes four selections, eight whole-disk comparisons,
CDC and three radio cycles. Original firmware and bindings are restored; see
[the direct comparison and restoration limits](picow-usb-reconfiguration-2026-10-23.md).
A subsequent mixed comparison on the actual Pico 2 `6839890534` build still
fails MSC and the Pico console with Metro CDC in either import order, while
Metro survives. Both initial and post-load single-Pico MSC/CDC controls now
pass, separating this load-dependent failure from the reconnect defect.
Production code, ports/imports/defaults and three radio checks are restored;
no bridge reboot occurs. A later UART capture proves channel exhaustion in both mixed cases; turning off the unused C6 makes the same workload pass in both orders with zero exhaustion messages. See [the instrumented capacity control](s31-channel-exhaustion-2026-10-23.md). The headroom job remains failed: other leaf devices reappeared during C6 power-on, and its cleanup/runtime checks failed after full firmware restoration. A separate no-flash recovery restored the original topology and passed all three radio checks; the bridge did not reboot.
See [the preserved mixed failure and restoration](s31-mixed-usbfix-2026-10-23.md).
The same-configuration source defect is already tracked as
[Zephyr #121843](https://github.com/zephyrproject-rtos/zephyr/issues/121843).
See [the controlled evidence, candidate and limits](usb-reconfiguration-2026-10-23.md).
No physical DATA0/DATA1 capture, production rollout, idle-failure closure or
full composite capacity qualification is claimed.

## ESP-NOW default-peer discrepancy: isolated below CircuitPython

The standalone C6 IDF probe captures all 30 submission results across three
rounds: broadcast-only NULL fails six times with 0x3069; explicit broadcast,
unicast-only and mixed-list calls are accepted. MicroPython documents this
exclusion; the ESP integration corrects the CircuitPython API documentation.
This closes the standalone-reproduction gap, not the mixed-list delivery or
multi-sender qualification gaps. Full flash restoration and `ea06dcb44e`
runtime verification passed. [Minimal C app and evidence](c6-espnow-idf-contract-2026-10-23.md).

## Controller candidate: physical power-cycle verification

The exact PR 2 adapter at `6ca2f2d` now passes a real C6 cycle, continuing
polling through an on-but-disabled port, absent parent hub, then returned
off state before accepting on/enabled/present. Independent runtime uptime
was 7.21 seconds; imports were detached. This is standalone candidate
qualification. The exact adapter has since been deployed after 61 isolated live-base tests, Ruff/mypy, six cutover controls and restart/readiness verification. See [physical trace](controller-c6-physical-2026-10-23.md) and [deployment evidence](controller-power-deployment-2026-10-23.md).

## C6 follow-up: bare-board checks completed

The C6 is now installed at `ea06dcb44e`. Five MCU-reset startup orderings,
connected GATT transfer/disconnect/reconnect, BLE restart, absent-SD SPI-lock
checks, AP/DHCP and five exact HTTP responses pass. Concurrent-radio ESP-NOW
delivered 93/100 exact round trips with seven send failures and no corrupt
payloads. Default `send(..., None)` with only a broadcast peer reproduces
`0x3069`; an explicit peer succeeds. The board is bare: display, RTC and SCD41
checks remain unavailable. Low negotiated MTU 23 is not established.
See [C6 results and preserved failures](c6-targeted-qualification-2026-10-23.md).

## Update on 23 October: DHCP scheduling failure reproduced and candidate passes

The earlier DHCP failure is now narrowed to socket-service starvation. On the
same binary, Pico-side sleeps let a lease arrive; changing only the service
priority from 15 to the interpreter's 0 also passes with no sleeps. A 15-second
busy-loop control acquires a lease in 4.467 seconds while Python continues
computing. The shared configuration fix is committed as `6b117bdce5`.
The production Pico 2 image now passes channel 1/6/11, DHCP, ping, matching station MAC/IP, departure and AP stop/restart. Cleanup passed. Pico W production rollout and the same AP checks now also pass, including BLE scans with a station associated. See the [controlled reproduction, provenance and limits](pico2-dhcp-scheduling-2026-10-23.md) and [production hardware evidence](pico2-production-ap-qualification-2026-10-23.json).

Both current Pico 2 512/2048-byte USB-worker diagnostics pass the same short concurrent CDC, read-only MSC, Wi-Fi/BLE workload. The maximum measured use is 260 bytes; this does not reproduce a 512-byte shortage. Production firmware was restored exactly. Pico 2 MSC writes, idle re-enumeration and broader stress remain open. A separate direct Pico W 9e153 test now passes three bounded raw-sector MSC writes with CDC checks and exact whole-disk restoration; this does not qualify Pico 2 or the S31 path. See [the write control](picow-msc-write-2026-10-23.md) and [the comparison](pico2-usb-stack-comparison-2026-10-23.md). The separately measured DHCP socket-service stack
reached 2184 of 2400 bytes with debug logging.

The historical ESP sleep-memory reload defect is already fixed upstream by
[CP #11274](https://github.com/adafruit/circuitpython/pull/11274), merge
`2a15ee1978b9c2fe10a77dcc26433cf1c658c766`. Ancestry was verified in both
official alpha.2 and deployed `cb5301b6fb`; no duplicate patch is needed.
A C5 `e467` physical control now verifies three VM reloads while the chip
reset reason remains POWER_ON: all 4,096 sleep-memory bytes survive each
reload, VM globals clear, and original memory is restored. The job still
fails its final combined cleanup assertion; separate read-only checks then
confirm original port/inventory/import state. This does not qualify fake/true
deep sleep or battery retention. See [the scoped test and minimal reproduction](c5-sleep-memory-reload-2026-10-23.md).

## Pico W production follow-up and newly verified API gap

Pico W production `6b117` now passes actual channel 1/6/11, DHCP, ping, matching
station MAC/IP, departure and AP stop/restart. Concurrent BLE scan and extended
request rejection controls also pass. Fresh full backup/readback and preserved
BLE identity passed. See [the report](picow-production-qualification-2026-10-23.md).

Separately, the earlier image remained connected after `stop_station()`: the
function was a no-op in the preceding integration and audited upstream source.
[CP fork #40](https://github.com/tyeth/circuitpython/issues/40) tracks the minimal
reproduction. The fix at `9e153ad624` now passes 46 native checks and physical Pico W connect/stop/reconnect, disabled-start and AP-preservation tests, including cleanup. Pico 2 now also passes these lifecycle checks at the same revision after full-flash/runtime verification; bounded trusted TLS with BLE and three certificate-rejection controls pass. Certificate date validity is deliberately unchecked. See [Pico 2 evidence and preserved fixture failures](pico2-station-tls-2026-10-23.md). See [the station lifecycle evidence](picow-station-lifecycle-2026-10-23.md).

## Earlier finding, superseded for DHCP by the production result above

On Pico 2 W at `7d4ef1aac7`, a direct-UART Feather ESP32 V2 station at
`cb5301b6fb-dirty` sees channel 1 and associates. Six AP station-table samples
show the station but no lease. The station's `connect(timeout=10)` still waits
at the 25-second host deadline; after interruption it reports associated with
address `0.0.0.0`. A static-address reconnect succeeds and pings the AP in
15 ms. Explicitly stopping/restarting the station DHCP client also fails to
complete the combined connect/ping command within 30 seconds. Thus the
association and basic IP path worked; this baseline had a faulty DHCP exchange.

The ESP timeout symptom matches existing upstream [CircuitPython #7557](https://github.com/adafruit/circuitpython/issues/7557).
It is separate from the DHCP scheduling failure subsequently fixed above. Do not close the
softAP tracker or call the diagnostic job's successful completion an AP pass.
The first combined test also failed station cleanup; a subsequent bounded
Ctrl-C recovery restored it. Both later tests confirmed station/AP cleanup.

A separate attempt using two S31 composite-device imports failed before AP
start: Pico console worked, but the S3 console did not respond. Both imports
were detached and original port states restored. The installed bridge still
claims every interface on first data traffic; unbinding host-side unused
drivers does not release those bridge claims. This supports investigating
channel pressure, but does not establish the failure's root cause.

The diagnostic image was subsequently flashed and measured, then replaced by the production fix. Channels 6/11 and station departure now pass. The later current-revision 512/2048 comparison is reported above. See [sanitized evidence](pico2-ap-dhcp-investigation-2026-10-22.json).

Minimal paired reproduction (use disposable bench credentials): start a Pico
AP on channel 1; on an ESP station call `start_station()`, `stop_dhcp()`,
`start_dhcp()`, then `connect(ssid, password, timeout=10)`. Independently sample
the AP station table and enforce a host deadline with Ctrl-C recovery. Compare
with a static station address in the same subnet and ping the AP. Stop the AP
and station, then restore the station DHCP client. This does not require a soak.

## Update at 23:41 UTC: connected-session BLE passes on Feather S3

A real BlueZ central received all 10,240 bytes from an unpaced Nordic UART
transfer, with the expected SHA-256. It then disconnected during an active
PacketBuffer burst. The write loop returned zero, reported disconnected and
returned to the host in 2.20 seconds after the disconnect request. Bytes queued
at disconnect were intentionally not expected to arrive. Reconnection produced
no unsolicited stale bytes, then delivered an exact fresh 1,024-byte payload.

After these connections, BLE disabled, re-enabled and scanned successfully
(59 advertisements) with Wi-Fi enabled and an ESP-NOW object still resident.
This addresses the connected-session part of original report 11 on this S3.
It also supplies physical regression evidence for reports 8/9 on S3, beyond
the upstream-source ancestry check. The original C6 and sustained radio/display
load variants remain unverified; do not close those reports from this result.
Bleak warned that its reported MTU was a default: negotiated MTU was not measured.
No flash writes or resets were requested, and the original USB/port state was
restored. See [sanitized evidence](s3-connected-ble-2026-10-22.json).

## Earlier targeted evidence

- Feather ESP32-S3, 4 MB flash / 2 MB PSRAM, actual banner
  `CircuitPython 11.0.0-alpha.2-15-gcb5301b6fb-dirty on 2026-10-22`:
  five BLE disable/re-enable cycles passed; each subsequent two-second scan
  received advertisements (111, 111, 106, 118, 112). Five absent-card SD
  constructors raised `OSError: no SD card`; SPI was immediately lockable after
  every failure. No firmware/file writes or resets were performed. Original
  port-off state and detached imports were restored. This does **not** recreate
  the original post-connected-NUS-session teardown with ESP-NOW running, nor
  the C6 shared display/SD configuration.
- HAL Pico #6: compiling the actual `cyw43_btbus_init` function and injecting
  allocation, download, ready, buffer-init and awake failures gives six passing
  candidate cases including success. The preceding revision aborts on the
  ready, buffer-init and awake cases. Cleanup and the absence of later startup
  stages are checked. This is native execution with mocked hardware hooks.
- HAL Pico #3: four actual-function controls demonstrate normal cached access,
  a dropped write with divergent cache/hardware, a noncached hardware read,
  and an out-of-band hardware change. A HOST_CTRL read does not verify hardware
  and the write wrapper reports success in the injected lost-write case. This
  is a diagnostic limitation; no physical lost write or stall cause is proved.
- Historical ESP BLE notification changes `8042913c2e` (PacketBuffer) and
  `f3926284f8` (Characteristic.value) are ancestors of both official alpha.2
  (`d53b2277cf`) and deployed ESP integration `cb5301b6fb`. They are upstream
  changes, not missing fork patches. The later S3 connected-session regression above passes; C6/load variants remain.
- Existing host regressions for RTC logic, UTC/timezone rules, ESP-NOW message
  confirmation, and datastore/history relabel/recovery pass. The datastore
  suite used an isolated scratch directory; the first attempt was stopped by
  filesystem permission before assertions. These tests do not measure flash
  latency, actual RTC battery retention or physical power-cut recovery.

Run the new native reproduction with a configured C compiler:

```sh
python3 tools/check_pico_btbus_reports.py /path/to/hal_rpi_pico \
  --baseline cc2ea478cd42c70f17562f983e6cb0e5f520bdee \
  --output /tmp/pico-btbus-results.json
```

Use HAL revision `725e9e429eab65eda01762a1af9016426dee00ac` for the recorded
candidate. The script extracts exact functions rather than reimplementing
their control flow. See [native evidence](pico-btbus-reproduction-2026-10-22.json)
and [hardware evidence](s3-targeted-issue-checks-2026-10-22.json).

## Update: ESP-NOW corruption reproduced with exact source

The three linked upstream ESP-NOW trackers (#9816, #7903, #9380) remain open.
Actual callback/read/ring-buffer source deterministically reproduces an invalid
buffer when the reader runs after header publication but before the packet is
complete. The source blobs match current upstream main. Exact-capacity controls
pass: the packet size already includes the MAC. Eight application fault-injection
checks pass for AP-safe reset, non-AP rebuild/failure handling, peer rotation,
unconfirmed node delivery, explicit broadcast peer and channel-switch ordering.
The follow-up `ea06dcb44e` packet synchronization fix passes ten native groups, including 20,000 concurrent packets with exact delivery/drop accounting, and fresh ESP32/C6 builds. It is now installed on Feather ESP32 V2: physical baseline fails on channels 1/6/11, candidate passes the identical traffic/integrity test with an S3 sender; see [the physical comparison](espnow-physical-comparison-2026-10-23.md). C6 is now physically checked: five MCU-reset orderings, connected GATT and bounded concurrent traffic; see the C6 follow-up above. See [the candidate evidence](espnow-rx-synchronization-2026-10-23.md). See [the reproduction and limits](espnow-targeted-investigation-2026-10-23.md).

## Original firmware reports

Numbers refer to headings in the original bug document, not GitHub IDs.

| Report | Current evidence / disposition | Remaining targeted check |
|---|---|---|
| 0, 1, 5, 6, 10: C6 AP/DHCP/import/BLE/ESP-NOW memory failures | Later August notes identify IDF heap starvation and the reserve workaround, correcting earlier coexistence-only diagnoses. Reserve and frozen libraries are carried. C5 application/HTTPS overnight results are useful but are not a C6 reproduction. | Five C6 MCU-reset orderings with heavy imports and actual DHCP/HTTP/ESP-NOW now checked; controlled allocation failures and original display/sensor load remain. |
| 2: Wi-Fi/socket creation leaves shared SPI locked | Historical staged observation; no fresh proof of corruption. | Probe lock ownership around AP, UDP/socket and display setup on the original shared-bus wiring. Distinguish bus ownership from a corrupted flag. |
| 3: failed SD init leaves SPI locked | Current constructor unlocks after normal `init_card` error returns. Five physical S3 absent-card cases now pass. | Five C6 absent-card cases also pass; shared display setup and exceptional SPI/configure failures remain. Do not close the broader report from S3 alone. |
| 4: e-paper splash refresh / misleading errors | Workaround assigns a real root group; display behaviour has not been freshly measured. | Instrument timer, busy and bus ownership separately; reproduce splash versus explicit group on the actual panel. |
| 7: BLE-mode memory starvation | Historical application fix gates HTTP imports; recorded resolved on the earlier bench. | Current constrained C6 boot and GATT connection with the intended display configuration. Silent low-memory GATT failure remains a separate diagnostic concern. |
| 8: dropped BLE notifications | Upstream alpha.2 contains retry fixes; S3 unpaced 10,240-byte transfer passes exactly. | C6 10,240-byte exact transfer now passes; verified low negotiated MTU and sustained radio/display load remain. |
| 9: PacketBuffer blocks after disconnect | Actual S3 mid-burst disconnect returns in 2.20 seconds; reconnect has no stale bytes and transfers 1,024 fresh bytes exactly. | C6 mid-burst disconnect returns in 2.252 s and reconnect transfers 1,024 exact bytes; sustained radio/display load and broader timing/race coverage remain. |
| 11: S3 adapter disable hard-fault / cannot re-enable | Five basic cycles plus post-connected-NUS teardown with Wi-Fi/ESP-NOW resident pass on current Feather S3. | Sustained concurrent traffic and the original application/sensor configuration; no crash reproduced in this targeted check. |
| Large code.py prevents Wi-Fi initialization | Historical MPY shim and current frozen libraries address memory placement. Eleven variants build; current app has completed deep-sleep/report cycles. | Board-specific cold-boot qualification, especially C6 with the real sensor/display load; no claim that compilation removes all memory limits. |
| Raw-REPL write then hard-reset filesystem corruption; S3 MSC write crashes | Historical evidence and safe deployment workarounds retained. | Disposable backed-up filesystem with explicit flush/soft reload controls and concurrent-radio variants. Avoid corrupting the live application store to obtain evidence. |
| sleep_memory after soft reload | Upstream #11274 fixes reload clearing; merge ancestry verified in alpha.2 and deployed cb530. True deep-sleep confirmations also passed in the app run. | C5 subsequently passed a fresh 4096-byte, three-pattern sentinel/VM-reload regression and restoration; see the physical sleep-memory result above. No duplicate source patch needed. |
| Windows empty GATT table / Service Changed | Still a report; cache mechanism unconfirmed. | Same device address, deliberate service-table change, cached versus uncached Windows discovery and Service Changed observation. |
| JD79667 logging/defaults | Exact upstream/frozen driver constructor reproduces hex output in four host controls; print-removal controls are silent. Inherited 40/180 defaults and explicit timing pass-through verified in source/host execution. | Actual panel timing and stray AttributeError still unverified; minimal patch retained, not deployed. See [library/tool evidence](library-tool-investigation-2026-10-23.md). |
| mpremote new-file ENOENT | Actual-board baseline reproduces existing MicroPython #17752: error conversion aborts existence check, while direct create/overwrite work. Parser fix passes new-file/overwrite/readback/cleanup; first candidate's line-ending failure retained. Full stock CLI/SerialTransport baseline reproduces the failure; candidate passes both copies, exact readbacks and cleanup. Fork draft PR #1 carries host regressions. | Stock CLI path is now verified on Feather ESP32 V2; matching MicroPython hardware suite and other host/serial-reset variants remain unrun. Human review/upstream submission pending. See [comparison](library-tool-investigation-2026-10-23.md). |

## Application TODOs and known limits

| Item | Coverage and next step |
|---|---|
| Node MPY shim, wake/report/deep sleep | Real sleep and confirmation cycles passed; sensor data in that run was simulated. Real SCD41 sampling is not qualified. |
| RTC detection, sync, battery retention, drift | Host register/detection/sync cases pass. Inventory the real RTC first; coin-cell retention, cell changes, drift and ambiguous chip identification remain physical tests. |
| UTC/NTP/browser time and calibration offset | Host timezone tests pass. Physical NTP/display observation and real scheduled calibration are separate. |
| Missing SD/day files, low-memory sensor startup | Historical root cause documented: unmounted directory/unsynced rows and uncaught MemoryError. Current real SD/sensor startup not requalified. |
| History RAM rows, relabel, interrupted job, read-only drive | Existing host suite freshly passes. Large-file flash timing plus simultaneous HTTP/ESP-NOW and real interruption remain. |
| Node autoconnect; collector in station mode; channel agility | Historical AP-channel 6/11 bench success. Autoconnect and router-channel variants still need targeted tests. |
| Outage stash, hub time correction, real sensor discovery | Confirmation protocol host tests and simulated-sensor overnight delivery pass. Fresh collector-outage replay and real-sensor test remain. Unsynced duplicates remain a documented design limit. |
| ESP-NOW buffer corruption / peer limits / broadcast / channel mismatch | All three upstream trackers remain open. Actual-source packet interleaving reproduces #9816; eight current application guard checks pass, including AP-safe recovery, peer limits, explicit broadcast and channel order. Packet synchronization candidate ea06 passes native checks and ESP32/C6 builds; physical ESP32/S3 baseline/candidate comparison now passes (old image reproduces invalid-buffer); short BLE scan coexistence also passes integrity (996/1000 received, 13 ads); broadcast gaps persist with 2 ms pacing; C6 bounded traffic now measured at 93/100 exact echoes with seven sender failures; multi-sender and sustained-load remain open; unused PHY-rate feature is not an application blocker. |
| Battery watermark | Requires a controlled battery/unplug event; not verified by USB port commands alone. |
| Calibration | Historical hub dry-run only; node window/result end-to-end still unverified. Do not perform an actual sensor FRC just to test transport. |
| AI model download progress and revisit cache | Implemented/tested portal paths. Android emulator retained model through page, Chrome and emulator restarts; offline inference did not download weights. Physical phone memory/performance remains unknown. Emulator lacks supported AICore; JS fallback is separate. |
| QT Py / tri-colour display rig and BUSY wiring | Physical rig work outstanding; not established by builds. |
| GitHub Pages and Adafruit IO | Deployment/future feature TODOs, not firmware defects; outside the present targeted regression pass. |

## CP #15 / Zephyr / HAL index

The [source audit](upstream-disposition-2026-10-22.md) contains exact upstream
revisions, closure reasoning and minimal reproductions. Its earlier timed
status sections are historical; completed hardware results are in the later
rollout and follow-up reports.

| Group | Status |
|---|---|
| Zephyr #5/#7, HAL Pico #7; CP #24 and console-wake portion of #20 | Upstream resolution checked; duplicate patches omitted or older-release compatibility patches retained as appropriate. |
| CP #26 TLS policy, #28 empty version, #9 extended-scan contract, #10 version refresh | Executed source/native/simulator regression evidence; physical failure injection is not implied. |
| CP #27 startup retry | Unfaulted original diagnostic passes; both single-ready-error and three-error retries halt on HCI Read_BD_ADDR completion timeout. A temporary ready-firmware download guard passes the identical three-error sequence and an unfaulted control, with stable identity and BLE scans. HAL #8 is now pinned in CP #32; both normal builds succeed and both boards pass physical startup and three BLE reenable/radio cycles, with original-code restoration. Two earlier Pico 2 original-firmware preflight failures remain preserved and unexplained; matched recorded commands also pass. Pico 2 forced-error retries subsequently passed three injected software errors, usable Wi-Fi after each, one firmware download across four attempts, stable BLE identity and three scans; see [Pico 2 retry evidence](pico2-bt-forced-retry-2026-10-24.md). Natural faults and workflow client transfers remain unqualified. See [normal qualification](pico-normal-ble-ready-guard-2026-10-23.md). All boards restored. See [matched evidence and reproducer](picow-bt-retry-ready-guard-2026-10-23.md). |
| Zephyr #3 settings geometry, #10 p256-m; shared-bus window/power/wake/RX locks | Reproduced and fixed/worked around with exact-source controls; earlier physical stall cause remains unproved. |
| HAL Pico #6 startup assertions | Native and physical ready/buffer/awake forced error returns pass. Retry then exposed repeated patch-RAM download; a separate ready-state guard passes the matched three-error retry and unfaulted control. These inject software returns after successful hardware work, not electrical faults. Production integration and bounded normal startup now pass on both Pico boards; Pico 2 forced-error qualification subsequently passed the three-error sequence; see [Pico 2 retry evidence](pico2-bt-forced-retry-2026-10-24.md). Natural-fault recovery remains open. See [follow-up](picow-bt-retry-ready-guard-2026-10-23.md). |
| HAL Pico #3 HOST_CTRL cache | Newly reproduced cache/hardware divergence under injected lost write. Production cache policy and physical incidence unresolved. |
| Zephyr #6 USB stack | Both current Pico 2 512/2048-byte USB-worker diagnostics pass the same short concurrent CDC, read-only MSC, Wi-Fi/BLE workload. The maximum measured use is 260 bytes; this does not reproduce a 512-byte shortage. Production firmware was restored exactly. Later targeted MSC writes now pass on both boards: the #43 candidate reports rejected-write errors correctly and passes valid writes plus three free-sector controls with exact full-disk restoration. Pico 2 uses S31 USB/IP; its original restoration job failed a ROM identity guard and separate recovery passed. See [MSC comparison](zephyr-msc-errors-2026-10-24.md). Idle re-enumeration, broader stress, #42 and the slow 64 KiB USB/IP workload remain open. The earlier direct Pico W 9e153 control is preserved separately. See [the write control](picow-msc-write-2026-10-23.md) and [the comparison](pico2-usb-stack-comparison-2026-10-23.md). |
| Zephyr #8 softAP | Channel 1 association/static ping pass. DHCP starvation reproduced; equal-priority candidate passes idle and busy Python controls. Production Pico 2 channel 1/6/11, DHCP/ping and station departure now pass. Pico W production follow-up also passes, including concurrent BLE scan with an associated station. Station lifecycle #40 is now fixed and verified on both Pico W and Pico 2 at 9e153. Pico 2 bounded TLS/BLE and hostname/default-bundle/unrelated-CA controls also pass; certificate dates remain unchecked. |
| Zephyr #9 legacy timeout | Direct Zephyr hardware reproduction on Pico 2 now confirms two timeout=300 (3 s) requests keep delivering reports beyond 6 s with no callback; timeout=0 control and explicit-stop controls pass. Production restored exactly after a separate ROM-handshake recovery. Current upstream still omits the field, with other source differences disclosed. CircuitPython host deadline remains the workaround; no Zephyr fix yet. See [reproduction and limits](legacy-ble-scan-timeout-2026-10-23.md). |
| HAL Infineon #2 coexistence assets | Asset selection audited; current Pico W two-hour and Pico 2 W thirty-minute concurrent-radio runs passed. This does not prove every traffic pattern. |
| CP #25 warm reset | Earlier 45% failure claim retracted after 45/45 successes; original trigger unresolved. |
| CP #29 Windows GATT cache | Unconfirmed mechanism; see targeted test above. |
| CP #8/#12/#16/#30, flash layouts, connection/memory choices | Project integration/configuration; do not label every choice an upstream defect. |
| ESP-IDF DHCP debug-format PR #19074 | Refreshed 2026-10-24 02:08 UTC: still OPEN, unmerged, head `60bf48d497c086d5b26f123f49df1401c523b727`. The latest official CircuitPython prerelease remains `11.0.0-alpha.2`; stable remains `10.3.1`. |

## Bench transport and board coverage

- Fresh sequential inspection of all eight previously off S31 leaf ports
  found no C6 identity and restored original power states with no bridge reset.
  A bare C6 was subsequently connected and tested (see follow-up above);
  the user confirmed no JD79667/RTC/SCD41 rig is attached. The configured sensor strand names SCD30, not SCD41,
  and the mux returned no usable live status/topology response. Configuration
  alone does not establish physical peripheral presence. Matched current
  Pico 2 512/2048-byte USB-stack diagnostics subsequently passed the bounded
  concurrent comparison; production firmware was restored. See
  [the stack comparison](pico2-usb-stack-comparison-2026-10-23.md).
  See [availability evidence and precise limits](farm-hardware-availability-2026-10-23.md).

- New direct Pico W USB recurrence: the final inventory failed with the Pico
  absent after descriptor/address timeouts and failed re-enumeration. Guarded
  hub recovery restored USB, and Pico W 9e153 / Feather ea06 runtime checks
  passed; S31 bec1d71 stayed healthy. Cause and CDC-versus-MSC behavior remain
  unresolved. A short CDC-only / CDC-plus-MSC-read / CDC-only control now
  passes 270 serial checks and 90 uncached reads, with original bindings
  restored and no USB errors captured. A later power snapshot has the Pico
  and external hubs forced active, with zero runtime suspend time. Neither
  result establishes the cause of the earlier failure. See [the class comparison](picow-usb-class-comparison-2026-10-23.md).
  The later [bounded MSC write control](picow-msc-write-2026-10-23.md) passes
  three 1,024-byte free-sector writes plus CDC checks, with exact restoration of
  the whole 520,704-byte disk. No mounted-file or idle-recovery claim follows.
  Preserve this failure independently of the successful S31
  two-console comparison. See [the failure and recovery evidence](picow-idle-usb-recurrence-2026-10-23.md).

- Bridge interface-claim cleanup is implemented and installed; 24 source cases
  and five sequential Pico composite imports passed. A fresh reversed-order control
  now shows either board works first and fails second; the first stays responsive.
  Both expose seven non-control endpoints. The earlier source budget was inferential. A later matched CDC/MSC test captures explicit HCD channel-exhaustion logs and passes after the unused third leaf is turned off; exact live channel counts remain unmeasured.
  A new physical control prevents MSC/HID probing before attachment and still
  reproduces the second-console failure in both orders: client admission alone
  is insufficient. Per-interface candidate bec1d71 in draft bridge PR #25 now
  passes 17 actual-source native groups and a fresh full S31 build. It is now
  installed after fresh full backup, app-only update and whole-flash verification.
  The identical selective-interface comparison passes both consoles in both
  orders; descriptors and admission states match the failed baseline. Defaults,
  ports and imports were restored with no reset during the comparison. Broader
  MSC/HID/throughput and capacity scheduling remain open. A subsequent targeted MSC
  investigation now fails: first Pico 2 import reads pass, but the next three
  single imports do not enumerate MSC while CDC stays usable. Mixed-console
  cases also fail MSC and lose the Pico console, with Metro surviving; those
  cases are confounded by the sequential failure. Ports/imports/defaults restore
  without bridge reboot. See [the reproducer](s31-msc-reimport-2026-10-23.md).
  The independent diagnostic UART recovered from USB control timeouts after hub
  recovery, but a subsequent open/read check coincided with an unexpected bridge
  reboot. Final network inspection found original inventory, no imports or active
  soaks. Reset cause remains unverified; the failed no-reset check is retained.
  See [the capacity investigation](s31-simultaneous-capacity-2026-10-23.md).
- Controller power/disappearance checks have 61 passing tests and a draft fix,
  and are now deployed with the exact physically tested adapter; live-base tests and guarded restart/readiness checks pass. Capacity scheduling and stale imports remain open. See [deployment evidence](controller-power-deployment-2026-10-23.md).
- Metro S3 now runs ea06 after private file recovery, fresh full backup,
  bounded partition/firmware migration and whole-chip verification. Runtime
  identity and three overlapping Wi-Fi/BLE scan cycles pass. Extended storage
  explains its 12,255,232-byte logical volume; offline `mdir` passes and the
  read-only checker reports only a volume-label mismatch. Original malformed
  Wipper FAT cause, boundary writes, TLS/connected-GATT and a current Metro soak
  remain unverified. Earlier transport/boot-transition failures are preserved.
  See [migration and runtime evidence](metro-ea06-migration-2026-10-23.md).
- Feather S3 and Metro S3 are updated with the targeted tests above. Other
  build-only variants, C6/load variants of BLE, physical displays/RTC/sensors
  and full Pico USB stress remain explicit gaps. Three completed
  overnight runs and later targeted follow-ups retain their actual revisions;
  a newer image is not retrospectively covered by an older soak.

A later host xHCI capture series did not reproduce CP #42: 25 traced and seven
untraced reads pass, including ten closed-console reads. Zero capture losses
were reported; original bindings and private trace instances were restored.
This establishes capture readiness, not a fix or root cause. See [the retained
non-reproduction evidence](picow-console-storage-stall-2026-10-23.md#host-controller-trace-capture-stall-not-reproduced).

A separate xHCI control with active Python workloads also passes seven exact
reads, including six closed-console attempts (three busy, three sleeping), in
31.4–52.3 ms with zero trace drops. This is retained as negative evidence, not
a fix; see [the workload control](picow-console-storage-stall-2026-10-23.md#host-trace-with-active-python-workloads).

The remaining ESP rollout audit confirms C5 and C61 upgraded from `cb530` to
`e467`, retaining UART consoles. Each has a verified fresh 8 MiB backup,
application-only write and whole expected-image verification. Both immediate
post-watchdog console checks failed; separate power-on checks verified the
new runtimes and three Wi-Fi/BLE cycles each. C5 additionally passed all seven
portal asset hashes, trusted HTTPS/hostname checks, wrong-host rejection and
API checks on unchanged portal `83526b0`. The initial failed jobs remain failed;
older eight-hour soaks are not attributed to these new images. Original port,
import and network states were restored. The preceding C5 matched console
control identifies a usable continuous-handle path, not an established root
cause. Feather S3 was moved/removed and its update awaits reconnection.
See [the rollout evidence](remaining-esp-rx-rollout-2026-10-23.md).

A further MCU-reset/fresh-enumeration Pico control also fails to reproduce
CP #42: seven exact reads (six closed-console) finish in 32.146–41.485 ms
with zero trace drops. This is negative evidence, not a fix or rollout
qualification; [the reset control](picow-console-storage-stall-2026-10-23.md#mcu-reset-and-fresh-usb-enumeration-control) records its scope.

The goal remains active. The final CP #15 comment has not been posted; it must
carry the remaining limitations rather than claim every issue is resolved.

## Normal Pico 2 hub receives actual Pico W node advertisements

The normal CP3254/Zephyr5bf hub now passes actual node-to-hub BLE reception,
decoding and HTTP API exposure. Three changing synthetic readings match node
UART sequences36/37/38, with RSSI and receive counts4/5/6; twelve HTTP checks
pass. All44hub/eightnode files match after deployment. Both complete original
storage images restore exactly, original board/version/files verify, networking
and imports are cleaned up, and independent postflight passes.

Three failed predecessors remain failed, including a separately recovered node
harness re-enumeration failure and two original-hub preflight timeouts. A
no-sender control localizes the original9e timeout to import wifi after successful
identity; no radio-root-cause claim follows. The successful candidate experiment
uses exact original identity/full-flash guards; restoration certifies bytes and
runtime identity/files, not original radio health. Normal Pico W3254 remains
build-only here. No real sensor/display/SD, outage replay or long-soak claim.
See [paired evidence and minimal timeout observation](pico-paired-overair-2026-10-24.md).

The original numbered reports0–11 all have explicit dispositions in the table
above. The historical request to file original reports1–4/#5 does not establish
that separate upstream issues exist; unreproduced mechanisms are not newly
filed or closed. JD79667 has a retained host-verified patch but no library PR.
Application certificate-sync#25 protocol tests are distinct from CP warm-reset#25
and from app#38's uncorrected non-atomic promotion. Large actual-drive relabel/
interruption, concurrent HTTP/ESP-NOW, router-channel/autoconnect, physical battery
events and calibration remain bounded verification gaps, not silently passed
requirements. Future GitHub Pages/Adafruit IO and missing-rig assembly remain
outside this targeted regression work.
