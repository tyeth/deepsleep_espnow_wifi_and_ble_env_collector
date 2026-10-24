# Completed Env Hub soaks — 22 October 2026

All four selected runs passed independent verification at 19:45 UTC. The
verifier checked stopped successful services, exact starts and configured
durations, raw-log/status consistency, firmware attribution, and preserved
failed-run evidence. [Reports and hashes](completed-soaks-2026-10-22.json).

| Run | Duration | Result | Firmware actually exercised |
|---|---:|---|---|
| C5 collector / C61 sleeping node | 28,800.5 s | 236 confirmed deliveries and true deep-sleep wakes; 958 HTTP successes, one startup HTTP error; 225 BLE successes, no BLE errors | C5 `cb5301b6fb`; C61 `2a7f9987f3` |
| Feather ESP32 V2 Wi-Fi/BLE scans | 28,800 s | 960 cycles; no failed recorder conditions | `4730c980ca` |
| C5 trusted HTTPS | 28,800 s | 240 cycles, three API requests per cycle, no errors | C5 `cb5301b6fb`, portal `a53f137` |
| Pico W Wi-Fi/BLE replacement | 7,200 s | 240 cycles; no failures | CP `7d4ef1aac7`, Zephyr `7379648278` |

The application collector started once, with no fatal log lines or serial
interruptions. Maximum delivery/HTTP/BLE gaps were 122.921/31.173/132.993 seconds.
Its BLE-reported free-memory samples ranged from 3,977,792 to 3,980,464 bytes,
ending 2,464 bytes below the first sample; this is an observation, not a leak
verdict. The node sends explicitly labelled synthetic sensor measurements.

Feather scan times ranged from 5.000 to 5.020 seconds, with a maximum cycle gap
of 30.01 seconds. Wi-Fi counts were 1–3; BLE counts were 0–33. Occasional empty
BLE scans did not reach the recorder's three-consecutive-empty failure threshold.
GC allocation ranged from 1,984 to 3,200 bytes, ending 32 bytes above the first
sample. Free-memory values are port estimates, not measured physical free RAM.

Every HTTPS cycle used normal CA and hostname verification against the same
leaf identity. Cycle durations were 1.148–2.079 seconds, with a maximum start
gap of 120.832 seconds. Earlier intermittent browser empty responses remain a
separate observation; this result does not retroactively explain them.

The Pico replacement exceeded the earlier 71-minute failure and independently
passed its complete two hours. [Detailed result and source-defect limits](pico-rx-contention-2026-10-22.md).
The earlier failed and externally interrupted runs remain separate and retained.

These runs do not qualify subsequent C61 firmware or portal asset changes.
Pico 2 W and other board variants need their own physical evidence; build
coverage alone is not a hardware pass. The completed runs release the guarded
portal/C61 rollout and controlled board-discovery steps.
