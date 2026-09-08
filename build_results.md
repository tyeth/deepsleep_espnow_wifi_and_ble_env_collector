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
BLE under `ports/zephyr-cp`. The whole prerequisite stack is still open:

* [tyeth/circuitpython#4](https://github.com/tyeth/circuitpython/pull/4),
  stacked on [tyeth/circuitpython#5](https://github.com/tyeth/circuitpython/pull/5)
* [tyeth/zephyr#1](https://github.com/tyeth/zephyr/pull/1), stacked on
  [tyeth/zephyr#2](https://github.com/tyeth/zephyr/pull/2)
* [tyeth/hal_rpi_pico#1](https://github.com/tyeth/hal_rpi_pico/pull/1) and
  [tyeth/hal_rpi_pico#2](https://github.com/tyeth/hal_rpi_pico/pull/2) --
  **no single hal_rpi_pico branch builds working firmware; both commits
  must be cherry-picked onto one branch**
* [tyeth/hal_infineon#1](https://github.com/tyeth/hal_infineon/pull/1)

Relevance to this repo: both examples target ESP32 Feathers and lean on
ESP-NOW, which the Pico 2 W does not have. The Pico 2 W BLE work matters
only for the BLE UART path (`collector/net_ble.py`, `node/net_ble.py`,
`adafruit_ble`), not for the ESP-NOW mesh.

### CI assets on tyeth/circuitpython

Two separate Actions runs are involved. Artifacts expire 90 days after
the run (early December 2026).

**1. mpy-cross -- run [34253440312](https://github.com/tyeth/circuitpython/actions/runs/34253440312)**
(the normal `Build CI` workflow on `zephyr-pico2w-ble` @ `f4d3e598`).
Provides only the `mpy-cross` artifacts: `mpy-cross`, `mpy-cross.static`,
`mpy-cross.static-aarch64`, `mpy-cross.static-raspbian`,
`mpy-cross.static.exe`, `mpy-cross-macos-arm64`. It does **not** build
board firmware. The run's overall conclusion is **failure** (its
`tests / zephyr` job fails), so these binaries come from an otherwise-red
run. This is what `tools/build_bundle.sh` downloads by default.

**2. Pico 2 W firmware -- run [34258666665](https://github.com/tyeth/circuitpython/actions/runs/34258666665)**
(the `Build board (custom)` workflow, `.github/workflows/build-board-custom.yml`,
dispatched for board `raspberrypi_rpi_pico2_w_zephyr`, language `en_US`,
version `latest`, on branch `ci/pico2w-ble-assets` @ `f9626482`).

**Status at the time of writing (2026-09-08T17:53Z): `queued`, conclusion empty.**
The run had been dispatched but no runner had picked it up
(`gh run view --repo tyeth/circuitpython 34258666665 --json status,conclusion`
returned `"status":"queued","conclusion":""`, about twelve minutes after it was
created at 17:41Z). So there is **no firmware artifact yet and no pass/fail
result** -- this is a dispatched-but-unfinished run, not a success. This
document is a snapshot; check the run link above for the current state
rather than trusting it. If the run does complete, the artifact to look for
is `raspberrypi_rpi_pico2_w_zephyr-en_US-latest`, containing `firmware.uf2`
and `firmware.elf`; if it fails, there is still no CI-built Pico 2 W
firmware and the `.uf2` has to be built locally with
`make BOARD=raspberrypi_rpi_pico2_w_zephyr` in `ports/zephyr-cp`.

`ci/pico2w-ble-assets` is a **CI-only branch**: it is `zephyr-pico2w-ble`
(the PR #4 branch) plus one commit that does three things --

* adds `tools/board_build_extensions.py` and makes the custom-board
  workflow ask for `firmware.<ext>` targets by name. The zephyr-cp
  Makefile's default goal is the Zephyr ELF, so without this the
  `firmware.*` copies the artifact upload globs for are never produced
  and the upload is empty. (The workflow predates the zephyr-cp port.)
* checks out hal_rpi_pico's `cyw43-driver` submodule during port setup,
  which the CYW43 shared-bus Bluetooth transport needs for the controller
  patchram.
* **repoints `ports/zephyr-cp/zephyr-config/west.yml` at fork branches**:
  `tyeth/zephyr` @ `cyw43-shared-bus-ble`, `tyeth/hal_rpi_pico` @
  `integration-pico2w-ble` (the two hal_rpi_pico PR commits cherry-picked
  onto one branch), `tyeth/hal_infineon` @ `cyw43-shared-bus-ble`.

> **The firmware is BLE-capable only because of that west.yml override.**
> It is marked `CI-ONLY OVERRIDES -- do not merge to main` in the manifest
> and must not be merged; PR tyeth/circuitpython#4 itself does not carry
> it, so building #4 as-is against upstream Zephyr modules gives a Pico 2 W
> build *without* working BLE. The first two changes (the workflow fixes)
> are candidates for a real PR; the third is not.

## Continuous integration (this repo)

`.github/workflows/build-bundle.yml` runs `tools/build_bundle.sh` on
every push to `main`, on pull requests, and on demand, and uploads the
compiled `.mpy` files plus the staged `node/lib` and `collector/lib` as
an artifact (`bundle-<sha>`). It fails if mpy-cross rejects any source or
if circup leaves either `lib/` empty (the script pipes circup through
`grep`, which would otherwise mask a circup error).

It downloads `mpy-cross` from tyeth/circuitpython with `gh run download`,
which needs a token with **Actions: read** on *that* repository -- the
job's own `GITHUB_TOKEN` is scoped to this repo and cannot do it. The
workflow reads a repository secret named **`CP_CI_TOKEN`**, which has to
be created by hand:

1. GitHub -> Settings -> Developer settings -> Fine-grained personal
   access tokens -> Generate new token.
2. Repository access: *Only select repositories* -> `tyeth/circuitpython`.
3. Repository permissions: **Actions: Read-only** (Metadata: Read-only is
   added automatically). Nothing else.
4. In this repo: Settings -> Secrets and variables -> Actions -> New
   repository secret, name `CP_CI_TOKEN`, paste the token.

(A classic PAT works too but needs the whole `repo` scope, which is far
broader; prefer the fine-grained token.) The workflow's own
`permissions:` block is `contents: read` only. Pull requests from forks
do not receive secrets, so the job can only pass for branches in this
repository. On `workflow_dispatch` the run id to take mpy-cross from can
be overridden (`mpy_cross_run`), and an optional `firmware_run` input
re-hosts the Pico 2 W firmware artifact from a `Build board (custom)` run
alongside the bundle -- informational only, the bundle build does not
use it.
