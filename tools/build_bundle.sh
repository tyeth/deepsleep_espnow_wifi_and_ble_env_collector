#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# build_bundle.sh - "build" both device trees: byte-compile every source with
# mpy-cross, stage the libraries with circup --path, and compile any .py
# libraries that only ship as source. Nothing here needs a board.
#
#   MPY_CROSS=/path/to/mpy-cross tools/build_bundle.sh
#
# Without MPY_CROSS it downloads Adafruit's static Linux x86-64 mpy-cross for
# CP_VERSION (default 11.0.0-alpha.1; any tag published on S3 works). Set
# MPY_CROSS_RUN instead to take the `mpy-cross` artifact from a
# tyeth/circuitpython Actions run (needs `gh` authenticated, and the artifact
# expires after 90 days). CP 11 still emits mpy v6.3, the same as 10.x, so
# either compiler's output loads on both. circup is used from the venv at
# $VENV (default ./venv), created and populated if missing.
#
# code.py and boot.py are syntax-checked but NOT put in the bundle as .mpy:
# the supervisor only ever runs them as source (see tools/build_mpy.sh).
set -u
cd "$(dirname "$0")/.."
BUILD=${BUILD_DIR:-build}
VENV=${VENV:-venv}
CP_VERSION=${CP_VERSION:-11.0.0-alpha.1}
MPY_CROSS_RUN=${MPY_CROSS_RUN:-}

if [ -z "${MPY_CROSS:-}" ]; then
    if [ -n "$MPY_CROSS_RUN" ]; then
        MPY_CROSS=$BUILD/mpy-cross/run-$MPY_CROSS_RUN/mpy-cross
        if [ ! -x "$MPY_CROSS" ]; then
            mkdir -p "$(dirname "$MPY_CROSS")"
            gh run download --repo tyeth/circuitpython "$MPY_CROSS_RUN" \
                --name mpy-cross --dir "$(dirname "$MPY_CROSS")" || exit 2
        fi
    else
        MPY_CROSS=$BUILD/mpy-cross/mpy-cross-$CP_VERSION
        if [ ! -x "$MPY_CROSS" ]; then
            mkdir -p "$BUILD/mpy-cross"
            curl -fsSL -o "$MPY_CROSS" \
                "https://adafruit-circuit-python.s3.amazonaws.com/bin/mpy-cross/linux-amd64/mpy-cross-linux-amd64-$CP_VERSION.static" \
                || { rm -f "$MPY_CROSS"; exit 2; }
        fi
    fi
    chmod +x "$MPY_CROSS"
    [ -x "$MPY_CROSS" ] || { echo "no mpy-cross at $MPY_CROSS" >&2; exit 2; }
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
        case "$f" in
            node/code.py|node/boot.py|collector/code.py|collector/boot.py)
                # Ship the source; the .mpy is only proof that it compiles.
                mkdir -p "$BUILD/$label" && cp "$f" "$BUILD/$label/"
                out=$BUILD/syntax-only/$f.mpy ;;
        esac
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
