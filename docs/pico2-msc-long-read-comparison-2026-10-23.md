# Pico 2 full-disk read delays on both firmware revisions

The Pico 2 W independently fails a bounded full-disk MSC read using 64 KiB
requests through the S31 USB/IP bridge on both original `9e153ad624` and latest
normal `0d545efdcf74`. New original-firmware controls below complete two entire
disk reads using 4 KiB requests with identical contents.
The latest image includes Zephyr `c6200e80` (paired USB reconfiguration and CDC
rearming fixes) and HAL Pico `de12fc2a` (Bluetooth ready-state retry guard).
Those changes do not resolve this workload. This does not establish that the
failure shares a cause with [direct Pico W issue #42](https://github.com/tyeth/circuitpython/issues/42).

The host disk is unmounted and has no userspace owner after enumeration settles.
CircuitPython is paused in raw REPL with its root read-only. The serial handle
remains open throughout the reads, unlike the closed-console trigger in #42.
CDC, MSC and HID stay bound. The bridge has three hubs, the tested Pico and one
other enumerated leaf; there are no unrelated imports or active soaks.

| Firmware / capture | First 4 KiB | First 64 KiB | Full 2,617,856-byte disk |
|---|---:|---:|---|
| Original, UART/kernel capture | 0.065 s | 0.165 s | 120 s timeout; 576 KiB retained, process returned after 122.535 s |
| Original, USBmon capture | 0.065 s | 0.165 s | 45 s timeout plus 5 s kill grace; 256 KiB retained |
| Latest candidate, USBmon capture | 0.065 s | 0.166 s | 45 s timeout plus 5 s kill grace; 256 KiB retained |

CDC arithmetic-free print checks pass after both small reads in each test.
The original untraced read had only 192 KiB after about 47 seconds but eventually
retained 576 KiB. It therefore made intermittent progress; no fixed failing LBA
is established. The full-disk failures remain failed jobs.

## Request timing

Original and candidate traces each show 20 MSC commands, 19 successful status
wrappers, and one read still lacking its status when capture ends. Three slow
READ(10) commands each request 65,536 bytes and finish with success and zero
residue. Their durations are respectively 10.051/14.037/14.037 seconds on the
original and 10.050/14.037/14.037 seconds on the candidate. The delay is in the
bulk-IN completion on endpoint 0x83. This rules out treating the full-disk timeout
as a complete lack of progress or as an observed SCSI error response.

The original final capture has 161 packets; the candidate has 115. Both report
zero kernel drops and zero truncated packets. Original capture includes detach;
candidate capture stops before restoration, so pending/cancelled requests at
their ends are not directly comparable. USBmon does not expose the bridge's
individual 4 KiB segments or electrical ACK/NAK timing.

Original bridge UART contains four endpoint-zero STALL messages during
enumeration, before successful small reads, and zero HCD-channel-exhaustion
messages. Neither comparison restarts the bridge. These observations do not
identify which device, bridge, host or interaction owns the defect.

## Firmware and recovery boundaries

The candidate transaction takes a fresh 4 MiB ROM backup, updates only the
1,212,416-byte aligned code span, and verifies the entire expected flash image.
Normal startup retains BLE identity and passes three Wi-Fi/BLE cycles before
the storage workload. Original code is restored afterward with another entire
expected-image verification and three successful radio cycles. Runtime data is
retained; the restored image is **not** byte-identical to the pretest backup.
The initial 64 KiB data also differs between firmware runs; no cross-firmware
filesystem equality or corruption conclusion is claimed.

Imports are detached, the original off state is restored, and bridge uptime
continues. No raw-sector patterns or mounted-file writes were attempted.
The existing write helper assumes different FAT geometry and must not be used
unchanged: this disk has 512-byte sectors, two-sector clusters and one FAT.

An earlier instrumentation attempt reset S31 by explicitly changing DTR/RTS
while opening its log UART. It stopped before Pico access; a separate recovery
restored the recorded topology. That fixture failure is retained separately.
The original USBmon run also failed to stop its capture because its PID file
was root-owned. A separate identity-checked cleanup stopped that process; the
final hash and zero-drop totals above come from the closed capture. Candidate
capture cleanup uses the corrected privileged PID read and completes normally.

## Minimal reproduction

1. Import the identity-verified Pico 2 over USB/IP. Confirm the current firmware
   and matching serial/block devices. Keep all normal interfaces bound.
2. Stop the application in raw REPL and keep the serial handle open. Confirm
   the disk and its partitions are unmounted and unused. Record its capacity.
3. Run `dd if=/dev/<verified-disk> bs=4096 count=1 iflag=direct status=none`,
   saving output privately; check CDC. Repeat with `bs=65536 count=1` and check
   CDC again. Compare the overlapping bytes.
4. Capture that virtual bus with USBmon, then run
   `sudo timeout --signal=TERM --kill-after=5 45 dd if=/dev/<verified-disk> bs=65536 iflag=direct status=none`,
   redirecting stdout to a private file and retaining stderr, exit code, elapsed
   time and partial-file length/hash. This reads the whole disk; do not add
   `count=1` and call that full-disk qualification.
5. Stop only the owned capture process, retain its drop counters, detach the
   owned import and restore the recorded port state. Decode READ(10) submission,
   bulk-IN completion and status-wrapper timestamps.

There is no storage fix, permanent candidate rollout, direct-Pico-2-USB test,
or common-cause claim for Pico W #42. The simultaneous network/USB capture below narrows the delay to before the
first reply arrives. Transfer-size and CDC-activity controls below now narrow
the behavior further. Bridge-side segment/completion timestamps and a direct
USB comparison remain useful next discriminators.
See [structured evidence](pico2-msc-long-read-comparison-2026-10-23.json).

## Simultaneous network and USB timing

A further read-only original-firmware run reproduces the same full-disk failure:
256 KiB retained after the 45-second deadline plus five-second kill grace.
Small reads and their CDC checks pass. Both capture processes stop normally;
imports and original port state are restored without a bridge restart.

The network pcap contains one import session, with 53 data-IN requests of at
least 4 KiB: 46 at 4 KiB, one at 8 KiB, five completed at 64 KiB and one pending
64 KiB request. The three slow 64 KiB requests wait 10.037075, 14.023629 and
14.023845 seconds from the captured request-header first byte to the captured
reply-header first byte. Once that first reply byte arrives, all reply bytes
arrive in 0.009708, 0.009651 and 0.008658 seconds respectively. USBmon independently
records the corresponding bulk-IN completions at about 10.047/14.033/14.033 seconds.

Thus slow delivery of the bulk reply after it begins arriving does not account
for these long delays. The interval before the reply reaches the host remains
unlocalized: outbound request delivery, bridge admission/USB work/completion
queuing, device behavior and related interactions have not been separated.
This is not a blanket exclusion of networking or a bridge/device root-cause claim.

The completion decoder uses the latest of the earliest arrival times of every
byte in the reply, so a late middle byte is handled correctly even if the final
byte arrived earlier. Nine controls cover reassembly, malformed streams and
arrival order. Corrected interval completion equals the original final-byte
timestamp for all 52 completed replies in this capture; no timing changes result.
The pending reply remains pending. A decode PASS does not turn the read job PASS.

USBmon contains 146 packets with zero truncation. The network capture reports
1,785 captured / 1,824 received by filter and zero kernel drops; these counters
are retained distinctly, not treated as 39 missing payload packets. Strict TCP
reassembly found no gaps or conflicting overlaps in the captured session.
Both captures report zero kernel drops. Timings are host-interface observations,
not the times at which a remote application consumed data.

The candidate job's final stderr label says “Normal BLE qualification failed”
because its reused wrapper raises that generic message for any earlier failure.
The actual candidate output and assertions complete all three radio cycles and
set `normal_ble_passed` before entering `qualify_msc`, whose full-read assertion
fails. The stderr is preserved; it does not supersede those per-stage results.

See [timing evidence](pico2-msc-network-timing-2026-10-23.json) and
[decoder with arrival-order controls](../tools/repro_usbip_timing/README.md).


## Transfer-size and console-activity controls

Two further read-only tests on original `9e153ad624` preserve the same topology,
open raw-REPL console and normal interface bindings. No firmware or filesystem
writes are made. Both controller jobs finish PASS: their bounded diagnostic
steps complete, but the long-read slowdown remains unresolved.

| Sequential size-control step | Bytes read | Elapsed | Result |
|---|---:|---:|---|
| Entire disk, `bs=4096` | 2,617,856 | 6.881316 s | Complete |
| Prefix, `bs=65536 count=4` | 262,144 | 24.307075 s | Exact matching prefix |
| Entire disk again, `bs=4096` | 2,617,856 | 6.477851 s | Exact match to first entire disk |

Both entire disk images have SHA-256
`8554756db54eb98a74be479d97aa3ae162e20475cb8927f23e4a781b36479535`.
CDC checks pass after every step. Across the network capture, all 1,320 data-IN
requests of 4 KiB complete with matching lengths and first-reply delays of
5.204–6.430 ms. The four 64 KiB requests have first-reply delays of
0.069872, 0.072969, 10.038891 and 14.024299 seconds. Their full reply delivery
after the first byte takes 9.206–10.540 ms. The 4 KiB success covers every disk
byte; it is not a single-sector or cached-file check (`iflag=direct` is used).
It does not qualify the latest candidate's entire-disk 4 KiB path, writes,
unattended storage use or permanent deployment.

The next test reads the same 256 KiB prefix three times using four 64 KiB
requests per step. Quiet / active-console / quiet durations are 24.310519,
56.259576 and 56.210091 seconds, with identical output each time. The active
step completes 20 raw-REPL `print("CDC_ACTIVITY")` commands without errors.
The driver waits 200 ms after each completed command before starting another;
the observed commands themselves take 1.803170–2.863758 seconds. This is **not**
a successful 5 Hz heartbeat. The reported active-step elapsed time includes
joining that activity thread before the final CDC check.

All four 64 KiB requests in the active step and all four in the following quiet
step wait about 14.02 seconds for their first reply. Periodic console activity
does not remove the slowdown in this control. The first quiet step's two fast
requests are followed by the familiar 10/14-second delays; since the last quiet
step stays slow too, this sequence does not establish that console activity
causes or worsens the delay. The affected component and any relationship to
direct Pico W #42 remain unproven.

All captured MSC commands receive status wrappers: 1,377 in the size control
and 34 in the console control. Both captures report zero kernel drops and
USBmon zero truncation. The size capture also contains one successful status
wrapper 2.102 ms after capture begins whose command is not captured; it is not
counted as an extra completed test command. Its one pending USBmon URB belongs
to the virtual hub's interrupt endpoint, and its 16 pending network requests
are CDC IN receives. All its error completions occur after the last disk read,
during console close/detach. These boundary records are retained rather than
misreported as failed storage reads or packet loss.

Both tests stop their owned captures, detach imports and restore the original
Pico port state without restarting S31. Neither logs HCD channel exhaustion.
Original failed full-disk 64 KiB tests remain failures; these successful
diagnostics do not replace them.

To reproduce the size comparison after the identity, ownership and REPL checks
above, capture USBmon and the complete USB/IP session, then save stdout from
three bounded `dd if=/dev/<verified-disk> iflag=direct status=none` invocations:
`bs=4096`, `bs=65536 count=4`, and `bs=4096`. Use a 60-second timeout with
five-second kill grace, retain partial output on failure, compare full lengths
and bytes, and check CDC after each. For the activity comparison, use three
`bs=65536 count=4` invocations, driving bounded raw-REPL print commands only
during the middle invocation and retaining every command's start/end/output.
Do not label the 256 KiB prefix test a full-disk pass.

See [sanitized sizes, hashes, timing populations and all large requests](pico2-msc-size-cdc-controls-2026-10-23.json).
Full logs, raw captures and disk contents remain private. Smaller agents indexed
the complete saved logs against explicit success/failure markers; the primary
agent reviewed the flagged timing and capture-boundary evidence.


## Direct Pico W timing control

The directly attached Pico W on the same original `9e153ad624` revision reads
its entire 520,704-byte disk using 4 KiB / 64 KiB / 4 KiB requests in
1.117140 / 1.018847 / 1.119596 seconds. All three outputs match, with SHA-256
`18d471d9170495a7fce4958d1b7103f73231a51533bdc365a4f8fb7957736977`,
and each following CDC check passes. This adds command timings to the earlier
successful direct-board geometry/backup checks.

The target's seven 65,536-byte READ(10) commands complete in 0.116170–0.119606
seconds with status zero and no residue; its final partial large read requests
57,856 bytes and completes in 0.105618 seconds. All 298 captured target MSC
commands have successful status wrappers. The whole-bus capture has 1,853
packets, zero kernel drops, zero truncation and no pending URBs. Its 17 target
error completions are retained as `-2`; they are not missing or failed MSC
status wrappers. No 10–14-second READ(10) pause occurs in this control.

The serial console remains open in raw REPL throughout the disk reads. This
does not contradict the intermittent closed-console Pico W issue #42.
Pico W differs from Pico 2 in MCU, transport and disk geometry, so the comparison
does not isolate S31 as the cause. A same-device direct-Pico-2 comparison or
bridge-side segment admission/completion timings are still needed. Bindings
remain unchanged, S31 remains untouched, and no firmware or filesystem writes
are made. [Sanitized direct-board timing evidence](picow-direct-msc-size-timing-2026-10-23.json).
