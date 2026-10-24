# Temporary Pico W USB snapshots

Diagnostic instrumentation for [the captured console-close stall](../../docs/picow-console-storage-stall-2026-10-23.md#passive-usb-and-thread-snapshots).
This is not a production fix or a general-purpose module.

Use the exact source pins and binary hashes in the linked JSON evidence.
Append `picow_usb_diag_driver.c` to Zephyr's `drivers/usb/udc/udc_rpi_pico.c`
and `picow_usb_diag_binding.c` to CircuitPython's
`shared-bindings/microcontroller/__init__.c` in a temporary build tree. The latter
must participate in QSTR extraction. Build the Pico W Zephyr target using the
same configuration, including thread monitor, thread entry and stack-info fields.
The source depends on that version's private kernel and driver structures.
Restore both files after building. Keep the matching ELF to resolve thread and
queue addresses; addresses change between builds.

After installing the temporary image with a verified backup/recovery path,
start a raw-REPL program that waits 0.4 seconds, saves 20 calls to
`envhub_usb_diag.snapshot()` in a list separated by `time.sleep(0.3)`, and only
then prints each snapshot as hexadecimal. Keep the host console open for a
control; for the comparison close its actual file handle, start an uncached
4 KiB MSC read, and reopen the console three seconds later. Record read duration
and data hash. Collect the RAM snapshots after reopening. A fast closed run
does not disprove this intermittent fault. Never emit console data during the
sample interval. Repeat open/closed/closed/closed/open, then restore and verify
the original firmware and USB bindings.

The decoder accepts `[{"data_hex": "..."}, ...]` through `summarize()`.
Its strict checks reject invalid lengths/schema, duplicate or absent UDC
threads, and non-increasing timestamps. Run its six controls with:

```sh
python3 -m unittest discover -s tools/repro_picow_usb_snapshot -p 'test_*.py'
```

The accessor copies into static RAM with IRQs locked; Python byte allocation
happens after unlocking. It does not change endpoint state, thread priorities
or request USB transfers. The ~300 ms cadence can miss transitions. Only
endpoint numbers 0 through 3 in both directions are captured, so HID IN 0x84
is outside this schema. No packet payloads or device serials are recorded by
the accessor. Keep raw disk, flash and host USB captures private.
