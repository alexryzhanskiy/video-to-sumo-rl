#!/usr/bin/env python3
"""
SUMO Route XML Generator
Generates route XML files with specified vehicle types and traffic patterns.
Supports different traffic rates for straight, right turn, and left turn routes.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
import argparse
import sys

def generate_route_xml(duration_seconds, base_veh_per_hour, output_filename, flow_prefix="flow"):
    """
    Generate SUMO route XML file with specified traffic patterns
    
    Args:
        duration_seconds (int): Simulation duration in seconds
        base_veh_per_hour (int): Base vehicles per hour for straight routes
        output_filename (str): Output XML filename
        flow_prefix (str): Prefix for flow IDs
    """
    
    # Define route classifications based on intersection geometry
    # Assuming: e=east, w=west, n=north, s=south, t=intersection center
    straight_routes = ['route_ns', 'route_sn', 'route_ew', 'route_we']
    right_turn_routes = ['route_ne', 'route_es', 'route_sw', 'route_wn']  # 50% less
    left_turn_routes = ['route_nw', 'route_en', 'route_se', 'route_ws']   # 75% less
    
    # Calculate traffic rates
    straight_rate = base_veh_per_hour
    right_turn_rate = int(base_veh_per_hour * 0.5)  # 50% reduction
    left_turn_rate = int(base_veh_per_hour * 0.25)  # 75% reduction
    
    # Create root element
    root = ET.Element('routes')
    
    # Add vehicle type with CO2 emission parameters
    vtype = ET.SubElement(root, 'vType')
    vtype.set('id', 'type2_co2')
    vtype.set('vClass', 'passenger')
    vtype.set('carFollowModel', 'KraussPS')
    vtype.set('emissionClass', 'PHEMlight/PC_G_EU4')
    vtype.set('mass', '1850')
    vtype.set('loading', '300')
    vtype.set('length', '4.2')
    vtype.set('accel', '2.3')
    vtype.set('decel', '4.5')
    vtype.set('maxSpeed', '50')
    
    # Add parameters to vType for detailed vehicle modeling
    params = [
        ('maximumPower', '50000'),
        ('frontSurfaceArea', '1.9'),
        ('airDragCoefficient', '0.30'),
        ('rollDragCoefficient', '0.009'),
        ('wheelRadius', '0.30'),
        ('rotatingMass', '25'),
        ('radialDragCoefficient', '0.1'),
        ('constantPowerIntake', '180')
    ]
    
    for key, value in params:
        param = ET.SubElement(vtype, 'param')
        param.set('key', key)
        param.set('value', value)
    
    # Define route edges mapping for 4-way intersection
    route_edges = {
        'route_en': 'e_t t_n',  # East to North (left turn)
        'route_es': 'e_t t_s',  # East to South (right turn)
        'route_ew': 'e_t t_w',  # East to West (straight)
        'route_ne': 'n_t t_e',  # North to East (right turn)
        'route_ns': 'n_t t_s',  # North to South (straight)
        'route_nw': 'n_t t_w',  # North to West (left turn)
        'route_se': 's_t t_e',  # South to East (left turn)
        'route_sn': 's_t t_n',  # South to North (straight)
        'route_sw': 's_t t_w',  # South to West (right turn)
        'route_we': 'w_t t_e',  # West to East (straight)
        'route_wn': 'w_t t_n',  # West to North (right turn)
        'route_ws': 'w_t t_s'   # West to South (left turn)
    }
    
    # Add route definitions
    for route_id, edges in route_edges.items():
        route_elem = ET.SubElement(root, 'route')
        route_elem.set('id', route_id)
        route_elem.set('edges', edges)
    
    # Add flow definitions with traffic rate adjustments
    flow_id = 1
    for route_id in route_edges.keys():
        # Determine traffic rate based on route type
        if route_id in straight_routes:
            rate = straight_rate
            route_type = "straight"
        elif route_id in right_turn_routes:
            rate = right_turn_rate
            route_type = "right_turn (-50%)"
        else:  # left_turn_routes
            rate = left_turn_rate
            route_type = "left_turn (-75%)"
        
        # Skip routes with zero traffic
        if rate <= 0:
            continue
            
        # Create flow element
        flow = ET.SubElement(root, 'flow')
        flow.set('id', f'{flow_prefix}_{route_id}_{flow_id:02d}')
        flow.set('begin', '0.00')
        flow.set('end', f'{duration_seconds}.00')
        flow.set('type', 'type2_co2')
        flow.set('route', route_id)
        flow.set('vehsPerHour', str(rate))
        flow.set('departLane', 'best')
        flow.set('departPos', 'base')
        
        # Add comment for clarity
        comment_text = f' {route_type}: {rate} veh/h '
        root.append(ET.Comment(comment_text))
        
        flow_id += 1
    
    # Create formatted XML string
    rough_string = ET.tostring(root, 'unicode')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="    ")
    
    # Remove empty lines and fix formatting
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    formatted_xml = '\n'.join(lines[1:])  # Remove XML declaration
    
    # Add custom header
    final_xml = "<?xml version='1.0' encoding='UTF-8'?>\n" + formatted_xml
    
    # Write to file
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(final_xml)
    
    # Print summary
    print(f"✅ Generated route file: {output_filename}")
    print(f"📊 Simulation duration: {duration_seconds} seconds ({duration_seconds/3600:.1f} hours)")
    print(f"🚗 Traffic rates:")
    print(f"   • Straight routes: {straight_rate} veh/h")
    print(f"   • Right turn routes: {right_turn_rate} veh/h (50% reduction)")
    print(f"   • Left turn routes: {left_turn_rate} veh/h (75% reduction)")
    print(f"📈 Total flows generated: {flow_id - 1}")
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description='Generate SUMO route XML files with customizable traffic patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_route_xml.py -t 3600 -k 100 -o resco_benchmark/environments/2way_single/routes/gen.rou.xml
  python generate_route_xml.py --duration 7200 --base-rate 200 --output traffic_high.rou.xml
  python generate_route_xml.py -t 1800 -k 50 -o test_scenario.rou.xml --prefix "test_flow"
        """
    )
    
    parser.add_argument('-t', '--duration', type=int, default=3600,
                        help='Simulation duration in seconds (default: 3600 = 1 hour)')
    parser.add_argument('-k', '--base-rate', type=int, default=100,
                        help='Base vehicles per hour for straight routes (default: 100)')
    parser.add_argument('-o', '--output', type=str, default='generated_routes.rou.xml',
                        help='Output XML filename (default: generated_routes.rou.xml)')
    parser.add_argument('--prefix', type=str, default='flow',
                        help='Prefix for flow IDs (default: flow)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose output')
    
    args = parser.parse_args()
    
    # Validate inputs
    if args.duration <= 0:
        print("❌ Error: Duration must be positive")
        sys.exit(1)
    
    if args.base_rate < 0:
        print("❌ Error: Base rate cannot be negative")
        sys.exit(1)
    
    if args.verbose:
        print(f"🔧 Configuration:")
        print(f"   Duration: {args.duration}s")
        print(f"   Base rate: {args.base_rate} veh/h")
        print(f"   Output: {args.output}")
        print(f"   Flow prefix: {args.prefix}")
        print()
    
    try:
        success = generate_route_xml(args.duration, args.base_rate, args.output, args.prefix)
        if success:
            print(f"\n🎉 Route generation completed successfully!")
            print(f"💡 Use this file in SUMO with: sumo -r {args.output} -n your_network.net.xml")
        
    except Exception as e:
        print(f"❌ Error generating route file: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
