# Zephyr MSC error propagation — 24 October 2026

CircuitPython [PR #32](https://github.com/tyeth/circuitpython/pull/32), commit
`5f73172d46cd6c49f9b08570fe793bf1d12b7768`, fixes the silent block-write
acknowledgement reported in [#43](https://github.com/tyeth/circuitpython/issues/43).
Both the direct-connected Pico W and the Pico 2 W through S31 USB/IP pass
the before/after SCSI comparison. The Pico 2 test job remains failed because
its subsequent firmware restoration stopped at a USB identity guard; a
separate recovery restored and verified the original firmware.

## Change

The USB disk wrapper now propagates failed reads, writes and capacity queries,
rejects missing media and overflowing/out-of-range requests, and refreshes
FatFs's cached sector only after a successful write that includes that sector.
A write crossing from the reserved region into the FAT/data area marks content
changed. Failed writes release autoreload suspension without treating rejected
data as a successful content write.

The common flash layer still rejects a multi-sector write beginning at the
synthetic MBR. This fix makes the rejection visible; it does not add support
for whole-disk multi-sector restoration starting at LBA 0.

## Actual USB comparison

The host sent the same WRITE(10), LBA 0, eight 512-byte sectors, on installed
`9e153ad624` and candidate `5f73172d46`. Each payload was the disk's existing
first 4 KiB, so even an unexpected successful write would be identical data.
The CDB was `2a000000000000000800`.

| Firmware | SCSI status | Sense | Residual bytes | Whole disk after command |
| --- | --- | --- | ---: | --- |
| Original 9e153 | GOOD (0), incorrectly | None | 0 | Unchanged |
| Candidate 5f731 | CHECK CONDITION (2) | MEDIUM ERROR / WRITE ERROR (03/0c/00) | 4096 | Unchanged |

The candidate also accepts an eight-sector same-data write beginning at LBA 1.
Three disjoint free-sector pattern tests pass at LBAs 43, 47 and 1015, two
sectors each. After each write, an uncached whole-disk read matches only the
expected changed sectors; after each restoration, all 520,704 bytes match the
candidate pretest snapshot. CDC remains usable between checks. Thirteen
candidate whole-disk reads and four baseline reads are retained privately;
their hashes and changed-sector lists are in [the evidence JSON](zephyr-msc-errors-2026-10-24.json).

The candidate disk snapshot/restoration SHA-256 is
`67ee0cd75cc0bab54d70616ecaa44dbd289cba003e053d8af022105093569378`.
A fresh 2 MiB flash backup preceded the temporary firmware installation.
Both installation and original-code restoration matched their complete
expected flash images. Runtime data after the code span was preserved, so
the restored image is **not** bit-identical to the pretest flash snapshot.
Original firmware subsequently passed three Wi-Fi/BLE scans (76/78, 75/74,
83/80), with unchanged BLE identity. Host bindings were restored and the
bridge was not restarted. No recovery remains necessary.

## Pico 2 W physical comparison and separate recovery

On the same `5f73172d46` candidate, the Pico 2 W reproduces the baseline false
GOOD and returns CHECK CONDITION / `03/0c/00` after the fix, with the exact
same CDB and 4096-byte payload. The valid LBA 1 control succeeds. Its FAT12
volume uses two sectors per cluster; the volume is 5104 sectors inside a
5112-sector partition. Three two-sector tests at LBAs 186, 191 and 5102
change only their expected sectors and restore exactly. Four baseline and
13 candidate complete 2,617,856-byte reads use 4096-byte requests. The candidate
disk restores to SHA-256
`7e0a850f00e5d513cb30359e29f041722d7bcd03d32c5f7c36bb61606089947f`.
The middle span crosses a cluster boundary, with both clusters verified free.

The original job **failed after these checks**: while attaching the ROM
bootloader for restoration, the host's USB attribute tuple failed the exact
identity assertion. This was before any restore directory, read or write.
The mismatched tuple was not recorded, so stale sysfs data is a possibility,
not an established cause. Inspection found the expected ROM device, no active
test services and no imports. The bridge had not restarted.

A separate recovery waits for the expected tuple within a bounded interval
and records observations. It restores the original code span, verifies the
complete expected 4 MiB image, and boots `9e153ad624`. Three Wi-Fi/BLE cycles
pass (64/76, 59/71, 57/76) with unchanged BLE identity. Imports are detached,
the original port-off state is restored, and no recovery remains necessary.
Runtime data is preserved: the complete restored image matches its expected
hash `3268e4530429f08d960ab57a5266b484f6eef680ea3618b921b70f9781755e11`,
but is not bit-identical to the pretest backup. The failed original job and
successful recovery remain separate records in the evidence JSON.

This qualifies the storage fix on both boards. It does **not** qualify the
known slow 64 KiB USB/IP read workload, intermittent closed-console stall,
or full Pico 2 hub application. Twelve host geometry controls cover the
free-sector planner's one/two-sector clusters, shorter BPB volume and bounds.

## Native checks and builds

The [actual-source harness](https://github.com/tyeth-ai-assisted/circuitpython/blob/5f73172d46cd6c49f9b08570fe793bf1d12b7768/tools/check_zephyr_msc_io.py)
extracts the real USB wrappers, FatFs read/write adapters and synthetic-MBR
write implementation. It mocks flash, capacity and autoreload and injects
errors. All 28 cases pass under each of two sector-size configurations with
ASan/UBSan: **56/56**. The preceding `0d545efdcf` source fails 34/56, including
an absent-media write crash. This is native fault coverage, not physical
failure injection. One baseline capacity-error pass depends on old uninitialized
state and is not evidence of correct error handling.

Run from the CircuitPython checkout:

```sh
python3 tools/check_zephyr_msc_io.py --circuitpython .
python3 tools/check_zephyr_msc_io.py --circuitpython . --revision 0d545efdcf
```

Fresh normal Pico W and Pico 2 W builds pass with clean, matching pins:
Zephyr `c6200e80ea69`, HAL Pico `de12fc2a0f75`, HAL Infineon `7f93dc606751`.
Automatic Bluetooth workflows remain compiled in; no BT fault hooks are
present. Firmware sizes are 1,252,824 and 1,209,212 bytes respectively.
Eight host transaction tests verify preservation and rollback behavior.
Build warnings remain, including the existing Pico W test-RNG configuration;
this work does not qualify secure entropy.

## Minimal physical reproduction and retained failure

On an unmounted, backed-up CircuitPython disk, pause autoreload and send the
WRITE(10) CDB above with the disk's existing first 4096 bytes through Linux
SG_IO. Inspect SCSI status and sense, rather than only the ioctl return code.
The old wrapper reports GOOD despite the underlying rejection; the fixed
wrapper reports CHECK CONDITION with sense `700003000000000a000000000c0000000000`.
Compare an uncached complete read against the backup afterward. A same-data
LBA 1 control uses CDB `2a000000000100000800` and should report GOOD.

The first hardware job stopped before flashing because the exclusive-access
guard found a temporary block-device owner after the baseline SCSI command.
The post-write read was never performed, so this is **not** a disk mismatch.
Its final full read matched the backup, and autoreload/bindings were restored.
That failed job and traceback are retained. The corrected transaction waits
briefly for exclusive access, records every busy observation, and still refuses
mounted or persistently owned disks. The owner's process identity was not
established; the kernel log records partition rescanning.

This addresses #43's reproduced write acknowledgement. Missing-media and
injected read failures, cache-window edge cases and overflow are native-only
coverage. It does not resolve #42's intermittent closed-console stall, Pico 2
latency through S31, natural radio failures, or sustained application testing.
Both production Picos remain on 9e153 pending those separate rollout checks.
