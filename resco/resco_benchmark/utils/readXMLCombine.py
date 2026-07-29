import os
import xml.etree.ElementTree as ET
import numpy as np
import sys
from resco_benchmark.config.map_config import map_configs
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import glob

log_dir = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), 'results' + os.sep)
#log_dir = os.path.join(os.path.dirname(os.getcwd()), 'results' + os.sep)

#log_dir = r"C:\Clinical\results\results_010_2way_single\\"

print(f"Log dir: {log_dir}, cwd:'{os.getcwd()}'")
env_base = '..'+os.sep+'environments'+os.sep
names = sorted([folder for folder in next(os.walk(log_dir))[1]])
print(f"Names: {names}")

metrics = ['duration', 'waitingTime', 'CO2_abs', 'waitingCount']
#metrics = ['CO2_abs']

for metric in metrics:
    run_avg = dict()

    for name in names:
        split_name = name.split('-')
        map_name = split_name[2]
        average_per_episode = []

        files = glob.glob(os.path.join(log_dir, name, 'tripinfo_*.xml'))
        count = len(files)
        begins_from = 1

        for i in range(begins_from, count + 1):
            trip_file_name = log_dir+name + os.sep + 'tripinfo_'+str(i)+'.xml'
            if not os.path.exists(trip_file_name):
                print('No '+trip_file_name)
                break
            try:
                tree = ET.parse(trip_file_name)
                root = tree.getroot()
                num_trips, total = 0, 0.0
                last_departure_time = 0
                last_depart_id = ''
                for child in root:
                    try:
                        num_trips += 1
                        
                        if metric == 'CO2_abs':
                            for emission in child:
                                total += float(emission.attrib[metric])
                        else:
                            total += float(child.attrib[metric])
                            
                        if metric == 'timeLoss':
                            total += float(child.attrib['departDelay'])
                            depart_time = float(child.attrib['depart'])
                            if depart_time > last_departure_time:
                                last_departure_time = depart_time
                                last_depart_id = child.attrib['id']
                    except Exception as e:
                        break
                

                if metric == 'timeLoss':    # Calc. departure delays
                    route_file_name = env_base + map_name + os.sep + map_name + '_' + str(i) + '.rou.xml'
                    try:
                        tree = ET.parse(route_file_name)
                    except FileNotFoundError:
                        route_file_name = env_base + map_name + os.sep + map_name + '.rou.xml'
                        tree = ET.parse(route_file_name)
                    root = tree.getroot()
                    last_departure_time = None
                    for child in root:
                        if child.attrib['id'] == last_depart_id:
                            last_departure_time = float(child.attrib['depart'])     # Get the time it was suppose to depart
                    never_departed = []
                    if last_departure_time is None: raise Exception('Wrong trip file')
                    for child in root:
                        if child.tag != 'vehicle': continue
                        depart_time = float(child.attrib['depart'])
                        if depart_time > last_departure_time:
                            never_departed.append(depart_time)
                    never_departed = np.asarray(never_departed)
                    never_departed_delay = np.sum(float(map_configs[map_name]['end_time']) - never_departed)
                    total += never_departed_delay
                    num_trips += len(never_departed)
                    
                average = total / num_trips
                average_per_episode.append(average)
            except ET.ParseError as e:
                break
           
        metricName = ''
        if metric == 'duration':
            metricName = 'Duration'
        elif metric == 'waitingTime':
            metricName = 'Waiting Time'
        elif metric == 'waitingCount':
            metricName = 'Waiting Count'
        elif metric == 'CO2_abs':
            metricName = 'CO2'
        else:
            metricName = 'Not defined'
            
        agentName = split_name[0]
        if 'CO2' in split_name[4]:
            agentName += 'CO2'
            
        run_name = f'Agent: {agentName}.{split_name[4]}.{split_name[5]} | {split_name[2]} | {metricName}'
        average_per_episode = np.asarray(average_per_episode)

        if run_name in run_avg:
            run_avg[run_name].append(average_per_episode)
        else:
            run_avg[run_name] = [average_per_episode]
        
         

    alg_res = []
    alg_name = []
     
    for run_name in run_avg:
        list_runs = run_avg[run_name]
        min_len = min([len(run) for run in list_runs])
        list_runs = [run[:min_len] for run in list_runs]
        avg_delays = np.sum(list_runs, 0)/len(list_runs)
        err = np.std(list_runs, axis=0)

        alg_name.append(run_name)
        alg_res.append(avg_delays)

    alg_labels = ['[25] IDQN',
                  #'[26] IDQN Multiple (prior)',
                  'Ours',
                  '[23] MaxPressure',
                  '[24] MPLight',
                  ]
    alg_ordering = [1,0,2,3]
    colors = ['blue', 'green', 'purple', 'orange']
    plt.title(f'Comparison of {metricName}')
    print(f'Comparison of {metricName}')
    for k, label in enumerate(alg_labels):
        i = alg_ordering[k]
        print(f"label:'{label}, alg:'{alg_name[i]}'")
        if 'yerr' not in alg_name[i]:
            res = alg_res[i]
            x = np.arange(begins_from, begins_from + len(res))
            plt.plot(x, res, label=label, color=colors[k])

    
    # print(f'Comparison of {metricName}')
    # for i in range(len(alg_name)):
    #     print(f"alg:'{alg_name[i]}'")
    #     if 'yerr' not in alg_name[i]:
    #         res = alg_res[i]
    #         x = np.arange(begins_from, begins_from + len(res))
    #         plt.plot(x, res, label=alg_name[i])
    
    plt.xticks(fontsize=16)
    plt.yticks(fontsize=16)
    #plt.legend(fontsize=20)
    plt.legend(fontsize=26)
    plt.grid(True)
    plt.show()

   
