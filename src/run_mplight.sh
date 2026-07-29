#!/usr/bin/env bash
cd "C:/Work/RESCO/resco_benchmark"
export PYTHONPATH="C:/Work/RESCO"; export OMP_NUM_THREADS=4
PY="C:/Work/RESCO/resco_env/Scripts/python.exe"
for map in prybuzka prybuzka_12 prybuzka_15; do
  for tr in 1 2 3 4 5; do
    echo ">>> MPLight $map tr$tr START $(date +%H:%M:%S)"
    "$PY" main.py --agent MPLight --map $map --tr $tr --eps 100 --procs 1 >/dev/null 2>&1
    echo ">>> MPLight $map tr$tr DONE  $(date +%H:%M:%S)"
  done
done
echo "ALL MPLIGHT DONE $(date +%H:%M:%S)"
