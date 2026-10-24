# S31 mixed storage/console check with the USB fixes — 23 October 2026

**Mixed CDC plus Pico MSC still fails in both import orders. With the USB fixes,
the initial and final single-Pico storage controls now both pass.** The failed
mixed-load job remains failed; its successful restoration is reported separately.

| Import / admitted traffic | Pico MSC | Pico console afterward | Metro console afterward |
|---|---|---|---|
| Pico alone, CDC then MSC | Two matching 4 KiB reads | Pass | — |
| Pico then Metro, both CDC then Pico MSC | No disk within 20 seconds | EIO | Pass |
| Metro then Pico, both CDC then Pico MSC | No disk within 20 seconds | EIO | Pass |
| Pico alone after both mixed cases | Two matching 4 KiB reads | Pass | — |

All initially admitted consoles answer before MSC is enabled. Linux attempts
four virtual USB resets during each mixed case. HID remains unauthorized, as
does Metro MSC. There are three physical leaf devices and three hubs throughout;
the third leaf is not imported. Captured descriptors and interface-admission
states match the [earlier comparison](s31-msc-reimport-2026-10-23.md).
The only firmware substitution is the Pico build carrying the USB fixes.

The installed bridge is `bec1d71e1379e08e279327bdb222b3207456cebe` from
[draft #25](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/pull/25).
The temporary Pico 2 image is the actual CP `6839890534` production build,
1,209,068 bytes, SHA-256
`c32dbc54a53cd8cb9b416af0898ba987af1688ec3fdcf06aff079051bdba124d`.
It pins Zephyr `c6200e80ea`; Metro remains `ea06dcb44e`.
The successful reads report the same 2,617,856-byte disk and SHA-256
`d6995cdde5696faf0286ffe6ca46afaad322c141a8c063fb1666579e2fcfd4a2`
for each 4 KiB sample, before and after both mixed cases.

The final single-device pass is the important difference from the old-firmware
run, whose final single-device MSC check also failed. This separates a remaining
load-dependent failure from the independently reproduced reconfiguration bug.
It supports further channel-pressure investigation; it does not directly measure
channel exhaustion or establish which allocation fails. No live channel counter
or bridge transfer log was captured. Network logging remains unavailable and
the diagnostic UART was not opened. Full composite capacity remains open in
[bridge #20](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/20).

## Restoration

A fresh 4 MiB backup precedes a code-only update and full-flash verification.
Cleanup restores the original `9e153ad624` code and verifies the expected full
image, preserving runtime data outside the touched sectors. The restoration
snapshot differs from the original backup by exactly ten bytes in a runtime
build-version string; no other bytes differ. This snapshot is taken before
rebooting the restored firmware. Three restored Wi-Fi/BLE checks pass.

All imports, temporary leaf-port power and interface defaults are restored.
The C6 remains untouched; there is no bridge reboot or S31 firmware change.
Raw snapshots, kernel logs, the failed run and private recovery files are retained.
The adjacent JSON records exact scope and the restoration audit. Both Pico
production devices still run `9e153ad624` after the temporary comparisons.

## Minimal next discriminator

Keep the same population and corrected Pico firmware. Admit CDC on Pico and
Metro, verify both consoles, then admit only Pico MSC. Reverse the import order,
then repeat the single-device control. Capture channel allocation/release or the
specific host allocation failure, with a verified non-resetting console capture
or instrumented network telemetry. Do not infer capacity solely from an EIO or
from the earlier single-device reconnect failure.

Subsequent [UART evidence and a one-fewer-leaf control](s31-channel-exhaustion-2026-10-23.md) now establish channel exhaustion for the matched mixed workload. The earlier uninstrumented results above retain their original scope.
