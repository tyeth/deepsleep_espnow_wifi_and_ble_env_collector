# Certificate installation failure paths

The closed application issue [#25](https://github.com/tyeth/deepsleep_espnow_wifi_and_ble_env_collector/issues/25)
concerns oversized BLE writes. Current protocol checks pass (20 JavaScript groups
and all Python parser/receiver checks). The following separate failure paths are
reproduced on a POSIX host with temporary synthetic files and mocked certificate
expiry. They are not fresh physical CircuitPython filesystem qualification.

```sh
python3 tools/repro_cert_install_failures.py .
```

1. Start with an old chain/key pair. Feed a replacement pair to `Installer`.
   Let chain promotion succeed, then inject `OSError` on key promotion.
   `finish()` returns false but the live chain is new and the live key is old.
   The new key remains as `key.pem.new`. Two individual renames do not make
   the pair atomic, and this error path does not roll back the first rename.
2. Feed an invalid pair through `receive(begin/c/k/end)`. The end command rejects
   it and clears `_rx`. A subsequent `receive(abort)` returns success but has no
   receiver left to clean up: both `.new` files remain. They are not installed
   by an empty later upload because `_got` requires both halves from that upload.

The fixture deliberately mocks validation to isolate promotion in case 1 and
forces validation rejection in case 2. It never reads actual certificates or
modifies device storage. Run it on Linux/WSL: Windows `os.rename` refuses an
existing destination, which stops at the first rename and does not reproduce
the injected second-rename case. A Windows attempt hit that fixture limitation;
the WSL run reproduced both failures.

Expected recovery: a reported installation failure should retain a usable old
pair or expose a recoverable transaction, and rejected uploads should close and
remove their temporary files. A power-loss-safe pair update needs a defined
recovery protocol; adding another rename alone is not sufficient. These findings
are recorded as open application work, not upstream CircuitPython defects.
