# Pico 2 USB stack comparison — 23 October 2026

Both 512-byte and 2048-byte USB worker stacks passed the same bounded
concurrent CDC, read-only MSC, Wi-Fi and BLE workload on Pico 2 W at
CircuitPython `9e153ad624`. This workload **did not reproduce a 512-byte
stack shortage** and does not establish a need for a universal 2048-byte
default. The downstream production setting is unchanged.

| USB worker allocation | Maximum measured use | Minimum unused | Radio cycles | Exact 4 KiB reads | BLE advertisements |
|---:|---:|---:|---:|---:|---:|
| 2048 | 260 | 1788 | 8 | 147 | 383 |
| 512 | 260 | 252 | 8 | 150 | 384 |

Each cycle started a three-second BLE scan, scanned Wi-Fi while BLE was
active, consumed the advertisements and emitted a numbered 512-byte serial
payload. A separate host worker performed uncached reads at eight offsets,
comparing every chunk byte-for-byte with its pretest reference. The radio
loop ran for at least 60 seconds, followed by 12 seconds for analyzer output.
Storage was unmounted and idle before the workload. No MSC writes occurred.

Both binaries use the same source/dependency pins and resolved configuration
except `CONFIG_UDC_RPI_PICO_STACK_SIZE`. Stack initialization, sentinel and
the ten-second thread analyzer were enabled. The linked `udc_priv_0` object
is at `0x200048e0`; its first member is the USB worker's `struct k_thread`.
This identifies the measured worker independently of the separate MSC worker.
Captured kernel logs contain no matched USB/storage error patterns, and the
console contains no matched stack/fatal diagnostic. Raw logs remain preserved.

## Restoration and failed first attempt

Every firmware write followed a fresh 4 MiB read, changed only the rounded
code span and passed complete flash readback. The original production code
and padding were restored; the final full flash matched the pretest backup
exactly. Production identity and three Wi-Fi/BLE recovery cycles passed.
Imports were detached and no S31 reset was observed. This restoration required
a separate recovery job: the comparison job failed after both workloads
because a bridge USB-inventory GET timed out before ROM entry or restoration
writes. A fresh read-only bridge/idle check passed, then the separate recovery
verified the installed diagnostic hash, restored production and passed the
full-flash/runtime checks. The original comparison job remains recorded as
failed; its two successful workload phases are not an overall job pass.

The first attempt stopped at an immediate storage-user assertion before its
workload; it supplied no stack samples. It also restored production exactly
and passed recovery checks. The utility was present and working, but that
attempt did not capture the owner, so a udev race is not established. The
corrected fixture waits for udev, requires two consecutive idle checks and
records remaining owners without terminating them. It passed both phases.

## Minimal reproduction and limits

Build the pinned firmware twice, changing only the USB worker allocation
between 512 and 2048 bytes and enabling the instrumentation above. Locate
the worker object in each linker map. Back up a dedicated board, verify each
installed image, run the same overlapping radio/serial/read-only-storage
workload and parse the named worker's high-water values. Restore and verify
the original firmware and runtime afterward.

This short fixed-order run does not qualify every execution path, MSC writes,
storage boundaries, long-term stability, or idle USB re-enumeration. It does
not explain the earlier Pico W descriptor/address failures. Keep those
failures separate from this negative stack-overflow result.

[Measured results and provenance](pico2-usb-stack-comparison-2026-10-23.json) ·
[Build hashes](firmware-pico2-stack-pair-2026-10-23.json) ·
[Tracker](https://github.com/tyeth/zephyr/issues/6)
