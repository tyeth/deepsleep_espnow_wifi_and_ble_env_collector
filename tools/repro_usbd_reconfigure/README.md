# Repeated SET_CONFIGURATION handler control

This extracts and compiles the actual `sreq_set_configuration` function from
the supplied Zephyr source. A host C compiler is required. Dependencies are
observable stubs; this is not a hardware or full-stack USB test.

```sh
python3 check_handler.py /path/to/zephyr/subsys/usb/device_next/usbd_ch9.c
```

At `7379648278ab49e391af00f1a62ec73387d4c519`, 11 cases execute and two fail.
Apply `candidate.patch` in a disposable Zephyr checkout and repeat: all 11 pass.
The patch is a FAILED HARDWARE CANDIDATE, retained as a reproduction artifact.
It preserves the already-unconfigured zero case, but reinitializes the
current nonzero configuration. Error propagation and malformed-request rejection
are checked as well as the normal state transitions. Physical candidate and
matched-control evidence are in `docs/usb-reconfiguration-2026-10-23.md`.

The underlying issue was already reported upstream as
https://github.com/zephyrproject-rtos/zephyr/issues/121843.

## Combined candidate

The configuration-only candidate above fails CDC on the physical Pico 2.
Apply `cdc-cancel-rearm.patch` as well, then run:

```sh
python3 check_cdc_cancel.py /path/to/zephyr/subsys/usb/device_next/class/usbd_cdc_acm.c
```

Twelve cases pass with rearm; the original fails two. Cancellation returns the
buffer before resubmitting RX work. Other errors and normal completion paths
retain their handling. Both patches together passed the four-import Pico 2
hardware comparison; production was restored. No long-term qualification is
claimed. Related upstream report: https://github.com/zephyrproject-rtos/zephyr/issues/122768.
