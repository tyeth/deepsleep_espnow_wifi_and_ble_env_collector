# Pico W console-close storage stall — 23 October 2026

Tracked in [CircuitPython fork #42](https://github.com/tyeth/circuitpython/issues/42).

Closing Pico W's USB serial console can stall a read-only MSC command until the console is reopened. This is physically reproduced on the older CircuitPython `9e153ad624` integration and is also observed during attempted rollout of `6839890534` / Zephyr `c6200e80ea`. It is not established as a regression introduced by the two new USB reconfiguration fixes.

Both builds are based on official 11.0.0-alpha.2. Device: `raspberrypi_rpi_pico_w_zephyr`, RP2040, direct Linux xHCI USB connection. This reproduction does not use the S31/USB-IP bridge. Pico 2 and other UDC implementations have not been qualified for this trigger.

## Matched physical controls on 9e153ad624

All reads are the same uncached 4 KiB range, with identical hashes and no device filesystem writes or firmware changes.

| Host console state | Read time |
|---|---:|
| Open | about 31 ms |
| Handle open, DTR deasserted | about 31 ms; also 60 ms in the repeat |
| Closed, reopen scheduled after 2 s | 2.068 s |
| Closed, reopen scheduled after 4 s | 4.066 s |
| Open after reconnect | about 30–53 ms |
| Closed, reopen scheduled after 1 s | 30 ms; this attempt did **not** stall |

The trigger is intermittent; do not claim every close stalls. A separate sleep / CPU-busy / sleep control completed the same reads in 31 / 32 / 60 ms while Python executed an eight-second workload. That control does not support changing thread priority as a fix.

## Candidate rollout and USB trace

Two actual `6839890534` attempts answered CDC but timed out after 10 seconds in `blockdev --getsize64` before any repeated SET_CONFIGURATION test. The second attempt captured 15,762 USBmon events with zero reported drops or packet truncation. The candidate runtime's delayed TEST UNIT READY command completed successfully after 10.126 seconds, as recovery opened the console. All captured MSC command wrappers have matching status wrappers; this is host-request evidence, not an electrical bus trace.

The first automatic restore was blocked before writing by a timed-out `usb-storage` unbind. A separate guarded recovery requested ROM through CDC without waiting for that unbind and restored the original code with whole-image verification and three radio checks. The traced attempt used that recovery path and also restored successfully. Both production Picos remain on `9e153ad624`; the new USB build is not retained in production.

## Minimal reproduction

1. On a Pico W running the revision above, use a verified, unmounted CIRCUITPY block device and its matching serial device. Keep HID/USB configuration unchanged.
2. Open the console, enter/leave raw REPL and confirm the firmware banner. With the serial handle open, time `dd if=/dev/<DUT-disk> bs=4096 count=1 iflag=direct status=none` and retain the hash.
3. Keep the handle open but deassert DTR. Repeat the same read, then restore DTR. This is the negative control.
4. Close the serial handle. Schedule a fresh open at the same baud (115200, not the 1200-baud bootloader trigger) after two or four seconds. Immediately issue the identical uncached read with a bounded host timeout. Compare its completion time with the scheduled reopen.
5. Repeat open-console controls and compare exact read hashes. Preserve the non-stalling close attempts too. Restore the original host bindings.

Do not infer a flash/storage data-corruption defect from this delay. Root cause and whether the owner is CircuitPython, Zephyr UDC/class code, or host interaction remain open. The existing Zephyr SET_CONFIGURATION and cancelled-OUT reports (#121843 and #122768) and CircuitPython #11531 are related USB work, but equivalence to this trigger is not established. See [fork integration PR #32](https://github.com/tyeth/circuitpython/pull/32) for the existing USB fixes; this report is an additional rollout blocker.

Raw flash backups, kernel logs and the 25,864,944-byte USBmon capture remain private. The adjacent JSON retains sanitized timing and hash evidence. Four native decoder controls cover command/status pairing, missing status, negative USB completion and failed SCSI status. The unchanged flash transaction modules pass eight fault controls per Pico variant. No priority or USB source change is made in response to this finding.

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

## Host-controller trace capture: stall not reproduced

On the unchanged `9e153` Pico W, three bounded xHCI capture runs completed 25
read-only 4 KiB reads, including eight closed-console reads. All completed in
30.2-34.3 ms with matching data. The private trace instances recorded URB
enqueue/giveback, transfer-ring entries, endpoint doorbells and completion
events with zero reported drops or overruns. Inspection confirms actual Pico
MSC traffic; the open control includes the queued 4 KiB IN transfer, its
doorbell and successful completion. These are successful-transfer traces,
not captures of the earlier stall.

The first two runs included a host marker between console close and the read.
The second was intended to remove it, but a line-ending mismatch retained the
marker; it is recorded as another marker-present run. The third actually
removed that marker and still did not reproduce the stall. Finally, the
original uninstrumented script also passed seven reads (two closed-console
attempts with reopen scheduled after one/four seconds), in 30.2-59.0 ms.
Thus this series does not establish that tracing or the extra marker prevents
the fault. It does not invalidate the earlier failed controls or identify a
host, hub or device root cause.

No firmware or device-filesystem writes occurred. All bindings were restored,
the bridge was untouched, and a subsequent read-only check confirmed no private
trace instances remained. Raw host traces stay private; [sanitized timings,
hashes and per-CPU loss counters](picow-xhci-nonreproduction-2026-10-23.json)
preserve every round. CP #42 remains an unresolved rollout blocker. The next
useful capture must contain an actual stall before transfer timing can choose
between host scheduling and device-side response hypotheses.

## Host trace with active Python workloads

A separate control on the unchanged `9e153` Pico W combines the xHCI capture
with eight-second Python workloads. The open-console sleeping control and six
closed-console rounds (three busy, three sleeping) all read the same 4 KiB in
31.4–52.3 ms. The planned console reopen is three seconds after close, and no
host marker is inserted between close and the disk read. Python completes all
seven loops; maximum iteration gaps are below 20 ms. Trace loss and overrun
counters remain zero.

This is another non-reproduction, including while Python runs outside the
REPL prompt. It neither overturns the earlier busy/sleep stalls nor identifies
a fix. No firmware or device-filesystem writes occurred; bindings and the
private trace instance were restored, and the bridge was untouched. The
[sanitized workload measurements](picow-xhci-workload-control-2026-10-23.json)
retain all seven rounds. Further repetitions of this passing setup alone
cannot resolve CP #42; a changed reproduction condition or an actual failing
trace is needed.

## MCU reset and fresh USB enumeration control

A subsequent control changes the startup history: `microcontroller.reset()`
restarts the unchanged `9e153` Pico W, and the host observes a new USB device
number with the same identity. Target uptime changes from 5,529.012 seconds to
8.364 seconds. This is an MCU reset, not a power-removal test.

The same xHCI-captured workload then completes seven exact 4 KiB reads,
including six closed-console rounds, in 32.146–41.485 ms. Python progresses,
the scheduled reopen remains three seconds after close, and all trace loss
counters are zero. Firmware and filesystem were not written; host bindings
and the private trace instance were restored and the bridge was untouched.

This changed condition still does not reproduce the earlier stalls. It does
not prove a reset repairs them, remove the rollout blocker, or identify the
responsible host/device component. [Exact measurements](picow-xhci-reset-control-2026-10-23.json)
retain the failed-to-reproduce result alongside earlier actual failures.
