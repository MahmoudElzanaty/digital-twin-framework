"""
Simplified Simulator with Dynamic Calibration
Automatically generates routes from network topology
"""
import os
import traci
from datetime import datetime
from modules.logger import TrafficLogger
from modules.dynamic_calibrator import DynamicCalibrator
from modules.database import get_db
from modules.area_comparison import AreaBasedComparison

def create_config(net_file, route_file, cfg_path, sim_time=3600):
    """Create SUMO configuration file with anti-deadlock settings"""
    net_rel = os.path.relpath(net_file, start=os.path.dirname(cfg_path))
    route_rel = os.path.relpath(route_file, start=os.path.dirname(cfg_path))

    cfg_content = f"""<configuration>
    <input>
        <net-file value="{net_rel}"/>
        <route-files value="{route_rel}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{sim_time}"/>
        <step-length value="1"/>
    </time>
    <processing>
        <time-to-teleport value="300"/>
        <time-to-teleport.highways value="120"/>
        <max-depart-delay value="300"/>
        <collision.action value="teleport"/>
        <collision.mingap-factor value="0.5"/>
        <routing-algorithm value="dijkstra"/>
    </processing>
    <report>
        <verbose value="true"/>
        <duration-log.statistics value="true"/>
        <no-step-log value="true"/>
    </report>
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
    enable_dynamic_calibration=True,  # ENABLED BY DEFAULT - Real-time parameter adjustment!
    initial_params=None  # Cairo parameters from traffic configurator
):
    """
    Run SUMO simulation with enhanced features:
    - Dynamic calibration (real-time adjustment) - ENABLED BY DEFAULT!
    - Area-based comparison with real-world data
    - Traffic pattern analysis

    Args:
        cfg_file: Path to SUMO config file
        gui: Whether to use GUI
        scenario_id: Unique ID for this simulation run
        enable_digital_twin: Enable area-based comparison with real data
        enable_dynamic_calibration: Enable real-time parameter adjustment (default: True)
        initial_params: Initial vehicle parameters (from traffic configurator)
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

    # Standard traffic logging (interval=50 for better performance on large networks)
    logger = TrafficLogger(log_dir="data/logs", interval=50)

    # DYNAMIC CALIBRATION - Real-time parameter optimization
    dynamic_calib = None
    if enable_dynamic_calibration:
        try:
            dynamic_calib = DynamicCalibrator(
                update_interval=300,  # Update every 5 sim-minutes
                learning_rate=0.1,
                window_size=10,
                scenario_id=scenario_id,  # Pass scenario_id for area-specific data
                initial_params=initial_params  # Start with Cairo parameters!
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

            # DYNAMIC CALIBRATION (Real-time adjustment!)
            if dynamic_calib:
                updated = dynamic_calib.update(step)
                if updated:
                    print(f"[SIMULATOR] 🎯 Parameters updated at step {step}")

            # Progress updates
            if step % 100 == 0:
                status = f"Step {step}"

                if dynamic_calib and dynamic_calib.last_sim_speed:
                    status += f" | Sim speed: {dynamic_calib.last_sim_speed:.1f} km/h"

                print(f"[SIMULATOR] {status}")
                
    finally:
        print("\n[SIMULATOR] Simulation ending, finalizing results...")
        
        # Save standard logs
        logger.close()

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
        if dynamic_calib:
            print(f"  - Dynamic calibration: Database")
        print(f"  - Comparison report: data/reports/report_{scenario_id}.txt")

        print(f"\nNext steps:")
        print(f"  1. Analyze results in GUI: Results & Analysis tab")
        print(f"  2. View calibration improvements")
        print(f"  3. Compare with real-world data")
        
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