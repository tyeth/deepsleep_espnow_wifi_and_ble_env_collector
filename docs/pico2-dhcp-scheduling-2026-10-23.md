# Pico 2 DHCP starvation: controlled reproduction and fix

The DHCP failure is reproducible when the Pico waits at the raw REPL. The
server starts successfully and the station associates, but the lower-priority
socket-service thread does not process its queued Discover messages until
the interpreter sleeps. This is separate from ESP CircuitPython's existing
[`connect(timeout=...)` issue #7557](https://github.com/adafruit/circuitpython/issues/7557).

The physical comparison used the same CP `7d4ef1aac7` / Zephyr `7379648278`
source on a Pico 2 W, with a Feather ESP32 V2 station at `cb5301b6fb-dirty`:

| Case | Outcome |
|---|---|
| Socket service priority 15, interpreter priority 0, raw REPL idle | No lease within the 25-second host deadline. Static-IP ping passes. |
| Same binary, two-second Pico sleeps between observations | Lease acquired; server logs Discover and Request allocation. |
| Only socket-service priority changed to 0, raw REPL idle | Lease acquired without application sleeps. |
| Priority 0, 15-second Python busy loop | Lease acquired in 4.467 seconds while the loop was still running; 1,266,409 iterations completed. |

The complete generated configurations differed in exactly one setting:
`CONFIG_NET_SOCKETS_SERVICE_THREAD_PRIO=15` versus `0`. Both had the main
thread at priority 0 and a 20 ms scheduler timeslice. The configuration change
is now implemented in CircuitPython commit `6b117bdce5` as a conditional
default to `MAIN_THREAD_PRIORITY`. The physical candidate predates that
commit and uses an equivalent configuration override; production-image
qualification must retain that distinction. The existing 85 build-tool tests
pass, but those tests alone do not validate network scheduling.

## Minimal recreation

Use a Zephyr Pico AP and a second CircuitPython Wi-Fi station, each with an
independently controlled serial console. Keep the AP console connected in raw
REPL throughout the test. Use disposable bench credentials.

1. On the AP, run `wifi.radio.start_ap("cp-dhcp-repro", password="test-only-password", channel=1)` and leave it waiting at the raw REPL prompt.
2. On the station, call `start_station()`, `stop_dhcp()`, `start_dhcp()`, then `connect("cp-dhcp-repro", "test-only-password", timeout=10)`. Enforce a separate 25-second host deadline; the ESP timeout issue can otherwise leave this call waiting.
3. Sample `wifi.radio.stations_ap` on the AP. Baseline associates the station but reports no lease. Interrupt the station command with Ctrl-C before cleanup.
4. Repeat on the same image while running `time.sleep(2)` on the AP between observations. The lease now arrives.
5. Change only the socket-service priority to match the main thread, rebuild, and repeat step 1 without sleeps. DHCP must succeed. Also test a 15-second Python busy loop on the AP and require the station to acquire its lease before that loop ends.
6. Stop the AP and station and restore the station DHCP client. The recorded runs confirmed cleanup and restored their original USB/port state.

For logs, both the module debug level and global ceiling must permit debug:
`CONFIG_NET_LOG=y`, `CONFIG_NET_DHCPV4_SERVER_LOG_LEVEL_DBG=y`, and
`CONFIG_LOG_MAX_LEVEL=4`. A module level of 4 under a global ceiling of 2
does not produce DHCP debug output. The corrected binary's debug strings and
runtime messages were checked.

## Limits and stack measurements

This establishes the scheduling failure and a working priority change for
the tested Pico 2 AP workload. The production `6b117bdce5` Pico 2 image now passes channels 1, 6 and 11: actual scanned channel, DHCP lease, ping, matching station MAC/IP, station departure, and AP stop/restart. Cleanup passed. See the [production hardware evidence](pico2-production-ap-qualification-2026-10-23.json). Pico W now also passes production channel 1/6/11 and station departure, with ordinary BLE scans while the AP serves a station. See the [Pico W result](picow-production-qualification-2026-10-23.md). Both Pico W and Pico 2 W production builds now
pass at `6b117bdce5` without diagnostic overrides; their resolved socket-service
priority is 0. See the [production artifact manifest](firmware-pico-socket-priority-6b117-2026-10-23.json).

The instrumented USB driver thread used 248–256 bytes of its 2048-byte stack
during these CDC/AP tests. The socket-service thread used 2184 of 2400 bytes
with DHCP debug logging. These are different threads. Neither measurement
qualifies a 512-byte USB default or concurrent MSC/radio stress.

All firmware updates used a fresh verified 4 MiB backup, preserved settings,
NVM and filesystem bytes, and verified the entire resulting flash. Private
backups and failed evidence remain retained. See the [sanitized manifest](pico2-dhcp-scheduling-2026-10-23.json).
