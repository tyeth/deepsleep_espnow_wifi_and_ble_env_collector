# Pico 2 W / S31 per-segment timing

A temporary diagnostic on bridge base `bec1d71` reproduces the slow 64 KiB
reads and places their long pauses between the USB host submission call and
the client completion callback. This narrows the investigation; it is not a fix
or proof that either the host or device alone causes the delay.

The same 262,144-byte prefix is read with 4 KiB / 64 KiB / 4 KiB requests in
0.716015 / 25.001545 / 0.715908 seconds. All outputs match and all following
CDC checks pass. Pico 2 W remains on `9e153ad624`. Four successful 64 KiB
network requests match four complete UART groups, each with sixteen successful
4 KiB segments and exactly one host submission attempt per segment.

| USB/IP sequence | Queue to submit sum, us | Submit to callback sum, us | Callback to done sum, us | Last done to reply attempt, us | Reply delivery, seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1785053 | 1756 | 66729 | 996 | 8309 | 0.008135 |
| 1785056 | 1824 | 70888 | 1061 | 8410 | 0.008159 |
| 1785059 | 2383 | 10034347 | 1314 | 7974 | 0.007710 |
| 1785064 | 2634 | 14018808 | 1320 | 7921 | 0.007844 |

In the third request, segments 6–15 each spend 1,000,537–1,000,914 us between
submission and callback. In the fourth, segments 2–15 each spend
1,000,554–1,000,798 us there. Application admission and completion handling
account for only milliseconds in total; delivery after the reply begins takes
under 9 ms. The timestamp interval still includes synchronous submission,
host driver/hardware and device work, and callback dispatch. A timestamp at
submit return and at host completion dispatch would separate these stages.

The capture contains 146 MSC commands, all with successful status wrappers,
zero missing wrappers, zero packet truncation and zero reported kernel drops.
One pending USBmon URB has not been separately classified for this run; target
error completions `-2` (17) and `-108` (1) remain in the evidence. They are not
missing MSC status wrappers. Network captured/received counts differ by two;
that counter difference alone is not proof of lost payload.

The controller transaction finished successfully. Both diagnostic installation
and original-application restoration verified the whole expected 16 MiB image,
then used a watchdog reset and checked API return. Protected runtime data was
retained. Imports were detached and the initial leaf-power topology restored.
The diagnostic is no longer installed. The bounded probe itself made no Pico
firmware or filesystem writes; the outer transaction did write bridge firmware.

Instrumentation logs after the reply and can perturb later requests. Earlier
full-disk failures on original and latest candidate firmware remain failures.
The direct Pico W comparison uses different hardware and cannot assign cause.

[Sanitized measurements](pico2-s31-segment-timing-2026-10-24.json) retain all 64 segment records.
[Instrumentation and reproduction instructions](../tools/repro_s31_segment_timing/README.md)
describe the exact patch, parser and native checks. Raw UART, packet captures
and recovery images remain private.
