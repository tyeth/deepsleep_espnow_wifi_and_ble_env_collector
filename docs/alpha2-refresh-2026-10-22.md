# CircuitPython 11 refresh and farm soak â€” 22 October 2026

## Portal installed and verified, 19:59 UTC

The staged mobile loading/retention UI and service-worker revision is now
installed on C5. All seven served assets passed trusted HTTPS verification;
native Chromium 155 WebMCP queried 697 actual device rows and rejected a DELETE
without changing the count. See [deployment evidence and boundaries](portal-rx-rollout-2026-10-22.md).


## Completed soaks, 19:45 UTC

The three original eight-hour runs and the replacement Pico W two-hour run
have now passed independent terminal verification. This supersedes the running
statuses in the historical entries below. The failed Pico predecessor remains
failed and preserved; its physical root cause is not claimed proven.
See [durations, exact firmware attribution, counts, limits and evidence hashes](completed-soaks-2026-10-22.md).
New portal and C61 deployments require separate validation.


## Update at 17:28 UTC: Pico failure and replacement candidate

The a0c two-hour Pico run failed after 140 cycles/4,236.05 seconds. A separately
reproduced receive-lock defect is fixed in Zephyr `7379648278`, pinned by CP
`7d4ef1aac7`; both Pico builds pass and Pico W runtime preflight passes. Its new
two-hour soak began at 17:26 UTC and is still running. The physical stall's root
cause remains unproven; no completed replacement soak is claimed. The three
eight-hour runs remain uninterrupted. The prior one-hour/settings-only plan is
superseded. See [the incident, minimal reproduction and current evidence](pico-rx-contention-2026-10-22.md).

## Upstream issue disposition, 16:46 UTC

Three fork defect trackers are now closed after confirming the fixes in current
upstream source and verifying their commit ancestry: [Zephyr #5](https://github.com/tyeth/zephyr/issues/5)
(USB DPRAM alignment), [Zephyr #7](https://github.com/tyeth/zephyr/issues/7)
(the transfer-queue busy log), and [HAL Pico #7](https://github.com/tyeth/hal_rpi_pico/issues/7)
(flash helpers executing while XIP is disabled). Their fixes are upstream commits
`c2d5de2a0ac6`, `2f0bc11264a8` and `74cc3dfda63e`, respectively.

This supersedes older blanket statements below that all these trackers remain
open. It does not change the alpha.2 dependency pins or remove compatibility
patches still needed on that older base. In particular, another endpoint-busy
log remains in a different path upstream; its presence does not mean the
transfer-queue fix is missing.

The [updated disposition and minimal reproduction notes](upstream-disposition-2026-10-22.md)
separate current upstream source, carried fork fixes, historical reports and
executed validation. [Exact source revisions and blob IDs](upstream-escalation-source-audit-2026-10-22.json)
are recorded. No hardware or running soak was changed during this audit.
The concluding comment on CircuitPython #15 remains pending final results.

## Zero-sector settings fix and new Pico builds, 16:16 UTC

[Zephyr issue 3](https://github.com/tyeth/zephyr/issues/3) is now addressed in
`353bcd30f76e1fa140291540dde20334e952e0e6`: both NVS and ZMS reject a returned
sector count of zero with `-EINVAL` before reading the undefined descriptor
or attempting to mount storage. The valid first-sector result returned with
`-ENOMEM` remains accepted. The issue stays open pending review.

Six native-simulator scenarios use real flash-map enumeration and settings
backends: valid and misaligned 2 KiB partitions for NVS, ZMS automatic sector
count and ZMS custom sector count. Before the fix, all three malformed cases
fail while the valid controls pass. After the fix, all six scenarios / twelve
cases pass, including settings save/load. Test-only mount wrappers prove that
invalid geometry is rejected before mounting; valid cases call the real mount.
An earlier unwrapped ZMS run crashed on the malformed partition. NVS initially
returned `EINVAL` later in mounting, which motivated checking the rejection
point rather than only its errno. Zephyr checkpatch reports zero errors/warnings.
See [the regression results and source hashes](settings-geometry-regression-2026-10-22.json).

CircuitPython `1ca79521f3261cf90e0e7c6dfa398d5ad9885735` pins this new Zephyr
commit. Both Pico variants have fresh builds with empty `CP_VERSION`, verified
actual dependency checkouts, clean embedded versions and compiled wake calls.
Pico W BIN/RAM: 1,252,376/208,208 bytes; Pico 2 W: 1,208,780/275,756 bytes.
Their BINs and [full manifest](firmware-pico-settings-1ca-2026-10-22.json) are
hash-verified on the Pi, **not flashed**. Existing artifacts are unchanged.

The full BLE scan simulator file also passes at the new `1ca79521f3` /
`353bcd30f7` integration: **10/10 cases** across nRF5340 and nRF54LM20 in
54.40 seconds, covering ordinary scans, reloads, entry properties, passive
scans and extended-mode rejection. The same `make test` invocation passes
all **85 build-tool tests**. Input revisions were verified before and after.

The running two-hour Pico soak remains the physically validated `a0c1485cf5`
image with Zephyr `0589940bee`; it does not include this latest settings guard.
Its configured partition is aligned and the new regression separately covers
valid geometry. Preserve its actual image attribution and complete its run
before further Pico firmware changes. The three original eight-hour runs also
remain untouched. A completed soak result is still pending.

The official release list rechecked at 16:16 UTC still begins with
**11.0.0-alpha.2** (published 21 October); no alpha.3 is listed. The parameterized
release-list query returned an empty array, so the unparameterized list and
the direct alpha.2 release endpoint were checked instead.


## Pico W installed and shorter soak started, 15:54 UTC

Following explicit authorization to repurpose the Pico and use a shorter soak,
the old Pico baseline was deliberately stopped after 545 scan cycles and
16,337 seconds (about 4 h 32 min). Its snapshot and final interrupted status
are preserved. The recorder's `KeyboardInterrupt` is the authorized stop,
not a spontaneous radio failure or an eight-hour pass.

Pico W now runs `11.0.0-alpha.2-28-ga0c1485cf5`, built with the synchronized
Zephyr/HAL pins in [the candidate manifest](firmware-pico-scan-a0c-2026-10-22.json).
The missing SWD probe did not recover after a reset and power cycle of its
empty dedicated hub. The update therefore used the Pico USB ROM loader.
An initial picotool argument/selector failure occurred before any flash write;
it is preserved separately. The corrected transaction passed at 15:49:24 UTC:
immediate 2 MiB backup, exact installed-image check, new-image readback and
byte preservation of all untouched flash, including settings, NVM and FAT.

Physical runtime checks passed at 15:51:02 UTC:

- The extended-scan request raises `NotImplementedError`; the original scan
  remains usable and receives 181 advertisements. A later ordinary scan receives 214.
- The BLE address is unchanged across the firmware update.
- Wi-Fi connects; trusted TLS returns the expected response during BLE scanning
  (68 advertisements); the wrong hostname is rejected.

The replacement **two-hour Wi-Fi/BLE scan soak** started at
15:51:33 UTC and is due at 17:51:33 UTC (18:51 BST). It has six cycles with no
recorded failures at 15:54 UTC; this is progress, not a completed soak result.
The other three original eight-hour observers retain their original processes:
124 app deliveries/true sleep-wakes, 499 Feather scan cycles and 125 HTTPS cycles.
Their failures lists are empty; the app retains its single earlier startup HTTP
error. Their latest deadline remains 19:45 UTC (20:45 BST).

The separately staged portal updater now requires three full eight-hour passes
and this exact replacement two-hour pass, with independent evidence validation.
Eight guard tests pass and its live check refuses the four active observers.
The retained-model/loading portal candidate remains staged, not deployed.

Physical failed-open/retry injection still requires a working debug probe;
normal boot, scanning and TLS success do not establish that recovery case.
Pico 2 W and the remaining board variants still need runtime qualification.
No issue has been closed or draft PR merged. Older sections below are historical
snapshots; their “not flashed” and four-original-run requirements are superseded.


## Extended-scan guard and replacement Pico builds, 15:17 UTC

[CP #9](https://github.com/tyeth/circuitpython/issues/9) now has a source fix in
`a0c1485cf53a1f333a28cd3bb9dd307fd2470f36`: Zephyr `_bleio.Adapter.start_scan(extended=True)`
raises `NotImplementedError` before replacing an existing scan or allocating
results. This explicitly reports the port limitation; it does not implement
extended-advertising support. Ordinary active/passive scanning is preserved.
The historical audit row saying the argument is still discarded is superseded.
The issue remains open pending review and hardware validation.

The actual C entry-point regression reproduces 11 failures out of 26 checks
before the fix, then passes all 26 with the guard. The 85 build-tool tests,
Ruff and whitespace checks pass. A BabbleSim integration case checks that an
existing scan survives rejection and a later ordinary scan still sees a beacon.
The focused integration case now passes on **both** `native_nrf5340bsim`
and `native_nrf54lm20bsim` (2 passed, 8 unrelated cases deselected, 28.51 s),
through `make test` after building both simulator boards. Each receives the
beacon with the original scan after the rejected request, then receives it
again with a subsequent ordinary scan. The same invocation passes all 85
build-tool tests. This is simulated radio evidence, not Pico hardware evidence.

Both Pico boards build from this exact commit with empty `CP_VERSION`, clean
tracked inputs, Zephyr `0589940bee`, HAL Infineon `7f93dc6067` and HAL RPi Pico
`725e9e429e`. Pico W BIN/RAM: 1,252,368/208,208 bytes. Pico 2 W BIN/RAM:
1,208,772/275,756 bytes. Both compiled wake/transfer/unlock checks pass, with
the older baseline rejected by the same check. Full hashes and pins are in
[the new manifest](firmware-pico-scan-a0c-2026-10-22.json).

The new `*-scan-a0c` binaries are staged and hash-verified on the Pi, not flashed.
The separate `update_picow_scan_a0c.py` retains the immediate full backup,
protected-region checks, readback and rollback safeguards; its nine Linux
transaction tests pass. Its live check refuses all four active soaks before
identity checks, SWD access, reset or flash. Prior d86 images/updaters remain
historical artifacts rather than being relabelled.

The physical failed-start test boundary was rechecked offline against the new
Pico W BIN and ELF. No debug attachment or injected failure has been performed.
The running Pico soak still covers the older baseline, not this candidate.

Perfetto 0.58.2 is installed in the existing WSL test environment, with protobuf
6.33.5 retained to match the port's CI pin. The missing protobuf compiler was
supplied by grpcio-tools 1.81.1; `pip check` reports no broken requirements.
All twelve BabbleSim project revisions match the pinned manifest and its tools
build successfully. Initial missing-Perfetto/missing-protoc failures and the
pre-setup simulator skips are environment results, not successful test runs.

## Updated Pico artifacts, 14:28 UTC

Both Pico variants have now been rebuilt from `d86cb7ae95` with an explicitly
empty `CP_VERSION`, verified against actual dependency checkouts and compiled
wake-call structure, and staged under new filenames. Neither has been flashed.
This supersedes the 14:20 artifact-availability note below; the prior builds
and hashes remain historical evidence. See [the new build and rollout evidence](ble-startup-and-build-provenance-2026-10-22.md#current-branch-rebuilt-and-staged-1428-utc).


## Source-audit correction and build-version repair, 14:20 UTC

The release API still lists **11.0.0-alpha.2** as the newest published release.
This follow-up checked actual source against the release tag, separately from
the open/closed state of the issues in the [escalation index](https://github.com/tyeth/circuitpython/issues/15#issuecomment-5617383669).

The earlier patch-disposition row for [CP #28](https://github.com/tyeth/circuitpython/issues/28)
was too broad: the empty `CP_VERSION` fallback was present in the ESP integration
`cb5301b6fb`, but **absent from the Pico integration through `5bb1d64004`**.
The custom-board workflow can still pass an empty version to mpy-cross for
boards with frozen libraries. A regression invoking the real
`py/makeversionhdr.py` against an isolated tagged Git repository reproduced
`Cannot determine version` only for the empty override (one failure out of
four cases).

Pico branch commit `d86cb7ae956e953afb076cbb896a5a2934deb732` restores the same
`os.environ.get("CP_VERSION")` fix already carried by the ESP branch.
`python3 tools/check_build_version.py` now passes all four cases: unset and
empty values use Git, a nonempty explicit version wins, and an invalid
nonempty override still fails. Ruff and whitespace checks pass. This is
version-generation evidence, not a claim that a fresh hosted CI run passed.

| Follow-up | Current evidence and disposition |
|---|---|
| CP #10, stale incremental version | Already carried in `5afc122780`: version-header generation uses `always_run=True`, while unchanged output retains its timestamp. Both existing `cptools/tests/test_cpbuild.py` regressions pass. The issue remains open; the earlier blanket statement that this report had no integration fix is superseded. |
| CP #27, failed Bluetooth startup/retry | Readiness and settings-error handling are present in the candidate source; its 60 source-level checks are recorded above. Physical failure/retry and the new eight-hour candidate soak remain outstanding. |
| CP #26, TLS client-certificate policy | The source still carries the server-specific default authentication policy in `shared-module/ssl/SSLSocket.c`; it was not removed as upstreamed. |
| CP #9, ignored extended-scan argument | Current `Adapter.c` still explicitly discards `extended`. Keep open; the host scan deadline does not fix this separate capability issue. |
| Zephyr #3, zero settings sectors | Current `settings_nvs.c` still declares an uninitialized `hw_flash_sector` and uses it after the return-code check without validating `sector_cnt`. The aligned board partition avoids this trigger; it is not a general fix. Keep open. |
| ESP-IDF #19074 | GitHub still reports open and unmerged. Do not retire it as upstreamed. |

The new commit changes build-time version handling and adds its regression;
it changes no runtime C source or dependency pin. **Existing staged Pico
binaries remain the explicitly identified `5bb1d64004` builds**, not builds of
`d86cb7ae95`. Their saved hashes, manifests and guarded updater are unchanged.
Do not relabel those artifacts as the newer branch head. The running Pico
baseline still has the separate Zephyr provenance limitation described below.
No device was flashed or reset, and no issue was closed in this audit.


## Build-provenance correction, 13:30 UTC

The earlier Pico manifests requested Zephyr `560a6a2f4`, but the build-local checkout remained at `ea703e85b6`. Preserved ELFs confirm the current Pico soak lacks the Bluetooth wake-before-access guard, although the HAL locking changes are present. Treat it as baseline evidence. The historical hardware observations below remain valid for their binaries; their attribution to the complete bus-power candidate is superseded.

The synchronized candidate is now CircuitPython `5bb1d64004` / Zephyr `0589940bee`. Both Pico variants build, actual checkout pins and compiled wake calls are verified, and 60 startup-retry checks pass. It is staged, not flashed. See [the full correction and new validation evidence](ble-startup-and-build-provenance-2026-10-22.md). The older artifact JSON files now record actual and requested revisions separately.


The newest published upstream release checked on 22 October is
**11.0.0-alpha.2**, released 21 October, including prereleases. An alpha.3
was not published at that check. This integration is based on that exact tag,
not the older 10.x release or an arbitrary main snapshot.

## CPU fallback and HTTPS soak follow-up, 11:20 UTC

The CPU-only browser test used the real polyfill with WebGPU disabled,
WASM inference in a worker and a 390 by 844 touch viewport. The q4 model
generated correct SQL but a wrong summary: it omitted the local zone and
called bedroom's 2261 ppm the highest value despite local's 2573 ppm.
This failure is preserved; it is not counted as a successful answer.

The same model's q8 export is now selected for WASM only. WebGPU retains
the separately validated q4 setting. The published q8 download is about
512 MB versus q4's 786 MB. Observed renderer working-set snapshots during
the same question were 2.46 GB (q8) and 3.72 GB (q4); these are desktop
observations, not peak-memory measurements or proof of phone compatibility.

The q8 model returned valid SQL inside a fence after a short introduction.
The parser previously required the fence at the beginning and rejected the
whole reply. A regression reproduced that failure. Extraction now accepts
a prefaced SQL fence and still validates the entire extracted block;
write statements, multiple statements and unfenced prose remain rejected.
The service-worker cache advances to v19.

After the fix, the actual CPU model completed the full query-and-answer
flow in 42.1 seconds, reporting bedroom 2261 and local 2573. Its prose was
verbose, but both values and zone mappings matched the displayed SQL result.
Stop during another request followed by immediate retry completed in
43.1 seconds with the same correct mapping. All portal regressions pass
(11 browser integration tests, two native cancellation tests, plus the
SQL/certificate/history/clock groups). Physical-phone memory, latency and
answer quality remain unverified. No active DUT portal was modified for
these browser changes; deploy them after every active soak finishes.

A fourth, network-only eight-hour observer now exercises the upgraded C5's
trusted HTTPS. It began 11:13:32.712613 UTC, due 19:13:32 UTC (20:13 BST),
in `https-fullchain-overnight-01`. Each cycle checks the system CA chain,
hostname and pinned leaf, then reuses one TLS socket for latest readings,
history listing and certificate status. Every response is logged with a
hash. There are no hidden retries or device resets; any error prevents a
terminal pass. The first cycle passed all three routes in 1.244 seconds.
Running remains provisional. C5 must stay undisturbed through this later
deadline, even after the application and radio runs finish.

The independent evidence reporter now validates HTTPS cycles, response
coverage, trust settings, sequence, timestamps, count and maximum gap.
Thirteen report tests pass, including rejection of short/sparse evidence,
missing responses, hidden failures and disabled trust checks.

## Actual-origin WebMCP pass and fresh soaks, 10:56 UTC

Chromium 155 loaded 333 rows from the actual C5 over normally verified
HTTPS. Native `envhub_dataset` reported both sources and the correct date
range. `envhub_query` grouped 238 `bench-c61-sim` and 95 `local` rows, both
with peak CO2 616 ppm. A DELETE attempt returned `SELECT only`; a subsequent
count remained 333. Job `6ac73090-0da2-4d68-ba64-e36a118fccdb` passed at
10:55:05 UTC. These are synthetic bench measurements, not environmental
accuracy validation. The intermittent earlier empty responses remain an
open observation: a later controlled clock-sync and repeated TLS sequence
also passed, so neither clock sync nor connection reuse is a proven cause.

A new C5/C61 application soak began at 10:52:13 UTC, due 18:52:13 UTC
(19:52 BST), in separate `overnight-fullchain-01` evidence. C5 runs
`cb5301b6fb`; C61 remains on `2a7f9987f3`. At 221 seconds it had two confirmed
deliveries/true wakes, seven HTTP successes/one startup error, two BLE
successes/no errors, one collector start and no serial failures. Running
does not mean passed. This supersedes the older statement that no new run
was active; it does not change the original eight-hour pass or failed runs.

Pico run 03 was dispatched separately with firmware `1609ec9b0b` and the
current verified recorder. An initial start guard rejected the older
staged recorder before touching the device; the published recorder was
then staged under a distinct filename. Feather run 02 is also dispatched
on its existing `4730c980ca` firmware, with C5 left running as a BLE source.
Both radio runs still require confirmed startup and their full eight hours.

## Portal and Pico RAM validation, 10:50 UTC

The C5 full-chain firmware and eight-file portal deployment are complete.
The loaded `certstore.py` and firmware `cb5301b6fb` were checked on hardware.
Normal system-CA and hostname verification passed twice, most recently at
10:43:50 UTC: seven served asset hashes match release `a53f1378ef6a`, the
three-certificate chain is accepted, the wrong hostname is rejected, and
the latest-reading API returns valid JSON. Clock synchronization restores
the certificate lifetime display after a soft restart. This is a real
trusted HTTPS pass, without disabling verification.

Chromium 155 registers both native WebMCP tools at the device's HTTPS
origin through a loopback-only tunnel. A first history load held 329 rows;
subsequent history requests return an empty response after reconnect/clock
sync, including a separate Python keep-alive reproduction. Diagnosis is
ongoing; this is not yet an end-to-end data-query pass. Local-model startup
on the controller exhausted memory and the kernel killed Chrome at 10:30.
The recovered browser leaves that fallback disabled. Prior desktop WebGPU
inference, WASM worker checks and phone-viewport tests do not establish
physical-phone performance or memory compatibility.

Pico W's larger TLS buffers exhausted its native heap on candidate
`9f2ff6968d`, even after successful Wi-Fi association. Candidate
`1609ec9b0b` disables MSC double buffering on Pico W only, reclaiming 4,132
bytes of static RAM while preserving the full 4,096-byte transfer buffer.
The Pico 2 W setting is unchanged. Both builds pass; Pico W BIN/RAM sizes
are 1,252,176/208,208 bytes, Pico 2 W 1,208,580/275,756 bytes. Exact hashes
are in `firmware-pico-singlemsc-2026-10-22.json`.

Pico W programming and verification passed, followed by a physical test
of public-network association, RSA HTTPS (126 response bytes), 123 BLE
advertisements and wrong-hostname rejection. USB reset/re-enumeration was
then observed, beginning before the failed first storage check. It
recovered without a requested reset. A later read-only storage check
passed two matching 64 KiB reads at 10:43:07 UTC. These checks do not prove
long-run USB or radio stability. The previous two failed soaks remain
failed, and no new eight-hour run has yet passed. Pico 2 W is staged only.

## Completed ESP soak and bus-power follow-up, 10:04 UTC

The C5/C61 application run **passed its complete eight hours**: 28,800.6
seconds, finished 09:37:42.407915 UTC, 236 confirmations and true deep-sleep
wakes, 958 HTTP successes/one startup error, 225 BLE successes/zero errors,
one collector start and no serial errors or failures. The independent report
found consistent terminal evidence and the observer was inactive/PID zero.
Synthetic readings remain labelled `sim`. This pass covers `2a7f9987f3`.

The Feather scan run **failed**, after 382 completed cycles/11,465.06 seconds
at 09:39:12 UTC. The final two saved scans still saw two Wi-Fi networks but
zero BLE adverts, after 26 adverts and three networks at 09:37:42. Its
three-empty-BLE condition coincided with the C5 entering backup mode. The
missing radio source is a plausible test-environment explanation, not a
proven firmware diagnosis. Preserve this run; a new full-duration run needs
stable radio sources throughout. Read-only evidence job:
`c9e443d7-90df-480f-8bd0-0659763f1f9e`.

Pico run 02 remains failed. Two additional defects were reproduced with
actual-source harnesses: Bluetooth accesses a sleeping WLAN bus, and a
competing wake can interleave with a sleep transition, leaving software awake
while hardware is asleep. Zephyr `560a6a2f4` now wakes and accesses under the
shared recursive mutex; HAL `7f93dc6` serializes software state and hardware
clock/KSO transitions under that same mutex. Old commits fail; the fixes
pass 25 BT-shim and 40 vendor power-transition UBSan cases. The prior
28-case window-lock regression remains applicable. This does not establish
resolution of the long-run hardware failure.

CircuitPython `9f2ff6968d` pins both commits. Pico W and Pico 2 W builds pass
with TLS input/output 16/8 KiB. BIN sizes are 1,252,224 and 1,208,580 bytes;
linked RAM is 212,340 and 275,756 bytes. Exact candidate hashes are in
`firmware-pico-buspower-2026-10-22.json`; original full-chain artifacts remain
unchanged. Both candidates were staged and verified on Pi in job
`0e8958bc-6a29-42d6-8c6c-e62cf0280c60`.

Pico W's immediate private 2 MiB snapshot matches the previous firmware,
and SWD programming/verification of the candidate passed in job
`13f708b4-50be-4fde-a42a-244656212f3f`. It boots as `9f2ff6968d` and associates
with the public bench network. The first TLS preflight hit ECONNREFUSED at
the expired Pi test endpoint; this is not a TLS pass. No new eight-hour
Pico run has yet passed. Pico 2 W remains staged, not physically validated.

C5's protected full-chain firmware update passed at 10:00:20 UTC, job
`51f3261d-6943-4545-8db9-e5d5f94e834a`: immediate backup, new firmware,
protected data regions and resume all verified. Its portal returned HTTP 200
after Pi rejoined the AP. Runtime console inspection and final portal/certificate
deployment are still in progress; HTTPS is not yet verified. See the rollout
document for private backup references and transaction limits.

## Second Pico overnight failure, 09:25 UTC

Pico W run `pico-radio-overnight-02` FAILED at 09:06:33 UTC on 22 October after 9,576.07 seconds and 318 completed cycles, on firmware `6fc7497ef4` with HAL `12f662c34e21e7c1addd3f7aad0488d35bffd8c2`. Controller job `aa40cc1a-dc2c-4141-aa86-2e395798ee50` is terminal with result `fail`. The next scan command accepted raw REPL input but produced no terminator within 35 seconds. The shared-window race fix remains supported by its deterministic regression, but it does not resolve the complete long-run hardware failure. Both failed runs remain failed.

The failed state was preserved before any reset or reflash. Capture job
`708168e9-03ff-4640-8533-1c2722393dca` briefly halted only the Pico through its
identified SWD probe, saved RAM/registers, and resumed without reset. Private
evidence is in Pi `pico-radio-failure-02/`; the 270,336-byte RAM image SHA-256
is `5b00becb086a707cb603bf7e9c1670e05d23d9a4593a438ac92a374e4ba98756`.
Do not publish RAM or flash images.

The matching bus-lock ELF confirms the main thread is again waiting in
`common_hal_wifi_scannednetworks_next()` / `k_poll(K_FOREVER)`. This time the
channel index is 10, the result queue and completion signal are empty, the
scan is in progress and the driver callback remains registered. Corrected
saved-state decoder job `c7e19c75-6f99-41c5-b28b-f837808018c6` passed.

The Bluetooth polling thread owns the recursive bus mutex (count 1) while
waiting for space in the deferred log buffer. Public static formats in that
buffer include repeated out-of-range Bluetooth ring indices and exhausted
rereads. The separate "RX transfer already in progress" warning comes from
USB CDC ACM, **not the SPI driver**; it does not establish a SPI failure.
Detailed decode job `db8f9bef-ac79-4780-83a6-b97d295e292a` confirms an intact
main stack sentinel, at most 3,536 bytes touched, 4,652 untouched stack bytes,
42,116 libc heap bytes free, and no WHD packet-allocation failure counters.
Two later CPU/UART samples progressed through different PCs; they do not
establish a permanently stuck UART FIFO. The ring corruption and scan hang
remain unresolved; no new full-duration run has started.

The independent C5/C61 and Feather V2 observers remain active. At 09:11 UTC,
C5/C61 had 223 confirmed deliveries/true wakes, 905 successful HTTP checks
(one startup error), 213 BLE successes/no BLE errors, one collector start
and no recorder failures. Feather V2 had 327 cycles without recorded failure.

The tested final C5 portal transaction is now staged; its eight preservation
and recovery tests and exact hashes are in the
[rollout procedure](c5-fullchain-rollout-2026-10-22.md). Guarded controller job
`7cf4ddd9-b209-4f30-8d03-bbc4e1759052` waits for all 28,800 application-soak
seconds, an independently consistent pass and observer shutdown before reading
and verifying a fresh C5 backup. It does not write firmware. C5 deployment and
actual secure-origin browser validation remain pending; Pico diagnosis does
not justify interrupting either healthy soak.

## C5 transaction and browser preparation at 08:45 UTC

The [concrete rollout procedure](c5-fullchain-rollout-2026-10-22.md) now
records a staged exact-image firmware transaction, nine offline layout/FAT
tests, six transaction fault-injection tests, live active-soak refusal,
the trusted-HTTPS verifier and a working Chromium 155 session on Tachyon.
The browser path is loopback-only and keeps normal TLS validation. No new
firmware or portal files have been installed on any active DUT. Actual module
inspection, deployment, secure-origin browser checks and the full-duration
results remain pending.

## Verified staging and headless TLS check at 08:10 UTC

The corrected eight-file portal package is verified on Pi storage in
`portal-release-a53f137`; it includes the seven web assets and the corrected
`certstore.py`. Job `7d0868c8-19c9-4892-9c15-d268518ad0ba` checked every
size/hash and confirmed the active-soak guard refused console access.
The 53,535-byte archive SHA-256 is
`ec5b89772624a3a55d4f0aa9fe5e9ac2be6bdb08c3c6e9de5df2f54e4a38ef8f`.
See the [file manifest](portal-a53f137-manifest.json). The module destination
is a planning hint: inspect the installed `.py`/`.mpy` layout before writing.
No replacement firmware, certificate or asset has reached a DUT yet.

The staged `backup_c5_for_fullchain.py` helper has SHA-256
`0209e0f4700c2095313df5c49d6bf66ee27494a601105759e5b6761ceabf33ea`.
It requires all 28,800 seconds, a terminal pass, consistent independent
evidence and an inactive observer before opening the exact C5 UART. Job
`628b2560-8e51-40d8-93c0-5307fd00e80f` proved its live refusal. Seven offline
guard tests also pass: running, short, failed, incomplete, still-active,
unreadable-service and inconsistent-evidence cases cannot become ready;
completed transient units may be collected safely. The fresh backup itself
has **not run**. It will read and verify 8 MiB, compare partition layouts,
save private recovery evidence, and resume the unchanged old firmware.
Before any later flash, establish active/inactive OTA selection as well as
FAT bounds; an unchanged partition table alone does not establish where an
extended filesystem currently lives.

The native simulator now builds at `e4553033a1` with a temporary headless
configuration and overlay disabling SDL display/audio/input. The generated
TLS limits remain 16 KiB input / 8 KiB output. Standard 32-bit GCC dependencies
were installed in WSL (24 new packages, no upgrades/removals); protoc and
Perfetto Python dependencies were isolated under `/tmp`. The existing pinned
MP3 submodule was initialized. No SDL/Mesa packages were installed.

All 85 cptools tests pass. The normal SSL pytest launch still fails because
its fixture always supplies SDL-only options. A separate launch omitted only
those options and executed the **unchanged** `tests/test_ssl.py` function and
assertions. It passed verified TLS to `www.adafruit.com`, HTTP 200, JSON quote
content and clean completion at 08:06 UTC. Evidence is in WSL
`/tmp/envhub-headless-ssl-wjt4mg80`; executable SHA-256 is
`7a69065130816dba59ce0bb75bf1928482b7b763cc792a36562efd8b49ad3ec8`.
The headless generated board metadata was preserved with the evidence and
restored afterwards. This is a headless simulator client-TLS pass, not a
standard full-simulator suite pass, hardware TLS pass or server-chain test.

The 07:56 UTC read-only snapshot (job
`9e881bda-b6e3-420e-a852-d9300c8491ce`) still showed three running soaks:
C5/C61 187 confirmations/true wakes, 756 HTTP successes/one startup error,
178 BLE successes/no BLE errors, one collector start and no serial errors;
Pico W 180 scan cycles; Feather V2 177 scan cycles. No recorder reported a
failure. The full-duration deadlines remain 09:37:42 UTC for C5/C61 and
14:26:57 / 14:28:07 UTC for Pico W / Feather V2. These results are provisional.

## Full-chain HTTPS correction at 07:35 UTC

Final portal deployment is on hold. The previously staged `30e57d2` release
does not contain the newly verified certificate-chain correction. Current
portal source is `a53f137`; the new ESP and Zephyr firmware revisions are
`cb5301b6fb` and `e4553033a1`. None has replaced the images under soak.

A normal HTTPS probe of the C5 was refused (job
`73c03d66-7269-4755-ae1b-8307e8af155a`). Its `/api/cert` reports no certificate
and HTTPS disabled. HTTP asset verification alone cannot establish a secure
origin for WebMCP or the Prompt API.

The configured public certificate source now supplies three certificates.
Truncating to leaf plus one intermediate failed OpenSSL verification;
retaining all three passed normal CA/hostname checks and key matching in job
`d20500e4-01c1-4e79-b788-94dc24789766`. This matches the current
[Let's Encrypt chain hierarchy](https://letsencrypt.org/certificates/): a
cross-signed Root YR must be sent between YR2 and the trusted ISRG Root X1.
The verified chain/key are staged privately in `portal-https-staging` on Pi,
expire 16 December 2026, and are not installed on the C5. No key material is
included in this repository or controller output.

The browser's `pemChain()` and device-side `certstore.renew()` both discarded
that third certificate. Regression expectations failed on each old path and
pass after preserving the complete supplied chain. The service-worker cache
is now `envhub-v18`. Twenty browser certificate groups, the new renewal
regression, existing BLE certificate transport checks, 12 browser AI/tool
tests and inline syntax checks pass.

The complete chain is 5,781 PEM bytes / 4,143 DER bytes. The actual mbedTLS
TLS 1.2 server writer needs 4,159 bytes including message/certificate lengths
and explicitly rejects a chain that exceeds `MBEDTLS_SSL_OUT_CONTENT_LEN`.
The former 4,096-byte output limit cannot serve this chain. All nine ESP
integration boards and the Zephyr integration now use 16 KiB input / 8 KiB
output. Fresh builds pass for all nine ESP configurations (C5/C61 UART,
C6/S3 devkits, Feather C6, both Feather S3 variants, Feather V2, Metro S3)
and both Pico W/2 W. Generated limits, partition bounds, app-slot fit and
combined image placement were checked before collecting artifacts. See the
[new image manifest](firmware-alpha2-fullchain-2026-10-22.json); previous
images and evidence remain intact. C61 still has only 30,272 application
bytes free. Pico W/Pico 2 W BIN sizes are 1,252,192 / 1,208,552 bytes, with
212,340 / 275,756 bytes of linked RAM. TLS allocations need hardware retesting.

All 85 cptools tests pass at the new Zephyr revision. The required `make test`
target was attempted with the native simulator SSL test, but configuration
stopped on missing SDL2/SDL2_image development libraries. That simulator
test did not run. No packages were installed; the dependency check was a
simulation only.

At 07:29 UTC the original ESP service was still active: 173 confirmed
deliveries/true wakes, 702 HTTP successes/one startup error, 165 BLE
successes/no BLE errors, no serial errors or failures. The corrected Pico
controller job was running with 125 cycles; Feather V2's service was active
with 123 cycles, both without recorded failures. These are provisional
results on the previously documented images, not tests of the new TLS builds.

After the full ESP run ends, save its terminal evidence and a fresh backup
of the C5's current firmware/filesystem before its HTTPS upgrade. Preserve
measurement files, configuration and the failed-run records. Install and
validate the new firmware, complete certificate chain, corrected renewal
module and portal assets, then verify trusted HTTPS and browser secure-context
behavior. Do not use the old seven-asset helper as proof of this expanded
deployment, and do not interrupt the Pico/Feather scans.

Filesystem migration preparation also found that extended ESP CircuitPython
storage appends the inactive OTA partition to the FAT partition. The
read-only `extract_esp_fat.py` helper on Pi requires an established inactive
partition label rather than guessing. Five offline tests with real FAT tools
passed, including byte-for-byte recovery of a file spanning that seam.
The already-saved C5/C61 backups have no CircuitPython FAT partition and
were correctly refused as extraction candidates; this is not yet a recovery
test of the remaining Feather/Metro filesystems. Their physical identity,
verified backups, file preservation and runtime checks remain pending.

## Current state at 06:40 UTC

| Work | Verified state | Still required |
|---|---|---|
| C5 collector / C61 node | Alpha.2 flash and application preflight pass; full eight-hour run active | Terminal soak evidence after 09:37:42 UTC / 10:37:42 BST |
| Pico W | `6fc7497ef4` with atomic backplane fix; flash, first public-bench association and TLS/BLE preflight pass | New eight-hour scan run ends 14:26:57 UTC / 15:26:57 BST; failed run 01 remains failed |
| Feather ESP32 V2 | `4730c980ca`; flash and HTTP/TLS/BLE preflight pass | Eight-hour scan run ends 14:28:07 UTC / 15:28:07 BST |
| Pico 2 W | Corrected `6fc7497ef4` image built and hash-verified on Pi storage | Backup, flash and runtime/application validation |
| Feather C6, Feather S3 variants, Metro S3 | Alpha.2 images built; effective partitions/TLS checked; staged hashes verified | Physical identity, backups, required filesystem migration and runtime/application validation |
| Chrome WebMCP | Actual Chrome tool discovery/query/rejection tests pass | Final staged portal deployment to C5 and served-byte verification after its soak |
| Separate mobile Prompt API polyfill | Opt-in native/fallback integration; actual desktop WebGPU/WASM inference and phone-size layout checked | Final C5 asset deployment; physical-phone performance is unverified |

No active run is an overnight pass. The Pico/Feather radio runs cover scan
coexistence; they do not replace the ESP collector/node application soak.
Shared USB/IP, hub-port, Wi-Fi and Bluetooth cleanup waits for all active
tests and portal verification. Subsequent sections preserve earlier build
and failed-run evidence; this table and the latest dated run records
supersede their historical pending/running statements.

## Hardware and recovery

Pi 6 (`rpi-hil006`) hosts the ESP32-S31 bridge on its USB hub. The S31
exports the downstream hub tree over USB/IP. ROM identification found:

| Role | Board | Flash | RAM / initial Python free heap |
|---|---|---|---|
| Collector | ESP32-C5-DevKitC-1-N8R8, rev 1.0 | 8 MB | about 4 MB free |
| Node | ESP32-C61-DevKitC-1-N8R2, C61HR2 rev 1.0 | 8 MB | about 2 MB free |

These are C5/C61 devkits, not the C6/S3 pair described in the older bench
notes. The C5/C61 flashed builds use the UART bridge for the console;
normal builds retain their native USB console. Their common source commit
is `2a7f9987f3`, based on alpha.2. The version string includes `dirty`
because of the build checkout's submodule state; retain the artifacts and
their hashes rather than treating that version string as a clean release.

Both complete 8 MB original flash images were saved and verified against
the chip before writing. Private backups are on Pi 6 in
`/home/pi/envhub-bench-20261022/`:

| File | SHA-256 |
|---|---|
| `c5-before.bin` | `06ede177e60cb854c318080132882564d7c71e502f6f1e7c6d0601fb836ad666` |
| `c61-before.bin` | `2e8441c57e5facc41147b7ac582a1a56412a953e5928c1145a070cb7b0f2674a` |

Do not publish these images: they can contain previous configuration.
Both new firmware writes passed esptool's hash verification. Reliable
flash reads used 230400 baud; 921600 produced truncated packets through
this bridge.

The S31 initially exhausted DWC host channels while claiming composite
devices across three hubs. Its UART reported `No more HCD channels
available`. Disabling unused downstream ports and restarting the bridge
restored actual flash-tool access. This failure was in the USB transport,
not proof of a CircuitPython crash. Pi 6 also needed one reboot to recover
its stuck physical USB inventory.

Ports temporarily off for this run: `1-1.1`, `1-1.2`, `1-1.3.1`,
`1-1.3.2`, `1-1.3.4.2`, `1-1.3.4.4`. Restore them only after all active tests and portal verification permit
shared-hub changes. UARTs at `1-1.3.4.1` and `1-1.3.4.3` remain on. Opening
these UART bridges can reset a board even with DTR/RTS deasserted; do not
open another serial client during a soak.

## Patch disposition

The starting audit is the
[escalation index on tyeth/circuitpython#15](https://github.com/tyeth/circuitpython/issues/15#issuecomment-5617383669),
linked from [collector issue #7](https://github.com/tyeth/deepsleep_espnow_wifi_and_ble_env_collector/issues/7).
Issue state and source presence were checked separately: an open tracking
issue alone does not establish that a patch is missing upstream.

| Work | Disposition on alpha.2 |
|---|---|
| DEBUG / EXTRA_CONF quoting, CP #24 | Already upstream in [adafruit #11423](https://github.com/adafruit/circuitpython/pull/11423); obsolete implementation dropped. RTT option adapted to the new upstream Makefile. |
| Second console RX wake | Already upstream in [adafruit #11448](https://github.com/adafruit/circuitpython/pull/11448); old patch dropped. |
| Global BT_MAX_CONN=4 | Dropped; upstream uses 5. Pico W's board-specific limit remains with its BLE work. |
| TCP errno conversion, part of CP #21 | Upstream already uses `mp_raise_OSError(errno)`; duplicate conversion dropped. Other accepted-socket/timeout and TCP/TLS settings retained. |
| [CP #26](https://github.com/tyeth/circuitpython/issues/26), server TLS client-certificate policy | Still needed; retained. |
| [CP #28](https://github.com/tyeth/circuitpython/issues/28), empty CP_VERSION | Still needed; retained. |
| [CP #30](https://github.com/tyeth/circuitpython/pull/30), frozen application libraries | Retained, extended to C5/C61. Old UART debug relocation omitted. |
| Radio heap reserve / TLS tickets | Retained. C5/C6/S3/C61 integration uses 4 KB TLS records where configured; 2 KB is too small for the certificate chain. |
| C5 and C6 devkit image size | Frozen images exceed 2 MB. Dedicated 3 MB OTA slots fit; this changes the filesystem location and requires backup before flashing. |
| [CP #25](https://github.com/tyeth/circuitpython/issues/25), alleged warm-reset failure | Earlier 45% failure claim was retracted after 45/45 successful resets. Do not revive that claim or close unrelated reset work on its basis. |
| [CP #29](https://github.com/tyeth/circuitpython/issues/29), Windows BLE cache | Host GATT-cache diagnosis; not evidence of a new upstream CircuitPython fix. |
| [ESP-IDF #19074](https://github.com/espressif/esp-idf/pull/19074) | Still open at audit; do not describe as merged. |

Zephyr CircuitPython integration `6fc7497ef4` pins Zephyr
`ea703e85b630897a5df75f4156f22f72edd5a81d`, based on alpha.2's upstream
`3ab36efea64edda80e45ece016753e3686bb763f`. It retains Pico W/Pico 2 W BLE,
USB stack headroom, association-related scan waits, AP DHCP, socket/TLS
and RTT work, plus the HCI framing and WLAN/CLM coexistence corrections
described below. The asynchronous Python scan iterator still waits for
driver completion; the old association timeout did not bound the failed
overnight scan.

Current HAL pins are:

* `hal_rpi_pico`: `725e9e429eab65eda01762a1af9016426dee00ac`
* `hal_infineon`: `12f662c34e21e7c1addd3f7aad0488d35bffd8c2`, adding atomic
  backplane window/access locking to the prior coexistence pin
  `daae5ca73811dbee8ad01fb1aaeafa98896ef94b`; see
  [HAL follow-up #3](https://github.com/tyeth/hal_infineon/pull/3).

Review drafts: [ESP integration #31](https://github.com/tyeth/circuitpython/pull/31),
[Zephyr CircuitPython #32](https://github.com/tyeth/circuitpython/pull/32),
and [Zephyr dependency #11](https://github.com/tyeth/zephyr/pull/11).

The unresolved capability/extended scan, stale boot_out, absent-HCI CI,
BLE retry, CYW43 cache, and Zephyr logging reports remain open. No issue
was closed merely because this integration builds. The previously closed
upstreamed reports do not need another closure.

## Validation and overnight protocol

ESP builds succeeded for C5, C61, C6 devkit and S3 devkit. C5/C61 UART
variants also built and booted. C61's 2 MB app slot has only about 30 KB
headroom; adding more frozen libraries requires another size check.

Current Zephyr Pico 2 W and Pico W builds at `6fc7497ef4` pass
(1,208,548 and 1,252,188 firmware bytes respectively). The cptools suite
passed 85 tests, and the HAL transaction harness passes 28 cases. Pico W required
two BLE connections, IPv4 only and six network contexts to fit the new
stack in 264 KB RAM; Pico 2 W retains dual stack and the larger limits.
The Pico W has since been flashed and tested as detailed below; Pico 2 W
hardware validation remains outstanding. A custom firmware `BUILD` directory was leaking into the nested host mpy-cross
build; host preparation now explicitly selects its expected output path.

Application deployment caught and fixed the collector's assumption that
every bare devkit exposes IO19/IO20. C5 with PSRAM has neither pin alias;
it now runs with no local I2C sensor. Serial deployment also handles
external UART DTR correctly and reports raw-REPL stderr as an exception
instead of waiting for two adjacent end markers and timing out.

The node explicitly uses `sensor: "sim"`; every reading says `type: sim`.
This is a radio/application soak on real hardware, not sensor accuracy
validation. Preflight demonstrated CRC-confirmed ESP-NOW delivery and
`ResetReason.DEEP_SLEEP_ALARM` after real sleep. Opening the collector's
UART restarted its AP; Pi's stale Wi-Fi association required reconnecting.
The initial six-minute preflight therefore records an HTTP availability
failure. Keep that result; it is not an overnight pass.

`tools/overnight_soak.py` runs for a full eight monotonic hours under
systemd on Pi 6. It keeps both UARTs open, records serial output, polls
`/api/latest` every 30 seconds, and optionally performs BLE `mem`/`latest`
round trips every two minutes. It syncs UTC through `/api/time`, never
resets a stalled DUT, and atomically updates `status.json`.

A pass requires the whole duration, confirmed deliveries with no gap over
300 seconds, HTTP with no gap over 120 seconds, true deep-sleep wakes, no
collector restart, no serial disconnect or fatal device exception, and
(when enabled) no BLE gap over 300 seconds. A running test is not a pass.
Raw logs and manifests stay under `/home/pi/envhub-bench-20261022/`.

The actual eight-hour run is `overnight-01`, systemd unit
`envhub-overnight`, started **01:37:42 UTC / 02:37:42 BST** on 22 October,
due **09:37:42 UTC / 10:37:42 BST**. BLE probes are enabled. An hourly
follow-up checks meaningful failures/completion and restores temporary
bridge-port power, Pi Wi-Fi and Bluetooth settings after completion.
The initial HTTP poll during boot failed; subsequent polls, BLE commands,
confirmed delivery and real deep-sleep wakes are succeeding. No pass is
claimed until the full duration finishes.

Use a private JSON configuration with `boards` (name, role, by-id `port`,
`uart: true`), `url`, `hours: 8`, `sensor: "sim"` and optional `ble_name`.
The output directory must not already exist, so a new run cannot overwrite
an earlier failed run. The Pi's test Wi-Fi profile never supplies the
default route; SSH remains on Ethernet.

## Expanded Feather and Metro builds

Commit `2c096e11e7` extends the ESP integration after testing the remaining
board configurations. This does not replace the C5/C61 firmware during
the active soak.

| Target | Firmware bytes | Application slot | Build result |
|---|---:|---:|---|
| Feather C6 4 MB, no PSRAM | 2,207,760 | 2,883,584 | Pass |
| Feather S3 no PSRAM | 2,040,976 | 2,097,152 | Pass |
| Feather S3 4 MB flash / 2 MB PSRAM | 1,996,704 | 2,883,584 | Pass |
| Metro S3 16 MB flash / 8 MB PSRAM | 2,106,880 | 3,145,728 | Pass |

The original Metro build exceeded its 2 MB slot by 9,728 bytes. It now
uses two 3 MB slots, while keeping the existing TinyUF2 factory app at
`0x410000`. Its filesystem moves to `0x750000`, size 8,896 KiB. The
Feather C6 also exceeded its old 2 MB slot; it now uses the standard
2,816 KiB application layout, filesystem at `0x2d0000`, size 1,216 KiB.
Back up, reformat and restore files when upgrading either layout. An
application-only UF2 update cannot install a changed partition table.

All four builds explicitly allow 4,096-byte outbound TLS records for the
collector's certificate chain; inbound records retain the upstream size.
Artifact collection decoded and verified each built partition table,
checked application size against every slot, confirmed the actual TLS
configuration, and recorded SHA-256 hashes for the BIN/available UF2 files.
These are compilation/configuration results, not hardware passes. The
physical S31 Feather/Metro ports remain off until the C5/C61 soak ends.

The directly attached Pico W was independently identified at Pi 6 USB
`1-1.2.2`, flash ID `E663AC91D3444127`. It ran WipperSnapper rather than
CircuitPython. Before upgrading, its full 2 MiB flash was saved with
picotool verification as `picow-before.bin` (SHA-256
`4b86f3fa60e115d93396cfcc15bc38f33660bfe76863017a85f4e8374ad8c9ba`),
plus its 512 KiB WIPPER disk image. Backups remain private on Pi 6.
The controller's supported inline jobs provide a working route while
the desktop SSH agent cannot sign; no S31 binding or active soak console
was changed for Pico preparation.

## Pico W runtime validation

The original alpha.2 integration linked but exposed only USB mass storage:
the default WHD packet pool and thread stacks left too little runtime RAM
to allocate USB CDC. CircuitPython commit `168149058e` and Zephyr dependency
`62aa864927d3ae43ede3b2b557b6f410aae8899a` reduce only Pico W's shared WHD
pool from 20 to 10 full-sized buffers and its main stack to 16 KiB. The
six-buffer Bluetooth coexistence reserve remains; Pico 2 W keeps defaults.
Both builds pass, at 1,273,644 and 1,230,244 bytes respectively. The Pico W
link map now leaves 32,168 bytes below `0x20040000`, plus the remaining
upper SRAM. This is build headroom, not a runtime free-heap measurement.

The physical debug probe `E6654854576EB830` was matched to the Pico by
comparing its first 4 KiB of flash against the installed UF2 before recovery.
SWD flashing and verification of the revised image passed. USB CDC then
enumerated, Python ran, BLE enabled, and a two-second BLE scan returned
42 entries in 2.047 seconds. The firmware's cached version header still
reported `cef2fe5f7a`; artifact hashes and build inputs identify this build.

**Pico W is not yet a compatibility or soak pass.** Wi-Fi scanning returned
`OSError(11)` / EAGAIN, including bounded follow-up scans with BLE enabled
and disabled (about five seconds to failure). USB stalled afterwards and
the host attempted recovery. A separate RTT diagnostic image was installed;
its boot logs show WLAN firmware, Bluetooth firmware and USB initialization.
The remaining radio/USB behavior needs diagnosis before an overnight test.
The ESP observer was not interrupted by these Pico jobs.

Revised Pico W UF2 SHA-256:
`ae65271a434aa715d346cca9ce82401d05e36911ecad2176e6c9d3dfe4028863`.
Diagnostic RTT UF2 SHA-256:
`50c092757fa7959df9a8064ad68f048a8fb19cbf64c4c26295597c53e7678c81`.
Full original firmware/filesystem backups remain private on Pi 6.

At 03:12 UTC the ESP observer was still running after 94 minutes:
47 confirmed deliveries and true deep-sleep wakes, 188 HTTP successes
(one startup error), 45 BLE successes, one collector start, zero serial
errors and no recorded test failures. The full eight-hour result is pending.
The follow-up can use the controller API when desktop SSH signing fails;
credentials are obtained at execution time rather than saved in its prompt.

### Startup isolation and build provenance

CircuitPython commit `5afc122780` fixes stale incremental-build version
headers. Version generation now runs for each build and retains unchanged
output timestamps; Git commits, tags and dirty state are no longer hidden
by the command cache. All 85 cptools tests pass, including cache-bypass and
unchanged-output tests. A real incremental build reports the current
`11.0.0-alpha.2-19-g5afc122780-dirty` diagnostic source state.

Autonomous C diagnostics over SWD/RTT reproduce the Wi-Fi failure without
Python or USB: the scan command's `event_msgs` IOVAR times out after five
seconds (`0x060e0000`, then `-EAGAIN`). The WHD packet pool has zero buffers
in flight at failure, and the diagnostic thread remains alive. A full-chip
watchdog reset also reproduces it.

The same image accepts a scan before CircuitPython startup. With automatic
BLE workflow startup suppressed only for diagnosis, it accepts the later
scan too. With BLE startup restored, the later scan fails again. Request
acceptance is not a completed scan, association, TLS or soak pass. Disabling
BLE is not proposed as a compatibility fix. USB enumeration also remains an
unresolved problem, including in the no-BLE-startup control.

Two controlled candidates did not fix the failure: notifying WHD whenever
the shared IRQ pin is asserted on re-enable, and locking complete backplane
read/write transactions. Both experiments were reverted from source. Their
negative results are retained locally alongside exact firmware and ELF
hashes; neither is included in the published branches.

A further startup probe successfully read the Wi-Fi MAC immediately after
Bluetooth firmware loading. Subsequent HCI initialization in that
instrumented run produced repeated hardware errors and an opcode `0x0c03`
command timeout, halting before the later scan. In a separate control with
normal startup, suspending only the Bluetooth poll thread at 25 seconds
did not restore Wi-Fi: the scan at 33 seconds still timed out. These results
narrow the investigation but do not identify a validated repair. All
temporary driver and startup instrumentation was removed after testing.

At 03:52 UTC, the ESP observer process was verified active after 134 minutes:
66 confirmed deliveries and true deep-sleep wakes, 268 HTTP successes
(one startup error), 63 BLE successes, one collector start, zero serial
errors and no recorded failures. The eight-hour result remains pending.

### Validated CYW43 coexistence repair

The Pico SDK selects a different WLAN image when Bluetooth is enabled.
Using its `wb43439A0_7_95_49_00_combined.h` WLAN/CLM pair fixes the
post-Bluetooth Wi-Fi control timeout on Pico W. The generic Murata image
reported WLAN 7.95.88; the SDK combo image reports 7.95.61. The fix follows
the SDK's coexistence selection rather than choosing the higher version.
NVRAM is unchanged. Prior failed IRQ and transaction-lock candidates remain
reverted.

Zephyr commit `ea703e85b630897a5df75f4156f22f72edd5a81d` extracts the pair
from the already pinned hal_rpi_pico header during configuration, validates
the length metadata and retains explicit custom-resource overrides.
Eight extractor tests pass. The durable selector produces an image
byte-identical to the successful diagnostic build. Its preceding commit
`8d632a8238990c624a3e407f93bdf8694b775977` also fixes HCI TX length counting:
the H:4 type byte was counted twice, advertising an extra byte and allowing
an out-of-bounds read at maximum length. A sanitizer harness using the real
send function fails on the original and passes the corrected framing,
boundary, error and ownership cases.

Hardware job `0147637e-9a23-45cd-a786-018de6df887c` completed three Wi-Fi
scans while BLE scanning was active. They returned 3, 7 and 8 AP results;
BLE received eight advertisements. All scan request/completion statuses
and BLE start/stop returned zero. This is C-level radio validation through
RTT; it does not establish Python API, association, TLS or long-soak results.
Diagnostic UF2 SHA-256:
`fb9ec7660f5a86f6ff21f82ed1df4f0b95f6c709edb76545642a29122d35e51a`.

CircuitPython commit `a24d38f09fd11e0a20c599a8eeaead2b7e3ba9fa` pins the
fixed Zephyr revision. Normal builds with clean tracked source pass for
Pico W (1,251,876 bytes, 32,168 bytes SRAM0 headroom) and Pico 2 W
(1,208,484 bytes). Both report `11.0.0-alpha.2-20-ga24d38f09f`.
The Pico W incremental build initially stopped at a generated-file cache
check; rerunning without source changes completed successfully.
Normal UF2 hashes are Pico W
`dd0f032b54ac6e8e5beeb6f9f9a3a6188ba8aca0fa591928a17783440264e132`
and Pico 2 W
`e7a732980af901dd74fa996ded84561c2d1ad37cc6b90d415f3f36e31df1708c`.
The normal Pico W image passed SWD flash verification, but the host still
times out reading USB descriptors and no CDC console appears. Its CPU
remains active. Python API checks and extended Pico testing are therefore
still blocked by USB; the successful C-level radio scans do not resolve
this separate validation gap. Pico 2 W hardware testing remains pending.

The three firmware draft PRs now target comparison branches pinned exactly
to the CircuitPython alpha.2 tag and its upstream Zephyr revision, so their
diffs contain the carried integration changes rather than upstream history.
At 04:40 UTC the ESP observer was active after 182 minutes: 90 confirmed
deliveries and true deep-sleep wakes, 364 HTTP successes (one startup
error), 86 BLE successes, one collector start, zero serial errors and no
recorded failures. Its eight-hour result remains pending.

### USB recovery and Python radio validation

The USB investigation found a host-side contributor: Pico W also failed
enumeration while executing its built-in ROM USB boot loop (verified by
SWD). Resetting the Genesys hub's single transaction translator, followed
by toggling only Pico's USB pull-up, restored ROM enumeration. A picotool
reboot then exposed the unchanged normal CircuitPython image's CDC, MSC
and HID interfaces. No shared hub power was switched. The exact trigger
for the stuck translator is not established.

On clean-source firmware `a24d38f09f`, Python-level simultaneous scan job
`38523d67-198c-408a-9577-7cea6c4870b1` passed three cycles: Wi-Fi returned
87/103/96 scan results and BLE received 26/27/26 advertisements, each cycle
taking about 8.2 seconds. Association to the bench AP and an HTTP 200
response also passed while BLE received 128 advertisements. The console
remained responsive.

The reported `gc.mem_free()` near 71 KB is **not actual free physical RAM**.
This port adds a fixed 64 KB fallback estimate for a possible new split
heap. Treat it only as an estimate; linked RAM bounds and actual allocation
success remain the relevant constraints.

TLS preflight is still failing. The published image raises `MemoryError`
while wrapping the socket, both with and without active BLE scanning.
A local, unpublished Pico W-only candidate reduces WHD pools from 5+5 to
4+4, network packet counts from 14 to 8 per direction, and data-buffer
counts from 36 to 24. It frees 9,456 bytes and gets past wrapping, but an
RSA TLS handshake still raises `MemoryError`. HTTP/BLE continues to pass.
Full TLS records and the six-buffer Bluetooth reserve are retained.
Further checked-stack RAM testing is in progress; no TLS compatibility or
Pico overnight pass is claimed.

At 04:54 UTC the ESP observer remained active after 197 minutes: 97
confirmed deliveries and true deep-sleep wakes, 393 HTTP successes (one
startup error), 93 BLE successes, one collector start, zero serial errors
and no recorded failures. The eight-hour deadline remains 09:37 UTC.

### Pico TLS RAM validation and eight-hour radio soak

The published Pico W update is now CircuitPython
`3e8c1601cf8511ad691170906a98eeca412744ed`, with the same Zephyr
`ea703e85b630897a5df75f4156f22f72edd5a81d` pin. It keeps full TLS
records and full network MTU while reducing WHD packet pools to 4+4,
network packets to eight per direction and chained data buffers to 24.
An 8 KiB main stack, initialization pattern, stack sentinel and allocator
counters retain measurable stack/heap evidence. The six-buffer shared-radio
reserve remains intact. Pico 2 W configuration is unchanged.

The pool-only and 12 KiB-stack candidates still failed the RSA handshake
with `MemoryError`. The 8 KiB candidate passed local RSA-2048 TLS with a
trusted self-signed certificate, correct hostname verification and BLE
scanning; a wrong hostname was rejected (`OSError(-9984)`). Its post-TLS
stack sentinel was intact, with 4,652 untouched bytes and an upper bound
of 3,536 touched bytes. The allocator peak was 53,640 bytes. This is
controlled-endpoint evidence, not a guarantee for larger certificate
chains. The existing test RNG setting has not been changed.

The committed, clean-source build uses 1,252,124 bytes of firmware flash
and leaves 49,800 bytes in SRAM0 before runtime allocations (plus the
remaining SRAM region). Its BIN is 1,252,352 bytes, SHA-256
`0bc60f402d3cd3bc8bb073980090b770cf2c886882924ba5b418426923de9fa9`;
UF2 is 2,504,704 bytes, SHA-256
`d7957a79df767f1391bb7505479a6c0e289ccd810fbc8d9cd16f860aafc4f475`.
SWD programming/verification and normal USB enumeration passed in job
`efad2eb1-1a4b-4159-a17f-5dde3dba9560`.

**First association remains an open runtime issue.** Both the 8 KiB
candidate and the clean committed image failed the first association
after boot with `ConnectionError: Unknown failure 1`. One bounded retry
succeeded on each. The clean-image retry, job
`a449335a-3d1a-4323-a54a-c67b27bd09cd`, received HTTP 200 with 120 BLE
advertisements, then a verified TLS response with 63 BLE advertisements,
and rejected the wrong hostname. The failed first attempt is retained as
job `61a36b12-e3d1-4a43-9799-cc8064b821dc`. No first-connect reliability
claim or related issue closure is justified by the retry.

`tools/pico_radio_soak.py` records simultaneous Wi-Fi/BLE scan cycles,
atomic status and JSONL samples. It selects the exact USB serial and
checks the firmware revision, never reconnects/resets automatically, and
requires the full requested duration for a pass. It fails on bounded scan
or serial errors and three consecutive empty-radio cycles. Four evidence
parsing/validation tests pass. A separate 30-second recorder preflight
completed three cycles; it was not the overnight run.

The real eight-hour Pico radio soak started **2026-10-22 05:28:11 UTC**,
due **13:28:11 UTC (14:28 BST)**, controller job
`c39ae3ca-1470-4839-b90b-7b1c078ad31e`, on Pico serial
`E663AC91D3444127`. Status and samples live on Pi 6 under
`/home/pi/envhub-bench-20261022/pico-radio-overnight-01/`. The first cycle
returned 81 Wi-Fi results and 26 BLE advertisements in 5.71 seconds.
**Failed after 46 cycles; see the failure analysis below.** This is scan coexistence testing, not sustained
TLS, association reliability or the full ESP-NOW collector application.
The port's `gc.mem_free()` includes a fixed growth estimate; the recorder
labels it `gc_free_estimate` and does not claim physical RAM from it.

Reproduction uses pyserial plus the adjacent `serial_deploy.py`:

```sh
python tools/pico_radio_soak.py --serial-number E663AC91D3444127 \
  --revision 3e8c1601cf --hours 8 --interval 30 --output /new/run-directory
```

At 05:28 UTC the separate ESP observer remained active after 230 minutes:
114 confirmed deliveries and true deep-sleep wakes, 460 HTTP successes
(one startup error), 108 BLE successes, one collector start, zero serial
errors and no recorded failures. Its deadline remains 09:37 UTC. The
existing hourly monitor now tracks both runs; shared Wi-Fi/Bluetooth and
hub cleanup must wait until the Pico run also finishes. Remaining Pico
2 W, Feather and Metro hardware validation stays pending.

### Remaining firmware staged on Pi

The previously built Feather C6, Feather S3 (both RAM variants), Metro S3
and Pico 2 W BIN images are staged under
`/home/pi/envhub-bench-20261022/`, with their source revisions, lengths
and SHA-256 values in `remaining-firmware-manifest.json`. Job
`b63bcafd-16f8-4928-bd35-57e5f2fe5eea` independently verified all five
destination hashes. This copied host files only: no DUT console, flash or
USB port state was changed. Hardware identification, full private flash
backup and board-specific flashing still precede any runtime claim.
In particular, confirm the physical Feather's RAM/flash variant before
selecting its image, and preserve files across the changed C6/Metro
partition layouts described above.

### Post-soak portal release staging

The exact tested portal commit
`30e57d225c32e65ea212bba12a5acc24804748e9` is now staged on Pi 6 at
`/home/pi/envhub-bench-20261022/portal-release-30e57d2`. Its
`release.json` identifies only `index.html`, `sw.js`, `manifest.json`,
`icon.svg`, `ai_tools.js`, `webmcp.js` and `prompt_backend.js`, with byte
counts and SHA-256 hashes. The archive SHA-256 is
`3ddfdfdd67228ce7e5d0a303c30d9439fc220735f25ca177c0788cf215f1b8f5`.

Staging job `66619060-dc3a-496b-88fc-e079f377e924` verified all assets.
The read-only gate `/home/pi/envhub-bench-20261022/check_portal_release_ready_30e57d2.py`
also requires a terminal ESP observer with a full 28,800 seconds and no
active systemd PID. At 05:44 UTC it correctly returned deployment-not-ready
while PID 5493 remained active. No console was opened and no DUT files
were changed. The hourly monitor knows this release path and gate.
Actual C5 deployment and served-asset hash verification remain pending;
preserve its vendor assets, configuration and logged measurements.

This release supersedes the earlier `1b79d14` staged bundle. Review found
that the native model loop omitted the Stop signal when placing work in
the shared SQL queue. A behavioral regression using the actual portal
loop and queue reproduced a stopped query reaching the engine. The
one-line correction forwards that signal: stopped queued work now skips
the engine, normal work still executes, and temporary sessions are
released. Both new regressions, the ten existing browser-AI integration
tests and all thirteen SQL validation groups pass. The mobile fallback
already forwarded its signal and is unchanged.

The separate first-association investigation narrowed the Python error
to `WIFI_RADIO_ERROR_UNSPECIFIED` (1), rather than the event-result
`WIFI_RADIO_ERROR_CONNECTION_FAIL` (205). AIROC performs WHD join
synchronously and collapses its failures to `-EAGAIN`; current logging
does not retain the underlying WHD result. The cause is not established.
After the Pico soak, capture that result and compare a clean disconnect
before reset with an abrupt restart against the same AP. Do not add an
automatic retry or close the issue based solely on the successful retry.

### Pico overnight failure and independent Feather V2 build

The Pico W eight-hour scan soak FAILED at 2026-10-22 05:51:47 UTC after 1,416.05 seconds and 46 good cycles, job `c39ae3ca-1470-4839-b90b-7b1c078ad31e`. Cycle 47 accepted the raw-REPL command but produced no terminator before the 35-second deadline. This is not an overnight pass. The preserved main thread is blocked in `common_hal_wifi_scannednetworks_next()` / `k_poll(K_FOREVER)`, on channel index 3 with no queued results or completion signal; the driver still has its scan callback registered. Root cause remains under investigation. The stack sentinel is intact, touched stack is at most 3,536 bytes, and libc reports 42,116 bytes free. UART samples do not establish a stuck FIFO. No USB resets or disconnects were reported around the failure. The failed run is retained; Pico 2 W validation remains pending.

Failure occurred during the independent Feather V2 backup read/verify, but
timing alone does not establish causation. No shared hub reset occurred.
The private RAM snapshot remains on Pi in `pico-radio-failure-01/ram.bin`
(270,336 bytes, SHA-256
`c6056b860d69700dd8f37fd4ac45833b139606457533a666df77f3ddee42f9c6`).
Do not publish this RAM or full-flash backup: either can contain credentials.
Snapshot job: `9b815563-f0e9-4ad7-8fa8-a27f5bd3d6dc`; decoded scan/thread
state job: `3398f984-7fe1-4e6f-9101-2b2018250408`.
The AIROC 12-second timeout protects association-related scans, not this
asynchronous `airoc_mgmt_scan` path. A recovery or bounded timeout alone
will not establish reliable scan coexistence; a new full-duration run is needed.

At 06:03 UTC the independent ESP soak was still active: 131 confirmed
deliveries and true sleep wakes, 529 HTTP successes (one startup error),
125 BLE successes, one collector start, zero serial errors, no recorded
failures. Its eight-hour deadline remains 09:37:42 UTC. The hourly monitor
now records the Pico failure and preserves its evidence instead of waiting
for its obsolete deadline. Shared cleanup remains deferred while diagnostics
or additional tests are active.

The directly attached Feather ESP32 V2 has USB serial `564E053407`, ROM MAC
`E8:9F:6D:32:50:04`, and 8 MiB flash. Backup/verification job
`e59059c9-ca53-494c-a7a6-e186924af8e6` passed before any write. Its private
8,388,608-byte backup SHA-256 is
`c2d4abdd4554c680555729669ceb5a0a91eef4dbf23db8d93b883757669e150e`.

The first Feather V2 integration build exceeded its 2 MiB slot by 12,736
bytes. ESP integration `4730c980cafabb18ed889d680db26ff4ffafeb28`
adds two 3 MiB OTA slots and a 1,984 KiB filesystem at 0x610000, with
16 KiB inbound / 4 KiB outbound TLS records. A fresh build uses 2,109,904
application bytes, leaving 1,035,824 bytes. An incremental build retained
the old generated sdkconfig and failed; the fresh output directory is the
verified artifact source. The combined BIN is 2,175,440 bytes, SHA-256
`146ca9a4b13f88a11a78dc4570f25c4c2886347b72c667301411dca33d3362dc`.
Bootloader, partition table and app offsets were checked against the build.
Staging job `e4a01886-c56e-4083-b1fb-c4042b8e2adb` verified the Pi copy.
Flash job `5609ec7b-f3ca-4890-b024-1ed61301ce86` was submitted after preserving
Pico diagnostics; runtime preflight later passed, as recorded in the next section.

### Atomic backplane fix and new independent eight-hour runs

Pico firmware `6fc7497ef4` now pins HAL `12f662c34e21e7c1addd3f7aad0488d35bffd8c2` (https://github.com/tyeth/hal_infineon/pull/3). The old mutex protected individual SPI transfers but left backplane window selection and access exposed to a competing Bluetooth thread. The actual-source regression reproduces a wrong-window access on the old code; 28 corrected success/error/cleanup/recursive-lock cases pass under UBSan. This is a demonstrated race fix, not yet proof that the overnight failure is resolved. The clean build and SWD write verification pass. Same-session first association to the public bench network, verified RSA TLS with 79 BLE advertisements and wrong-host rejection pass. A NEW eight-hour scan soak started 06:26:57 UTC, due 14:26:57 UTC (15:26:57 BST), job `aa40cc1a-dc2c-4141-aa86-2e395798ee50`, separate evidence `pico-radio-overnight-02`. Three initial cycles passed; running is not passed. The failed first run remains intact.

The failed run's saved log buffer contains repeated CYW43 out-of-range
Bluetooth ring indices, including exhaustion of all eight rereads. The
concurrent USB CDC warning is `RX transfer already in progress`; its
presence does not establish it caused the radio failure. Extracted static
log strings are recorded in job `0e984d78-9cc7-4254-af54-83c9f5609010`.
No private dynamic RAM values were published.

The corrected Pico BIN is 1,252,188 bytes, SHA-256
`20ed2907a0ae42b4adb86e4fc2c1ce1e313478061e712f251278e4b1c3b90e8a`;
UF2 SHA-256
`187046a87efed286a788a4752626790285930793662c2c72f0ea406943f2a915`.
Original firmware artifacts and failed-run RAM remain preserved. Flash
job `4610fd80-3d2c-4694-9828-ee8de1983994` verified the new write and normal
USB enumeration; TLS preflight job `3ab93b72-5c3c-4a43-8035-6093db4c409b`
passed. This successful first association used a different public bench
network from earlier failed attempts, so it does not close that issue.

Feather ESP32 V2 write verification passed in job `5609ec7b-f3ca-4890-b024-1ed61301ce86`. Runtime identity matches `4730c980ca`; HTTP with 61 BLE advertisements and verified RSA TLS with 56 BLE advertisements passed, with wrong-host rejection (`MBEDTLS_ERR_X509_CERT_VERIFY_FAILED`). The successful TLS job is `de6a83c5-73d7-49f5-b028-d02f1ca7df3b`. Earlier TLS attempts failed because the bounded test server expired and a later REPL session had no Wi-Fi association; those failed jobs remain recorded. The successful test uses documented public bench Wi-Fi and associates within the TLS session. An independent eight-hour scan soak started 06:28:07 UTC, due 14:28:07 UTC (15:28:07 BST), Pi service `envhub-feather-radio`, evidence `feather-radio-overnight-01`. Its first cycle received three Wi-Fi results and 25 BLE advertisements. Running is not passed; this is scan coexistence, not sustained TLS or the full collector application.

The reusable recorder now accepts an explicit USB vendor ID and `--uart`,
keeping UART DTR/RTS deasserted. Selection requires exactly one matching
serial/vendor pair and refuses missing or ambiguous matches. Six recorder
tests pass. The separate Pi Feather copy has SHA-256
`d2b9e56c34ada9e621df6d28bde1ee8131283372693cf9f59d574a143fda0477`;
the already-running Pico recorder was not overwritten. Feather service
launch job: `10bc9da2-5e5f-463b-9bab-370f024364c5`.

Read-only status job `17401d4b-6f92-4cd7-b54e-380d6703b827` confirmed all
three active runs at 06:28 UTC. The ESP application run had 143 confirmed
deliveries/true wakes, 579 HTTP successes (one startup error), 136 BLE
successes, one collector start, no serial errors and no recorded failures.
The corrected Pico had three completed cycles and no failures; Feather
had its first successful cycle. Full duration is still required for each.
The hourly monitor tracks their separate deadlines. Shared Wi-Fi/Bluetooth,
USB/IP and hub-port cleanup waits for active tests; the final C5 portal-only
release remains gated on its own complete ESP observer. Pico 2 W and the
remaining Feather/Metro board runtime validation remain pending.

Pico 2 W also builds at CircuitPython `6fc7497ef4` with HAL `12f662c34e21e7c1addd3f7aad0488d35bffd8c2`: 1,208,548 bytes firmware and 275,756 bytes linked RAM. Its replacement BIN SHA-256 is `bb7416ab8261e2a83f50db6bcfbaf8351b53d070a2dd7557c9e78f21b292f0bd`. Staging job `b0274c48-137c-42fc-ae87-120340c994dc` verified it and the unchanged Feather/Metro images, then updated `remaining-firmware-manifest.json`. The older Pico 2 W artifact remains preserved. The new image is not flashed or runtime validated.

## Portal browser validation

WebMCP uses the current `document.modelContext.registerTool` API with
page-lifetime cancellation. Actual Chrome 155 with WebMCP enabled listed
both tools. On the 2,377-row demo dataset, `envhub_query` returned bedroom
2,261 ppm and local 2,573 ppm for `MAX(co2)` grouped by zone. A DELETE
request was refused with `SELECT only`. Concurrent SQL requests share a
queue around Pyodide's globals. No device-write tool is exposed.

The separate opt-in Prompt API polyfill is pinned to 1.22.2 with
Transformers.js 4.3.0 and Qwen2.5-0.5B-Instruct q4. Native Prompt API remains
preferred. Both fresh WASM-worker and WebGPU sessions correctly answered
an arithmetic smoke check. q4f16 produced incorrect inference on this AMD
GPU despite advertised shader-f16 support, so the integration uses q4
weights with full-precision arithmetic (about 786 MB to download).

The final saved query/summary code was loaded into the warmed Chrome page
to avoid another model download, then exercised through the actual Ask
controls. It generated a grouped MAX(co2) SELECT, executed it against
SQLite, and correctly answered bedroom 2,261 ppm and local 2,573 ppm in
4.2 seconds. Earlier attempts with the longer schema and a shared summary
brief generated wrong queries or extra examples; those failures informed
the shorter SQL brief, two examples, first-fence extraction and separate
summary session. Read-only validation is enforced regardless of model output.

Twelve browser integration tests, 13 SQL test groups, 20 certificate
test groups and inline/helper syntax checks pass. The controls fit a
390-pixel viewport. This is desktop browser validation, not a physical
phone performance claim. Browser cache writes were sometimes refused;
offline model availability is not guaranteed. Small-model answers can
still be wrong, and executed SQL/results remain visible for inspection.

The C5 copy was deployed before these final browser fixes. Update only its
`/www` assets after the eight-hour observer finishes, then verify the
served files. Do not interrupt the soak to update the portal.

### Prepared portal-only deployment

The Pi now has `deploy_portal_release_30e57d2.py`, SHA-256
`61a58fe3a4d4de2f06b1bb694e43f3f065d9e9b796a1441241ae8cf3be7bcf4d`.
It invokes the existing full-duration readiness gate before any console
access. A nonblocking host lock prevents concurrent deployments. After
the gate passes, it selects only the C5 UART serial, verifies the known
chip MAC, backs up the seven existing `/www` assets, writes only the
manifest-listed replacements using the UART-safe helper, reads each back
for hash verification, resumes the collector, then checks every HTTP-served
asset hash and `/api/latest`. Configuration, logged measurements and
`/www/vendor` are outside its write set. Backups and atomic deployment
status are saved under the existing private Pi evidence root.

Staging/check job `97fd1e6c-f21d-4f89-a11f-bf77b91fdb24` verified the helper
hash and confirmed exit 2 while the observer was active at 06:42 UTC,
18,288 seconds into the run. No console was opened and no portal asset
was deployed. The eventual rollout still needs actual terminal-soak,
device-file and served-byte evidence; a prepared helper is not deployment.

### Independent evidence snapshot at 06:56 UTC

The read-only `tools/report_soak.py` recomputes log counts, delivery/HTTP/BLE
coverage, reset/fatal evidence and memory summaries without opening hardware.
It hashes the input snapshots, rejects short or failed terminal runs, and
labels every active run provisional. A terminal consistency result still
requires separate confirmation that the observer process has stopped. Nine
regression tests cover premature passes, count drift, corrupt terminal logs,
partial live appends, failed-run preservation, missing scan spans, empty
radio scans and collector restarts. Memory summaries are observations, not
statistical leak verdicts; Pico GC free is a port estimate.

Pi reporter SHA-256:
`bf010eb4b7a5c113d33b29a827752245eed6e7eb87d5e1f368e04665b2f907f7`.
Read-only analysis job `2c420bb1-a451-4467-a69f-08184a72954a` found:

* ESP application run: 19,101 seconds, 157 confirmations and true deep-sleep
  wakes, 635 HTTP successes / one startup error, 150 BLE successes / no BLE
  errors, one collector start, no fatal lines. Largest observed delivery,
  HTTP and BLE gaps were 122.509, 31.000 and 131.015 seconds. BLE-reported
  free memory ranged from 3,985,904 to 3,988,304 bytes; the latest sample was
  2,240 bytes below the first. Synthetic sensor values remain labelled `sim`.
* Corrected Pico run 02: 59 cycles, maximum cycle 5.883 seconds, maximum
  cycle gap 30.150 seconds. GC allocation ranged from 2,032 to 2,208 bytes.
* Feather V2: 56 cycles, maximum cycle 5.007 seconds and 30-second maximum
  gap. GC allocation ranged from 1,984 to 3,152 bytes. At least one isolated
  BLE scan returned zero advertisements; the three-consecutive-empty
  failure condition was not reached.
* Failed Pico run 01 remains rejected: 1,416.05 seconds and 46 cycles,
  below the required eight hours, with a recorded failure.

All three current runs remain provisional. Their log hashes are snapshots,
not final immutable evidence. Repeat this report after each observer stops
and retain the terminal hashes with the final result.
