#!/usr/bin/env bash
# Actuated (gap-based) базовий рівень: нативний SUMO з sumo/intersection_act.net.xml.
# 5 сідів × 3 навантаження -> sumo/seeds/act_{10,12,15}_s{1..5}.xml
# Ті самі параметри, що й фікс-база: end=1500, пристрій емісій (CO2), tripinfo.
set -e
cd "$(dirname "$0")/../sumo"
SUMO="C:/Program Files (x86)/Eclipse/Sumo/bin/sumo.exe"
declare -A ROU=( [10]=demand.rou.xml [12]=demand_12.rou.xml [15]=demand_15.rou.xml )
for ld in 10 12 15; do
  for s in 1 2 3 4 5; do
    "$SUMO" -n intersection_act.net.xml -r "${ROU[$ld]}" --end 1500 \
      --tripinfo-output "seeds/act_${ld}_s${s}.xml" --device.emissions.probability 1 \
      --seed $s --no-step-log --duration-log.disable --no-warnings
    echo "act_${ld}_s${s} done"
  done
done
