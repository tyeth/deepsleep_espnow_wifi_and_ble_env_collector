# Upstream disposition and reproduction notes — 22 October 2026

## Update at 23:35 UTC: targeted investigation takes priority

The [coverage ledger](issue-investigation-coverage-2026-10-22.md) now includes the original ESP/application reports as well as this index. Fresh HAL Pico startup/cache fault injection and Feather S3 BLE-toggle/failed-SD-init checks are recorded there. Earlier running-soak and hardware-availability statements below are historical; the later rollout/follow-up reports contain their terminal results. Several targeted physical checks remain outstanding.

## Update at 17:56 UTC: TLS server policy reproduced and validated

[CP #26](https://github.com/tyeth/circuitpython/issues/26) is freshly reproduced
with the actual alpha.2 policy block, which still matches current upstream's
source blob. A normal client without a certificate fails with `-0x7480`; the
carried fix accepts it. Eight test cases cover fourteen real TLS handshakes,
including encrypted application data on success. Explicit CA loading still
requires a trusted client certificate, and clients still reject untrusted
servers and wrong hostnames. All assertions pass; the baseline failure is an
explicitly asserted control. See the [standalone reproduction](../tools/repro_tls_server_policy/README.md)
and [source-pinned evidence](tls-server-policy-reproduction-2026-10-22.json).
This is native shared-policy/cryptography validation, not a new physical-board
test. Production firmware and active soaks remain unchanged.

## Update at 17:44 UTC: p256-m report freshly reproduced

[Zephyr #10](https://github.com/tyeth/zephyr/issues/10) remains reproducible with
real PSA ECDH in the native simulator. p256-m gives TLS a one-byte premaster
buffer and returns -138; the built-in provider gives 32 bytes and succeeds.
Both providers pass an explicit 32-byte control. The relevant TLS and ECP header
blobs match current upstream. Keep the existing workaround; see the
[minimal reproduction](../tools/repro_p256_premaster/README.md) and
[exact evidence](p256-premaster-reproduction-2026-10-22.json). No firmware pin,
running device or soak changed for this test.

## Update at 17:28 UTC: Pico failure and replacement candidate

The a0c two-hour Pico run failed after 140 cycles/4,236.05 seconds. A separately
reproduced receive-lock defect is fixed in Zephyr `7379648278`, pinned by CP
`7d4ef1aac7`; both Pico builds pass and Pico W runtime preflight passes. Its new
two-hour soak began at 17:26 UTC and is still running. The physical stall's root
cause remains unproven; no completed replacement soak is claimed. The three
eight-hour runs remain uninterrupted. The prior one-hour/settings-only plan is
superseded. See [the incident, minimal reproduction and current evidence](pico-rx-contention-2026-10-22.md).

This updates the [3 October escalation index](https://github.com/tyeth/circuitpython/issues/15#issuecomment-5617383669).
It is an interim review record; the final issue comment and completed hardware
results are still pending. Fork issue state, current upstream source and the
dependencies shipped by CircuitPython are checked separately.

Source inspection at 16:46 UTC used CircuitPython `d53b2277cfad71589028e5da77c984c045db990d`,
Zephyr `8bfd51a5ec69187f630e7717c25c768c89f24f43`, HAL Pico
`2e9dbf14fa56e5907aefb07e8e75010ec5210946` and HAL Infineon
`eae914ed1ad0b54af28191d13da9b8e98fb5cb2b`. The [source audit](upstream-escalation-source-audit-2026-10-22.json)
records exact file blob IDs and links. A source inspection is not a new hardware test.

## Confirmed upstream fixes

The following three fork defect trackers were closed as completed on 22 October.
The referenced fixes are ancestors of the inspected upstream branch heads, and
their relevant code is still present there.

| Fork tracker | Upstream fix | Scope and release distinction |
|---|---|---|
| [Zephyr #5](https://github.com/tyeth/zephyr/issues/5), unaligned USB DPRAM copy | [`c2d5de2a0ac6`](https://github.com/zephyrproject-rtos/zephyr/commit/c2d5de2a0ac6cb569e014116967aba91501bcfda) | Uses aligned word-length copies and byte tails in TX/RX, retaining the original packet length for the short-packet decision. The alpha.2 dependency still has the old copy path, so the carried [fork patch #2](https://github.com/tyeth/zephyr/pull/2) remains useful for that base. |
| [Zephyr #7](https://github.com/tyeth/zephyr/issues/7), misleading endpoint-busy errors | [`2f0bc11264a8`](https://github.com/zephyrproject-rtos/zephyr/commit/2f0bc11264a8e72e214f3db0a3fa221eb022453a) | Removes the error in the `XFER_NEW` queuing path. A separate busy log remains in the completion path; a text search for the message alone would incorrectly classify this fix as absent. |
| [HAL Pico #7](https://github.com/tyeth/hal_rpi_pico/issues/7), flash helpers executing with XIP disabled | [`74cc3dfda63e`](https://github.com/zephyrproject-rtos/hal_rpi_pico/commit/74cc3dfda63ea8d8323869d6b0bad806cd1e545d) | Marks all three helpers `__not_in_flash_func`. This is an equivalent resolution to the fork's forced-inline [PR #2](https://github.com/tyeth/hal_rpi_pico/pull/2), which remains carried on the older pinned dependency. |

These closures do not claim that alpha.2 already includes the newer Zephyr/HAL
changes, or that our fork PRs were merged upstream. No integration dependency
was moved during this audit. Existing firmware and running soaks are unchanged.

Already recorded as upstreamed: [CP #24](https://github.com/tyeth/circuitpython/pull/24)
via [Adafruit #11423](https://github.com/adafruit/circuitpython/pull/11423), and
the console-wake portion of [CP #20](https://github.com/tyeth/circuitpython/pull/20)
via [Adafruit #11448](https://github.com/adafruit/circuitpython/pull/11448).
Those duplicate patches were omitted during the alpha.2 rebase. The old global
`BT_MAX_CONN=4` override was also dropped because upstream uses 5; Pico W's
board-specific limit is separate.

## Candidates still requiring upstream review

These are fork fixes or reports, not claims of upstream submission. The minimal
steps below are reproduction instructions; only the validation explicitly
listed in the last column was executed in this refresh.

| Tracker / candidate | Current fix or review branch | Minimal reproduction and validation boundary |
|---|---|---|
| [CP #28](https://github.com/tyeth/circuitpython/issues/28), empty version override | [CP #32](https://github.com/tyeth/circuitpython/pull/32), `d86cb7ae95` carried in `1ca79521f3` | In a tagged checkout, run `CP_VERSION= python3 py/makeversionhdr.py /tmp/version.h`; compare with `env -u CP_VERSION python3 py/makeversionhdr.py /tmp/version.h`. Empty must fall back to Git. Four header-generation cases pass; current upstream still tests presence rather than a nonempty value. |
| [CP #26](https://github.com/tyeth/circuitpython/issues/26), TLS server client-certificate policy | Shared-module fix carried in [CP #32](https://github.com/tyeth/circuitpython/pull/32) | Create a default server context, load only its own certificate/key, then wrap with `server_side=True` and connect without a client certificate. The inherited default root bundle must not demand client authentication. Alpha.2/current upstream fails with `-0x7480`; the carried fix passes. Explicit `load_verify_locations()` deliberately retains client verification. The [native reproduction](../tools/repro_tls_server_policy/README.md) passes eight cases / fourteen real TLS handshakes, including trusted/untrusted client controls and client-side CA/hostname rejection. It compiles unmodified source-policy extracts with real Mbed TLS, not the whole interpreter or a physical board. |
| [CP #27](https://github.com/tyeth/circuitpython/issues/27), failed BLE startup/retry | [CP #32](https://github.com/tyeth/circuitpython/pull/32) plus [Zephyr #11](https://github.com/tyeth/zephyr/pull/11) | Inject one `-EIO` return from the first `bt_hci_open`, then retry initialization. Require a real second open; never load settings on an uninitialized host or manufacture a random identity. From the CircuitPython checkout, `python3 tools/check_zephyr_ble_startup.py --circuitpython . --zephyr ports/zephyr-cp/zephyr` passes 60 actual-source checks; old sources fail 37. Physical failed-open injection remains unrun because the SWD probe is unavailable. |
| [Zephyr #3](https://github.com/tyeth/zephyr/issues/3), zero-sector settings geometry | [Zephyr #11](https://github.com/tyeth/zephyr/pull/11), `353bcd30f7`; CP pin in #32 | Configure a 2 KiB settings partition offset by 2 KiB on a 4 KiB erase-page flash simulator. `flash_area_get_sectors` returns zero sectors with success; initialization must return `-EINVAL` before mount. Run `west twister -T tests/subsys/settings/sector_geometry -p native_sim/native/64` in the configured Zephyr environment. NVS and both ZMS modes: six scenarios / twelve cases pass; all three malformed controls fail before the fix. Current upstream NVS and ZMS still lack the guard. |
| [Zephyr #6](https://github.com/tyeth/zephyr/issues/6), USB thread stack headroom | 2048-byte downstream setting in [CP #32](https://github.com/tyeth/circuitpython/pull/32) | On Pico 2 W, exercise USB CDC/MSC concurrently with sustained radio activity and compare stack instrumentation at 512 versus 2048 bytes. Upstream's default remains 512. Current builds verify 2048; a new instrumented Pico 2 W comparison is still needed before proposing a universal driver default. |
| [Zephyr #8](https://github.com/tyeth/zephyr/issues/8), AIROC softAP channel/events | Rebased in [Zephyr #11](https://github.com/tyeth/zephyr/pull/11) | Enable a CYW43439 softAP on channel 1 through the non-supplicant management path; check the channel passed to `whd_wifi_init_ap`, then associate/deauthenticate a station. Current upstream still constructs a chanspec for that call. The fork passes a bare channel and handles AP events; no fresh alpha.2 Pico 2 W AP/DHCP run is claimed. |
| [Zephyr #9](https://github.com/tyeth/zephyr/issues/9), legacy scan timeout | CircuitPython host deadline in [CP #20](https://github.com/tyeth/circuitpython/pull/20), carried in #32 | With `CONFIG_BT_EXT_ADV=n`, privacy disabled and an advertiser nearby, start a passive Zephyr scan with `.timeout=300` (3 seconds, 10 ms units). Check for reports beyond the deadline. Current upstream legacy start still does not use the timeout; the downstream deadline is a workaround, not a Zephyr fix. |
| [Zephyr #10](https://github.com/tyeth/zephyr/issues/10), p256-m premaster sizing | Configuration workaround from [CP #21](https://github.com/tyeth/circuitpython/pull/21), carried in #32 | Build TLS 1.2 ECDHE/P-256 with p256-m enabled and the ECP module absent; inspect premaster size and perform a handshake. Compare with p256-m disabled. Fresh native reproduction now confirms the one-byte buffer and real `PSA_ERROR_BUFFER_TOO_SMALL` (-138): p256-m fails the TLS-sized output while its explicit 32-byte control succeeds; disabling p256-m passes both cases. Relevant tested headers match current upstream blobs. Run the [standalone reproduction](../tools/repro_p256_premaster/README.md); three of four cases pass and the affected case intentionally fails. This is component evidence, not a new network handshake. Current outbound TLS tests retain the workaround. |
| [HAL Pico #3](https://github.com/tyeth/hal_rpi_pico/issues/3), cached HOST_CTRL check | Report only | Instrument the backplane-read hook while calling `cybt_reg_read(HOST_CTRL_REG_ADDR, ...)`; current upstream returns `host_ctrl_cache_reg` without reading hardware. Simulate a lost hardware write to demonstrate divergence. No production cache-policy change or new hardware fault injection is claimed. |
| [HAL Pico #6](https://github.com/tyeth/hal_rpi_pico/issues/6), startup assertions pre-empt errno | [HAL Pico #5](https://github.com/tyeth/hal_rpi_pico/pull/5), carried at `725e9e429e` | Force ready/init-buffer/awake to fail one at a time during `cyw43_btbus_init`; require an error return with the host still alive. Current upstream still asserts success before those existing returns. The real failed-start hardware path remains unverified here. |
| [HAL Infineon #2](https://github.com/tyeth/hal_infineon/issues/2), coexistence asset | [HAL Infineon #1](https://github.com/tyeth/hal_infineon/pull/1), extended by [#3](https://github.com/tyeth/hal_infineon/pull/3) | Inspect the selected CYW43439 Murata 1YN NVRAM and loaded WLAN/CLM assets, then run concurrent Wi-Fi/BLE traffic. Upstream's text asset still contains `btc_mode=0`. Current integration selects its documented matching coexistence resources; the shortened hardware soak is not yet complete. |
| Shared-bus window and power races | [HAL Infineon #3](https://github.com/tyeth/hal_infineon/pull/3) plus [Zephyr #11](https://github.com/tyeth/zephyr/pull/11) | Inject a competing owner between window selection/access and during power-state transition. Run `python3 tests/test_whd_backplane_lock.py` and `python3 tests/test_whd_bus_power_lock.py` in the HAL checkout. Actual-source harnesses reproduce the old failures and pass 28 window-lock / 40 power-transition checks after fixing them. The paired Zephyr wake guard passes 25 cases. Prior failed soak evidence remains preserved. |

## Port and project work retained separately

[CP #9](https://github.com/tyeth/circuitpython/issues/9) now has a small API-contract
fix in #32: `start_scan(extended=True)` raises `NotImplementedError` before
replacing an active scan. Minimal check: start an ordinary scan, try the
unsupported extended request, consume the original scan, then start another
ordinary scan. The actual-source harness passes 26 checks; both simulator
boards and the installed `a0c1485cf5` Pico W pass the scan-preservation check.
This does not implement extended advertising. Upstream still discards the argument.

[CP #10](https://github.com/tyeth/circuitpython/issues/10) is carried in #32:
build, change the Git version/override and rebuild without cleaning; the version
header must refresh while unchanged output keeps its timestamp. Both existing
incremental-version regressions pass. CI override plumbing (#12/#16), frozen
collector libraries (#30, now integrated by [ESP #31](https://github.com/tyeth/circuitpython/pull/31))
and application flash layouts remain project integration work.

[CP #25](https://github.com/tyeth/circuitpython/issues/25)'s earlier 45% warm-reset
failure claim was retracted after 45/45 successes. [CP #29](https://github.com/tyeth/circuitpython/issues/29)
still needs confirmation of the Windows GATT-cache / Service Changed mechanism
before an upstream firmware claim. Neither report is closed by this audit.
[ESP-IDF #19074](https://github.com/espressif/esp-idf/pull/19074) is the existing
upstream DHCP debug-format submission; its final state must be rechecked when
posting the concluding index.

## Hardware attribution

The Pico W two-hour run uses `a0c1485cf5`, not the newest settings-fix image.
`1ca79521f3` / Zephyr `353bcd30f7` are built for both Pico variants and staged;
their physical qualification is pending. The new updater is tested and refuses
the active soak. A separate one-hour run is planned after the current Pico
run passes and the new firmware's runtime preflight succeeds. Three eight-hour
app/Feather/HTTPS runs continue independently. All remain in progress at this
audit; no new completed-soak or Pico 2 W hardware claim is made.
