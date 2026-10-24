# S31 MSC reimport failure — 23 October 2026

**Follow-up:** [packet traces, matched endpoint controls and a temporary Zephyr candidate](usb-reconfiguration-2026-10-23.md) now narrow this failure; the baseline results below remain unchanged.

**A Pico 2 MSC disk works on the first USB/IP import, but not the next three,
even with no second imported console. CDC remains usable.** This failure is
preserved separately from the earlier successful selective dual-CDC comparison.
It shows why simultaneous endpoint pressure cannot explain the whole MSC result.

Tested bridge `bec1d71e1379e08e279327bdb222b3207456cebe`, Pico 2 CircuitPython
`9e153ad624`, and Metro S3 `ea06dcb44e`. The physical topology stayed at three
hubs and three leaf devices, including an untouched powered C6. Only Pico 2
was imported in the sequential control; Metro and C6 were not imported.

| Sequential import | Pico MSC | Pico CDC after MSC attempt |
|---|---|---|
| 1 | Two matching uncached 4,096-byte reads | Pass |
| 2 | No disk after 20 seconds | Pass |
| 3 | No disk after 20 seconds | Pass |
| 4 | No disk after 20 seconds | Pass |

The initial disk size was 2,617,856 bytes; both reads hashed to
`d6995cdde5696faf0286ffe6ca46afaad322c141a8c063fb1666579e2fcfd4a2`.
Imports were detached between rounds, without MCU or bridge reset commands.
No firmware or filesystem writes were requested. The final job remains failed.
Cleanup restored original leaf-port power, imports and virtual-bus authorization
defaults. Bridge uptime increased from 11,842 to 11,937 seconds.

## Mixed-interface control and its confound

A preceding run first passed the same single Pico MSC read. It then imported
Pico and Metro CDC interfaces in both orders. Both consoles initially responded.
Authorizing Pico MSC next produced no disk within 20 seconds, and the Pico
console returned EIO; Metro remained responsive. The kernel recorded four
virtual USB reset attempts in each mixed case. After detaching both, a final
single Pico import retained CDC but still did not enumerate MSC. Cleanup passed
and bridge uptime increased from 11,628 to 11,734 seconds.

These mixed cases are not an isolated capacity proof: the sequential control
now demonstrates a repeated-session failure without a second console. The
three-hub/three-leaf baseline and two CDC configurations also leave little
modeled headroom, but no live channel counter was captured. Resource retention,
protocol/toggle state, and device-side behavior remain hypotheses.

## Minimal reproduction

1. Begin with a freshly powered Pico 2 on the tested bridge and no USB/IP imports.
   Keep the physical hub/leaf inventory constant. Save virtual-bus interface
   authorization defaults; deny interfaces before import so MSC/HID cannot probe.
2. Import only Pico 2. Authorize both CDC interfaces together, probe the driver,
   enter raw REPL and verify firmware. Keep HID unauthorized.
3. Authorize and probe MSC. Require no host mounts or conflicting block-device
   owner; allow asynchronous media readiness. Read the first 4 KiB twice with
   direct I/O and require exact equality. Recheck CDC.
4. Close CDC and detach the owned import. Repeat steps 2–3 three more times
   without power-cycling the board. Record failed enumeration and surviving CDC.
5. Preserve logs and restore imports, authorization defaults and original power.

An earlier fixture's first MSC control stopped at an unlabeled assertion; that
failed evidence is retained and is not counted as an MSC pass. The refined
fixture records failure stage and traceback, waits for transient block-device
owners and media capacity, and establishes the positive control above. Another
attempt stopped before any probe because the optional network log port refused
connections. Inspection found `log_server_start()` commented out in `main.c`;
the later run recorded that limitation. No diagnostic UART was opened.

The installed host library does unwind partial endpoint allocations on a failed
interface claim. Source inspection alone does not prove that the live failure
was a claim error, nor that session release/toggle state was correct. A direct
Pico 2 replug control, USB/IP transfer capture and live claim/release telemetry
remain useful discriminators. No new firmware fix or upstream regression is claimed.

See [structured evidence](s31-msc-reimport-2026-10-23.json),
[earlier capacity investigation](s31-simultaneous-capacity-2026-10-23.md),
[bridge capacity #20](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/20)
and [earlier MSC halt/toggle #13](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/13).

A later comparison using the actual Pico 2 USB-fixed build separates the remaining
mixed-load failure from the reconnect defect: both single-device controls pass,
but mixed CDC/MSC still fails in either order. See [the new failure and recovery evidence](s31-mixed-usbfix-2026-10-23.md).
