#!/usr/bin/env bash
# Чекаут RESCO и Python задаются через RESCO_DIR и PY; по умолчанию RESCO/ в корне репозитория.
RESCO_DIR="$(cd "${RESCO_DIR:-$(dirname "$0")/../RESCO}" && pwd)"
cd "$RESCO_DIR/resco_benchmark"
export PYTHONPATH="$RESCO_DIR"; export OMP_NUM_THREADS=4
PY="${PY:-python}"
for map in prybuzka prybuzka_12 prybuzka_15; do
  for tr in 1 2 3 4 5; do
    echo ">>> MPLight $map tr$tr START $(date +%H:%M:%S)"
    "$PY" main.py --agent MPLight --map $map --tr $tr --eps 100 --procs 1 >/dev/null 2>&1
    echo ">>> MPLight $map tr$tr DONE  $(date +%H:%M:%S)"
  done
done
echo "ALL MPLIGHT DONE $(date +%H:%M:%S)"
