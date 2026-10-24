# Remaining hardware availability — 23 October 2026

At 10:05 UTC, sequential inspection of all eight previously off S31 leaf
ports completed and restored every original power state. No active Env Hub
soak or USB/IP import was present; the bridge did not reset. Inspection used
USB enumeration only, without serial access or firmware writes.

The newly powered ports identified a Feather ESP32-S3 with 4 MiB flash and
2 MiB PSRAM, Metro ESP32-S3, Raspberry Pi Debug Probe, Metro M4 AirLift Lite
and two USB UART adapters. Two ports did not enumerate a device during their
15-second observations. Existing devices were Pico 2 W on S31 and Pico W,
the previously runtime-identified Feather ESP32 V2 and the S31 UART on the Pi.
The two downstream UART adapter identities match the previously ROM-identified
C5/C61; this inventory did not repeat ROM access. It identified no C6.

The user will connect the Feather C6 with the JD79667/RTC/SCD41 rig. Current
C6 heavy-import, BLE/AP/HTTP ordering, notification/disconnect and shared-SPI
claims therefore remain pending that actual target. The prepared `ea06`
C6 image is build evidence, not an installed-board result. Identify the
newly attached hardware before choosing or flashing its image.

The controller lists an air-quality strand, including SCD30 and other sensors,
but no SCD41 or RTC model. Those entries describe configuration, not a fresh
physical inventory. Its mux status connection closed without a response and
the topology request timed out. The read-only diagnostic job completed, but
that is **not** a successful mux health check. No routes or sensor registers
were changed. These observations do not establish that the requested rig is
absent elsewhere, or that an SCD30 test substitutes for SCD41 qualification.

Separately, two matched Pico 2 USB-worker-stack diagnostics now build at
`9e153ad624`: 512 and 2048 bytes, with stack initialization, sentinel and
thread-analyzer instrumentation. The resolved Kconfig maps differ only in
`CONFIG_UDC_RPI_PICO_STACK_SIZE`; all source/dependency pins were checked
before and after. At this inventory checkpoint neither diagnostic had been installed. The
[subsequent physical comparison](pico2-usb-stack-comparison-2026-10-23.md)
passed both sizes and restored production exactly.
[Build hashes](firmware-pico2-stack-pair-2026-10-23.json) retain their provenance.

[Sanitized inventory and evidence hashes](farm-hardware-availability-2026-10-23.json).
