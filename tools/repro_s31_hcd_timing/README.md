# Temporary S31 HCD timing diagnostic

This is instrumentation, not a production fix. On bridge base
`bec1d71e1379e08e279327bdb222b3207456cebe`, first resolve USB dependency
`a391e1fd7fa6b3a527897a4bfec9d9f51141e014` and mDNS 1.14.0, then apply
`bridge-and-usb-timing.patch`. It modifies four managed USB component files
as well as the application. Re-resolving dependencies may overwrite changes;
verify the source hashes in the report before building.

The patch adds q/s/r/a/h/c/d timing for sixteen 4 KiB segments of 64 KiB MSC
IN requests. It changes private URB layout, preserving the public transfer as
the last member. Build all modified component files together. Do not treat
the USB dependency base hash as a clean-component claim.

```sh
python3 -m unittest discover -s tools/repro_s31_hcd_timing -p 'test_*.py'
python3 tools/repro_s31_hcd_timing/decode_s31_hcd_timing.py private-uart.log
```

Only complete successful one-attempt samples qualify. Match sequences to
complete network replies separately. A cancelled pending URB may lack HCD
retirement and must not be interpreted as a zero-time success. Activation can
precede submission return. The native segment harness used a stub timestamp
accessor, so its six passing sanitizer groups do not emulate the HCD.

Use an exclusive bench transaction with fresh full backup, app-only writes,
whole expected-image verification and restoration. This bundle does not
automate flashing. The published run's final network reply was incomplete:
the original job failed, while the four earlier complete replies permit the
explicitly bounded analysis in the report. Never discard that boundary to
claim a passing whole capture. Raw captures and recovery files stay private.
