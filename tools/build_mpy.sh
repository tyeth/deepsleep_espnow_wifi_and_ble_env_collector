#!/bin/bash
# Cross-compile the hub's modules to .mpy.
#
# code.py and boot.py are DELIBERATELY excluded: CircuitPython's supervisor
# looks for code.py/code.txt/main.py/main.txt and boot.py/boot.txt/
# settings.py/settings.txt, and never for a .mpy of either. Compile those
# two and the board has nothing to run and no boot-time USB-drive ownership.
#
# Usage: tools/build_mpy.sh <mpy-cross> <srcdir> <outdir>
set -euo pipefail
MPYX="$1"; SRC="$2"; OUT="$3"
mkdir -p "$OUT"
cd "$SRC"
total_py=0; total_mpy=0
for f in *.py; do
    case "$f" in
        code.py|boot.py) echo "  SKIP   $f (must stay source)"; continue ;;
    esac
    "$MPYX" -o "$OUT/${f%.py}.mpy" "$f"
    py=$(stat -c%s "$f"); mpy=$(stat -c%s "$OUT/${f%.py}.mpy")
    total_py=$((total_py + py)); total_mpy=$((total_mpy + mpy))
    printf "  ok     %-18s %7d -> %7d  (%d%%)\n" "$f" "$py" "$mpy" $((mpy * 100 / py))
done
printf "  TOTAL  %-18s %7d -> %7d  (%d%%)\n" "" "$total_py" "$total_mpy" \
       $((total_mpy * 100 / total_py))
