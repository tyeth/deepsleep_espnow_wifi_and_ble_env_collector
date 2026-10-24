# S31 simultaneous composite-device investigation — 23 October 2026

**Update at 04:38 UTC: the installed per-interface candidate passes both consoles in both import orders.** The identical selective-interface baseline failed its second console in both orders. This is a custom commit-to-commit comparison, not the standard release/CI-artifact matrix. See the candidate result below; broader class/capacity coverage remains open.

**Baseline result: the second imported console fails in either order; the first remains usable.**
This is a completed diagnostic, not a successful simultaneous-device qualification.
No firmware was written. Original port states and imports were restored, and
the bridge uptime increased throughout: no bridge reboot occurred.

| Import order | First console | Second console | First console recheck |
|---|---|---|---|
| Feather S3 alone | Pass | — | Pass |
| Pico 2 W, then Feather S3 | Pass | Raw-REPL timeout, twice | Pass |
| Feather S3, then Pico 2 W | Pass | Raw-REPL timeout, twice | Pass |

Bridge: `74975412c1b04c0738dcf57ab03bae82bc8ac71f` (claim-cleanup PR #24).
Pico 2 W: `6b117bdce5`. Feather S3: `cb5301b6fb-dirty`.
Both devices remained physically connected during all three controls. Each
captured configuration contains four interfaces: CDC control (one endpoint),
CDC data (two), MSC (two), HID (two), for **seven non-control endpoints each**.
Both have alternate setting zero only. Linux MSC/HID drivers were unbound after
enumeration, as in the earlier failure; this does not release bridge-side claims.

## Source and resource accounting

The installed backend calls `ensure_interfaces_claimed_locked()` on the first
non-control transfer, claiming every interface. The actual bundled host-library
path is `usb_host_interface_claim` → `interface_claim` → `ep_wrapper_alloc` →
`usbh_ep_alloc` → `hcd_pipe_alloc` → `usb_dwc_hal_chan_alloc`. Each interface's
endpoints get dedicated channels. Exhaustion returns an error, mapped to generic
`-EIO` by the bridge. Software URB slot availability does not remove this limit.

Using the 16-channel S31 budget documented in existing bridge issue #20, these
two complete configurations need 14 data channels plus two leaf EP0 channels.
Even a single external hub adds its EP0 and interrupt endpoint, taking the
minimum to 18. Extra hubs only increase that requirement. This accounting and
the reversed-order physical control strongly support channel exhaustion. We did
not capture a live channel counter or an exhaustion message in this run.

A native test compiled the actual installed claim/release functions with a
16-channel host model, four baseline channels, and the captured 1/2/2/2 interface
costs. Both orders reproduced second-device exhaustion; three retries preserved
the first device, rolled back all partial claims, and succeeded after releasing
the first device. No invalid release/reclaim occurred. This is modeled host
allocation, not hardware instrumentation. Backend source SHA-256:
`8c8ab8055ad45f67cefc024517d712070b90386f1a9d10b60a6ff28826eaa1ac`.
The installed cleanup fix therefore addresses leaks, while the simultaneous
capacity limitation remains open.

## Minimal reproduction and next fix

1. Use the above bridge revision and two composite CDC/MSC/HID boards with the
   same endpoint counts. Keep both physically enumerated behind a hub.
2. Import the first board via USB/IP and request its board ID and firmware version.
3. Import the second, unbind unwanted Linux class drivers, and request its identity.
4. Confirm the second times out while the first still responds. Detach both,
   reverse the order, and repeat. Restore the original imports and port states.

The next candidate should claim only the interface owning the requested endpoint,
retain correct partial-claim cleanup, and reset toggles only on claimed endpoints.
Linux class-driver probing can itself trigger unwanted traffic, so per-interface
claiming alone must not be assumed sufficient: test selective interface admission
before probing as well. Controller scheduling needs endpoint budget/headroom and
an actionable resource-exhausted result. Neither candidate is deployed by this report.

## Separate diagnostic-UART failure

The bridge's USB-to-UART adapter failed before these controls: Linux reported
enable-UART control-request timeouts and opening it returned EIO. A bounded,
adapter-only USB reset also timed out; a later check found no leftover reset
process and the bridge network API remained healthy with increasing uptime.
This prevented passive bridge-log capture. The successful diagnostic above
avoided that adapter. At that point recovery remained open. Those adapter errors are not evidence that
the simultaneous-import failure has the same cause. Failed attempts and
private recovery records remain preserved.

Structured evidence: [sanitized results](s31-simultaneous-capacity-2026-10-23.json).
Existing trackers: [bridge capacity #20](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/20),
[claim cleanup #23](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/23),
[controller #1](https://github.com/tyeth-ai-assisted/sbc-mcu-dut-controller/issues/1).

## Recovery follow-up at 02:40 UTC

A bounded direct-hub off/on operation restored the expected USB identities.
The next check successfully opened/read/closed the UART, and both directly
attached Pico W (`9e153ad624`) and Feather ESP32 V2 (`ea06dcb44e`) passed expected
firmware and disconnected Wi-Fi/AP/BLE assertions. However, that check then
**failed** its final bridge-uptime assertion: the bridge had rebooted during
the verification interval. Preserve this as a failed no-reset verification.
The UART was configured with DTR/RTS false before open, but that does not prove
the line transitions were harmless; reset cause and electrical behavior remain
unverified. No further UART open was attempted.

A subsequent read-only network check found the same bridge firmware, uptime
62 seconds, exactly the original downstream Pico 2 inventory, no USB/IP imports,
no active soak units, and no leftover adapter-reset process. Thus USB transport
was recovered and the bench left idle; unexpected reset behavior remains open.
This later recovery reset does not change the earlier capacity experiment's
verified uninterrupted uptime. No firmware was written in either operation.

## Selective-interface baseline and candidate — 03:40 UTC

The installed `7497541` bridge still fails the second console in either order
when Linux MSC/HID interfaces are **never authorized or probed**. Only the two
CDC interfaces were authorized, together before manual driver probing; both
bound to `cdc_acm`, while MSC/HID remained unauthorized and unbound. The first
console continued responding. The S3-alone control passed. Original VHCI
authorization defaults, imports and port states were restored; no UART was
opened, firmware written, or bridge reboot observed.

This closes the specific question of whether client selection alone repairs the
installed bridge: it does not. See [the captured admission states and results](s31-selective-interface-baseline-2026-10-23.json).
The procedure follows the kernel's [interface authorization documentation](https://www.kernel.org/doc/html/latest/usb/authorization.html):
set the empty virtual USB bus's default before attaching, authorize all interfaces
needed by a multi-interface driver, then explicitly probe. Restore the defaults
after detaching owned imports; do not change physical USB bus defaults.

Draft [bridge PR #25](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/pull/25),
stacked on cleanup PR #24, implements per-interface demand at
`bec1d71e1379e08e279327bdb222b3207456cebe`. It claims only the interface owning the
requested endpoint, retains active claims when another claim fails, and resets
toggles only on claimed endpoints. Sparse interface lookup and correct per-endpoint
descriptor offsets are included. Alternate setting zero remains the supported mode.

Seventeen actual-source native groups pass with address/undefined-behavior
sanitizers, including constrained two-CDC capacity, allocation/release failures,
retries, deferred cleanup, descriptor boundaries, sparse interfaces, packet sizing
and standard-request toggle handling. The historical cleanup harness still passes
24 cases on `7497541`. An actual-source bounded-host comparison shows the old
all-interface behavior exhausting the budget where the candidate fits both CDC
devices. The host allocation and descriptor parser are modeled in these tests.

A fresh full ESP32-S31 build passed with clean ESP-IDF
`ce2100de51a4d9a372f26578fd2ee763ca4b1279`; the application is 829,088 bytes,
SHA-256 `8a540fc8296b973072584c0bd59de509be8ffa0d0d5275540796804e52c87bd6`.
See [build provenance and artifact hashes](firmware-s31-demand-bec1d71-2026-10-23.json).

At 03:40 UTC this candidate was not yet installed. The following update supersedes that deployment status.

## Installed candidate comparison — 04:38 UTC

The guarded update from `7497541` to `bec1d71` completed successfully. A fresh
16 MiB backup was read and verified in 1 MiB chunks. Only the 1 MiB factory
application at `0x10000` was written; the entire resulting flash was verified,
including unchanged bootloader, partition table, NVS and other storage. The
candidate API returned after the intentional update reset. Private recovery
images remain retained. Fifteen host fault/bounds tests cover plan rejection,
partial writes, verification failures and rollback failure handling.
See [update evidence and hashes](s31-demand-update-2026-10-23.json).

The exact same selective-interface helper and descriptor hashes were used:

| Import order | Baseline 7497541 | Candidate bec1d71 |
|---|---|---|
| Feather S3 alone | Both probes pass | Both probes pass |
| Pico 2 W, then Feather S3 | Second console fails twice; first passes | Both probes on both consoles pass |
| Feather S3, then Pico 2 W | Second console fails twice; first passes | Both probes on both consoles pass |

Both CDC interfaces bound to `cdc_acm`; MSC/HID stayed unauthorized and unbound
from before probing. Imports, power state and authorization defaults were restored.
Bridge uptime increased from 61 to 88 seconds: no reset during the comparison.
The comparison itself opened no diagnostic UART and wrote no firmware.
See [candidate results](s31-selective-interface-candidate-2026-10-23.json) and
[the failed baseline](s31-selective-interface-baseline-2026-10-23.json).

This verifies two simultaneous CDC consoles under selective admission. It does
not establish general full-composite capacity, MSC/HID behavior, sustained
throughput, or controller scheduling. Keep the capacity tracker open for those
limits; there is still no direct live channel-counter measurement.

## Subsequent MSC investigation — 14:38 UTC

The broader MSC check now has a preserved failure: a first Pico 2 read succeeds,
but three subsequent single-device imports fail to enumerate MSC while CDC
remains usable. Mixed-console cases also fail MSC and lose the Pico console;
those results cannot be attributed solely to simultaneous channel pressure.
Imports, port power and authorization defaults were restored without a bridge
reset. See [the separate minimal reproduction and limits](s31-msc-reimport-2026-10-23.md).

A later comparison using the actual Pico 2 USB-fixed build separates the remaining
mixed-load failure from the reconnect defect: both single-device controls pass,
but mixed CDC/MSC still fails in either order. See [the new failure and recovery evidence](s31-mixed-usbfix-2026-10-23.md).

Subsequent [UART evidence and a one-fewer-leaf control](s31-channel-exhaustion-2026-10-23.md) now establish channel exhaustion for the matched mixed workload. The earlier uninstrumented results above retain their original scope.
