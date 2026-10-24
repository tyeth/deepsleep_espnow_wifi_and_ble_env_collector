# Direct Pico W USB reconfiguration comparison — 23 October 2026

**The old firmware fails on the second repeated USB configuration; the paired
USB fixes pass all four repetitions on the direct-connected Pico W.** This
reproduces a storage/reconfiguration failure without the S31 USB/IP bridge.

## Controlled comparison

| Firmware | Repeated configuration 1 | Console and storage |
|---|---|---|
| `9e153ad624` | First passes; second fails | Console initially survives, disk is absent after 20 seconds; later Linux recovery loses the device |
| `6839890534` / Zephyr `c6200e80ea` | Four passes | Console works before/after each pair of exact whole-disk reads; three Wi-Fi/BLE checks pass |

The test closes console handles, checks that the disk is unmounted and unused,
and writes `1` to the identified device's `bConfigurationValue` sysfs attribute.
Linux rebuilds the host interfaces and sends SET_CONFIGURATION(1). After each
change it checks CDC, reads the entire 520,704-byte disk twice with direct I/O,
then checks CDC again. The candidate performs eight exact disk comparisons.
This is a direct Linux host test, separate from the earlier four S31 Pico 2
imports. [Linux's configuration attribute](https://docs.kernel.org/6.18/admin-guide/abi-stable.html)
and [configuration implementation](https://github.com/torvalds/linux/blob/master/drivers/usb/core/message.c)
describe the host mechanism; physical DATA0/DATA1 were not captured.

The baseline's second reconfiguration loses MSC enumeration while CDC still
responds. Subsequent kernel recovery logs descriptor timeouts (-110), failed
address setup (-71 and -22), disconnect, then a kernel-requested port power
cycle and successful re-enumeration. No agent hub-power command was issued.
A separate check confirms the original firmware, all original driver bindings,
and three Wi-Fi/BLE cycles. The failed job remains failed and made no firmware
or disk writes; it did not reach the candidate. A later independent transaction
performs the candidate test. A kernel power-cycle request does not prove that
the physical rail or MCU was reset.

## Firmware and recovery

The candidate is the production build at CP `6839890534556b06b8b3d7c491e36fd2005b2483`,
1,252,688 bytes, SHA-256
`2910af3498123383a9087be24120ba5572adb0ee01b3524b16a395bc19d23ce7`.
It carries the exact configuration-reset and CDC cancellation-rearm changes in
[Zephyr draft #11](https://github.com/tyeth/zephyr/pull/11), pinned by
[CP draft #32](https://github.com/tyeth/circuitpython/pull/32).
See the [build manifest](firmware-pico-usb-683989-2026-10-23.json) and
[Pico 2 controls and source reproductions](usb-reconfiguration-2026-10-23.md).

A fresh 2 MiB backup precedes the code-only update. Full-flash readback verifies
the installed candidate. Cleanup restores the original code, preserving data
outside the touched code sectors, and verifies that expected full image.
The restoration snapshot differs from the original full backup by exactly 10 bytes: the revision in `boot_out.txt` written when the candidate booted. All eight files remain present, and every other file content is unchanged. The code matches the original exactly; the restore preserved this runtime version-file change instead of overwriting filesystem data. This snapshot was taken before rebooting the restored firmware.
Three radio checks pass on restored `9e153ad624`, the BLE identity remains
unchanged, and all original host driver bindings are restored. The S31/C6
inventory is unchanged with no bridge reboot. Eight host fault controls cover
interrupted writes, failed readback/rollback, image mismatch and preservation.
The adjacent JSON records the byte-range restoration audit; raw flash/disk
images, logs and recovery material remain private.

## Minimal hardware reproduction and limits

On the identified, otherwise idle Pico, close console handles and ensure every
volume is unmounted. Record an uncached disk reference and a working console.
Write `1` to `/sys/bus/usb/devices/<identified-Pico>/bConfigurationValue`, wait
for interfaces, then check CDC and compare two whole-disk reads. Repeat four
times. Capture kernel errors and preserve failures. Compare the same host and
board on the two pinned images, with verified backup/restoration.

The source pair also passes 23 native handler checks; old handlers fail four
checks total. Existing upstream reports remain
[Zephyr #121843](https://github.com/zephyrproject-rtos/zephyr/issues/121843) and
[#122768](https://github.com/zephyrproject-rtos/zephyr/issues/122768).
This bounded comparison does not establish the cause of the earlier idle
failure, long-duration reliability, mounted-file writes, or full S31 composite
capacity. The new firmware was temporary; production rollout remains pending.

A later production attempt reveals an additional intermittent console-close storage stall on both old and candidate builds. [Failure, matched controls and recovery](picow-console-storage-stall-2026-10-23.md). The earlier pass above does not establish reliable closed-console operation.
