# bayes_opt_staged.py
#
# Покрокова оптимізація по типах етапів.
# Порядок кроків:
#   1. morning  — стартує з BASE_VALUES
#   2. evening  — стартує з кращих morning + BASE_VALUES для решти
#   3. grechani — стартує з кращих morning+evening + BASE_VALUES для решти
#   4. all      — стартує з кращих morning+evening+grechani + BASE_VALUES
#   5. random   — стартує з кращих всіх попередніх + BASE_VALUES
#                 random1/2/3/4 завжди мають однакові значення
#
# Між кроками міняти тільки OPTIMIZE_STAGE.

import libsumo  # preload до optuna

import json
import os
import traceback

import optuna
from optuna.samplers import TPESampler

from run_full_scenario import run_full_scenario_with_phases
from sumo_runner import expected_param_count, print_current_phases

# =========================================================
# НАЛАШТУВАННЯ — міняти між кроками
# =========================================================

SEED_NO = 256

# Який тип зараз оптимізуємо:
# "morning" | "evening" | "grechani" | "all" | "random"
OPTIMIZE_STAGE = "random"

WORK_DIR = "sumo_scenario2"

# Затримка перемикання фаз в секундах (0 = точно за розкладом)
SWITCH_DELAY = 0

# =========================================================
# PATHS
# =========================================================

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
BEST_PHASES_FILE = os.path.join(BASE_DIR, "best_phases_staged_scenario2_SWITCHDELAY.json")
HISTORY_FILE     = os.path.join(
    BASE_DIR,
    f"runs_staged_{OPTIMIZE_STAGE}_{SEED_NO}_scenario2_SWITCHDELAY.jsonl"
)

# =========================================================
# OPTIMIZATION SETTINGS
# =========================================================

DIRECTION        = "minimize"
N_TRIALS         = 1000
PATIENCE         = 1000
THRESHOLD        = 0.005  # 0.5%
N_STARTUP_TRIALS = 15

N_PARAMS = expected_param_count()  # 21
BOUNDS   = [(20, 90)] * N_PARAMS

# =========================================================
# БАЗОВІ ЗНАЧЕННЯ — глобальний оптимум всього сценарію
# =========================================================

# BASE_VALUES = [75, 35, 85, 25, 50, 25, 60, 25, 75, 55, 20, 90, 35, 80, 30, 50, 20, 90, 25, 40, 45]
BASE_VALUES = [90, 20, 85, 30, 55, 35, 35, 20, 60, 25, 25, 55, 25, 60, 40, 55, 45, 75, 20, 50, 60]

# Унікальні типи етапів (random — один тип для всіх random1/2/3/4)
STAGE_TYPES = ["morning", "evening", "grechani", "all", "random"]

# Маппінг: назва в сценарії -> тип
STAGE_MAP = {
    "morning":  "morning",
    "evening":  "evening",
    "grechani": "grechani",
    "all":      "all",
    "random1":  "random",
    "random2":  "random",
    "random3":  "random",
    "random4":  "random",
}

# =========================================================
# ЗАВАНТАЖЕННЯ / ЗБЕРЕЖЕННЯ ПОТОЧНИХ НАЙКРАЩИХ ФАЗ
# =========================================================

def load_current_phases() -> dict[str, list[int]]:
    """
    Завантажує поточний стан з файлу.
    Якщо файлу немає — всі типи починають з BASE_VALUES.
    """
    print(BEST_PHASES_FILE)
    if os.path.exists(BEST_PHASES_FILE):
        with open(BEST_PHASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded current phases from {BEST_PHASES_FILE}")
        print(f"Current best CO2: {data['co2']:.2f}")
        print(f"Optimized so far: {data.get('optimized', [])}")
        return data
    else:
        print("best_phases_staged.json not found — starting from BASE_VALUES")
        return {
            "co2": None,
            "optimized": [],
            "phases": {stage: BASE_VALUES[:] for stage in STAGE_TYPES},
        }


def save_current_phases(
    data: dict,
    new_values: list[int],
    new_co2: float,
):
    previous_co2 = data.get("co2")

    # зберігаємо тільки якщо покращилось або це перший запуск
    if previous_co2 is not None and new_co2 >= previous_co2:
        print(f"\n[Save] New CO2 {new_co2:.2f} >= previous {previous_co2:.2f}")
        print(f"[Save] Keeping previous best — NOT overwriting {BEST_PHASES_FILE}")
        return

    data["phases"][OPTIMIZE_STAGE] = new_values
    data["co2"] = new_co2
    if OPTIMIZE_STAGE not in data["optimized"]:
        data["optimized"].append(OPTIMIZE_STAGE)

    with open(BEST_PHASES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    improvement = (
        f" (improved from {previous_co2:.2f})"
        if previous_co2 is not None
        else " (first run)"
    )
    print(f"Saved to {BEST_PHASES_FILE}{improvement}")
    print(f"Optimized stages: {data['optimized']}")


def build_full_phases(
    phases_by_type: dict[str, list[int]],
    override_stage: str,
    override_values: list[int],
) -> dict[str, list[int]]:
    """
    Будує повний словник фаз для run_full_scenario_with_phases.
    override_stage отримує override_values, решта — з phases_by_type.
    random1/2/3/4 завжди беруть значення типу 'random'.
    """
    result = {}
    for scenario_name, stage_type in STAGE_MAP.items():
        if stage_type == override_stage:
            result[scenario_name] = override_values
        else:
            result[scenario_name] = phases_by_type[stage_type]
    return result

# =========================================================
# HISTORY
# =========================================================

def params_key(values: list[int]) -> str:
    return ",".join(map(str, values))


def load_history() -> dict[str, float]:
    history = {}
    if not os.path.exists(HISTORY_FILE):
        return history
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
                history[params_key(row["values"])] = row["score"]
            except Exception:
                pass
    return history


def save_result(values: list[int], score: float):
    row = {"values": values, "score": score}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

# =========================================================
# EARLY STOPPING
# =========================================================

class EarlyStopping:

    def __init__(self, patience: int, threshold: float):
        self.patience   = patience
        self.threshold  = threshold
        self.best       = float("inf")
        self.no_improve = 0

    def update(self, score: float) -> bool:
        relative_improvement = (
            (self.best - score) / abs(self.best)
            if self.best != float("inf")
            else float("inf")
        )
        if relative_improvement > self.threshold:
            self.best       = score
            self.no_improve = 0
            print(f"[EarlyStopping] New best: {self.best:.2f} "
                  f"(improved {relative_improvement*100:.3f}%)")
        else:
            self.no_improve += 1
            print(f"[EarlyStopping] No improvement "
                  f"{self.no_improve}/{self.patience} "
                  f"(best: {self.best:.2f})")
        return self.no_improve >= self.patience

# =========================================================
# OPTUNA HELPERS
# =========================================================

def values_to_params(values: list[int]) -> dict[str, int]:
    return {f"x{i}": values[i] for i in range(len(values))}

# =========================================================
# ТАБЛИЦЯ СВІТЛОФОРІВ
# =========================================================

def print_phases_table(phases_by_type: dict[str, list[int]]) -> None:
    """
    Виводить таблицю: для кожного світлофора — всі фази по кожному типу етапу.
    """
    from sumo_runner import TRAFFIC_LIGHTS

    # заголовок
    col_w     = 10
    type_cols = STAGE_TYPES  # ["morning", "evening", "grechani", "all", "random"]

    header_tls   = f"{'TLS ID':<42}"
    header_phase = f"{'phase':>6}"
    header_types = "".join(f"{t:>{col_w}}" for t in type_cols)
    print("\n" + "=" * (42 + 6 + col_w * len(type_cols)))
    print("TRAFFIC LIGHT PHASES TABLE")
    print("=" * (42 + 6 + col_w * len(type_cols)))
    print(header_tls + header_phase + header_types)
    print("-" * (42 + 6 + col_w * len(type_cols)))

    value_index = 0

    for tls_id, phase_count in TRAFFIC_LIGHTS:
        first_row = True

        for phase_index in range(0, phase_count, 2):
            tls_label   = tls_id if first_row else ""
            phase_label = f"phase[{phase_index}]"
            first_row   = False

            # значення для кожного типу
            type_values = "".join(
                f"{phases_by_type[t][value_index]:>{col_w}}"
                for t in type_cols
            )

            print(f"{tls_label:<42}{phase_label:>6}{type_values}")
            value_index += 1

        print("-" * (42 + 6 + col_w * len(type_cols)))

    print("Columns: " + " | ".join(type_cols))
    print("=" * (42 + 6 + col_w * len(type_cols)) + "\n")

# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 50)
    print(f"STAGED OPTIMIZATION — step: {OPTIMIZE_STAGE}")
    print(f"Seed:         {SEED_NO}")
    print(f"Switch delay: {SWITCH_DELAY}s")
    print(f"History file: {HISTORY_FILE}")
    print("=" * 50)

    # поточний стан всіх фаз
    data           = load_current_phases()
    phases_by_type = data["phases"]

    # стартові значення для поточного етапу
    start_values = phases_by_type[OPTIMIZE_STAGE]
    print(f"\nStart values for [{OPTIMIZE_STAGE}]: {start_values[:7]}...")
    print(f"Fixed stages: "
          f"{[s for s in STAGE_TYPES if s != OPTIMIZE_STAGE]}")

    history = load_history()
    print(f"Loaded history: {len(history)} runs\n")

    early_stopping     = EarlyStopping(patience=PATIENCE, threshold=THRESHOLD)
    simulation_counter = 0

    # =========================================================
    # OBJECTIVE
    # =========================================================

    def objective(trial: optuna.Trial) -> float:
        nonlocal simulation_counter

        values = [
            trial.suggest_int(f"x{i}", BOUNDS[i][0], BOUNDS[i][1], step=5)
            for i in range(N_PARAMS)
        ]

        key = params_key(values)

        if key in history:
            print(f"\nDUPLICATE SKIPPED")
            return history[key]

        # будуємо повний набір фаз для симуляції
        full_phases = build_full_phases(phases_by_type, OPTIMIZE_STAGE, values)

        print(f"\nSTART trial {trial.number} [{OPTIMIZE_STAGE}]")
        print(f"  {OPTIMIZE_STAGE}: {values[:7]}...")

        try:
            score = run_full_scenario_with_phases(
                full_phases,
                sumo_dir=WORK_DIR,
                switch_delay=SWITCH_DELAY,
            )
        except Exception:
            print("SIMULATION FAILED")
            traceback.print_exc()
            raise optuna.exceptions.TrialPruned()

        history[key] = score
        save_result(values, score)
        simulation_counter += 1

        print(f"CO2: {score:.2f}")

        if simulation_counter > N_STARTUP_TRIALS:
            if early_stopping.update(score):
                print(f"\n[EarlyStopping] Stopping.")
                trial.study.stop()
        else:
            print(f"[Startup phase] {simulation_counter}/{N_STARTUP_TRIALS}")

        return score

    # =========================================================
    # STUDY
    # =========================================================

    sampler = TPESampler(seed=SEED_NO, n_startup_trials=N_STARTUP_TRIALS)
    study   = optuna.create_study(direction=DIRECTION, sampler=sampler)

    # завантажити попередні результати в Optuna
    if history:
        print(f"Loading {len(history)} historical runs into Optuna...")
        for h_key, h_score in history.items():
            vals = list(map(int, h_key.split(",")))
            try:
                study.add_trial(
                    optuna.trial.create_trial(
                        params=values_to_params(vals),
                        distributions={
                            f"x{i}": optuna.distributions.IntDistribution(
                                low=BOUNDS[i][0],
                                high=BOUNDS[i][1],
                                step=5,
                            )
                            for i in range(N_PARAMS)
                        },
                        value=h_score,
                    )
                )
            except Exception:
                pass
        print("Done.")

    # стартова точка
    study.enqueue_trial(values_to_params(start_values))

    print("\nCurrent phases before optimization:")
    print_phases_table(phases_by_type)

    study.optimize(objective, n_trials=N_TRIALS)

    best_values = [
        study.best_params[f"x{i}"]
        for i in range(N_PARAMS)
    ]

    print("\n" + "=" * 50)
    print("OPTIMIZATION FINISHED")
    print("=" * 50)
    print(f"Stage:        {OPTIMIZE_STAGE}")
    print(f"Total trials: {len(study.trials)}")
    print(f"Best CO2:     {study.best_value:.2f}")

    # зберегти результат і вивести фінальну таблицю
    save_current_phases(data, best_values, study.best_value)

    # оновити phases_by_type для таблиці
    phases_by_type[OPTIMIZE_STAGE] = best_values
    print("\nUpdated phases after optimization:")
    print_phases_table(phases_by_type)

    # підказка наступного кроку
    remaining = [s for s in STAGE_TYPES if s not in data["optimized"] and s != OPTIMIZE_STAGE]
    if remaining:
        print(f"Next step: set OPTIMIZE_STAGE = '{remaining[0]}' and run again")
    else:
        print("All stages optimized!")


if __name__ == "__main__":
    main()
