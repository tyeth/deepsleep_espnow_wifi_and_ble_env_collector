# Pico W Bluetooth error-return checks and failed clean retry

The HAL assertion-removal patch passes three forced error-return checks on a
physical Pico W, but the subsequent unforced Bluetooth startup fatally halts.
This is partial evidence for [HAL Pico #6](https://github.com/tyeth/hal_rpi_pico/issues/6),
not successful retry qualification for [CP #27](https://github.com/tyeth/circuitpython/issues/27).

The [exact pins, hashes and sanitized measurements](picow-bt-startup-failure-2026-10-23.json)
describe the temporary CP 683989 / Zephyr c6200e8 image. The diagnostic disables
automatic BLE file and serial services; supervisor sources remain compiled.
Its first snapshot confirms no prior Bluetooth initialization. No reset occurs
between the three injected failures and the fourth unforced import.

| Forced error return after successful operation | Python errno | Subsequent Wi-Fi scan |
|---|---:|---:|
| Controller ready | EIO (5) | 66 results |
| Buffer initialization | ETIMEDOUT (116) | 67 results |
| Controller awake | ETIMEDOUT (116) | 67 results |

Each one-shot injection is consumed, download cleanup runs, completed-init
count stays zero and host readiness remains false. These are software return
injections after real successful hardware operations, not spontaneous hardware
faults. The fourth import produces no completion snapshot and USB disappears.

Follow-up: [the unfaulted control, isolated ready failure and ready-firmware guard](picow-bt-retry-ready-guard-2026-10-23.md) now distinguish these paths. The failures below remain preserved.

## Fatal location recovered without resetting the board

An independent SWD capture saves RAM, flash and core 0 registers before reset.
Core 1 registers are unavailable. The code bytes match the diagnostic image and
the exact ELF is retained. Core 0 is in `arch_system_halt`, called through the
fatal handler with reason 3 (`K_ERR_KERNEL_OOPS`), and IPSR is 11 (SVC).

The separately captured PSP points to a basic exception frame whose saved PC
is `0x10014e24`. Exact-ELF disassembly places `svc 2` at `0x10014e22`, in the
failure branch of `bt_hci_cmd_send_sync`'s assertion after waiting for command
completion. The function prologue stores the opcode at frame-SP + 4; this
saved slot contains `0x1009`, HCI **Read_BD_ADDR**. The saved caller return
address resolves to `hci_cyw43_setup` immediately after that command call.
This establishes the fatal site; it is not a complete unwound backtrace.

Saved HAL counters are `[4, 3, 0, 5, 0, 179, 4, 1]`: four initialization
attempts, three consumed faults, no armed fault, four download-finish calls,
and one completed transport initialization. Thus the fourth attempt gets past
the injected HAL stages and then fails waiting for the address-read command.
The counters do not contain a saved host-ready Boolean.

The missing HCI completion's cause is still unresolved. In particular, this
does not establish the historical NULL-work-handler mechanism in CP #27.
An unfaulted control with the same workflow-disabled configuration and separate
single-fault retry controls are still needed. Do not turn off the assertion
and claim a fix: command ownership and safe cleanup need investigation.

## Reproduction, failed predecessors and restoration

[Diagnostic patch and target probe](../tools/repro_picow_bt_startup/README.md)
reproduce the exact three modified source files. Applying the patch to copies
of the original files reproduces every recorded diagnostic source hash.

Earlier attempts are preserved separately: automatic workflow initialization
caused the first precondition failure; a host fixture incorrectly assumed
Linux ETIMEDOUT 110 rather than the target's 116; another attempt lost its USB
identity before flashing. None is relabelled as a successful full test.

The failed clean-retry test's automatic restoration could not use the absent
USB console. Host/hub recovery attempts also failed. A separate SWD operation
restored original 9e153 code and padding, verified the complete expected 2 MiB
image, restored host bindings, and passed three Wi-Fi/BLE scans (62/79, 55/78,
49/77). The full image differs from the pretest backup in runtime build-version
metadata; it is not claimed bit-identical. The S31 was unchanged. All these
jobs are terminal and the failure remains a failure despite successful recovery.
Raw RAM, flash and recovery material remain private.
