# Bounded FAT12 free-sector transaction

Run host controls here with `python -B -m unittest -v`.

`plan(image)` accepts only the deliberately narrow geometry used by the
captured Pico W disk: one MBR FAT partition starting at LBA 1, 512-byte sectors,
one sector per cluster, FAT12, and one or two matching FAT copies. It rejects
out-of-bounds geometry and chooses three non-overlapping pairs of FAT-free data
sectors. It never edits filesystem metadata.

`transact(image, read_all, write_span, check_cdc)` operates through caller-supplied
adapters. `read_all()` must read the entire actual disk without a host cache;
`write_span(lba, bytes)` must perform exact block writes and flush them;
`check_cdc(index)` must raise if the console stops responding. The helper
verifies a fresh preimage, checks the entire expected image after every pattern,
and restores each span in a `finally` block, followed by a whole-disk comparison.
Restoration failure propagates rather than reporting success.

This module does not discover or open hardware. A hardware wrapper must verify
the exact board identity, exclusive access, no running workload, no host mounts,
and read-only CircuitPython filesystem ownership; pause autoreload and preserve
its setting; keep two fresh matching private disk snapshots; and retain failed
write/restoration evidence. Do not substitute a filesystem file for the whole
disk snapshot. No firmware backup or protection is supplied by this module.

See [physical result and limits](../../docs/picow-msc-write-2026-10-23.md).
