# >>> video-to-sumo-rl: prybuzka signal entry
# Append to resco_benchmark/config/signal_config.py (the module defines `signal_configs`).
#
# The action phases are the four green phases of our tlLogic, which RESCO reads straight
# from the network file (a phase counts as green when its state string contains 'g' and
# no 'y'); yellow is inserted by RESCO itself:
#   [1, 7]  = Svobody through (S-S + N-N)
#   [0, 6]  = Svobody left    (S-W + N-E)
#   [4, 10] = Prybuzka through (W-W + E-E)
#   [3, 9]  = Prybuzka left    (W-N + E-S)
# lane_sets map our lane ids (<from>_<to>_<index>, lane 2 = protected left) to movements.
signal_configs['prybuzka'] = {
    'phase_pairs': [[1, 7], [0, 6], [4, 10], [3, 9]],
    'valid_acts': None,
    'nC': {
        'lane_sets': {
            'S-W': ['nS_nC_2'], 'S-S': ['nS_nC_0', 'nS_nC_1'], 'S-E': ['nS_nC_0'],
            'W-N': ['nW_nC_2'], 'W-W': ['nW_nC_0', 'nW_nC_1'], 'W-S': ['nW_nC_0'],
            'N-E': ['nN_nC_2'], 'N-N': ['nN_nC_0', 'nN_nC_1'], 'N-W': ['nN_nC_0'],
            'E-S': ['nE_nC_2'], 'E-E': ['nE_nC_0', 'nE_nC_1'], 'E-N': ['nE_nC_0'],
        },
        'downstream': {'N': None, 'S': None, 'W': None, 'E': None}
    }
}
# The stress maps reuse the same network and signal (identical lane ids).
signal_configs['prybuzka_12'] = signal_configs['prybuzka']
signal_configs['prybuzka_15'] = signal_configs['prybuzka']
# <<< video-to-sumo-rl
