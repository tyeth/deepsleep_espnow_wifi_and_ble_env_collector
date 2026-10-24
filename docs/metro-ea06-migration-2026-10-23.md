# Metro S3 migration and targeted runtime checks — 23 October 2026

The Metro now runs integration `ea06dcb44e3b953e3b750b28e2e60538d9904fa7`.
The guarded migration finished at 07:48 UTC; runtime checks passed at 07:54 UTC.
This closes the build-only and initial runtime gaps. It does not provide an
overnight soak, TLS, connected GATT, physical sensor/display or filesystem
boundary-write qualification on this revision.

## Recovering the previous files

The original 16 MiB backup remains unchanged. Two short files were extracted
into a restricted private directory using surviving directory entries and
their single data clusters; no FAT-chain reconstruction was required. Both long
filenames passed sequence and checksum validation. The configuration parses as
a JSON object. The boot report matches the earlier USB read after normalizing
six CRLF pairs. The initial raw comparison failed only because that earlier
read normalized line endings. Private configuration contents and their digest
are omitted from this report.

This recovers the two user-facing files observed during the earlier USB
inspection, not the complete original filesystem. Its malformed FAT/boot-sector
cause remains unresolved. The locally inspected SPIFlash implementation maps
logical sectors directly into the FAT partition, with a RAM sector cache;
the exact installed WipperSnapper dependency revision was not established.
That source inspection is not proof of a storage-corruption cause.

## Bounded migration and rollback

The new application exceeds the old 2 MiB slot. The tested migration replaces
the bootloader/partition-table range `0x0..0x9000` and the sector-rounded
application range `0x10000..0x213000`. It retains NVS, OTA selection, TinyUF2
and the old filesystem bytes before first boot. The application is written
first and the bootloader/table last, with no boot between writes.

A fresh verification of all 256 × 64 KiB chunks matched the original backup
exactly. The complete 16 MiB expected result then passed device verification.
Host fault tests cover failures after either write and at final verification,
restoring both ranges and verifying the original image; persistent recovery
failure disables resumption. Wrong layout, OTA selection, image digest,
recovery marker and occupied new-filesystem-region controls are rejected.

CircuitPython's actual build joins its application at `0x10000`. The generic
IDF flasher metadata points at the factory slot and was not used. Both private
backups and all failed diagnostics remain preserved.

## Boot transition and runtime evidence

The first no-reset ROM connection received no serial data. A targeted native
USB reset restored communication, but a strict comparison against the image
before first boot then failed. A subsequent per-chunk comparison captured the
changed data privately and verified every chunk: only the first 64 KiB at
`0x750000` changed. Bootloader, partition table, application, NVS, OTA metadata,
TinyUF2 and the old filesystem prefix still matched the verified result.
The helper cleared forced-download state and requested a watchdog reset.

The board then enumerated with the expected CircuitPython identity and reported
`11.0.0-alpha.2-16-gea06dcb44e-dirty`. Three overlapping Wi-Fi/BLE scan cycles
each found two Wi-Fi networks and respectively 25, 26 and 23 BLE advertisements.
Free GC memory was 8,262,480 bytes after each cycle. This is a bounded scan
check, not a sustained radio-load or connected-GATT result.

## Extended filesystem geometry

The reported 5,969 data clusters initially appeared too large for the new
`user_fs` partition. CircuitPython's extended-storage implementation maps that
partition followed by the inactive OTA slot: 8,896 KiB + 3,072 KiB = 11,968 KiB
(12,255,232 bytes). Reconstructing that logical mapping from the private
post-boot snapshot yields a readable FAT volume with the same geometry.

`mdir` exits 0. `fsck.fat -n` exits 1 because the boot sector has no volume
label while the root directory contains `CIRCUITPY`; it reports no allocation
errors and leaves the image unchanged. No repair was applied. The old
filesystem prefix occupies the reused OTA region and is not protected against
future extended-volume writes; its verified original backup remains private.
The recovered configuration has not been made active CircuitPython configuration.

The original downstream port states and empty import inventory were restored;
no active soak was interrupted. See [structured evidence](metro-ea06-migration-2026-10-23.json)
and the [earlier backup investigation](metro-backup-and-migration-investigation-2026-10-23.md).
