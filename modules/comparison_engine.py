"""
Comparison Engine - Digital Twin Validation
Compares simulation results with real-world traffic data
Calculates accuracy metrics for thesis
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from modules.database import get_db

@dataclass
class ComparisonResult:
    """Results of comparing simulation vs real data"""
    route_id: str
    route_name: str
    real_travel_time: float
    simulated_travel_time: float
    absolute_error: float
    percentage_error: float
    real_samples: int
    sim_samples: int

@dataclass
class ValidationMetrics:
    """Overall validation metrics for the digital twin"""
    mae: float  # Mean Absolute Error
    rmse: float  # Root Mean Squared Error
    mape: float  # Mean Absolute Percentage Error
    r_squared: float  # R-squared correlation
    num_routes: int
    comparisons: List[ComparisonResult]

class ComparisonEngine:
    """Compare simulation results with real-world data"""
    
    def __init__(self, db=None):
        self.db = db or get_db()
    
    def get_real_data_average(
        self,
        route_id: str,
        start_time: str = None,
        end_time: str = None
    ) -> Optional[Dict]:
        """Get average real traffic data for a route"""
        data = self.db.get_real_traffic_data(
            route_id=route_id,
            start_time=start_time,
            end_time=end_time
        )
        
        if not data:
            return None
        
        travel_times = [d['travel_time_seconds'] for d in data]
        speeds = [d['speed_kmh'] for d in data if d['speed_kmh']]
        
        return {
            'avg_travel_time': np.mean(travel_times),
            'std_travel_time': np.std(travel_times),
            'min_travel_time': np.min(travel_times),
            'max_travel_time': np.max(travel_times),
            'avg_speed': np.mean(speeds) if speeds else None,
            'sample_count': len(data)
        }
    
    def get_simulation_data_average(
        self,
        scenario_id: str,
        route_id: str
    ) -> Optional[Dict]:
        """Get average simulation results for a route"""
        data = self.db.get_simulation_results(
            scenario_id=scenario_id,
            route_id=route_id
        )
        
        if not data:
            return None
        
        travel_times = [d['travel_time_seconds'] for d in data]
        
        return {
            'avg_travel_time': np.mean(travel_times),
            'std_travel_time': np.std(travel_times),
            'min_travel_time': np.min(travel_times),
            'max_travel_time': np.max(travel_times),
            'sample_count': len(data)
        }
    
    def compare_single_route(
        self,
        route_id: str,
        scenario_id: str,
        start_time: str = None,
        end_time: str = None
    ) -> Optional[ComparisonResult]:
        """Compare simulation vs real data for a single route"""
        
        # Get route info
        routes = self.db.get_probe_routes()
        route_info = next((r for r in routes if r['route_id'] == route_id), None)
        if not route_info:
            return None
        
        # Get real data
        real_data = self.get_real_data_average(route_id, start_time, end_time)
        if not real_data:
            print(f"[COMPARISON] No real data for route {route_id}")
            return None
        
        # Get simulation data
        sim_data = self.get_simulation_data_average(scenario_id, route_id)
        if not sim_data:
            print(f"[COMPARISON] No simulation data for route {route_id}")
            return None
        
        # Calculate errors
        real_tt = real_data['avg_travel_time']
        sim_tt = sim_data['avg_travel_time']
        
        abs_error = abs(real_tt - sim_tt)
        pct_error = (abs_error / real_tt) * 100 if real_tt > 0 else 0
        
        return ComparisonResult(
            route_id=route_id,
            route_name=route_info['name'],
            real_travel_time=real_tt,
            simulated_travel_time=sim_tt,
            absolute_error=abs_error,
            percentage_error=pct_error,
            real_samples=real_data['sample_count'],
            sim_samples=sim_data['sample_count']
        )
    
    def compare_all_routes(
        self,
        scenario_id: str,
        start_time: str = None,
        end_time: str = None
    ) -> List[ComparisonResult]:
        """Compare all probe routes"""
        routes = self.db.get_probe_routes(active_only=True)
        results = []
        
        for route in routes:
            result = self.compare_single_route(
                route['route_id'],
                scenario_id,
                start_time,
                end_time
            )
            if result:
                results.append(result)
        
        return results
    
    def calculate_validation_metrics(
        self,
        scenario_id: str,
        start_time: str = None,
        end_time: str = None,
        save_to_db: bool = True
    ) -> ValidationMetrics:
        """
        Calculate overall validation metrics
        These are the KEY METRICS for your thesis!
        """
        comparisons = self.compare_all_routes(scenario_id, start_time, end_time)
        
        if not comparisons:
            raise ValueError("No comparisons available - need both real and simulation data")
        
        # Extract arrays for calculations
        real_values = np.array([c.real_travel_time for c in comparisons])
        sim_values = np.array([c.simulated_travel_time for c in comparisons])
        
        # Calculate MAE (Mean Absolute Error)
        mae = np.mean(np.abs(real_values - sim_values))
        
        # Calculate RMSE (Root Mean Squared Error)
        rmse = np.sqrt(np.mean((real_values - sim_values) ** 2))
        
        # Calculate MAPE (Mean Absolute Percentage Error)
        mape = np.mean(np.abs((real_values - sim_values) / real_values)) * 100
        
        # Calculate R-squared
        ss_res = np.sum((real_values - sim_values) ** 2)
        ss_tot = np.sum((real_values - np.mean(real_values)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        metrics = ValidationMetrics(
            mae=mae,
            rmse=rmse,
            mape=mape,
            r_squared=r_squared,
            num_routes=len(comparisons),
            comparisons=comparisons
        )
        
        # Save to database
        if save_to_db:
            self.db.store_validation_metrics(
                scenario_id=scenario_id,
                mae=mae,
                rmse=rmse,
                mape=mape,
                r_squared=r_squared,
                num_samples=len(comparisons),
                time_period_start=start_time,
                time_period_end=end_time
            )
        
        return metrics
    
    def print_comparison_report(
        self,
        scenario_id: str,
        start_time: str = None,
        end_time: str = None
    ):
        """Print detailed comparison report"""
        print("\n" + "="*70)
        print("DIGITAL TWIN VALIDATION REPORT")
        print("="*70)
        print(f"Scenario: {scenario_id}")
        print()
        
        try:
            metrics = self.calculate_validation_metrics(
                scenario_id,
                start_time,
                end_time,
                save_to_db=False
            )
            
            # Overall metrics
            print("OVERALL ACCURACY METRICS:")
            print("-" * 70)
            print(f"  Mean Absolute Error (MAE):       {metrics.mae:.2f} seconds ({metrics.mae/60:.2f} min)")
            print(f"  Root Mean Squared Error (RMSE):  {metrics.rmse:.2f} seconds ({metrics.rmse/60:.2f} min)")
            print(f"  Mean Absolute % Error (MAPE):    {metrics.mape:.2f}%")
            print(f"  R-squared (correlation):         {metrics.r_squared:.4f}")
            print(f"  Routes compared:                 {metrics.num_routes}")
            print()
            
            # Interpret results
            print("INTERPRETATION:")
            print("-" * 70)
            if metrics.mape < 10:
                accuracy = "Excellent (< 10%)"
            elif metrics.mape < 20:
                accuracy = "Good (10-20%)"
            elif metrics.mape < 30:
                accuracy = "Acceptable (20-30%)"
            else:
                accuracy = "Needs Calibration (> 30%)"
            
            print(f"  Accuracy Level: {accuracy}")
            
            if metrics.r_squared > 0.9:
                correlation = "Very Strong (> 0.9)"
            elif metrics.r_squared > 0.7:
                correlation = "Strong (0.7-0.9)"
            elif metrics.r_squared > 0.5:
                correlation = "Moderate (0.5-0.7)"
            else:
                correlation = "Weak (< 0.5)"
            
            print(f"  Correlation: {correlation}")
            print()
            
            # Per-route comparison
            print("PER-ROUTE COMPARISON:")
            print("-" * 70)
            print(f"{'Route':<35} {'Real':<12} {'Simulated':<12} {'Error':<12}")
            print("-" * 70)
            
            for comp in metrics.comparisons:
                real_min = comp.real_travel_time / 60
                sim_min = comp.simulated_travel_time / 60
                error_pct = comp.percentage_error
                
                print(f"{comp.route_name[:34]:<35} {real_min:>10.1f}m {sim_min:>10.1f}m {error_pct:>10.1f}%")
            
            print("="*70)
            
            # Recommendations
            print("\nRECOMMENDATIONS:")
            if metrics.mape > 20:
                print("  ⚠️  Consider calibration to improve accuracy")
                print("  ⚠️  Check SUMO parameters: car-following model, speed limits, lane changing")
            elif metrics.mape < 15:
                print("  ✅ Digital twin accuracy is good for practical use")
                print("  ✅ Suitable for prediction and scenario testing")
            
            print()
            
            return metrics
            
        except Exception as e:
            print(f"❌ Error generating report: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def export_comparison_csv(self, scenario_id: str, output_path: str):
        """Export comparison data to CSV for thesis charts"""
        import csv
        
        comparisons = self.compare_all_routes(scenario_id)
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Route ID', 'Route Name', 
                'Real Travel Time (s)', 'Simulated Travel Time (s)',
                'Absolute Error (s)', 'Percentage Error (%)',
                'Real Samples', 'Simulation Samples'
            ])
            
            for comp in comparisons:
                writer.writerow([
                    comp.route_id,
                    comp.route_name,
                    comp.real_travel_time,
                    comp.simulated_travel_time,
                    comp.absolute_error,
                    comp.percentage_error,
                    comp.real_samples,
                    comp.sim_samples
                ])
        
        print(f"[COMPARISON] Exported to {output_path}")