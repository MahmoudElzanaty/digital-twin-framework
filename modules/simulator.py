"""
Updated Simulator with Dynamic Calibration and Fixed Route Tracking
REPLACES simulator.py
"""
import os
import traci
from datetime import datetime
from modules.logger import TrafficLogger
from modules.route_tracker import RouteMonitor  # Use FIXED version
from modules.dynamic_calibrator import DynamicCalibrator  # NEW!
from modules.database import get_db
from modules.area_comparison import AreaBasedComparison

def create_config(net_file, route_file, cfg_path):
    """Create SUMO configuration file"""
    net_rel = os.path.relpath(net_file, start=os.path.dirname(cfg_path))
    route_rel = os.path.relpath(route_file, start=os.path.dirname(cfg_path))

    cfg_content = f"""<configuration>
    <input>
        <net-file value="{net_rel}"/>
        <route-files value="{route_rel}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
    </processing>
</configuration>"""
    
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    
    return cfg_path


def run_simulation(
    cfg_file, 
    gui=True, 
    scenario_id=None, 
    enable_digital_twin=True,
    enable_dynamic_calibration=False  # NEW OPTION!
):
    """
    Run SUMO simulation with ALL enhanced features:
    - Fixed route tracking (spatial matching)
    - Dynamic calibration (real-time adjustment)
    - Area-based comparison
    - Digital twin validation
    
    Args:
        cfg_file: Path to SUMO config file
        gui: Whether to use GUI
        scenario_id: Unique ID for this simulation run
        enable_digital_twin: Enable route monitoring and comparison
        enable_dynamic_calibration: Enable real-time parameter adjustment
    """
    # Generate scenario ID if not provided
    if scenario_id is None:
        scenario_id = f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print("\n" + "="*70)
    print(f"STARTING SIMULATION: {scenario_id}")
    print("="*70)
    print(f"Config file: {cfg_file}")
    print(f"GUI: {gui}")
    print(f"Digital Twin: {enable_digital_twin}")
    print(f"Dynamic Calibration: {enable_dynamic_calibration}")
    print("="*70 + "\n")
    
    # Start SUMO
    sumo_binary = "sumo-gui" if gui else "sumo"
    traci.start([sumo_binary, "-c", cfg_file])
    
    step = 0

    # Standard traffic logging
    logger = TrafficLogger(log_dir="data/logs", interval=10)

    # FIXED ROUTE MONITORING
    route_monitor = None
    if enable_digital_twin:
        try:
            route_monitor = RouteMonitor()
            
            # CRITICAL: Initialize route mappings AFTER SUMO starts
            if not route_monitor.initialize_routes():
                print("[SIMULATOR] ⚠️ Route monitoring disabled - no routes mapped")
                route_monitor = None
            else:
                print(f"[SIMULATOR] ✅ Route monitoring enabled")
                
        except Exception as e:
            print(f"[SIMULATOR] ⚠️ Could not enable route monitoring: {e}")
            route_monitor = None

    # DYNAMIC CALIBRATION (NEW!)
    dynamic_calib = None
    if enable_dynamic_calibration:
        try:
            dynamic_calib = DynamicCalibrator(
                update_interval=300,  # Update every 5 sim-minutes
                learning_rate=0.1,
                window_size=10
            )
            print(f"[SIMULATOR] ✅ Dynamic calibration enabled")
            
        except Exception as e:
            print(f"[SIMULATOR] ⚠️ Could not enable dynamic calibration: {e}")
            dynamic_calib = None

    print("[SIMULATOR] Simulation running...")
    
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
            
            # Standard logging
            logger.log_step(step)
            
            # ROUTE MONITORING (Fixed version)
            if route_monitor:
                route_monitor.update(step)
            
            # DYNAMIC CALIBRATION (Real-time adjustment!)
            if dynamic_calib:
                updated = dynamic_calib.update(step)
                if updated:
                    print(f"[SIMULATOR] 🎯 Parameters updated at step {step}")
            
            # Progress updates
            if step % 100 == 0:
                status = f"Step {step}"
                
                if route_monitor:
                    tracker_stats = route_monitor.tracker.get_stats()
                    status += f" | Tracking: {tracker_stats['active_vehicles']} active, {tracker_stats['completed_vehicles']} completed"
                
                if dynamic_calib and dynamic_calib.last_sim_speed:
                    status += f" | Sim speed: {dynamic_calib.last_sim_speed:.1f} km/h"
                
                print(f"[SIMULATOR] {status}")
                
    finally:
        print("\n[SIMULATOR] Simulation ending, finalizing results...")
        
        # Save standard logs
        logger.close()
        
        # ROUTE MONITORING RESULTS
        if route_monitor:
            try:
                # Print summary
                route_monitor.print_summary()
                
                # Save to database
                route_monitor.save_results_to_db(scenario_id)
                
                # Coverage report (for debugging)
                coverage = route_monitor.get_coverage_report()
                print(f"\n[SIMULATOR] Coverage: {coverage['routes_with_data']}/{coverage['total_routes']} routes have data")
                
                if coverage['routes_without_data']:
                    print(f"[SIMULATOR] Routes without data: {', '.join(coverage['routes_without_data'][:3])}...")
                    
            except Exception as e:
                print(f"[SIMULATOR] ⚠️ Error in route monitoring results: {e}")
        
        # DYNAMIC CALIBRATION RESULTS
        if dynamic_calib:
            try:
                # Print calibration report
                dynamic_calib.print_report()
                
                # Save to database
                dynamic_calib.save_to_database(scenario_id)
                
            except Exception as e:
                print(f"[SIMULATOR] ⚠️ Error in dynamic calibration results: {e}")
        
        # AREA-BASED COMPARISON (Works even without route matching!)
        print("\n" + "="*70)
        print("DIGITAL TWIN: Area-based comparison with real-world data")
        print("="*70)
        
        try:
            area_comp = AreaBasedComparison()
            results = area_comp.compare_area_metrics(
                scenario_id=scenario_id,
                log_file="data/logs/edge_state.csv"
            )
            
            if results:
                print(f"\n💾 Digital twin comparison completed")
                print(f"📊 Scenario ID: {scenario_id}")
                print(f"📈 Speed accuracy: {results['comparison']['speed_error_pct']:.1f}% error")
                print(f"📈 Congestion similarity: {results['comparison']['congestion_similarity']:.1f}%")
                
                # Export detailed report
                area_comp.export_comparison_report(scenario_id, f"data/reports/report_{scenario_id}.txt")
                
        except Exception as e:
            print(f"[SIMULATOR] ⚠️ Could not perform area comparison")
            print(f"[SIMULATOR]    Error: {e}")
            print(f"[SIMULATOR]    Note: Collect real data using: python setup_digital_twin.py")
        
        # Close TraCI
        traci.close()
        
        print("\n" + "="*70)
        print(f"✅ SIMULATION COMPLETE: {scenario_id}")
        print("="*70)
        
        # Summary
        print(f"\nResults saved:")
        print(f"  - Traffic logs: data/logs/edge_state.csv")
        print(f"  - Route tracking: Database (scenario: {scenario_id})")
        if dynamic_calib:
            print(f"  - Dynamic calibration: Database")
        print(f"  - Comparison report: data/reports/report_{scenario_id}.txt")
        
        print(f"\nNext steps:")
        print(f"  1. View detailed comparison: python testsim.py")
        print(f"  2. Run digital twin tests: python test_digital_twin_comparison.py --quick")
        print(f"  3. Analyze results in GUI: Results & Analysis tab")
        
        return scenario_id


# Convenience wrapper for backward compatibility
def run_simulation_simple(cfg_file, gui=True):
    """Simple simulation without digital twin features"""
    return run_simulation(cfg_file, gui=gui, enable_digital_twin=False)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cfg = sys.argv[1]
        use_gui = "--nogui" not in sys.argv
        use_dynamic = "--dynamic" in sys.argv
        
        run_simulation(
            cfg, 
            gui=use_gui,
            enable_dynamic_calibration=use_dynamic
        )