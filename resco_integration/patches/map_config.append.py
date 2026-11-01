# >>> video-to-sumo-rl: prybuzka map entries
# Append to resco_benchmark/config/map_config.py (the module defines `map_configs`).
# end_time 1500 = the 24.4 min of reconstructed demand; 1800 for the stress loads.
map_configs['prybuzka'] = {               # Prybuzka-Svobody intersection (from video)
    'lights': ['nC'],
    'net': 'environments/prybuzka/intersection.net.xml',
    'route': 'environments/prybuzka/routes/gen',
    'step_length': 5,
    'yellow_length': 3,
    'step_ratio': 1,
    'start_time': 0,
    'end_time': 1500,
    'warmup': 0
}
map_configs['prybuzka_12'] = {            # stress x1.2
    'lights': ['nC'],
    'net': 'environments/prybuzka_12/intersection.net.xml',
    'route': 'environments/prybuzka_12/routes/gen',
    'step_length': 5, 'yellow_length': 3, 'step_ratio': 1,
    'start_time': 0, 'end_time': 1800, 'warmup': 0
}
map_configs['prybuzka_15'] = {            # stress x1.5
    'lights': ['nC'],
    'net': 'environments/prybuzka_15/intersection.net.xml',
    'route': 'environments/prybuzka_15/routes/gen',
    'step_length': 5, 'yellow_length': 3, 'step_ratio': 1,
    'start_time': 0, 'end_time': 1800, 'warmup': 0
}
# <<< video-to-sumo-rl
