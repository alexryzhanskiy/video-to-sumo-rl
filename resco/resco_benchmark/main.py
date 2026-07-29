import sys
if r"c:\clinical\resco" in sys.path:
    sys.path.remove(r"c:\clinical\resco")

import pathlib
import os
import multiprocessing as mp

from datetime import datetime
from multi_signal import MultiSignal
import argparse

import resco_benchmark
from resco_benchmark import set_random_seeds, GLOBAL_SEED
from resco_benchmark.config.agent_config import agent_configs
from resco_benchmark.config.map_config import map_configs
from resco_benchmark.config.mdp_config import mdp_configs
import winsound

import sys
print(sys.path)
from resco_benchmark.config import map_config
print(map_config.__file__)

def pretty_beep_sequence():
    try:
        frequencies = [500, 440, 660, 990]   
        durations = [750, 250, 250, 500]  
        # Sequence of 3 beeps
        for freq, dur in zip(frequencies, durations):
            winsound.Beep(freq, dur)
    except Exception as e:
        print(f"An error occurred: {e}")

max_trials = 1   # было 5: main() гонял весь эксперимент 5x с ОДНИМ сидом (дубли). 1 = один прогон.

def main():
    for i in range(1, max_trials + 1):
        # Initialize global random seeds for reproducibility
        set_random_seeds()
        
        ap = argparse.ArgumentParser()
        ap.add_argument("--agent", type=str, default='STOCHASTIC',
                        choices=['STOCHASTIC', 'MAXWAVE', 'MAXPRESSURE', 'IDQN', 'IDQN_pressure', 'IDQNCO2', 'IDQNCO2Multiple', 'IDQNCO2_Occupancy',
                                'IDQN_start_stop',
                                'IPPO', 'MPLight', 'MPLightCO2', 'MPLightCO2Multiple', 'MA2C', 'FMA2C',
                                'MPLightFULL', 'FMA2CFull', 'FMA2CVAL'])
        ap.add_argument("--trials", type=int, default=1)
        ap.add_argument("--eps", type=int, default=100)
        ap.add_argument("--procs", type=int, default=1)
        ap.add_argument("--map", type=str, default='ingolstadt1',
                        choices=['grid4x4', 'arterial4x4', 'ingolstadt1', 'ingolstadt7', 'ingolstadt21',
                                'cologne1', 'cologne3', 'cologne8', '2way_single', '1way_single', '1way_single_uphill',
                                'prybuzka', 'prybuzka_12', 'prybuzka_15'
                                ])
        ap.add_argument("--pwd", type=str, default=os.path.dirname(__file__))
        ap.add_argument("--log_dir", type=str, default=os.path.join(os.path.dirname(os.getcwd()), 'results' + os.sep))
        ap.add_argument("--gui", type=bool, default=False)
        ap.add_argument("--libsumo", type=bool, default=False)
        ap.add_argument("--tr", type=int, default=0)  # Can't multi-thread with libsumo, provide a trial number
        ap.add_argument("--save_freq", type=int, default=100)
        ap.add_argument("--load", type=bool, default=False)
        args = ap.parse_args()

        if not args.log_dir.endswith(os.sep):
            args.log_dir += os.sep

        if args.libsumo and 'LIBSUMO_AS_TRACI' not in os.environ:
            raise EnvironmentError("Set LIBSUMO_AS_TRACI to nonempty value to enable libsumo")

        print('Running', args.agent, 'on', args.map, 'with', args.trials, 'trials and', args.eps, 'episodes each')
        if args.procs == 1 or args.libsumo:
            run_trial(args, args.tr)
        else:
            pool = mp.Pool(processes=args.procs)
            for trial in range(1, args.trials+1):
                pool.apply_async(run_trial, args=(args, trial))
            pool.close()
            pool.join()


def run_trial(args, trial):
    mdp_config = mdp_configs.get(args.agent)
    if mdp_config is not None:
        mdp_map_config = mdp_config.get(args.map)
        if mdp_map_config is not None:
            mdp_config = mdp_map_config
        mdp_configs[args.agent] = mdp_config

    agt_config = agent_configs[args.agent]
    agt_config['save_freq'] = args.save_freq
    agt_config['load'] = args.load
    agt_map_config = agt_config.get(args.map)
    if agt_map_config is not None:
        agt_config = agt_map_config
    alg = agt_config['agent']

    if mdp_config is not None:
        agt_config['mdp'] = mdp_config
        management = agt_config['mdp'].get('management')
        if management is not None:    # Save some time and precompute the reverse mapping
            supervisors = dict()
            for manager in management:
                workers = management[manager]
                for worker in workers:
                    supervisors[worker] = manager
            mdp_config['supervisors'] = supervisors

    
    map_config = map_configs[args.map]
    num_steps_eps = int((map_config['end_time'] - map_config['start_time']) / map_config['step_length'])
    route = map_config['route']
    if route is not None: route = os.path.join(args.pwd, route)
    if args.map == 'grid4x4' or args.map == 'arterial4x4':
        if not os.path.exists(route): raise EnvironmentError("You must decompress environment files defining traffic flow")

    env = MultiSignal(alg.__name__+'-tr'+str(trial),
                      args.map,
                      os.path.join(args.pwd, map_config['net']),
                      agt_config['state'],
                      agt_config['reward'],
                      route=route, step_length=map_config['step_length'], yellow_length=map_config['yellow_length'],
                      step_ratio=map_config['step_ratio'], end_time=map_config['end_time'],
                      max_distance=agt_config['max_distance'], lights=map_config['lights'], gui=args.gui,
                      log_dir=args.log_dir, libsumo=args.libsumo, warmup=map_config['warmup'],
                      seed=GLOBAL_SEED + trial)

    agt_config['episodes'] = int(args.eps * 0.8)    # schedulers decay over 80% of steps
    agt_config['steps'] = agt_config['episodes'] * num_steps_eps
    agt_config['log_dir'] = os.path.join(args.log_dir, env.connection_name)
    agt_config['num_lights'] = len(env.all_ts_ids)

    # Get agent id's, observation shapes, and action sizes from env
    obs_act = dict()
    for key in env.obs_shape:
        obs_act[key] = [env.obs_shape[key], len(env.phases[key]) if key in env.phases else None]
    agent = alg(agt_config, obs_act, args.map, trial)

    start_time = datetime.now()
    print(f'started: {start_time.strftime("%H:%M:%S")}')
    for _ in range(args.eps):
        obs = env.reset()
        done = False
        while not done:
            act = agent.act(obs)
            obs, rew, done, info = env.step(act)
            agent.observe(obs, rew, done, info)
        if hasattr(agent, 'save'):
            agent.save()
    env.close()
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60
    print(f'finished: {end_time.strftime("%H:%M:%S")}, total duration: {duration:.1f} min')
    pretty_beep_sequence()


if __name__ == '__main__':
    main()
