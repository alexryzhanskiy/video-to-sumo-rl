#!/usr/bin/env python3
"""
CO2 Emissions Calculator for SUMO Route Files
Calculates total CO2 emissions from vehicle flows in XML route files
"""

import xml.etree.ElementTree as ET
import os
import sys
from datetime import datetime
from collections import defaultdict

# SUMO Emission Classes and their approximate CO2 emission factors (g/km)
# Based on HBEFA (Handbook Emission Factors for Road Transport) database
EMISSION_FACTORS = {
    # Passenger Cars
    'HBEFA3/PC_G_EU0': 180,    # Old gasoline car (high emissions)
    'HBEFA3/PC_G_EU1': 170,    # EU1 gasoline car
    'HBEFA3/PC_G_EU2': 160,    # EU2 gasoline car
    'HBEFA3/PC_G_EU3': 150,    # EU3 gasoline car
    'HBEFA3/PC_G_EU4': 140,    # EU4 gasoline car
    'HBEFA3/PC_G_EU5': 130,    # EU5 gasoline car
    'HBEFA3/PC_G_EU6': 120,    # EU6 gasoline car (cleanest)
    'HBEFA3/PC_D_EU0': 160,    # Old diesel car
    'HBEFA3/PC_D_EU1': 150,    # EU1 diesel car
    'HBEFA3/PC_D_EU2': 145,    # EU2 diesel car
    'HBEFA3/PC_D_EU3': 140,    # EU3 diesel car
    'HBEFA3/PC_D_EU4': 135,    # EU4 diesel car
    'HBEFA3/PC_D_EU5': 130,    # EU5 diesel car
    'HBEFA3/PC_D_EU6': 125,    # EU6 diesel car
    
    # Heavy Duty Vehicles (Trucks, Buses)
    'HBEFA3/HDV': 850,         # Standard heavy duty vehicle
    'HDV_12_8': 950,           # Heavy truck (12-8 tons) - very high emissions
    'HBEFA3/Bus': 1200,        # Bus
    'HBEFA3/Coach': 800,       # Coach
    
    # Light Commercial Vehicles
    'HBEFA3/LCV': 200,         # Light commercial vehicle
    
    # Motorcycles
    'HBEFA3/MC_G_EU0': 90,     # Old motorcycle
    'HBEFA3/MC_G_EU1': 85,     # EU1 motorcycle
    'HBEFA3/MC_G_EU2': 80,     # EU2 motorcycle
    'HBEFA3/MC_G_EU3': 75,     # EU3 motorcycle
    
    # Default for unknown types
    'default': 150,             # Average passenger car emissions
}

# Average trip distances for different route types (km)
# Based on typical urban intersection distances
ROUTE_DISTANCES = {
    'route_en': 0.8,    # East to North
    'route_es': 0.8,    # East to South  
    'route_ew': 1.2,    # East to West (through route)
    'route_ne': 0.8,    # North to East
    'route_ns': 1.2,    # North to South (main corridor)
    'route_nw': 0.8,    # North to West
    'route_se': 0.8,    # South to East
    'route_sn': 1.2,    # South to North (main corridor)
    'route_sw': 0.8,    # South to West
    'route_we': 1.2,    # West to East (through route)
    'route_wn': 0.8,    # West to North
    'route_ws': 0.8,    # West to South
    'default': 0.8,     # Default distance
}

def get_emission_factor(vehicle_type, emission_class):
    """Get CO2 emission factor for a vehicle type"""
    if emission_class and emission_class in EMISSION_FACTORS:
        return EMISSION_FACTORS[emission_class]
    elif vehicle_type and 'co2' in vehicle_type.lower():
        # High emission vehicles
        return EMISSION_FACTORS.get('HDV_12_8', 950)
    else:
        return EMISSION_FACTORS['default']

def get_route_distance(route_id):
    """Get average distance for a route"""
    return ROUTE_DISTANCES.get(route_id, ROUTE_DISTANCES['default'])

def parse_vehicle_types(xml_file):
    """Parse vehicle type definitions from XML"""
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    vehicle_types = {}
    for vtype in root.findall('vType'):
        type_id = vtype.get('id')
        emission_class = vtype.get('emissionClass', '')
        vehicle_types[type_id] = emission_class
    
    return vehicle_types

def calculate_co2_emissions(xml_file, time_period_hours=1.0):
    """
    Calculate total CO2 emissions from vehicle flows
    
    Args:
        xml_file: Path to SUMO route XML file
        time_period_hours: Duration to calculate for (default 1 hour)
    
    Returns:
        Dictionary with emission calculations
    """
    
    # Parse vehicle types
    vehicle_types = parse_vehicle_types(xml_file)
    
    # Parse XML
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    # Storage for calculations
    emissions_by_period = defaultdict(lambda: defaultdict(float))
    emissions_by_type = defaultdict(float)
    emissions_by_route = defaultdict(float)
    total_vehicles_by_period = defaultdict(int)
    
    print(f"=== CO2 EMISSIONS ANALYSIS ===")
    print(f"File: {xml_file}")
    print(f"Calculation period: {time_period_hours} hour(s)")
    print(f"\n=== VEHICLE TYPE EMISSION FACTORS ===")
    
    # Display emission factors
    for vtype_id, emission_class in vehicle_types.items():
        factor = get_emission_factor(vtype_id, emission_class)
        print(f"{vtype_id}: {emission_class} -> {factor} g CO2/km")
    
    print(f"\n=== FLOW ANALYSIS ===")
    
    total_co2 = 0
    flow_count = 0
    
    for flow in root.findall('flow'):
        flow_id = flow.get('id')
        begin_time = float(flow.get('begin', 0))
        end_time = float(flow.get('end', 3600))
        route_id = flow.get('route')
        vehs_per_hour = float(flow.get('vehsPerHour', 0))
        flow_type = flow.get('type', 'default')
        
        # Get emission class
        emission_class = vehicle_types.get(flow_type, '')
        emission_factor = get_emission_factor(flow_type, emission_class)
        
        # Get route distance
        distance = get_route_distance(route_id)
        
        # Calculate vehicles in the time period
        period_duration_hours = (end_time - begin_time) / 3600.0
        actual_period = min(time_period_hours, period_duration_hours)
        num_vehicles = vehs_per_hour * actual_period
        
        # Calculate CO2 emissions (g)
        co2_per_vehicle = emission_factor * distance
        total_flow_co2 = num_vehicles * co2_per_vehicle
        
        # Store results
        period_key = int(begin_time)
        emissions_by_period[period_key]['co2'] += total_flow_co2
        emissions_by_period[period_key]['vehicles'] += num_vehicles
        emissions_by_type[flow_type] += total_flow_co2
        emissions_by_route[route_id] += total_flow_co2
        total_vehicles_by_period[period_key] += num_vehicles
        
        total_co2 += total_flow_co2
        flow_count += 1
        
        # Print detailed flow info for high-emission flows
        if emission_factor > 200 or 'co2' in flow_type.lower():
            print(f"HIGH EMISSION: {flow_id}")
            print(f"  Type: {flow_type} ({emission_class})")
            print(f"  Vehicles/hour: {vehs_per_hour}")
            print(f"  Distance: {distance} km")
            print(f"  CO2 factor: {emission_factor} g/km")
            print(f"  Total CO2: {total_flow_co2:.1f} g ({total_flow_co2/1000:.2f} kg)")
    
    # Convert to more readable units
    total_co2_kg = total_co2 / 1000
    total_co2_tonnes = total_co2 / 1000000
    
    results = {
        'total_co2_grams': total_co2,
        'total_co2_kg': total_co2_kg,
        'total_co2_tonnes': total_co2_tonnes,
        'emissions_by_period': dict(emissions_by_period),
        'emissions_by_type': dict(emissions_by_type),
        'emissions_by_route': dict(emissions_by_route),
        'total_vehicles': sum(total_vehicles_by_period.values()),
        'flow_count': flow_count,
        'avg_co2_per_vehicle': total_co2 / sum(total_vehicles_by_period.values()) if sum(total_vehicles_by_period.values()) > 0 else 0
    }
    
    return results

def print_results(results):
    """Print formatted results"""
    print(f"\n{'='*60}")
    print(f"CO2 EMISSIONS SUMMARY")
    print(f"{'='*60}")
    
    print(f"Total CO2 Emissions: {results['total_co2_grams']:,.0f} grams")
    print(f"                    {results['total_co2_kg']:,.1f} kg")
    print(f"                    {results['total_co2_tonnes']:,.3f} tonnes")
    print(f"Total Vehicles:      {results['total_vehicles']:,.0f}")
    print(f"Average CO2/Vehicle: {results['avg_co2_per_vehicle']:.1f} g")
    print(f"Total Flows:         {results['flow_count']}")
    
    print(f"\n=== EMISSIONS BY TIME PERIOD ===")
    for period, data in sorted(results['emissions_by_period'].items()):
        period_end = period + 2000
        co2_kg = data['co2'] / 1000
        print(f"Period {period}-{period_end}s: {co2_kg:,.1f} kg CO2 ({data['vehicles']:,.0f} vehicles)")
    
    print(f"\n=== EMISSIONS BY VEHICLE TYPE ===")
    sorted_types = sorted(results['emissions_by_type'].items(), key=lambda x: x[1], reverse=True)
    for vtype, co2 in sorted_types:
        co2_kg = co2 / 1000
        percentage = (co2 / results['total_co2_grams']) * 100
        print(f"{vtype:15s}: {co2_kg:8,.1f} kg ({percentage:5.1f}%)")
    
    print(f"\n=== EMISSIONS BY ROUTE ===")
    sorted_routes = sorted(results['emissions_by_route'].items(), key=lambda x: x[1], reverse=True)
    for route, co2 in sorted_routes:
        co2_kg = co2 / 1000
        percentage = (co2 / results['total_co2_grams']) * 100
        print(f"{route:12s}: {co2_kg:8,.1f} kg ({percentage:5.1f}%)")

def compare_files(file1, file2, time_period_hours=1.0):
    """Compare CO2 emissions between two route files"""
    print(f"\n{'='*80}")
    print(f"CO2 EMISSIONS COMPARISON")
    print(f"{'='*80}")
    
    results1 = calculate_co2_emissions(file1, time_period_hours)
    print(f"\n--- FILE 1: {os.path.basename(file1)} ---")
    print_results(results1)
    
    results2 = calculate_co2_emissions(file2, time_period_hours)
    print(f"\n--- FILE 2: {os.path.basename(file2)} ---")
    print_results(results2)
    
    # Comparison
    co2_reduction = results1['total_co2_kg'] - results2['total_co2_kg']
    co2_reduction_pct = (co2_reduction / results1['total_co2_kg']) * 100 if results1['total_co2_kg'] > 0 else 0
    
    vehicle_reduction = results1['total_vehicles'] - results2['total_vehicles']
    vehicle_reduction_pct = (vehicle_reduction / results1['total_vehicles']) * 100 if results1['total_vehicles'] > 0 else 0
    
    print(f"\n{'='*80}")
    print(f"REDUCTION ANALYSIS")
    print(f"{'='*80}")
    print(f"CO2 Reduction:     {co2_reduction:,.1f} kg ({co2_reduction_pct:+.1f}%)")
    print(f"Vehicle Reduction: {vehicle_reduction:,.0f} vehicles ({vehicle_reduction_pct:+.1f}%)")
    print(f"CO2 per Vehicle:   {results1['avg_co2_per_vehicle']:.1f} g → {results2['avg_co2_per_vehicle']:.1f} g")
    
    if co2_reduction > 0:
        print(f"\n✅ Environmental Benefit: {co2_reduction:,.1f} kg CO2 saved per hour")
        print(f"   Annual savings: {co2_reduction * 24 * 365 / 1000:,.1f} tonnes CO2")
    else:
        print(f"\n❌ Environmental Impact: {abs(co2_reduction):,.1f} kg CO2 increase per hour")

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python co2_calculator.py <route_file.xml> [time_period_hours]")
        print("  python co2_calculator.py <file1.xml> <file2.xml> [time_period_hours]  # Compare two files")
        print("")
        print("Examples:")
        print("  python co2_calculator.py single-intersection-gen1_co2.rou.xml")
        print("  python co2_calculator.py original.xml reduced.xml 1.0")
        return
    
    file1 = sys.argv[1]
    time_period = float(sys.argv[-1]) if len(sys.argv) > 2 and sys.argv[-1].replace('.', '').isdigit() else 1.0
    
    if not os.path.exists(file1):
        print(f"Error: File '{file1}' not found!")
        return
    
    if len(sys.argv) >= 3 and not sys.argv[2].replace('.', '').isdigit():
        # Two files provided - comparison mode
        file2 = sys.argv[2]
        if not os.path.exists(file2):
            print(f"Error: File '{file2}' not found!")
            return
        compare_files(file1, file2, time_period)
    else:
        # Single file analysis
        results = calculate_co2_emissions(file1, time_period)
        print_results(results)
        
        # Environmental context
        co2_tonnes_per_year = results['total_co2_tonnes'] * 24 * 365
        print(f"\n=== ENVIRONMENTAL CONTEXT ===")
        print(f"Annual CO2 emissions: {co2_tonnes_per_year:,.1f} tonnes")
        print(f"Equivalent to:")
        print(f"  - {co2_tonnes_per_year * 2.3:,.0f} liters of gasoline burned")
        print(f"  - {co2_tonnes_per_year / 0.4:,.0f} kg of coal burned") 
        print(f"  - {co2_tonnes_per_year / 22:,.0f} trees needed to offset (annual absorption)")

if __name__ == "__main__":
    main()
