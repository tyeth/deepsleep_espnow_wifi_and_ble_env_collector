# Post-soak firmware rollout — 22 October 2026

The ESP32-C61 DevKit and Feather ESP32 V2 now run ESP integration
`cb5301b6fb9ede7442d84e8aba72baad87430a80`, based on CircuitPython
11.0.0-alpha.2. The C61 runtime check passed at 20:16:47 UTC and the
Feather V2 check at 20:33:16 UTC.

Both transactions took and verified full current-flash recovery backups,
updated the bootloader and application, and verified the unchanged partition
table, NVS, OTA metadata, inactive OTA storage and filesystem before resuming.
The inactive OTA storage is part of each board's extended filesystem and was
preserved. Private backups remain on the bench.

Each running board passed its exact board/version/MAC assertions, fetched the
C5 portal through normal root-bundle and hostname validation with the complete
certificate chain, and rejected an intentionally incorrect hostname with a
certificate-verification failure. These are runtime checks, not new soak passes.

The [completed overnight results](completed-soaks-2026-10-22.md) still apply to
their recorded older C61/Feather images and portal assets. Follow-up soak
qualification of these newly installed images remains pending.

The matching [machine-readable record](post-soak-firmware-rollout-2026-10-22.json)
contains the exact image hashes, timestamps and separate transaction/runtime
job IDs. The adapted Feather transaction passed 16 offline tests covering its
actual old/new images, preserved storage and rollback failures; three runtime
gate tests also passed.

## Remaining physical coverage

All six previously powered-off S31 ports were inspected individually and
restored, without changing the original connected-device inventory. This found
a Pico 2 W, Feather ESP32-S3, Metro ESP32-S3, Metro M4 Airlift Lite and a debug
probe; one port was empty. These USB descriptors establish presence, not an
installed-firmware version or qualification result. The Pico 2 W's subsequent
USB/IP console attempt returned I/O errors before firmware identity could be
read; no Pico 2 W firmware write had been attempted at this report's cutoff.

Later update: [Pico 2 W migration and short-soak result](pico2-followup-2026-10-22.md) records the subsequent verified installation and qualification. The discovery and failed-console observations above retain their original cutoff.

Later update: the [controlled-advertiser Feather follow-up](feather-controlled-followup-2026-10-22.md) passed its complete thirty-minute run. The earlier failed attempt remains preserved.

## Feather ESP32-S3 update at 23:17 UTC

The 4 MB flash / 2 MB PSRAM Feather S3 now runs the `cb5301b6fb` integration.
Its actual banner is `CircuitPython 11.0.0-alpha.2-15-gcb5301b6fb-dirty on
2026-10-22`; the exact candidate SHA-256 is recorded in the JSON. A verified
4 MiB private backup preceded the application-only update. A fresh comparison
against the device and whole-flash verification preserved the bootloader,
partition table, NVS, OTA metadata and existing 960 KiB FAT filesystem.
The nominal TinyUF2 slot was already entirely erased and remains unchanged;
this board does not have a verified TinyUF2 recovery application.

The normal RTS reset left the board in its ROM loader. After another whole-flash
verification, esptool's watchdog reset resumed CircuitPython successfully.
The exact board/revision identity passed, existing filenames remained present,
and three overlapping Wi-Fi/BLE scan cycles found three Wi-Fi networks and
25, 25 and 24 BLE advertisements. Free GC memory was 2,069,056 bytes in each
cycle. This is a short runtime check, not a soak, leak verdict or TLS result.
The original port-off state was restored and the USB/IP import detached.

Fourteen offline plan/rollback checks pass. Earlier refused preflight and
failed RTS-resume evidence remain preserved separately from the successful
transaction and runtime check. Metro S3 qualification remains pending.
