#!/usr/bin/env bash
# Profile ImageGen backend availability probes (no full app lifecycle / quit noise).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROF="${TMPDIR:-/tmp}/imagegen_avail.prof"

python -m cProfile -o "$PROF" tools/profile_imagegen_availability.py

echo "Wrote $PROF"
python -c "
import pstats
p = pstats.Stats('$PROF')
p.sort_stats('cumulative').print_stats(30)
p.sort_stats('cumulative').print_stats('imagegen_plugins|pyinstaller_frozen_support', 20)
"
