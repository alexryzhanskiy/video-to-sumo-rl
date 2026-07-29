import traci
import copy
import re
from resco_benchmark.config.signal_config import signal_configs
from resco_benchmark.config.map_config import map_configs
import logging
# Module logger for hill/grade diagnostics
_logger = logging.getLogger(__name__)

_STOP_SPEED_EPS = 0.1                  # m/s threshold to consider a vehicle as 'stopped'

def create_yellows(phases, yellow_length):
    new_phases = copy.copy(phases)
    yellow_dict = {}    # current phase + next phase keyed to corresponding yellow phase index
    # Automatically create yellow phases, traci will report missing phases as it assumes execution by index order
    for i in range(0, len(phases)):
        for j in range(0, len(phases)):
            if i != j:
                need_yellow, yellow_str = False, ''
                for sig_idx in range(len(phases[i].state)):
                    if (phases[i].state[sig_idx] == 'G' or phases[i].state[sig_idx] == 'g') and (phases[j].state[sig_idx] == 'r' or phases[j].state[sig_idx] == 's'):
                        need_yellow = True
                        yellow_str += 'y'
                    else:
                        yellow_str += phases[i].state[sig_idx]
                if need_yellow:  # If a yellow is required
                    new_phases.append(traci.trafficlight.Phase(yellow_length, yellow_str))
                    yellow_dict[str(i) + '_' + str(j)] = len(new_phases) - 1  # The index of the yellow phase in SUMO
    return new_phases, yellow_dict


class Signal:
    def __init__(self, map_name, sumo, id, yellow_length, phases):
        self.sumo = sumo
        self.id = id
        self.yellow_time = yellow_length
        self.next_phase = 0

        self.map_config = map_configs.get(map_name, None) or {}
        self.lane_grade = {}
       
        self.links = self.sumo.trafficlight.getControlledLinks(self.id)
        lanes = []

        #for i, link in enumerate(links):
        #    link = link[0]  # unpack so link[0] is inbound, link[1] outbound
        #    if link[0] not in lanes: lanes.append(link[0])
        #print(self.id, lanes)

        # Unique lanes
        self.lanes = []
        self.outbound_lanes = []

        reversed_directions = {'N': 'S', 'E': 'W', 'S': 'N', 'W': 'E'}

        # Group of lanes constituting a direction of traffic
        myconfig = signal_configs[map_name]
        if self.id in myconfig:
            self.lane_sets = myconfig[self.id]['lane_sets']
            self.lane_sets_outbound = self.lane_sets.copy()
            for key in self.lane_sets_outbound:     # Remove values from copy
                self.lane_sets_outbound[key] = []
            self.downstream = myconfig[self.id]['downstream']

            self.inbounds_fr_direction = dict()
            for direction in self.lane_sets:
                for lane in self.lane_sets[direction]:
                    inbound_to_direction = direction.split('-')[0]
                    inbound_fr_direction = reversed_directions[inbound_to_direction]
                    if inbound_fr_direction in self.inbounds_fr_direction:
                        dir_lanes = self.inbounds_fr_direction[inbound_fr_direction]
                        if lane not in dir_lanes:
                            dir_lanes.append(lane)
                    else:
                        self.inbounds_fr_direction[inbound_fr_direction] = [lane]
                    if lane not in self.lanes: self.lanes.append(lane)

            # Populate outbound lane information
            self.out_lane_to_signalid = dict()
            for direction in self.downstream:
                dwn_signal = self.downstream[direction]
                if dwn_signal is not None:  # A downstream intersection exists
                    dwn_lane_sets = myconfig[dwn_signal]['lane_sets']    # Get downstream signal's lanes
                    for key in dwn_lane_sets:   # Find all inbound lanes from upstream
                        if key.split('-')[0] == direction:    # Downstream direction matches
                            dwn_lane_set = dwn_lane_sets[key]
                            if dwn_lane_set is None: raise Exception('Invalid signal config')
                            for lane in dwn_lane_set:
                                if lane not in self.outbound_lanes: self.outbound_lanes.append(lane)
                                self.out_lane_to_signalid[lane] = dwn_signal
                                for selfkey in self.lane_sets:
                                    if selfkey.split('-')[1] == key.split('-')[0]:    # Out dir. matches dwnstrm in dir.
                                        self.lane_sets_outbound[selfkey] += dwn_lane_set
            for key in self.lane_sets_outbound:  # Remove duplicates
                self.lane_sets_outbound[key] = list(set(self.lane_sets_outbound[key]))
        else:
            self.generate_config()

        self.waiting_times = dict()     # SUMO's WaitingTime and AccumulatedWaiting are both wrong for multiple signals

        self.phases, self.yellow_dict = create_yellows(phases, yellow_length)

        # logic = self.sumo.trafficlight.Logic(id, 0, 0, phases=self.phases) # not compatible with libsumo
        programs = self.sumo.trafficlight.getAllProgramLogics(self.id)
        logic = programs[0]
        logic.type = 0
        logic.phases = self.phases
        self.sumo.trafficlight.setProgramLogic(self.id, logic)

        self.signals = None     # Used to allow signal sharing
        self.full_observation = None
        self.last_step_vehicles = None

        # Track per-vehicle stopped state for start/stop transition detection
        self.prev_vehicle_stopped = dict()   # vehicle_id -> bool (was stopped last step?)

        # Hill-aware maps and precomputed grades
        
        self.lane_direction_map = {}
        if hasattr(self, 'inbounds_fr_direction'):
            for dir_letter, lanes in self.inbounds_fr_direction.items():
                for lane in lanes:
                    self.lane_direction_map[lane] = dir_letter
        if self.map_config.get('enable_grade', False) == True:
            self._compute_lane_grades()

    def generate_config(self):
        print('GENERATING CONFIG')
        # TODO raise Exception('Invalid signal config')
        index_to_movement = {0: 'S-W', 1: 'S-S', 2: 'S-E', 3: 'W-N', 4: 'W-W', 5: 'W-S', 6: 'N-E',
                             7: 'N-N', 8: 'N-W', 9: 'E-S', 10: 'E-E', 11: 'E-N'}
        self.lane_sets = {}
        for idx, movement in index_to_movement.items():
            self.lane_sets[movement] = []
        self.lane_sets_outbound = {}
        self.downstream = {'N': None, 'E': None, 'S': None, 'W': None}

        links = self.sumo.trafficlight.getControlledLinks(self.id)
        #print(self.id, links)
        for i, link in enumerate(links):
            link = link[0]  # unpack so link[0] is inbound, link[1] outbound
            if link[0] not in self.lanes: self.lanes.append(link[0])
            # Group of lanes constituting a direction of traffic
            if i % 3 == 0:
                index = int(i/3)
                self.lane_sets[index_to_movement[index]].append(link[0])
        #print(self.id, self.lane_sets)
        """split = self.lane_sets['S-W'][0].split('_')[0]
        if 'np' not in split: self.downstream['N'] = split
        split = self.lane_sets['W-N'][0].split('_')[0]
        if 'np' not in split: self.downstream['E'] = split
        split = self.lane_sets['N-E'][0].split('_')[0]
        if 'np' not in split: self.downstream['S'] = split
        split = self.lane_sets['E-S'][0].split('_')[0]
        if 'np' not in split: self.downstream['W'] = split"""
        lane = self.lane_sets['S-S'][0]
        fr_sig = re.findall('[a-zA-Z]+[0-9]+', lane)[0]
        fringes, isfringe = ['top', 'right', 'left', 'bottom'], False
        for fringe in fringes:
            if fringe in fr_sig: isfringe = True
        if not isfringe: self.downstream['N'] = fr_sig

        lane = self.lane_sets['N-N'][0]
        fr_sig = re.findall('[a-zA-Z]+[0-9]+', lane)[0]
        fringes, isfringe = ['top', 'right', 'left', 'bottom'], False
        for fringe in fringes:
            if fringe in fr_sig: isfringe = True
        if not isfringe: self.downstream['S'] = fr_sig

        lane = self.lane_sets['W-W'][0]
        fr_sig = re.findall('[a-zA-Z]+[0-9]+', lane)[0]
        fringes, isfringe = ['top', 'right', 'left', 'bottom'], False
        for fringe in fringes:
            if fringe in fr_sig: isfringe = True
        if not isfringe: self.downstream['E'] = fr_sig

        lane = self.lane_sets['E-E'][0]
        fr_sig = re.findall('[a-zA-Z]+[0-9]+', lane)[0]
        fringes, isfringe = ['top', 'right', 'left', 'bottom'], False
        for fringe in fringes:
            if fringe in fr_sig: isfringe = True
        if not isfringe: self.downstream['W'] = fr_sig
        print("'"+self.id+"'"+": {")
        print("'lane_sets':"+str(self.lane_sets)+',')
        print("'downstream':"+str(self.downstream)+'},')

        # print(self.id)
        # print(self.sumo.trafficlight.getControlledLinks(self.id))
        # print(self.lanes)
        # print(self.outbound_lanes)
        # print(self.lane_sets_outbound)

    @property
    def phase(self):
        return self.sumo.trafficlight.getPhase(self.id)

    def prep_phase(self, new_phase):
        if self.phase == new_phase:
            self.next_phase = self.phase
        else:
            self.next_phase = new_phase
            key = str(self.phase) + '_' + str(new_phase)
            if key in self.yellow_dict:
                yel_idx = self.yellow_dict[key]
                self.sumo.trafficlight.setPhase(self.id, yel_idx)  # turns yellow

    def set_phase(self):
        self.sumo.trafficlight.setPhase(self.id, int(self.next_phase))

    def observe(self, step_length, distance):
        full_observation = dict()
        all_vehicles = set()
        for lane in self.lanes:
            vehicles = []
            lane_measures = {'queue': 0, 'approach': 0, 'total_wait': 0, 'max_wait': 0, 'total_co2': 0, 'alpha': 0, 
                             "awg_speed": 0, "total_mass":0,
                             "vehicles": [], "grade": 0, 
                             "vehicles_started": 0, "vehicles_stopped": 0,"uphill_started_count": 0, "uphill_stopped_count": 0}
            lane_vehicles = self.get_vehicles(lane, distance)
            
            lane_length = self.sumo.lane.getLength(lane)
            
            total_speed = 0
            total_mass = 0
            alpha = 0
            grade_percent = 0.0
            dir_letter=None
            if self.map_config.get('enable_grade', False):
                base_grade = self.lane_grade.get(lane, 0.0)
                dir_letter = self.lane_direction_map.get(lane)
                if dir_letter in self.map_config.get('uphill_enabled_directions', ['N']):
                    grade_percent = base_grade #if base_grade > 0 else 0.0
                else:
                    grade_percent = 0.0
            for vehicle in lane_vehicles:
                all_vehicles.add(vehicle)
                # Update waiting time
                if vehicle in self.waiting_times:
                    self.waiting_times[vehicle] += step_length
                elif self.sumo.vehicle.getWaitingTime(vehicle) > 0:  # Vehicle stopped here, add it
                    self.waiting_times[vehicle] = self.sumo.vehicle.getWaitingTime(vehicle)

                vehicle_measures = dict()
                vehicle_measures['id'] = vehicle
                vehicle_measures['wait'] = self.waiting_times[vehicle] if vehicle in self.waiting_times else 0
                vehicle_measures['speed'] = self.sumo.vehicle.getSpeed(vehicle)
                vehicle_measures['acceleration'] = self.sumo.vehicle.getAcceleration(vehicle)
                vehicle_measures['position'] = self.sumo.vehicle.getLanePosition(vehicle)
                vehicle_measures['type'] = self.sumo.vehicle.getTypeID(vehicle)
                vehicle_measures['co2'] = self.sumo.vehicle.getCO2Emission(vehicle)
                vehicle_measures['alpha'] = self.sumo.vehicle.getAngle(vehicle)
                vehicle_measures['mass'] = self.sumo.vehicle.getMass(vehicle)
                vehicle_measures['relative_position'] = self.get_vehicle_relative_index(lane_length, vehicle_measures, distance)
                
                # Calculate start/stop transitions for this vehicle (for ALL lanes, not just uphill)
                current_stopped = (vehicle_measures['speed'] <= _STOP_SPEED_EPS)
                prev_stopped = self.prev_vehicle_stopped.get(vehicle, current_stopped)  # Default to current state if new vehicle
                
                # Track transitions: stopped->moving = start, moving->stopped = stop
                if prev_stopped and not current_stopped:
                    lane_measures['vehicles_started'] += 1
                    vehicle_measures['transition'] = 'started'
                elif (not prev_stopped) and current_stopped:
                    lane_measures['vehicles_stopped'] += 1
                    vehicle_measures['transition'] = 'stopped'
                else:
                    vehicle_measures['transition'] = 'no_change'
                
                self.prev_vehicle_stopped[vehicle] = current_stopped

                if dir_letter != None:
                    lane_measures['uphill_started_count']  = lane_measures['vehicles_started']
                    lane_measures['uphill_stopped_count'] = lane_measures['vehicles_stopped']                    
                
                total_speed += vehicle_measures['speed']
                total_mass += vehicle_measures['mass'] / 1000
                alpha += vehicle_measures['alpha']

                if vehicle_measures['co2'] > 0:
                    lane_measures['total_co2'] = lane_measures['total_co2'] + vehicle_measures['co2']
                if vehicle_measures['wait'] > 0:
                    lane_measures['total_wait'] = lane_measures['total_wait'] + vehicle_measures['wait']
                    lane_measures['queue'] = lane_measures['queue'] + 1
                    if vehicle_measures['wait'] > lane_measures['max_wait']:
                        lane_measures['max_wait'] = vehicle_measures['wait']
                else:
                    lane_measures['approach'] = lane_measures['approach'] + 1  
                    
                vehicles.append(vehicle_measures)


            lane_measures['vehicles'] = vehicles
            lane_measures['total_co2'] = round(lane_measures['total_co2'], 1)

            lane_measures['awg_speed'] = total_speed / len(lane_vehicles) if lane_vehicles else 0
            lane_measures['total_mass'] = total_mass
            lane_measures['alpha'] = alpha / len(lane_vehicles) if lane_vehicles else 0
            lane_measures['grade'] = grade_percent

            full_observation[lane] = lane_measures

        full_observation['num_vehicles'] = all_vehicles
        if self.last_step_vehicles is None:
            full_observation['arrivals'] = full_observation['num_vehicles']
            full_observation['departures'] = set()
        else:
            full_observation['arrivals'] = all_vehicles.difference(self.last_step_vehicles)
            departs = self.last_step_vehicles.difference(all_vehicles)
            full_observation['departures'] = departs
            # Clear departures from waiting times
            for vehicle in departs:
                if vehicle in self.waiting_times: 
                    self.waiting_times.pop(vehicle)
                if vehicle in self.prev_vehicle_stopped: 
                    self.prev_vehicle_stopped.pop(vehicle)

        self.last_step_vehicles = all_vehicles
        self.full_observation = full_observation

    # Remove undetectable vehicles from lane
    def get_vehicles(self, lane, max_distance):
        detectable = []
        for vehicle in self.sumo.lane.getLastStepVehicleIDs(lane):
            path = self.sumo.vehicle.getNextTLS(vehicle)
            if len(path) > 0:
                next_light = path[0]
                distance = next_light[2]
                if distance <= max_distance:  # Detectors have a max range
                    detectable.append(vehicle)
        return detectable

    def get_vehicle_distance_to_signal(self, vehicle_id):
        lane_id = traci.vehicle.getLaneID(vehicle_id)
        vehicle_pos = traci.vehicle.getLanePosition(vehicle_id)
        lane_length = traci.lane.getLength(lane_id)
        distance = lane_length - vehicle_pos  # distance from vehicle to the stop line
        return distance
    
    def get_vehicle_relative_index(self, lane_length, vehicle_obj, max_distance=100):         
        vehicle_pos = vehicle_obj['position']
        #lane_length = self.sumo.lane.getLength(lane_id)
        distance_to_stop = lane_length - vehicle_pos

        # Clamp distance to not exceed max_length
        clamped_distance = min(distance_to_stop, max_distance)

        # Calculate bucket index from 0 to 10
        relative_index = int((clamped_distance / max_distance) * 10)

        return relative_index

    def _compute_lane_grades(self):
        sample_len = float(self.map_config.get('grade_sample_length_m', 50.0))
        

        # Guard: if convert3D is missing, warn once and disable grades
        if not hasattr(self.sumo.simulation, 'convert3D'):
            
            _logger.warning("simulation.convert3D not available; setting all lane grades to 0.")
            
            for lane in self.lanes:
                self.lane_grade[lane] = 0.0
            return

        for lane in self.lanes:
            try:
                # Use 2D shape plus convert3D to get Z values
                shape2d = self.sumo.lane.getShape(lane)
                if not shape2d or len(shape2d) < 2:
                    self.lane_grade[lane] = 0.0
                    continue
                # cumulative distances along shape
                dists = [0.0]
                for i in range(1, len(shape2d)):
                    x0, y0 = shape2d[i-1]
                    x1, y1 = shape2d[i]
                    seg = ((x1 - x0)**2 + (y1 - y0)**2) ** 0.5
                    dists.append(dists[-1] + seg)
                total_len = dists[-1]
                target_from_end = max(total_len - sample_len, 0.0)
                # endpoint at stop line
                xA, yA = shape2d[-1]
                # point at target_from_end
                xB, yB = shape2d[0]
                for i in range(len(shape2d)-1, 0, -1):
                    if dists[i-1] <= target_from_end <= dists[i]:
                        x0, y0 = shape2d[i-1]
                        x1, y1 = shape2d[i]
                        seg_len = max(dists[i] - dists[i-1], 1e-6)
                        t = (target_from_end - dists[i-1]) / seg_len
                        xB = x0 + t * (x1 - x0)
                        yB = y0 + t * (y1 - y0)
                        break
                # convert to 3D robustly: prefer road-position signature (edgeID, pos, laneIndex)
                lane_len = self.sumo.lane.getLength(lane)
                # positions along lane from start
                posA = max(lane_len - 1e-3, 0.0)
                posB = max(lane_len - sample_len, 0.0)

                # parse edgeID and laneIndex from lane id (edgeID is lane id without last _index)
                try:
                    us = lane.rfind('_')
                    edge_id = lane[:us]
                    lane_idx = int(lane[us+1:])
                except Exception:
                    edge_id = lane
                    lane_idx = 0

                # First try road-position form
                try:
                    xA3, yA3, zA = self.sumo.simulation.convert3D(edge_id, float(posA), int(lane_idx))
                    xB3, yB3, zB = self.sumo.simulation.convert3D(edge_id, float(posB), int(lane_idx))
                except Exception:
                    # Fallback: try numeric XY forms
                    def _pt3(x, y):
                        last_exc = None
                        x_f, y_f = float(x), float(y)
                        calls = [
                            lambda: self.sumo.simulation.convert3D(x_f, y_f),
                            lambda: self.sumo.simulation.convert3D((x_f, y_f)),
                            lambda: self.sumo.simulation.convert3D((x_f, y_f, 0.0)),
                            lambda: self.sumo.simulation.convert3D(x_f, y_f, 0.0),
                        ]
                        for c in calls:
                            try:
                                return c()
                            except Exception as ee:
                                last_exc = ee
                                continue
                        raise last_exc if last_exc else RuntimeError('convert3D failed')

                    xA3, yA3, zA = _pt3(xA, yA)
                    xB3, yB3, zB = _pt3(xB, yB)
                # horizontal distance of sampled segment
                horiz = max(((xA3 - xB3)**2 + (yA3 - yB3)**2) ** 0.5, 1e-6)
                grade_percent = (zA - zB) / horiz * 100.0
                self.lane_grade[lane] = grade_percent
            except Exception as e:
                # Log once per lane to avoid spamming
                if lane not in _grade_error_lanes:
                    _grade_error_lanes.add(lane)
                    _logger.exception(
                        "convert3D/grade failed for lane=%s (sample_len=%.1fm, xA=%.2f, yA=%.2f, xB=%.2f, yB=%.2f). Fallback grade=0.",
                        lane,
                        sample_len,
                        xA if 'xA' in locals() else float('nan'),
                        yA if 'yA' in locals() else float('nan'),
                        xB if 'xB' in locals() else float('nan'),
                        yB if 'yB' in locals() else float('nan'),
                    )
                self.lane_grade[lane] = 0.0