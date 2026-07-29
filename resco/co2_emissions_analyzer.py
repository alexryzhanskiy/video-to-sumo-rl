#!/usr/bin/env python3
"""
CO2 Emissions Calculator for SUMO Emissions XML Files
Calculates total CO2 emissions from actual SUMO simulation emissions output
"""

import xml.etree.ElementTree as ET
import os
import sys
from collections import defaultdict
from datetime import datetime
import gc

def parse_emissions_xml(xml_file, progress_interval=1000):
    """
    Parse SUMO emissions XML file and calculate CO2 totals
    
    Args:
        xml_file: Path to SUMO emissions.xml file
        progress_interval: Show progress every N timesteps
    
    Returns:
        Dictionary with emission calculations
    """
    
    print(f"=== CO2 EMISSIONS ANALYSIS FROM SUMO OUTPUT ===")
    print(f"File: {xml_file}")
    
    if not os.path.exists(xml_file):
        print(f"Error: File '{xml_file}' not found!")
        return None
    
    file_size_mb = os.path.getsize(xml_file) / 1024 / 1024
    print(f"File size: {file_size_mb:.1f} MB")
    
    # Storage for results
    total_co2 = 0.0
    timestep_count = 0
    vehicle_count = 0
    unique_vehicles = set()
    
    # Detailed breakdowns
    co2_by_timestep = {}
    co2_by_vehicle_type = defaultdict(float)
    co2_by_emission_class = defaultdict(float)
    co2_by_route = defaultdict(float)
    
    # Vehicle tracking
    vehicle_totals = defaultdict(float)
    
    print("\n=== PARSING EMISSIONS DATA ===")
    print("Processing timesteps...", end="", flush=True)
    
    try:
        # Use iterparse for memory-efficient parsing of large files
        context = ET.iterparse(xml_file, events=('start', 'end'))
        event, root = next(context)
        
        current_timestep = 0
        timestep_co2 = 0.0
        timestep_vehicles = 0
        
        for event, elem in context:
            if event == 'start':
                continue
                
            if elem.tag == 'timestep':
                # Finished processing this timestep
                if 'time' in elem.attrib:
                    time_val = float(elem.attrib['time'])
                    co2_by_timestep[time_val] = timestep_co2
                    timestep_count += 1
                    
                    # Progress indicator
                    if timestep_count % progress_interval == 0:
                        print(f"\rProcessed {timestep_count} timesteps, current time: {time_val:.1f}s", end="", flush=True)
                
                # Reset for next timestep
                timestep_co2 = 0.0
                timestep_vehicles = 0
                
                # Clear processed elements to save memory
                elem.clear()
                
            elif elem.tag == 'vehicle':
                # Process vehicle emissions
                vehicle_id = elem.get('id', 'unknown')
                co2_str = elem.get('CO2', '0')
                vehicle_type = elem.get('type', 'unknown')
                emission_class = elem.get('eclass', 'unknown')
                route = elem.get('route', 'unknown')
                
                try:
                    co2_value = float(co2_str)
                except (ValueError, TypeError):
                    co2_value = 0.0
                
                # Add to totals
                total_co2 += co2_value
                timestep_co2 += co2_value
                timestep_vehicles += 1
                vehicle_count += 1
                
                # Track unique vehicles
                unique_vehicles.add(vehicle_id)
                
                # Breakdowns
                vehicle_totals[vehicle_id] += co2_value
                co2_by_vehicle_type[vehicle_type] += co2_value
                co2_by_emission_class[emission_class] += co2_value
                co2_by_route[route] += co2_value
                
                # Clear processed elements to save memory
                elem.clear()
            
            # Periodic garbage collection for large files
            if timestep_count % (progress_interval * 10) == 0:
                gc.collect()
    
    except Exception as e:
        print(f"\nError parsing XML: {e}")
        return None
    
    print(f"\rCompleted! Processed {timestep_count} timesteps")
    
    # Calculate statistics
    unique_vehicle_count = len(unique_vehicles)
    simulation_duration = max(co2_by_timestep.keys()) if co2_by_timestep else 0
    avg_co2_per_timestep = total_co2 / timestep_count if timestep_count > 0 else 0
    avg_co2_per_vehicle_instance = total_co2 / vehicle_count if vehicle_count > 0 else 0
    
    results = {
        'total_co2_mg': total_co2,  # SUMO outputs in mg
        'total_co2_g': total_co2 / 1000,  # Convert to grams
        'total_co2_kg': total_co2 / 1000000,  # Convert to kg
        'total_co2_tonnes': total_co2 / 1000000000,  # Convert to tonnes
        'timestep_count': timestep_count,
        'vehicle_instances': vehicle_count,
        'unique_vehicles': unique_vehicle_count,
        'simulation_duration': simulation_duration,
        'co2_by_timestep': co2_by_timestep,
        'co2_by_vehicle_type': dict(co2_by_vehicle_type),
        'co2_by_emission_class': dict(co2_by_emission_class),
        'co2_by_route': dict(co2_by_route),
        'vehicle_totals': dict(vehicle_totals),
        'avg_co2_per_timestep': avg_co2_per_timestep,
        'avg_co2_per_vehicle_instance': avg_co2_per_vehicle_instance
    }
    
    return results

def print_results(results):
    """Print formatted results"""
    if not results:
        return
    
    print(f"\n{'='*70}")
    print(f"CO2 EMISSIONS SUMMARY")
    print(f"{'='*70}")
    
    print(f"Total CO2 Emissions:     {results['total_co2_mg']:,.0f} mg")
    print(f"                        {results['total_co2_g']:,.1f} g")
    print(f"                        {results['total_co2_kg']:,.3f} kg")
    print(f"                        {results['total_co2_tonnes']:,.6f} tonnes")
    
    print(f"\nSimulation Statistics:")
    print(f"  Duration:              {results['simulation_duration']:.1f} seconds")
    print(f"  Timesteps:             {results['timestep_count']:,}")
    print(f"  Vehicle instances:     {results['vehicle_instances']:,}")
    print(f"  Unique vehicles:       {results['unique_vehicles']:,}")
    
    print(f"\nAverages:")
    print(f"  CO2 per timestep:      {results['avg_co2_per_timestep']:,.1f} mg")
    print(f"  CO2 per vehicle inst:  {results['avg_co2_per_vehicle_instance']:,.1f} mg")
    
    # Time-based analysis
    print(f"\n=== CO2 EMISSIONS BY TIME PERIOD ===")
    if results['co2_by_timestep']:
        # Group by larger time periods for readability
        period_size = 300  # 5-minute periods
        period_totals = defaultdict(float)
        
        for time, co2 in results['co2_by_timestep'].items():
            period = int(time // period_size) * period_size
            period_totals[period] += co2
        
        print("Time periods (5-minute intervals):")
        for period in sorted(period_totals.keys())[:20]:  # Show first 20 periods
            end_period = period + period_size
            co2_g = period_totals[period] / 1000
            print(f"  {period:4.0f}-{end_period:4.0f}s: {co2_g:8,.1f} g CO2")
        
        if len(period_totals) > 20:
            print(f"  ... and {len(period_totals) - 20} more periods")
    
    # Vehicle type breakdown
    print(f"\n=== CO2 EMISSIONS BY VEHICLE TYPE ===")
    sorted_types = sorted(results['co2_by_vehicle_type'].items(), 
                         key=lambda x: x[1], reverse=True)
    for vtype, co2_mg in sorted_types[:15]:  # Top 15
        co2_g = co2_mg / 1000
        percentage = (co2_mg / results['total_co2_mg']) * 100 if results['total_co2_mg'] > 0 else 0
        print(f"  {vtype:20s}: {co2_g:10,.1f} g ({percentage:6.2f}%)")
    
    # Emission class breakdown
    print(f"\n=== CO2 EMISSIONS BY EMISSION CLASS ===")
    sorted_classes = sorted(results['co2_by_emission_class'].items(),
                           key=lambda x: x[1], reverse=True)
    for eclass, co2_mg in sorted_classes[:10]:  # Top 10
        co2_g = co2_mg / 1000
        percentage = (co2_mg / results['total_co2_mg']) * 100 if results['total_co2_mg'] > 0 else 0
        print(f"  {eclass:25s}: {co2_g:10,.1f} g ({percentage:6.2f}%)")
    
    # Route breakdown
    print(f"\n=== CO2 EMISSIONS BY ROUTE ===")
    sorted_routes = sorted(results['co2_by_route'].items(),
                          key=lambda x: x[1], reverse=True)
    for route, co2_mg in sorted_routes:
        co2_g = co2_mg / 1000
        percentage = (co2_mg / results['total_co2_mg']) * 100 if results['total_co2_mg'] > 0 else 0
        print(f"  {route:15s}: {co2_g:10,.1f} g ({percentage:6.2f}%)")
    
    # Top CO2 emitting vehicles
    print(f"\n=== TOP CO2 EMITTING VEHICLES ===")
    sorted_vehicles = sorted(results['vehicle_totals'].items(),
                            key=lambda x: x[1], reverse=True)
    for vehicle_id, co2_mg in sorted_vehicles[:10]:  # Top 10
        co2_g = co2_mg / 1000
        print(f"  {vehicle_id:25s}: {co2_g:8,.1f} g")

def compare_emissions_files(file1, file2):
    """Compare CO2 emissions between two emissions XML files"""
    print(f"\n{'='*80}")
    print(f"CO2 EMISSIONS COMPARISON")
    print(f"{'='*80}")
    
    results1 = parse_emissions_xml(file1)
    if not results1:
        return
    
    print(f"\n--- FILE 1: {os.path.basename(file1)} ---")
    print_results(results1)
    
    results2 = parse_emissions_xml(file2)
    if not results2:
        return
    
    print(f"\n--- FILE 2: {os.path.basename(file2)} ---")
    print_results(results2)
    
    # Comparison
    co2_diff_kg = results1['total_co2_kg'] - results2['total_co2_kg']
    co2_diff_pct = (co2_diff_kg / results1['total_co2_kg']) * 100 if results1['total_co2_kg'] > 0 else 0
    
    vehicle_diff = results1['unique_vehicles'] - results2['unique_vehicles']
    vehicle_diff_pct = (vehicle_diff / results1['unique_vehicles']) * 100 if results1['unique_vehicles'] > 0 else 0
    
    print(f"\n{'='*80}")
    print(f"COMPARISON RESULTS")
    print(f"{'='*80}")
    print(f"CO2 Difference:        {co2_diff_kg:+,.3f} kg ({co2_diff_pct:+.1f}%)")
    print(f"Vehicle Difference:    {vehicle_diff:+,} vehicles ({vehicle_diff_pct:+.1f}%)")
    print(f"Duration Difference:   {results1['simulation_duration'] - results2['simulation_duration']:+.1f} seconds")
    
    if co2_diff_kg > 0:
        print(f"\n✅ File 2 has {co2_diff_kg:.3f} kg LESS CO2 emissions")
        print(f"   Environmental benefit: {co2_diff_kg * 365 * 24:.1f} kg CO2 saved annually")
    elif co2_diff_kg < 0:
        print(f"\n❌ File 2 has {abs(co2_diff_kg):.3f} kg MORE CO2 emissions")
    else:
        print(f"\n➡️  Files have identical CO2 emissions")

def summarize_emissions_file(xml_file):
    """Quick summary of emissions file without full parsing"""
    print(f"=== QUICK EMISSIONS FILE SUMMARY ===")
    print(f"File: {xml_file}")
    
    if not os.path.exists(xml_file):
        print(f"Error: File not found!")
        return
    
    file_size_mb = os.path.getsize(xml_file) / 1024 / 1024
    print(f"File size: {file_size_mb:.1f} MB")
    
    # Count elements quickly
    timestep_count = 0
    vehicle_count = 0
    
    try:
        with open(xml_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '<timestep' in line:
                    timestep_count += 1
                elif '<vehicle' in line:
                    vehicle_count += 1
                    
                if timestep_count > 0 and timestep_count % 1000 == 0:
                    print(f"\rCounting... {timestep_count} timesteps, {vehicle_count} vehicle instances", end="", flush=True)
    
        print(f"\rApproximate counts: {timestep_count} timesteps, {vehicle_count} vehicle instances")
        
        if timestep_count > 0:
            avg_vehicles_per_timestep = vehicle_count / timestep_count
            print(f"Average vehicles per timestep: {avg_vehicles_per_timestep:.1f}")
            
            estimated_duration = timestep_count  # Assuming 1-second timesteps
            print(f"Estimated simulation duration: {estimated_duration} seconds ({estimated_duration/60:.1f} minutes)")
    
    except Exception as e:
        print(f"Error analyzing file: {e}")

def main():
    """Main execution function"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python co2_emissions_analyzer.py <emissions.xml>")
        print("  python co2_emissions_analyzer.py <emissions1.xml> <emissions2.xml>  # Compare")
        print("  python co2_emissions_analyzer.py --summary <emissions.xml>         # Quick summary")
        print("")
        print("Examples:")
        print("  python co2_emissions_analyzer.py emissions.xml")
        print("  python co2_emissions_analyzer.py original_emissions.xml reduced_emissions.xml")
        print("  python co2_emissions_analyzer.py --summary emissions.xml")
        return
    
    if sys.argv[1] == '--summary':
        if len(sys.argv) < 3:
            print("Error: Please provide emissions file for summary")
            return
        summarize_emissions_file(sys.argv[2])
        return
    
    file1 = sys.argv[1]
    
    if len(sys.argv) >= 3 and sys.argv[2] != '--summary':
        # Comparison mode
        file2 = sys.argv[2]
        compare_emissions_files(file1, file2)
    else:
        # Single file analysis
        results = parse_emissions_xml(file1)
        if results:
            print_results(results)
            
            # Environmental context
            annual_co2_kg = results['total_co2_kg'] * (365 * 24 * 3600 / results['simulation_duration'])
            annual_co2_tonnes = annual_co2_kg / 1000
            
            print(f"\n=== ENVIRONMENTAL IMPACT (EXTRAPOLATED) ===")
            print(f"If this pattern continued for a full year:")
            print(f"  Annual CO2 emissions: {annual_co2_tonnes:,.1f} tonnes")
            print(f"  Equivalent to:")
            print(f"    - {annual_co2_tonnes * 2300:,.0f} liters of gasoline")
            print(f"    - {annual_co2_tonnes / 0.4:,.0f} kg of coal burned")
            print(f"    - {annual_co2_tonnes / 0.022:,.0f} trees needed for offset")

if __name__ == "__main__":
    main()
