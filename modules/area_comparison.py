import os
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from modules.database import get_db

class AreaBasedComparison:
    """
    Compare simulation area metrics with real-world traffic patterns
    More realistic than exact route matching
    """
    
    def __init__(self, db=None):
        self.db = db or get_db()
    
    def analyze_simulation_logs(self, log_file: str = "data/logs/edge_state.csv") -> Dict:
        """
        Analyze edge state logs from simulation
        Returns aggregate metrics for the simulated area
        """
        if not os.path.exists(log_file):
            print(f"[AREA_COMPARISON] Log file not found: {log_file}")
            return {}
        
        try:
            # Read simulation logs
            df = pd.read_csv(log_file)
            
            if df.empty:
                print("[AREA_COMPARISON] Log file is empty")
                return {}
            
            # Calculate aggregate metrics
            metrics = {
                'total_edges': df['edge_id'].nunique(),
                'avg_speed_kmh': df['meanSpeed'].mean() * 3.6,  # m/s to km/h
                'median_speed_kmh': df['meanSpeed'].median() * 3.6,
                'avg_occupancy': df['occupancy'].mean(),
                'avg_vehicles_per_edge': df['numVeh'].mean(),
                'total_vehicle_observations': df['numVeh'].sum(),
                'avg_travel_time_per_edge': df['travelTime'].mean(),
                'simulation_duration': df['time'].max(),
                'num_measurements': len(df)
            }
            
            # Calculate congestion levels (arbitrary thresholds)
            df['speed_kmh'] = df['meanSpeed'] * 3.6
            metrics['pct_free_flow'] = (df['speed_kmh'] > 40).sum() / len(df) * 100
            metrics['pct_moderate'] = ((df['speed_kmh'] > 20) & (df['speed_kmh'] <= 40)).sum() / len(df) * 100
            metrics['pct_congested'] = (df['speed_kmh'] <= 20).sum() / len(df) * 100
            
            print(f"[AREA_COMPARISON] Analyzed {len(df)} log entries from {metrics['total_edges']} edges")
            
            return metrics
            
        except Exception as e:
            print(f"[AREA_COMPARISON] Error analyzing logs: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def get_real_data_metrics(self) -> Dict:
        """
        Get aggregate metrics from real-world probe route data
        """
        routes = self.db.get_probe_routes(active_only=True)
        
        if not routes:
            return {}
        
        all_speeds = []
        all_travel_times = []
        
        for route in routes:
            data = self.db.get_real_traffic_data(route_id=route['route_id'])
            if data:
                all_speeds.extend([d['speed_kmh'] for d in data if d['speed_kmh']])
                all_travel_times.extend([d['travel_time_seconds'] for d in data])
        
        if not all_speeds:
            return {}
        
        metrics = {
            'avg_speed_kmh': np.mean(all_speeds),
            'median_speed_kmh': np.median(all_speeds),
            'std_speed_kmh': np.std(all_speeds),
            'min_speed_kmh': np.min(all_speeds),
            'max_speed_kmh': np.max(all_speeds),
            'num_routes': len(routes),
            'num_measurements': len(all_speeds)
        }
        
        # Categorize congestion (same thresholds as simulation)
        speeds_array = np.array(all_speeds)
        metrics['pct_free_flow'] = (speeds_array > 40).sum() / len(speeds_array) * 100
        metrics['pct_moderate'] = ((speeds_array > 20) & (speeds_array <= 40)).sum() / len(speeds_array) * 100
        metrics['pct_congested'] = (speeds_array <= 20).sum() / len(speeds_array) * 100
        
        return metrics
    
    def compare_area_metrics(self, scenario_id: str, log_file: str = "data/logs/edge_state.csv") -> Dict:
        """
        Compare simulation area metrics with real-world data
        Returns comparison results with accuracy metrics
        """
        print("\n" + "="*70)
        print("AREA-BASED DIGITAL TWIN COMPARISON")
        print("="*70)
        print(f"Scenario: {scenario_id}")
        print()
        
        # Get simulation metrics
        sim_metrics = self.analyze_simulation_logs(log_file)
        if not sim_metrics:
            print("❌ No simulation data available")
            return {}
        
        # Get real-world metrics
        real_metrics = self.get_real_data_metrics()
        if not real_metrics:
            print("❌ No real-world data available")
            print("   Collect data using: python setup_digital_twin.py")
            return {}
        
        # Compare average speeds
        sim_speed = sim_metrics['avg_speed_kmh']
        real_speed = real_metrics['avg_speed_kmh']
        speed_error = abs(sim_speed - real_speed)
        speed_error_pct = (speed_error / real_speed * 100) if real_speed > 0 else 0
        
        # Compare congestion distributions
        congestion_comparison = {
            'free_flow_diff': abs(sim_metrics['pct_free_flow'] - real_metrics['pct_free_flow']),
            'moderate_diff': abs(sim_metrics['pct_moderate'] - real_metrics['pct_moderate']),
            'congested_diff': abs(sim_metrics['pct_congested'] - real_metrics['pct_congested'])
        }
        
        # Overall similarity score (0-100, higher is better)
        congestion_similarity = 100 - (
            congestion_comparison['free_flow_diff'] +
            congestion_comparison['moderate_diff'] +
            congestion_comparison['congested_diff']
        ) / 3
        
        # Compile results
        results = {
            'scenario_id': scenario_id,
            'simulation': sim_metrics,
            'real_world': real_metrics,
            'comparison': {
                'speed_error_kmh': speed_error,
                'speed_error_pct': speed_error_pct,
                'congestion_similarity': congestion_similarity,
                'congestion_differences': congestion_comparison
            }
        }
        
        # Print report
        self._print_comparison_report(results)
        
        # Save to database
        self._save_area_comparison(scenario_id, results)
        
        return results
    
    def _print_comparison_report(self, results: Dict):
        """Print formatted comparison report"""
        sim = results['simulation']
        real = results['real_world']
        comp = results['comparison']
        
        print("SPEED COMPARISON:")
        print("-" * 70)
        print(f"  Real-world avg speed:        {real['avg_speed_kmh']:.2f} km/h")
        print(f"  Simulation avg speed:        {sim['avg_speed_kmh']:.2f} km/h")
        print(f"  Absolute difference:         {comp['speed_error_kmh']:.2f} km/h")
        print(f"  Percentage error:            {comp['speed_error_pct']:.2f}%")
        print()
        
        print("CONGESTION LEVEL DISTRIBUTION:")
        print("-" * 70)
        print(f"  {'Level':<20} {'Real-World':<15} {'Simulation':<15} {'Difference':<15}")
        print("-" * 70)
        print(f"  {'Free Flow (>40 km/h)':<20} {real['pct_free_flow']:>13.1f}% {sim['pct_free_flow']:>13.1f}% {comp['congestion_differences']['free_flow_diff']:>13.1f}%")
        print(f"  {'Moderate (20-40 km/h)':<20} {real['pct_moderate']:>13.1f}% {sim['pct_moderate']:>13.1f}% {comp['congestion_differences']['moderate_diff']:>13.1f}%")
        print(f"  {'Congested (<20 km/h)':<20} {real['pct_congested']:>13.1f}% {sim['pct_congested']:>13.1f}% {comp['congestion_differences']['congested_diff']:>13.1f}%")
        print()
        
        print("OVERALL ASSESSMENT:")
        print("-" * 70)
        
        # Speed accuracy assessment
        if comp['speed_error_pct'] < 10:
            speed_rating = "Excellent (<10%)"
        elif comp['speed_error_pct'] < 20:
            speed_rating = "Good (10-20%)"
        elif comp['speed_error_pct'] < 30:
            speed_rating = "Acceptable (20-30%)"
        else:
            speed_rating = "Needs Calibration (>30%)"
        
        print(f"  Speed Accuracy:              {speed_rating}")
        print(f"  Congestion Similarity:       {comp['congestion_similarity']:.1f}%")
        
        if comp['congestion_similarity'] > 80:
            print(f"  Overall Rating:              ✅ Excellent - Digital twin closely matches reality")
        elif comp['congestion_similarity'] > 60:
            print(f"  Overall Rating:              ✓ Good - Digital twin shows realistic patterns")
        else:
            print(f"  Overall Rating:              ⚠ Fair - Consider calibration")
        
        print()
        print("SIMULATION DETAILS:")
        print("-" * 70)
        print(f"  Edges simulated:             {sim['total_edges']}")
        print(f"  Total measurements:          {sim['num_measurements']}")
        print(f"  Simulation duration:         {sim['simulation_duration']}s ({sim['simulation_duration']/60:.1f} min)")
        print(f"  Avg vehicles per edge:       {sim['avg_vehicles_per_edge']:.2f}")
        print()
        
        print("REAL-WORLD DATA:")
        print("-" * 70)
        print(f"  Probe routes monitored:      {real['num_routes']}")
        print(f"  Data points collected:       {real['num_measurements']}")
        print(f"  Speed range:                 {real['min_speed_kmh']:.1f} - {real['max_speed_kmh']:.1f} km/h")
        print()
        
        print("="*70)
        
        # Recommendations
        print("\nRECOMMENDATIONS FOR THESIS:")
        if comp['speed_error_pct'] < 15 and comp['congestion_similarity'] > 70:
            print("  ✅ These results demonstrate good digital twin accuracy")
            print("  ✅ Suitable for 'what-if' scenario testing")
            print("  ✅ Can be used for traffic prediction")
        else:
            print("  📝 Document these results as 'baseline' accuracy")
            print("  📝 Implement calibration to improve accuracy (Chapter 5)")
            print("  📝 Show before/after calibration comparison")
        print()
    
    def _save_area_comparison(self, scenario_id: str, results: Dict):
        """Save comparison results to database"""
        try:
            # Store as validation metrics (adapted for area-based comparison)
            self.db.store_validation_metrics(
                scenario_id=scenario_id,
                mae=results['comparison']['speed_error_kmh'],
                rmse=results['comparison']['speed_error_kmh'],  # Same as MAE for single metric
                mape=results['comparison']['speed_error_pct'],
                r_squared=results['comparison']['congestion_similarity'] / 100,  # Normalize to 0-1
                num_samples=results['simulation']['total_edges'],
                notes=f"Area-based comparison: {results['simulation']['total_edges']} edges, "
                      f"{results['simulation']['num_measurements']} measurements"
            )
            print("💾 Comparison results saved to database")
        except Exception as e:
            print(f"⚠️  Could not save to database: {e}")
    
    def export_comparison_report(self, scenario_id: str, output_file: str = None):
        """Export detailed comparison to file for thesis"""
        if output_file is None:
            output_file = f"comparison_report_{scenario_id}.txt"
        
        # Redirect print to file with UTF-8 encoding to handle special characters
        import sys
        original_stdout = sys.stdout
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                sys.stdout = f
                log_file = "data/logs/edge_state.csv"
                self.compare_area_metrics(scenario_id, log_file)
        finally:
            sys.stdout = original_stdout
        
        print(f"Report exported to: {output_file}")