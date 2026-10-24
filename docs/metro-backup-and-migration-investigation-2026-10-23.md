# Metro S3 backup and migration investigation — 23 October 2026

The full 16 MiB Metro ESP32-S3 flash backup passed at 06:37 UTC. All 256
64 KiB chunks passed the read-protocol digest and a separate device verification.
The private image's SHA-256 is
`72803aa16d14e356b7cdd49c48bd0880bfa2b69092aadb395b2c7519250e8671`.
No flash writes were performed. The guarded operation temporarily entered ROM,
loaded the RAM stub, requested a reset afterwards, detached its USB/IP import
and restored the Metro's original off state and the original downstream
inventory. No active soak was interrupted.

The strict reader uses 512-byte packets with one packet in flight and refuses
short or oversized frames. This extends the earlier 64 KiB prefix proof to the
entire chip. Earlier 4095-versus-4096-byte failures remain preserved. The bridge
now runs `bec1d71`, whereas those earlier failures used older firmware; this is
not a controlled proof that packet size alone fixed them, or that normal
esptool reads are now reliable.

## Current build and incompatible layout

A fresh Metro build of integration commit `ea06dcb44e` passes using ESP-IDF
`29d36039e564db6df505d0582b94b230a17e63f3`. The combined image is 2,172,544 bytes,
SHA-256 `5f8fb1b435e4813ffde4ee4b4231bbf165177637e0bb50f0dd417c3d9aa94f20`.
It was not yet staged or installed at this checkpoint; the subsequent
[migration and runtime verification](metro-ea06-migration-2026-10-23.md) now pass. Existing unrelated checkout changes were
preserved. See [build provenance](firmware-metro-ea06-2026-10-23.json).

The saved partition table passes its MD5 check. The existing application slots
are each 2 MiB; the new application is 2,107,008 bytes, exceeding one by 9,856
bytes. The current integration reserves 3 MiB slots. Its filesystem starts at
`0x750000`, whereas the saved `ffat` partition starts at `0x450000` and occupies
12,255,232 bytes. TinyUF2 stays at `0x410000`. Installation requires an explicit
partition/storage migration and rollback plan; an application-only overwrite
does not fit.

## Saved filesystem does not pass normal FAT checks

Offline inspection found an `MSDOS5.0` marker and plausible FAT16 geometry:
512-byte sectors, four sectors per cluster, one 31-sector FAT, 512 root entries
and 23,936 total sectors, matching the saved partition size. However, bytes
510–511 are erased (`ff ff`), not the usual boot signature. No valid alternative
FAT boot sector was found by the bounded sector scan. The expected IDF
wear-level state locations are erased and do not pass the checked v2 CRC.
These observations alone do not establish the original firmware's storage
mapping or the cause of the malformed view.

`fsck.fat -n` and `mdir` both reject an unmodified partition copy. A separate
diagnostic copy changing only bytes 510–511 to `55 aa` still fails both checks.
`mdir` reports a FAT/media mismatch (`ff/f8`); fsck reports out-of-range
directory cluster values. Thus the missing signature is not the only obstacle
to reading this image as ordinary contiguous FAT. Both commands left each
input copy unchanged, verified by SHA-256. The original full image also remains
unchanged. No repaired image was written to hardware and no files were declared
recovered.

The initial offline tool checks failed before creating copies: first the SSH
PATH omitted the filesystem checker, then mtools was absent. Those attempts
are retained. mtools 4.0.48-1 was downloaded and unpacked privately without a
system installation; diagnostic logs and any private names remain local.

The subsequent [migration report](metro-ea06-migration-2026-10-23.md) records
private file recovery, installation and runtime results. Preserve the
complete original image and failed diagnostics. This result closes the full
backup verification gap, not Metro firmware/runtime qualification or the
broader filesystem-corruption reports.

See [structured evidence](metro-backup-and-migration-investigation-2026-10-23.json).
