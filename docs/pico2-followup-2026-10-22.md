# Pico 2 W migration and short radio soak — 22 October 2026

Pico 2 W now runs CircuitPython integration `7d4ef1aac72bf322f1bcead966a8d3eac0acb2af` with
Zephyr `7379648278ab49e391af00f1a62ec73387d4c519`, based on 11.0.0-alpha.2. Upstream's
release list still showed alpha.2 as newest when checked at 21:40 UTC.

The native 10.3.1 installation was backed up and verified across all 4 MiB.
Migration updated firmware/settings space and verified that NVM and the
existing filesystem remained byte-for-byte unchanged. Private recovery files
remain on the bench. Running-board identity, concurrent Wi-Fi/BLE scans and
rejection of unsupported extended scanning without losing the original scan
all passed before the follow-up.

The uninterrupted 30-minute radio soak completed 60 cycles in
1800.0 seconds. Every cycle received Wi-Fi and BLE results:
Wi-Fi 16–52, BLE
22–29. The recorder exited successfully;
an independent read of the terminal service, status and complete cycle log
confirmed the pass. The [JSON record](pico2-followup-2026-10-22.json) contains
exact source/image hashes, timestamps and evidence hashes. This is a short
radio result; no Pico 2 W TLS or overnight result is claimed.

## Transport findings

The first attempts encountered USB/IP and S31 enumeration failures. After
bridge recovery and isolation from other leaf devices, the console worked.
An older picotool 2.1.1 also failed to read this RP2350 ROM, while the existing
2.3.1 tool succeeded against the same device. These are separate observations,
not proof of one common cause.

Source inspection found that partial USB interface claims were not unwound.
[Bridge issue #23](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/23)
and [draft fix #24](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/pull/24)
track that defect. [Controller issue #1](https://github.com/tyeth-ai-assisted/sbc-mcu-dut-controller/issues/1)
tracks capacity/recovery handling; [draft fix #2](https://github.com/tyeth-ai-assisted/sbc-mcu-dut-controller/pull/2)
requires observed power transitions before reporting a cold boot. These fixes
were not deployed during this soak and do not remove the hardware channel limit.

## Feather follow-up boundary

The newly installed Feather V2 image's first short follow-up failed after
65 seconds because three consecutive scans received no BLE results. Its failed
evidence is retained. A controlled Pico W advertiser was then heard immediately,
before toggling either radio. A fresh controlled-advertiser follow-up started
at 21:28:41 UTC and is still pending at this report's cutoff. The older
[eight-hour Feather pass](completed-soaks-2026-10-22.md) retains its original
firmware attribution. This report does not replace or relabel either run.

Later update: the [controlled-advertiser Feather follow-up](feather-controlled-followup-2026-10-22.md) passed its complete thirty-minute run. The earlier failed attempt remains preserved.
