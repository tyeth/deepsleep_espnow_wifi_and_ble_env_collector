# Pico station lifecycle: fixed and physically verified

CircuitPython `9e153ad624` implements the Zephyr station lifecycle methods
tracked in [fork issue #40](https://github.com/tyeth/circuitpython/issues/40).
`stop_station()` now disconnects and waits for completion, clears the cached
SSID and DHCP state, and preserves the enabled radio. Driver failures do not
falsely clear a live connection. `start_station()` enables the interface.
Both operations preserve an active AP on the shared interface.

On Pico W, three channel-6 connect/lease/ping/stop cycles passed, including
reconnection to the same SSID, repeated stop and starting from disabled.
The peer AP independently confirmed each departure. Stops took 13–15 ms.
After switching roles, the Pico AP on channel 11 retained its client through
station stop/start, and the client pinged it in 18 ms. Both devices cleaned
up successfully, and bridge ports/imports were unchanged.

The installed image was verified against a fresh full-flash backup and
readback; settings, NVM, filesystem and BLE identity were retained. Both Pico
production images build from clean verified dependency pins, but Pico 2
still runs the preceding `6b117` image. [Build manifest](firmware-pico-station-9e153-2026-10-23.json).

The actual-source native harness passes 23 cases with DHCP and 23 without;
the preceding `6b117` source fails 38 checks. It covers asynchronous errors,
missing events, timeout, interruption, repeated calls and AP preservation.
Run from [the CircuitPython branch](https://github.com/tyeth-ai-assisted/circuitpython/tree/codex/zephyr-envhub-alpha2):

```sh
python tools/check_zephyr_station_lifecycle.py --circuitpython .
python tools/check_zephyr_station_lifecycle.py --circuitpython . --revision 6b117bdce576abf927554a4946b8610149150aa0
```

For a physical regression, use a disposable AP on channel 6. Connect, verify
a DHCP address and ping, stop the station, verify `connected == False` and
`ap_info is None`, and independently confirm departure on the AP. Repeat
the stop and reconnect to the same SSID. Repeat from `enabled = False`.
Then run the Pico as an AP with a connected client: station stop/start must
retain that client and its ping path. Always stop both test roles afterward.

Two earlier fixture failures remain preserved. The first sampled the ESP
AP address before it became available and passed `None` to IPv4Address.
The second passed every Pico functional check but asserted ESP cleanup
before state settled. Bounded readiness/shutdown waits fixed the fixture;
the final run measured about 50 ms for AP readiness and 1 ms for shutdown.
Those failed runs were not relabelled as successful.

See [sanitized results and evidence hashes](picow-station-lifecycle-2026-10-23.json).
This does not claim physical driver-failure injection, full USB/MSC stress,
Pico 2 runtime qualification at this revision, or another long soak.

## Later Pico 2 follow-up

Pico 2 was subsequently installed and verified at `9e153ad624`; station lifecycle
and bounded TLS/BLE controls passed. The earlier rollout status above is historical.
See [Pico 2 evidence and limits](pico2-station-tls-2026-10-23.md).
