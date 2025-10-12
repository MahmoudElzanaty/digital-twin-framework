import os
import traci
from modules.logger import TrafficLogger
from modules.route_tracker import RouteMonitor
from modules.database import get_db
from datetime import datetime

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
</configuration>"""
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    return cfg_path


def run_simulation(cfg_file, gui=True, scenario_id=None, enable_digital_twin=True):
    """
    Run SUMO simulation with optional Digital Twin monitoring
    
    Args:
        cfg_file: Path to SUMO config file
        gui: Whether to use GUI
        scenario_id: Unique ID for this simulation run
        enable_digital_twin: Enable route monitoring and comparison
    """
    # Generate scenario ID if not provided
    if scenario_id is None:
        scenario_id = f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    sumo_binary = "sumo-gui" if gui else "sumo"
    traci.start([sumo_binary, "-c", cfg_file])
    step = 0

    # Standard traffic logging
    logger = TrafficLogger(log_dir="data/logs", interval=10)

    # DIGITAL TWIN: Route monitoring
    route_monitor = None
    if enable_digital_twin:
        try:
            route_monitor = RouteMonitor()
            route_monitor.load_probe_routes_from_db()
            print(f"[DIGITAL TWIN] Route monitoring enabled for scenario: {scenario_id}")
            print(f"[DIGITAL TWIN] Monitoring {len(route_monitor.probe_routes)} probe routes")
        except Exception as e:
            print(f"[DIGITAL TWIN] Warning: Could not enable route monitoring: {e}")
            route_monitor = None

    print("[SIM] Simulation started ...")
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
            
            # Standard logging
            logger.log_step(step)
            
            # DIGITAL TWIN: Update route monitoring
            if route_monitor:
                route_monitor.update(step)
            
            if step % 100 == 0:
                print(f"[SIM] Step {step}")
                
    finally:
        # Save standard logs
        logger.close()
        
        # DIGITAL TWIN: Save and compare results
        if route_monitor:
            try:
                # Save simulation results to database (route-based, may be 0)
                route_monitor.save_results_to_db(scenario_id)
                
                # Print route monitoring summary
                route_monitor.print_summary()
                
                # AREA-BASED COMPARISON (works even without matching routes!)
                print("\n" + "="*70)
                print("DIGITAL TWIN: Area-based comparison with real-world data...")
                print("="*70)
                
                from modules.area_comparison import AreaBasedComparison
                area_comp = AreaBasedComparison()
                
                try:
                    results = area_comp.compare_area_metrics(
                        scenario_id=scenario_id,
                        log_file="data/logs/edge_state.csv"
                    )
                    
                    if results:
                        print("\n💾 Digital twin comparison completed and saved")
                        print(f"📊 Scenario ID: {scenario_id}")
                        print(f"📈 Speed accuracy: {results['comparison']['speed_error_pct']:.1f}% error")
                        print(f"📈 Congestion similarity: {results['comparison']['congestion_similarity']:.1f}%")
                    
                except Exception as e:
                    print(f"[DIGITAL TWIN] Note: Could not compare with real data")
                    print(f"               Error: {e}")
                    print(f"               Collect real data using: python setup_digital_twin.py")
                    
            except Exception as e:
                print(f"[DIGITAL TWIN] Warning: Error in digital twin comparison: {e}")
        
        # Close TraCI
        traci.close()
        print("[SIM] Simulation ended.")
        
        return scenario_id


def run_simulation_simple(cfg_file, gui=True):
    """
    Simple simulation without digital twin features
    Backward compatible with original code
    """
    return run_simulation(cfg_file, gui=gui, enable_digital_twin=False)


# For backward compatibility
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cfg = sys.argv[1]
        use_gui = "--nogui" not in sys.argv
        run_simulation(cfg, gui=use_gui)