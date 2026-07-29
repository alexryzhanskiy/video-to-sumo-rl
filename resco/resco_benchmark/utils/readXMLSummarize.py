import os
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import glob
import matplotlib.pyplot as plt
import re

# Define the metrics in one place
METRICS = {
    'Duration': 'Avg Duration',
    'Waiting Count': 'Avg Waiting Count',
    'CO2 Emissions': 'Total CO2 Emissions',
    'Waiting Time': 'Avg Waiting Time'
    
}

def parse_trip_info(xml_file):
    """Parses a SUMO tripinfo XML file and extracts relevant data."""
    tree = ET.parse(xml_file)
    root = tree.getroot()
    data = []
    
    for trip in root.findall('tripinfo'):
        data.append({
            'Trip ID': trip.get('id'),
            'Duration': float(trip.get('duration')),
            'Waiting Time': float(trip.get('waitingTime')),
            'CO2 Emissions': sum(float(em.get('CO2_abs')) for em in trip.findall('emissions')),
            'Waiting Count': int(trip.get('waitingCount', 0))
        })
    
    return data

def compute_metrics(trip_data):
    """Computes average metrics for the last N results dynamically."""
    df = pd.DataFrame(trip_data)
    #df = df.tail(last_n)
    
    metrics = {name: df[column].mean() if 'Total' not in name else df[column].sum() for column, name in METRICS.items()}
    return metrics

def generate_results_table(log_dir, last_n=10):
    """Generates a summary table by processing last N tripinfo XML files per algorithm folder."""
    results = []
    
    algo_folders = [f for f in os.listdir(log_dir) if os.path.isdir(os.path.join(log_dir, f))]
    for algo in algo_folders:
        algo_path = os.path.join(log_dir, algo)
        
        trip_files = sorted(glob.glob(os.path.join(algo_path, 'tripinfo_*.xml')), key=os.path.getctime)
        if last_n < 0:
            trip_files = trip_files[last_n:]  # Get last |last_n| items
        elif last_n > 0:
            trip_files = trip_files[:last_n]  # Get first last_n items
        
        
        all_trip_data = []
        for file in trip_files:
            trip_data = parse_trip_info(file)
            all_trip_data.extend(trip_data)
        
        if all_trip_data:
            metrics = compute_metrics(all_trip_data)
            results.append([algo] + list(metrics.values()))
    
    df_results = pd.DataFrame(results, columns=['Algorithm'] + list(METRICS.values()))
    return df_results

def plot_trip_metrics(log_dir, first_n=None, last_n=None):
    """
    Plots trip metrics over time for all algorithms.
    
    Args:
        log_dir: Directory containing algorithm folders
        first_n: Number of first files to include (None for all)
        last_n: Number of last files to include (None for all)
    """
    algo_folders = [f for f in os.listdir(log_dir) if os.path.isdir(os.path.join(log_dir, f))]
    metric_names = ['Duration', 'Waiting Time', 'CO2 Emissions', 'Waiting Count']
    colors = ['b', 'r', 'g', 'orange', 'purple', 'brown', 'pink', 'gray']
    
    # Store all data for all algorithms
    all_algo_data = {}
    
    # First iteration: collect all data for each algorithm
    for algo_idx, algo in enumerate(algo_folders):
        algo_path = os.path.join(log_dir, algo)
        
        # Get all tripinfo files and sort by index (extracted from filename)
        trip_files = glob.glob(os.path.join(algo_path, 'tripinfo_*.xml'))
        
        # Sort by numeric index in filename
        def get_file_index(filepath):
            match = re.search(r'tripinfo_(\d+)\.xml', os.path.basename(filepath))
            return int(match.group(1)) if match else 0
        
        trip_files.sort(key=get_file_index)
        
        # Apply first_n and last_n filtering
        if first_n is not None and last_n is not None:
            selected_files = trip_files[:first_n] + trip_files[-last_n:]
        elif first_n is not None:
            selected_files = trip_files[:first_n]
        elif last_n is not None:
            selected_files = trip_files[-last_n:]
        else:
            selected_files = trip_files
        
        # Calculate metrics for each file (parse once per file)
        file_indices = []
        metrics_data = {metric_name: [] for metric_name in metric_names}
        
        for file_path in selected_files:
            file_index = get_file_index(file_path)
            file_indices.append(file_index)
            
            trip_data = parse_trip_info(file_path)
            df = pd.DataFrame(trip_data)
            
            # Calculate all metrics at once for this file
            for metric_name in metric_names:
                metrics_data[metric_name].append(df[metric_name].sum())
        
        all_algo_data[algo] = {
            'file_indices': file_indices,
            'metrics': metrics_data,
            'color': colors[algo_idx % len(colors)]
        }
    
    # Second iteration: create separate plots for each metric
    for metric_name in metric_names:
        plt.figure(figsize=(12, 8))
        
        for algo in algo_folders:
            if algo in all_algo_data and all_algo_data[algo]['metrics'][metric_name]:
                plt.plot(all_algo_data[algo]['file_indices'], 
                        all_algo_data[algo]['metrics'][metric_name], 
                        label=f'{algo}',
                        color=all_algo_data[algo]['color'],
                        linewidth=1)
        
        plt.xlabel('File Index')
        plt.ylabel(metric_name)
        plt.title(f'{metric_name}')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

# Run the function and display results
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), 'results' + os.sep)

print(f"Log dir: {log_dir}, cwd:'{os.getcwd()}'")

print("Generating results table for first 1 file per algorithm...")
df_results = generate_results_table(log_dir, last_n=1)
print(df_results)
df_results.to_excel(log_dir + "results_started.xlsx", index=False)

print("Generating results table for last 1 file per algorithm...")
df_results = generate_results_table(log_dir, last_n=-1)
print(df_results)
df_results.to_excel(log_dir + "results_finished.xlsx", index=False)

plot_trip_metrics(log_dir, first_n=None, last_n=99)