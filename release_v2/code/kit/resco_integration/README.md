# RESCO modifications as patches

RESCO (https://github.com/Pi-Star-Lab/RESCO) is licensed CC BY-NC-SA 4.0 and is **not redistributed** here. The DRL runs used a RESCO copy that started from a RESCO-CO2 fork of upstream RESCO and was then changed for the frozen evaluation (E3), for E12 and for E13 (every line changed for E12 or E13 is marked `# E12` or `# E13` in the code). This folder rebuilds that copy from upstream RESCO.

| File | What |
|---|---|
| `resco_e13.patch` | Unified diff, upstream RESCO `fc65e91` → the E13 RESCO copy (code under `resco_benchmark/`, without `utils/` and `environments/`) |
| `resco_e12.patch` | The same for the E12 RESCO copy (used by `../e12.py`) |
| `maps_e13.json`, `maps_e12.json` | Every map folder under `resco_benchmark/environments/`: target file, its source in this package (`network/`, `demand/`) and its SHA-256 |
| `apply_to_resco.py` | Applies a patch to an upstream checkout and creates the map folders; with `--kit` it also fills `e13/b7_demand/` and `e13/e14_demand/` |

```bash
git clone -c core.longpaths=true https://github.com/Pi-Star-Lab/RESCO.git code/kit/e13/resco
git -C code/kit/e13/resco checkout fc65e91
python code/kit/resco_integration/apply_to_resco.py --resco code/kit/e13/resco --variant e13 --kit code/kit
```

`--dry-run` shows what would change; a second run reports everything as already in place. The patches are written with LF line endings; the script converts the touched files to LF first, so checkouts made with `core.autocrlf=true` work too.

**Check.** Applied to the upstream files of `fc65e91`, both patches give code identical to the kit's RESCO copies (325 files compared for E13, 147 for E12: every code file outside `utils/`, and every map file by SHA-256).

**What is not patched.** `resco_benchmark/utils/` (plotting scripts and data tables; no run imports them) stays as upstream. The fork's extra files that no run imports (`config/parse_net_xml.py`, `utils/readXML*`, `utils/transform_route_xml.py`, `utils/avg_waitingCount.py`), its CO2 helper scripts outside `resco_benchmark/`, and its `run_batch.cmd` are not included.

**Licence.** The patch files contain context and removed lines of RESCO and are therefore distributed under CC BY-NC-SA 4.0. The added and changed lines are the authors' work and may also be used under MIT.

**Main changes** (see the patches for every line): the Prybuzka maps and signal entry in `config/map_config.py` and `config/signal_config.py`; the rewards and states used (`rewards.py`, `states.py`, `config/agent_config.py`); seeding of each run (`--seed`, SUMO seed 42 + run + episode); explicit checkpoint loading for frozen evaluation (`--ckpt`); the field clearance (`--allred`; from E13 on, all-red only after a change of street); green limits 12–60 s and the field phase order by action masking (`--mode`, `--min_green`, `--max_green`); MPLight's phase input fixed to the green phase index (`--mplight_phase fixed`); tripinfo with unfinished and never-inserted vehicles; per-decision metrics with the green phase.
