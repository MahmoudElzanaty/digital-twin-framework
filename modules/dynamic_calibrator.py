"""
Dynamic Calibration System
Adjusts SUMO parameters IN REAL-TIME based on ongoing simulation performance
This is ADAPTIVE calibration - learns while simulating!
"""
import numpy as np
from typing import Dict, List, Tuple
from collections import deque
import traci
from modules.database import get_db
from modules.area_comparison import AreaBasedComparison

class DynamicCalibrator:
    """
    Real-time calibration that adjusts parameters during simulation
    Uses online learning to minimize error continuously
    """

    def __init__(
        self,
        update_interval: int = 300,  # Adjust every 300 simulation steps (5 min)
        learning_rate: float = 0.1,   # How aggressively to adjust
        window_size: int = 10,        # Keep last N measurements
        scenario_id: str = None,      # Scenario ID for area-specific data
        initial_params: Dict[str, float] = None  # Initial parameters from traffic configurator
    ):
        self.db = get_db()
        self.comparison = AreaBasedComparison(self.db)
        self.scenario_id = scenario_id

        self.update_interval = update_interval
        self.learning_rate = learning_rate
        self.window_size = window_size

        # Current parameters (use provided initial params or defaults)
        if initial_params:
            self.current_params = initial_params.copy()
            print(f"[DYNAMIC_CALIB] Starting with configured parameters:")
            print(f"[DYNAMIC_CALIB]   tau: {self.current_params['tau']:.2f}")
            print(f"[DYNAMIC_CALIB]   speedFactor: {self.current_params['speedFactor']:.2f}")
            print(f"[DYNAMIC_CALIB]   sigma: {self.current_params['sigma']:.2f}")
        else:
            # Fallback to defaults
            self.current_params = {
                'tau': 1.0,
                'accel': 2.6,
                'decel': 4.5,
                'sigma': 0.5,
                'speedFactor': 1.0
            }
        
        # Parameter bounds (Cairo-specific - allow wider range for congestion)
        self.param_bounds = {
            'tau': (0.5, 1.5),
            'accel': (1.5, 4.5),
            'decel': (3.5, 6.0),
            'sigma': (0.2, 0.9),
            'speedFactor': (0.5, 1.3)  # Allow down to 0.5 for heavy congestion!
        }
        
        # Performance history
        self.error_history = deque(maxlen=window_size)
        self.param_history = []
        
        # Real-time metrics
        self.last_real_speed = None
        self.last_sim_speed = None
        
        print("[DYNAMIC_CALIB] Initialized dynamic calibration system")
        print(f"[DYNAMIC_CALIB] Update interval: {update_interval} steps")
        print(f"[DYNAMIC_CALIB] Learning rate: {learning_rate}")
    
    def get_current_simulation_metrics(self) -> Dict:
        """
        Get current simulation metrics from running SUMO
        This is called during the simulation!
        """
        try:
            all_edges = [e for e in traci.edge.getIDList() if not e.startswith(':')]
            
            if not all_edges:
                return {}
            
            speeds = []
            occupancies = []
            vehicle_counts = []
            
            for edge_id in all_edges:
                speed = traci.edge.getLastStepMeanSpeed(edge_id)
                occupancy = traci.edge.getLastStepOccupancy(edge_id)
                num_veh = traci.edge.getLastStepVehicleNumber(edge_id)
                
                speeds.append(speed * 3.6)  # m/s to km/h
                occupancies.append(occupancy)
                vehicle_counts.append(num_veh)
            
            metrics = {
                'avg_speed_kmh': np.mean(speeds) if speeds else 0,
                'median_speed_kmh': np.median(speeds) if speeds else 0,
                'std_speed': np.std(speeds) if speeds else 0,
                'avg_occupancy': np.mean(occupancies) if occupancies else 0,
                'total_vehicles': sum(vehicle_counts),
                'congested_edges': sum(1 for s in speeds if s < 20)
            }
            
            return metrics
            
        except Exception as e:
            print(f"[DYNAMIC_CALIB] Error getting sim metrics: {e}")
            return {}
    
    def get_current_real_metrics(self) -> Dict:
        """
        Get real-world traffic metrics
        Uses freshly collected area-specific data or defaults to typical urban traffic speeds
        """
        try:
            # Priority 1: Try to get area-specific data collected before this simulation
            if self.scenario_id:
                cursor = self.db.conn.cursor()
                cursor.execute("""
                    SELECT speed_kmh
                    FROM real_traffic_data
                    WHERE area_id = ? AND speed_kmh IS NOT NULL
                    ORDER BY timestamp DESC
                """, (self.scenario_id,))
                results = cursor.fetchall()

                if results:
                    speeds = [r['speed_kmh'] for r in results if r['speed_kmh']]
                    if speeds:
                        avg_speed = sum(speeds) / len(speeds)
                        print(f"[DYNAMIC_CALIB] Using fresh real-world data from selected area: {avg_speed:.1f} km/h ({len(speeds)} samples)")
                        return {
                            'avg_speed_kmh': avg_speed,
                            'median_speed_kmh': sorted(speeds)[len(speeds)//2] if len(speeds) > 0 else avg_speed,
                            'std_speed': (sum((s - avg_speed)**2 for s in speeds) / len(speeds))**0.5 if len(speeds) > 1 else 0,
                            'num_samples': len(speeds)
                        }

            # Priority 2: Try recent real_traffic_data from any area
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT speed_kmh
                FROM real_traffic_data
                WHERE speed_kmh IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 10
            """)
            results = cursor.fetchall()

            if results:
                speeds = [r['speed_kmh'] for r in results if r['speed_kmh']]
                if speeds:
                    avg_speed = sum(speeds) / len(speeds)
                    print(f"[DYNAMIC_CALIB] Using recent real-world data: {avg_speed:.1f} km/h ({len(speeds)} samples)")
                    return {
                        'avg_speed_kmh': avg_speed,
                        'median_speed_kmh': sorted(speeds)[len(speeds)//2] if len(speeds) > 0 else avg_speed,
                        'std_speed': 0,
                        'num_samples': len(speeds)
                    }

            # Fallback: Use typical urban traffic speed
            # Based on global studies: urban traffic averages 30-40 km/h
            print(f"[DYNAMIC_CALIB] No real-world data found, using default urban speed: 36.9 km/h")
            default_speed = 36.9  # km/h (typical congested urban speed)
            return {
                'avg_speed_kmh': default_speed,
                'median_speed_kmh': default_speed,
                'std_speed': 0,
                'num_samples': 0
            }

        except Exception as e:
            print(f"[DYNAMIC_CALIB] Error getting real metrics: {e}")
            # Return default urban speed
            return {
                'avg_speed_kmh': 36.9,
                'median_speed_kmh': 36.9,
                'std_speed': 0,
                'num_samples': 0
            }
    
    def calculate_current_error(self) -> float:
        """
        Calculate current speed error between simulation and reality
        This is the optimization target!
        """
        sim_metrics = self.get_current_simulation_metrics()
        real_metrics = self.get_current_real_metrics()
        
        if not sim_metrics or not real_metrics:
            return None
        
        # Store for reporting
        self.last_sim_speed = sim_metrics['avg_speed_kmh']
        self.last_real_speed = real_metrics['avg_speed_kmh']
        
        # Calculate percentage error
        if real_metrics['avg_speed_kmh'] > 0:
            error = abs(sim_metrics['avg_speed_kmh'] - real_metrics['avg_speed_kmh'])
            error_pct = (error / real_metrics['avg_speed_kmh']) * 100
            
            return error_pct
        
        return None
    
    def compute_parameter_gradients(self, current_error: float) -> Dict[str, float]:
        """
        Compute gradients for parameter updates
        Uses heuristic rules based on speed differences

        CRITICAL: Gradients represent the DIRECTION to adjust parameters
        Positive gradient = parameter should INCREASE
        Negative gradient = parameter should DECREASE
        """
        gradients = {}

        if self.last_sim_speed and self.last_real_speed:
            # Speed difference: positive = sim too fast, negative = sim too slow
            speed_error = self.last_sim_speed - self.last_real_speed

            # Gradient descent formula: new = old - learning_rate * gradient
            # So POSITIVE gradient → value DECREASES
            # And NEGATIVE gradient → value INCREASES

            for param in self.current_params:
                if param == 'speedFactor':
                    # speedFactor controls how much vehicles exceed speed limits
                    # If sim too fast → DECREASE speedFactor → need POSITIVE gradient
                    # If sim too slow → INCREASE speedFactor → need NEGATIVE gradient
                    gradients[param] = speed_error * 0.01  # POSITIVE when too fast

                elif param == 'tau':
                    # tau = car-following headway time
                    # Larger tau = more cautious = slower speeds
                    # If sim too fast → INCREASE tau → need NEGATIVE gradient
                    # If sim too slow → DECREASE tau → need POSITIVE gradient
                    gradients[param] = -speed_error * 0.005  # NEGATIVE when too fast

                elif param == 'accel':
                    # Higher acceleration = can reach higher speeds faster
                    # If sim too fast → DECREASE accel → need POSITIVE gradient
                    # If sim too slow → INCREASE accel → need NEGATIVE gradient
                    gradients[param] = speed_error * 0.05  # POSITIVE when too fast

                elif param == 'decel':
                    # Higher decel = can brake harder = more conservative = slower
                    # If sim too fast → INCREASE decel → need NEGATIVE gradient
                    # If sim too slow → DECREASE decel → need POSITIVE gradient
                    gradients[param] = -speed_error * 0.03  # NEGATIVE when too fast

                elif param == 'sigma':
                    # sigma = driver imperfection
                    # Higher sigma = more random = generally slower
                    # If sim too fast → INCREASE sigma → need NEGATIVE gradient
                    # If sim too slow → DECREASE sigma → need POSITIVE gradient
                    gradients[param] = -speed_error * 0.02  # NEGATIVE when too fast

                else:
                    gradients[param] = 0.0
        else:
            # No speed data available, use zero gradients
            gradients = {param: 0.0 for param in self.current_params}

        return gradients
    
    def update_parameters(self, gradients: Dict[str, float]) -> Dict[str, float]:
        """
        Update parameters using gradient descent
        Returns new parameters
        """
        new_params = {}
        
        for param, current_value in self.current_params.items():
            gradient = gradients.get(param, 0.0)
            
            # Gradient descent update
            new_value = current_value - self.learning_rate * gradient
            
            # Clip to bounds
            min_val, max_val = self.param_bounds[param]
            new_value = np.clip(new_value, min_val, max_val)
            
            new_params[param] = new_value
        
        return new_params
    
    def apply_parameters_to_vehicles(self, params: Dict[str, float]):
        """
        Apply new parameters to vehicles in simulation
        This is the MAGIC - changing params during simulation!
        """
        try:
            # Get all vehicles currently in simulation
            vehicle_ids = traci.vehicle.getIDList()
            
            if not vehicle_ids:
                return
            
            # Apply parameters to each vehicle
            for veh_id in vehicle_ids:
                try:
                    # Update car-following parameters
                    traci.vehicle.setTau(veh_id, params['tau'])
                    traci.vehicle.setAccel(veh_id, params['accel'])
                    traci.vehicle.setDecel(veh_id, params['decel'])
                    traci.vehicle.setImperfection(veh_id, params['sigma'])
                    traci.vehicle.setSpeedFactor(veh_id, params['speedFactor'])
                    
                except traci.exceptions.TraCIException:
                    # Some vehicles might not support all parameters
                    pass
            
            print(f"[DYNAMIC_CALIB] ✅ Applied params to {len(vehicle_ids)} vehicles")
            
        except Exception as e:
            print(f"[DYNAMIC_CALIB] Error applying parameters: {e}")
    
    def update(self, current_step: int) -> bool:
        """
        Main update function - call this every simulation step
        Returns True if parameters were updated
        """
        # Only update at intervals
        if current_step % self.update_interval != 0:
            return False
        
        print(f"\n[DYNAMIC_CALIB] === Update at step {current_step} ===")
        
        # Calculate current error
        current_error = self.calculate_current_error()
        
        if current_error is None:
            print(f"[DYNAMIC_CALIB] No error data available yet")
            return False
        
        # Store error
        self.error_history.append(current_error)
        
        print(f"[DYNAMIC_CALIB] Current error: {current_error:.2f}%")
        print(f"[DYNAMIC_CALIB] Real speed: {self.last_real_speed:.1f} km/h")
        print(f"[DYNAMIC_CALIB] Sim speed: {self.last_sim_speed:.1f} km/h")
        
        # Compute gradients
        gradients = self.compute_parameter_gradients(current_error)
        
        # Update parameters
        new_params = self.update_parameters(gradients)
        
        # Show changes
        print(f"[DYNAMIC_CALIB] Parameter updates:")
        for param in self.current_params:
            old_val = self.current_params[param]
            new_val = new_params[param]
            change = new_val - old_val
            if abs(change) > 0.001:
                print(f"[DYNAMIC_CALIB]   {param}: {old_val:.3f} → {new_val:.3f} ({change:+.3f})")
        
        # Apply to simulation
        self.apply_parameters_to_vehicles(new_params)
        
        # Store history
        self.param_history.append({
            'step': current_step,
            'params': new_params.copy(),
            'error': current_error
        })
        
        # Update current parameters
        self.current_params = new_params
        
        return True
    
    def get_final_report(self) -> Dict:
        """
        Generate report after simulation
        Shows calibration progression
        """
        if not self.param_history:
            return {}
        
        initial_error = self.error_history[0] if self.error_history else None
        final_error = self.error_history[-1] if self.error_history else None
        
        improvement = None
        improvement_pct = None
        if initial_error and final_error:
            improvement = initial_error - final_error
            improvement_pct = (improvement / initial_error) * 100

        report = {
            'initial_error': initial_error,
            'final_error': final_error,
            'improvement': improvement,
            'improvement_pct': improvement_pct,
            'num_updates': len(self.param_history),
            'final_params': self.current_params.copy(),
            'error_history': list(self.error_history)
        }
        
        return report
    
    def print_report(self):
        """Print calibration report"""
        report = self.get_final_report()
        
        if not report:
            print("[DYNAMIC_CALIB] No calibration data available")
            return
        
        print("\n" + "="*70)
        print("DYNAMIC CALIBRATION REPORT")
        print("="*70)
        
        if report['initial_error'] and report['final_error']:
            print(f"Initial error: {report['initial_error']:.2f}%")
            print(f"Final error: {report['final_error']:.2f}%")
            
            if report['improvement']:
                print(f"Improvement: {report['improvement']:.2f}% points ({report['improvement_pct']:.1f}%)")
        
        print(f"\nNumber of updates: {report['num_updates']}")
        
        print(f"\nFinal parameters:")
        for param, value in report['final_params'].items():
            print(f"  {param}: {value:.3f}")
        
        print("="*70)
    
    def save_to_database(self, scenario_id: str):
        """Save calibration results to database"""
        report = self.get_final_report()

        if not report or not report['final_params']:
            return

        # Build notes with improvement info
        if report['improvement_pct'] is not None:
            notes = f"Dynamic calibration: {report['num_updates']} updates, " \
                    f"{report['improvement_pct']:.1f}% improvement"
        else:
            notes = f"Dynamic calibration: {report['num_updates']} updates"

        self.db.store_calibration_params(
            scenario_id=scenario_id,
            params=report['final_params'],
            rmse=report['final_error'],
            mae=report['final_error'],
            notes=notes
        )

        print(f"[DYNAMIC_CALIB] Saved results to database for scenario {scenario_id}")