#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# build_bundle.sh - "build" both device trees: byte-compile every source with
# mpy-cross, stage the libraries with circup --path, and compile any .py
# libraries that only ship as source. Nothing here needs a board.
#
#   MPY_CROSS=/path/to/mpy-cross tools/build_bundle.sh
#
# Without MPY_CROSS, and with `gh` authenticated, it fetches the mpy-cross
# artifact from a tyeth/circuitpython Actions run (MPY_CROSS_RUN, default
# 34253440312 = the zephyr-pico2w-ble branch). circup is used from the venv
# at $VENV (default ./venv), created and populated if missing.
set -u
cd "$(dirname "$0")/.."
BUILD=${BUILD_DIR:-build}
VENV=${VENV:-venv}
MPY_CROSS_RUN=${MPY_CROSS_RUN:-34253440312}

if [ -z "${MPY_CROSS:-}" ]; then
    MPY_CROSS=$BUILD/mpy-cross/mpy-cross
    if [ ! -x "$MPY_CROSS" ]; then
        mkdir -p "$BUILD/mpy-cross"
        gh run download --repo tyeth/circuitpython "$MPY_CROSS_RUN" \
            --name mpy-cross --dir "$BUILD/mpy-cross" || exit 2
        chmod +x "$MPY_CROSS"
    fi
fi
echo "mpy-cross: $("$MPY_CROSS" --version)"

[ -x "$VENV/bin/circup" ] || { python3 -m venv "$VENV" && "$VENV/bin/pip" -q install circup; } || exit 2
echo "circup:    $("$VENV/bin/circup" --version)"

rc=0
compile() {  # compile <label> <file...>
    local label=$1; shift
    local n=0 bad=0 f out
    for f in "$@"; do
        n=$((n + 1))
        out=$BUILD/$label/${f#*/}; out=${out%.py}.mpy
        mkdir -p "$(dirname "$out")"
        if ! err=$("$MPY_CROSS" -o "$out" "$f" 2>&1); then
            bad=$((bad + 1)); rc=1
            printf '  REJECTED %s\n%s\n' "$f" "$(sed 's/^/      /' <<<"$err")"
        fi
    done
    printf '%-24s %d compiled, %d rejected\n' "$label:" $((n - bad)) $bad
}

for d in node collector; do
    echo "=== $d ==="
    compile "$d" "$d"/*.py
    "$VENV/bin/circup" --path "$d" install -r "$d/requirements-circup.txt" \
        2>&1 | grep -E "Installed|already installed|WARNING|not a known|Error|problem|Falling" | sed 's/^/  /'
done
# SEN5x nodes: the driver lives in a custom bundle (README -> Install).
"$VENV/bin/circup" bundle-add good-enough-technology/circuitpython_goodenough_bundle >/dev/null 2>&1
"$VENV/bin/circup" --path node install sensirion_i2c_sen5x \
    2>&1 | grep -E "Installed|already installed|WARNING|not a known|Error|problem|Falling" | sed 's/^/  /'

echo "=== source-only libraries (no .mpy in their bundle) ==="
for d in node collector; do
    libs=$(find "$d/lib" -name '*.py' | sort)
    [ -n "$libs" ] && compile "$d-lib" $libs
done
exit $rc
