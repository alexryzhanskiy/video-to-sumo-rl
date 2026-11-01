# >>> video-to-sumo-rl: IDQN_pressure agent
# Append to resco_benchmark/config/agent_config.py (the module defines `agent_configs`
# and already imports `rewards` and `states`).
# Same IDQN hyper-parameters as the stock entry; only the reward differs.
agent_configs['IDQN_pressure'] = {
    'agent': agent_configs['IDQN']['agent'],
    'state': states.drq_norm1,
    'reward': rewards.pressure_norm,
    'max_distance': 200,
    'BATCH_SIZE': 64,
    'GAMMA': 0.99,
    'EPS_START': 1.0,
    'EPS_END': 0.0,
    'EPS_DECAY': 640,
    'TARGET_UPDATE': 500
}
# <<< video-to-sumo-rl
