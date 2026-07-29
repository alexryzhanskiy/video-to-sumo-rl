c:\
cd c:\clinical\resco\resco_benchmark
rem python main.py --agent IDQN --eps 100 --map 2way_single --procs 1 --libsumo True
rem python main.py --agent IDQNCO2Multiple --eps 100 --map 2way_single --procs 1 --libsumo True
python main.py --agent MPLight --eps 100 --map 2way_single --procs 1 --libsumo True
rem python main.py --agent MAXPRESSURE --eps 100 --map 2way_single --procs 1 --libsumo True