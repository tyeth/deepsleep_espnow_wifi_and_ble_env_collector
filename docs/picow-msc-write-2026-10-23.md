# Pico W bounded MSC writes — 23 October 2026

The directly attached Pico W running `9e153ad624` passed three raw MSC write,
whole-disk readback, CDC-response and restoration checks. This adds write-path
evidence to the earlier CDC/read-only comparison; it does not explain the
separate idle USB disappearance.

The logical disk is 520,704 bytes. Its MBR contains a partition starting at LBA 1
with 1,016 sectors. The BPB describes FAT12 with 512-byte sectors and clusters,
980 data clusters and 974 free clusters. CircuitPython's root was read-only,
while Linux could write the disk. Nothing was mounted on the host.

Two fresh uncached complete-disk snapshots matched before any write. With the
application paused in raw REPL and autoreload temporarily disabled, the planner
selected only FAT-free data sectors, without changing the FAT or directories:

| Position | Start LBA | Bytes | Result |
|---|---:|---:|---|
| First available two-sector span | 43 | 1,024 | Exact pattern and restoration |
| Across a logical 4 KiB boundary | 47 | 1,024 | Exact pattern and restoration |
| Last two sectors of the disk | 1,015 | 1,024 | Exact pattern and restoration |

Each write used direct block I/O with fsync. After each pattern, the entire
disk matched the expected image, including every untouched byte, and a CDC
arithmetic query passed. Restoration was entered even if the pattern write or
verification failed. After each restoration the whole disk matched the fresh
snapshot. The final SHA-256 was
`18d471d9170495a7fce4958d1b7103f73231a51533bdc365a4f8fb7957736977`,
identical to the initial image. Autoreload was restored to its original enabled
state. The kernel capture contained four partition-rescan messages and no USB
errors. No firmware was written; private disk snapshots remain retained.

Nine host controls pass for the transaction planner and restoration behavior:
successful round trip, partial write, CDC failure, visible restoration failure,
stale preimage, partition bounds, occupied clusters, full disk and unsupported
sector geometry. An initial host test caught overlapping planned spans after
marking the first clusters occupied; selection was corrected before hardware use.
The [transaction helper and controls](../tools/repro_msc_free_sectors/README.md)
are independent of private bench addresses and identities.

This is a bounded raw-sector test, not a mounted-file creation/remount or hard
reset test. No concurrent Wi-Fi/BLE workload was applied. The logical boundary
is not independently proven to coincide with a physical flash erase boundary.
It does not qualify Pico 2 writes, the S31 USB/IP path, broad capacity, or idle
re-enumeration. Those limits remain open.

See [structured evidence](picow-msc-write-2026-10-23.json),
[earlier class comparison](picow-usb-class-comparison-2026-10-23.md) and
[preserved idle failure](picow-idle-usb-recurrence-2026-10-23.md).
