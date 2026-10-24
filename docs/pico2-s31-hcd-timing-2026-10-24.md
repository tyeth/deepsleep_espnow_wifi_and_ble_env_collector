# Pico 2 W / S31 HCD timing

The long 64 KiB-read delay is inside the interval from USB host channel
activation to HCD retirement. Host submission returns promptly and completion
callback dispatch takes tens of microseconds. This narrows the earlier
[segment result](pico2-s31-segment-timing-2026-10-24.md); it does not identify
whether controller scheduling, bus traffic, interrupt handling or device
behavior is responsible. No firmware fix is claimed.

**The original job failed.** The strict network decoder rejects a final 4 KiB
reply header without captured payload. Automatic restoration nevertheless
verified the original bridge application across the full expected 16 MiB,
retained protected runtime data, resumed via watchdog and restored the API and
baseline topology. A separate read-only postflight passes. This is not a
byte-identical pretest full-flash restoration claim.

## Measurements and capture boundary

Three identical 262,144-byte prefix reads (4 KiB / 64 KiB / 4 KiB requests)
finish in 1.066946 / 25.507319 / 0.665900 seconds, each with a subsequent CDC
pass. The four 64 KiB replies occur before the incomplete final response and
are fully present in the capture. Offline strict decoding of that complete
prefix matches all four UART sequences and all 64 successful 4 KiB segments.
The incomplete response is explicitly retained as unqualified; the original
job and strict full-capture decode remain failed.

| Sequence | Submit call sum, us | Submit to activation sum, us | Activation to HCD retirement sum, us | Retirement to callback sum, us | First network reply delay, s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1785832 | 493 | 427 | 65912 | 536 | 0.070932 |
| 1785835 | 409 | 358 | 70149 | 527 | 0.074615 |
| 1785838 | 621 | 492 | 10032829 | 726 | 10.038685 |
| 1785843 | 740 | 572 | 14017723 | 610 | 14.023709 |

The third request's segments 6–15 and fourth request's segments 2–15 each
spend about 1.0004–1.0008 seconds between activation and retirement. All have
one submission attempt, status zero and 4,096 bytes. Complete network reply
delivery takes 8.54–9.01 ms after its first byte.

The final response at stream offset 1,024,638 has sequence 1786048, a complete
48-byte header, advertised length 4,096 and zero captured payload bytes. It
is a separate 4 KiB request. The response stream ends at 1,024,686 bytes.
The offline analysis reports this boundary rather than silently treating it
as success. Its reason remains unresolved. Both captures exit zero with zero
kernel drops; the network received/captured counter difference alone does not
prove packet loss. USBmon records 203 commands with no missing CSWs, but one
pending URB is not separately classified. Original captures stay private.

## Instrumentation and limits

Bridge base `bec1d71e1379e08e279327bdb222b3207456cebe`, IDF
`ce2100de51a4d9a372f26578fd2ee763ca4b1279`, USB dependency base
`a391e1fd7fa6b3a527897a4bfec9d9f51141e014`, mDNS 1.14.0. Four managed USB
component files are intentionally modified. The exact source/artifact hashes,
complete segment records and capture-boundary analysis are in the companion
JSON. Temporary bridge app SHA-256 is
`64964c8b59ffda51f9568ce40f60532da6952ce881c39551692b410fb9e94699`.

Activation is stamped immediately before the HAL activation call; retirement
is stamped after descriptor parsing. These are software observations, not
electrical bus timestamps. Cancellation may lack a retirement stamp; the
decoder rejects incomplete/failed samples. Activation can precede submit
return. Post-reply UART output can perturb following requests.

The diagnostic has no Pico firmware/filesystem writes. It does not qualify
full-disk 64 KiB reads, filesystem writes or the latest Pico candidate, and
does not establish the cause of the separate direct-Pico-W USB issue.
See `tools/repro_s31_hcd_timing` for instrumentation and decoding.
