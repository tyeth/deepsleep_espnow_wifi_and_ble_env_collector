# Build results — node/ and collector/ (2026-09-08)

A "build" of this repo is: byte-compile every device source with
`mpy-cross` for a specific CircuitPython, stage each tree's libraries
with `circup --path`, and compile any library that only ships as `.py`.
`tools/build_bundle.sh` does exactly that; this file records one run of it.
No board was involved — nothing below says the code *runs*, only that
CircuitPython will accept it and that every requested library exists.

## Toolchain

| Tool | Version | Source |
|---|---|---|
| mpy-cross | `CircuitPython 10.3.0-alpha.4-73-gf1ae373ad0 on 2026-09-08; mpy-cross emitting mpy v6.3` (x86-64 Linux, dynamically linked) | `gh run download --repo tyeth/circuitpython 34253440312 --name mpy-cross` |
| circup | 3.0.4 (in a venv) | PyPI |
| Adafruit_CircuitPython_Bundle | 20260905, `10.x-mpy` platform | via circup |
| CircuitPython_Community_Bundle | 20260826 | via circup (not actually needed) |
| good-enough-technology/circuitpython_goodenough_bundle | 202311252150 — **no `10mpy` platform**, circup fell back to `.py` | via `circup bundle-add` (SEN5x only) |

The committed `boot_out.txt` files pin circup to CircuitPython
10.3.0-alpha.4; circup notes 10.3.0 final is now released. The bundle
`.mpy` files and this mpy-cross's output carry byte-identical headers
(`43 06 00 1f`), so they target the same mpy format.

## node/ (remote sensor node)

**Compile: 8/8 sources OK, 0 rejected** — battery, calref, code, envproto,
net_ble, node_portal, node_sensors, node_store.

**Libraries: 10/10 requested resolved** (+3 transitive), all as `.mpy`
from the Adafruit bundle:

```
adafruit_ble==10.1.3            adafruit_requests==4.1.17
adafruit_connection_manager==3.1.8  adafruit_scd30==2.3.0
adafruit_httpserver==4.8.2      adafruit_scd4x==1.4.13
adafruit_lc709203f==2.3.10      adafruit_sen6x==1.1.0
adafruit_max1704x==1.1.0        neopixel==6.4.2
adafruit_bus_device==5.2.17  adafruit_pixelbuf==2.1.0  adafruit_register==1.12.1   (deps)
```

SEN5x driver (`sensirion_i2c_sen5x` + `sensirion_i2c_driver`) resolved
from the custom bundle **as source**: that bundle has no `10.x-mpy`
build, so circup installed the `.py` trees. All 22 of those `.py` files
compile with this mpy-cross (0 rejected). circup also warned
`circuitpython_sensirion_i2c_driver is not a known CircuitPython library`
— a dependency-metadata name mismatch inside the custom bundle; harmless,
the dependency was installed under its real name. Resulting `node/lib`:
74 files, 484 KB.

## collector/ (host controller)

**Compile: 15/15 sources OK, 0 rejected** — alerts, battery, boot,
calref, certstore, code, datastore, display_hw, display_ui, envproto,
net_ble, net_captive, net_espnow, net_wifi, sensors_local.

**Libraries: 9/9 requested resolved** (+4 transitive), all `.mpy`:

```
adafruit_ble==10.1.3            adafruit_max1704x==1.1.0
adafruit_display_text==5.0.5    adafruit_ntp==3.4.0
adafruit_httpserver==4.8.2      adafruit_sen6x==1.1.0
adafruit_il0373==2.0.5          adafruit_jd79667==1.0.3
adafruit_lc709203f==2.3.10
adafruit_bitmap_font==2.4.3  adafruit_bus_device==5.2.17  adafruit_register==1.12.1  adafruit_ticks==1.1.7  (deps)
```

Resulting `collector/lib`: 66 files, 332 KB (the 4 `.py` files in it are
empty package `__init__.py` placeholders plus `adafruit_ble/services/microbit.py`; all compile).

Informational: the 5 files in `examples/` and 9 in `tools/` also pass
mpy-cross, though `tools/` is host-side Python and not deployed.

## What this does not cover

* No firmware was flashed and nothing ran on hardware. The runtime
  issues in `bugs_issues_and_todos.md` (C6 hard faults, BLE/AP
  coexistence, ESP-NOW NO_MEM) are unchanged and unverified here.
* mpy-cross checks syntax and the compiler's view of the language only;
  missing board modules (`espnow`, `_bleio`, `alarm`, ...) on a given
  build of CircuitPython would still fail at import time.
* The libraries were resolved against the *latest* bundles, not the
  ones on the bench boards.

## Related CircuitPython fork work (BLE on Raspberry Pi Pico 2 W)

The mpy-cross above comes from CI of branch `zephyr-pico2w-ble` on
`tyeth/circuitpython` ([tyeth/circuitpython#4](https://github.com/tyeth/circuitpython/pull/4)),
which adds a CYW43439 shared-gSPI-bus HCI driver so the Pico 2 W gets
BLE under `ports/zephyr-cp`. It is stacked on
[tyeth/circuitpython#5](https://github.com/tyeth/circuitpython/pull/5)
and needs companion module PRs:
[tyeth/zephyr#1](https://github.com/tyeth/zephyr/pull/1) (stacked on
[tyeth/zephyr#2](https://github.com/tyeth/zephyr/pull/2)),
[tyeth/hal_rpi_pico#1](https://github.com/tyeth/hal_rpi_pico/pull/1) and
[tyeth/hal_rpi_pico#2](https://github.com/tyeth/hal_rpi_pico/pull/2)
(**no single hal_rpi_pico branch builds working firmware — both commits
must be cherry-picked onto one branch**), and
[tyeth/hal_infineon#1](https://github.com/tyeth/hal_infineon/pull/1).

What that CI run ([34253440312](https://github.com/tyeth/circuitpython/actions/runs/34253440312))
actually provides: only the `mpy-cross` artifacts (`mpy-cross`,
`mpy-cross.static`, `mpy-cross.static-aarch64`, `mpy-cross.static-raspbian`,
`mpy-cross.static.exe`, `mpy-cross-macos-arm64`). There is **no Pico 2 W
firmware artifact**; the `.uf2` has to be built locally with
`make BOARD=raspberrypi_rpi_pico2_w_zephyr` in `ports/zephyr-cp`. The
run's overall status is **failure** (its `tests / zephyr` job fails), so
the mpy-cross binaries come from an otherwise-red run.

Relevance to this repo: both examples target ESP32 Feathers and lean on
ESP-NOW, which the Pico 2 W does not have. The Pico 2 W BLE work matters
only for the BLE UART path (`collector/net_ble.py`, `node/net_ble.py`,
`adafruit_ble`), not for the ESP-NOW mesh.
