# >>> video-to-sumo-rl: pressure_norm reward
# Append to resco_benchmark/rewards.py.


def pressure_norm(signals):
    # Normalised max-pressure reward (throughput-aware): -queue / number of lanes.
    # For an isolated intersection (no downstream) this reduces to minimising the total
    # queue, which by max-pressure theory maximises throughput under saturation.
    rewards = dict()
    for signal_id in signals:
        q = 0
        for lane in signals[signal_id].lanes:
            q += signals[signal_id].full_observation[lane]['queue']
        rewards[signal_id] = -q / max(1, len(signals[signal_id].lanes))
    return rewards
# <<< video-to-sumo-rl
