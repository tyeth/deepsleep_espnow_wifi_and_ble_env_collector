# Controller power-cycle candidate — physical C6 check

The exact adapter from [controller PR 2](https://github.com/tyeth-ai-assisted/sbc-mcu-dut-controller/pull/2),
commit `6ca2f2dffa7dcc6ea0094744f77433f13e7aa278`, passed one real C6 power cycle
through ESP32-S31 bridge `bec1d71`. The adapter ran as a standalone client on
the Pi with httpx 0.28.1; the running controller service was not changed.

The candidate requested off, required reported hub power-off plus a device
404, held off for 30 seconds, then requested on. Its HTTP response trace records:

| Elapsed seconds | Observation |
|---:|---|
| 0.185 | Three hubs; target reported off and disabled |
| 0.194 | Target-device GET returned 404 |
| 30.211 | Power-on POST returned success |
| 30.226 | Target reported on but disabled; candidate continued polling |
| 30.823 | Only two hubs; target path absent; candidate continued polling |
| 31.404 | Three hubs; target returned but reported off; candidate continued polling |
| 31.939 | Target reported on and enabled |
| 31.958 | Matching target-device GET returned 200; candidate accepted the transition |

After the candidate's two-second settling period, a separate guarded observer
switched other leaf ports off and read the C6 without issuing a reset. It ran
the expected `ea06dcb44e` CircuitPython image with uptime 7.21 seconds. No
USB/IP imports remained. Bridge uptime increased from 6,111 to 6,145 seconds;
the bridge did not reboot during the candidate's cycle.

This is physical confirmation that the candidate tolerates a transiently
absent parent hub and rejects premature on-but-disabled observations. The
earlier ad-hoc power probe failed on that missing path; its failure remains
preserved. The candidate had already passed 61 mocked bridge/client/host
checks, with two central regression cases failing on the baseline.

Settings immediately before this check were `restore_port_power=false`,
`enforce_per_port_switching=false`, and `enum_timeout_ms=0`. Returning other
ports to on after hub re-enumeration is therefore not established as a
restoration bug. Parent-hub disappearance is still investigated in
[bridge issue 26](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/26).

Limits: one board, hub chain and cycle; no deliberate live HTTP failure
injection, voltage/current measurement, endpoint-capacity qualification or
controller-service deployment. Hub status alone is not a rail measurement;
the independent low-uptime observation supports the MCU restart in this run.

[Sanitized timings and exact adapter hash](controller-c6-physical-2026-10-23.json).

## Subsequent service deployment

The exact tested adapter was later installed in the controller service after
61 isolated live-base tests and guarded restart verification. See
[deployment evidence and limits](controller-power-deployment-2026-10-23.md).
The physical trace above remains the earlier standalone measurement.
