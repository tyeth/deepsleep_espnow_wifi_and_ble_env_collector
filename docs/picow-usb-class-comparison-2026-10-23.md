# Direct Pico W USB class comparison — 23 October 2026

The short comparison on installed firmware `9e153ad624` passed at 05:33 UTC.
It did **not** reproduce or resolve the earlier USB descriptor/address failure.

| Phase | Duration | Valid serial replies | Uncached storage reads |
|---|---:|---:|---:|
| CDC only; storage and HID drivers unbound | 90 s | 90/90 | 0 |
| CDC plus storage; HID driver unbound | 90 s | 90/90 | 90/90 |
| CDC only again | 90 s | 90/90 | 0 |

Each serial command returned its sequence number, monotonic time and 256-byte
marker. Storage reads used eight 512-byte sectors at changing offsets, direct
I/O and a discarded output buffer: 368,640 requested bytes in total. Read
completion was checked; storage contents were not compared to a reference.
Serial commands and storage reads were interleaved once per second, rather than
run concurrently or at maximum throughput. No storage or firmware writes, USB
reset or power-cycle commands were issued.

The guard verified the device identity, no active soak units or USB/IP imports,
no mounted Pico filesystem and no active serial/block-device reader. A kernel
follower and a per-sample journal started before driver changes. Original CDC,
MSC and HID bindings were restored; cleanup reported no errors. The kernel
capture contains the requested storage/HID rebindings, with no USB reset,
disconnect, descriptor timeout or address failure during the comparison.

The subsequent read-only power snapshot showed the Pico, both external hubs and
both UART adapters set to `power/control=on`, all active. The root hub was set
to `auto` but also active. All six nodes reported zero accumulated runtime
suspend time. The global USB autosuspend default was two seconds, but the
Pico's `on` setting disables automatic runtime suspension for that device.
This snapshot does not establish the settings before the earlier recovery.

Minimal repeat procedure: identify and guard the exact device; record current
interface bindings; unbind only MSC/HID; perform the first serial phase; rebind
MSC and perform the serial/read phase; unbind MSC for the final serial phase;
restore the original drivers in a finally block. Capture the kernel stream and
save every sample before proceeding so the first failing operation is retained.

Remaining limits: idle behavior, repeated enumeration, actual storage writes,
radio/application load and a 512-byte USB worker-stack build were not tested.
The earlier failure and recovery evidence remain valid and unresolved. The
current firmware's separate 1536-byte MSC worker and USB worker must not be
conflated when interpreting stack measurements.

See [machine-readable evidence](picow-usb-class-comparison-2026-10-23.json) and
[the earlier recurrence](picow-idle-usb-recurrence-2026-10-23.md).
