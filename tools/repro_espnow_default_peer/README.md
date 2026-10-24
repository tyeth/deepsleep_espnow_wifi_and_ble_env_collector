# ESP-NOW default-peer C reproduction

This standalone ESP-IDF app contains no CircuitPython. Tested on an ESP32-C6
with IDF `29d36039e564db6df505d0582b94b230a17e63f3`.

Source your IDF environment, then build with `idf.py set-target esp32c6`
and `idf.py build`. On a disposable C6 test board, `idf.py -p PORT flash monitor`
installs this diagnostic and its partition table. This replaces existing board
firmware; preserve anything needed before using that command. The farm test
instead used an app-only transaction and restored its verified full backup.

The app waits ten seconds, runs three rounds of broadcast-only, unicast-only
and mixed peer lists, then prints `SEND_START`, all 30 buffered measurements
at 200 ms intervals, and finally `SEND_DONE`. No serial input is needed.
`SEND_RESULT` records contain the ESP-IDF return code, not a delivery acknowledgement. The locally administered
unicast address `02:00:00:00:00:01` is a synthetic test target.

Each round produces ten records: broadcast-only NULL / explicit / NULL;
unicast-only NULL / explicit / NULL; mixed NULL / explicit broadcast /
explicit unicast / NULL. On the tested pin, the six broadcast-only NULL
calls return `ESP_ERR_ESPNOW_NOT_FOUND` (0x3069); the other 24 are accepted.
No actual receiver is needed to reproduce this submission behavior.

Wi-Fi NVS and PHY calibration storage are disabled. USB Serial/JTAG is used
for the polling console. No access point credentials are required. See [results and boundaries](../../docs/c6-espnow-idf-contract-2026-10-23.md).
