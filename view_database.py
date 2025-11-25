"""
Database Viewer - View all simulation scenarios and results
"""
import sqlite3
import sys

def view_all_scenarios():
    """Display all scenarios from the database"""
    conn = sqlite3.connect('data/digital_twin.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("\n" + "="*100)
    print("DIGITAL TWIN DATABASE - ALL SCENARIOS")
    print("="*100)

    # 1. Validation Metrics (completed simulations with validation)
    print("\n1. VALIDATION METRICS - ALL RECORDS (NO DEDUPLICATION)")
    print("   Shows every single simulation run, even if scenario names repeat")
    print("-"*100)
    cursor.execute("""
        SELECT scenario_id, timestamp, mape, r_squared, num_samples
        FROM validation_metrics
        ORDER BY timestamp DESC
    """)

    validation_results = cursor.fetchall()
    if validation_results:
        print(f"{'Row':<5} {'Scenario ID':<40} {'Date':<20} {'MAPE':<10} {'R²':<10} {'Samples'}")
        print("-"*100)
        for i, row in enumerate(validation_results, 1):
            r2_val = f"{row['r_squared']:.4f}" if row['r_squared'] else "N/A"
            print(f"{i:<5} {row['scenario_id']:<40} {row['timestamp'][:19]:<20} "
                  f"{row['mape']:>7.2f}% {r2_val:>10} {row['num_samples']}")
        print(f"\n>> Total: {len(validation_results)} TOTAL records (duplicates included)")
    else:
        print("No validation metrics found.")

    # 2. Simulation Results (raw simulation outputs)
    print("\n" + "="*100)
    print("2. SIMULATION RESULTS (Raw Route Simulations)")
    print("-"*100)
    cursor.execute("""
        SELECT scenario_id, route_id, timestamp, travel_time_seconds,
               avg_speed_kmh, num_vehicles
        FROM simulation_results
        ORDER BY timestamp DESC
    """)

    sim_results = cursor.fetchall()
    if sim_results:
        print(f"{'#':<4} {'Scenario ID':<30} {'Route ID':<30} {'Speed (km/h)':<15} {'Vehicles'}")
        print("-"*100)
        for i, row in enumerate(sim_results, 1):
            print(f"{i:<4} {row['scenario_id']:<30} {row['route_id']:<30} "
                  f"{row['avg_speed_kmh']:>12.2f} {row['num_vehicles']:>10}")
        print(f"\nTotal: {len(sim_results)} simulation result records")
    else:
        print("No simulation results found.")

    # 3. Calibration Parameters (all simulation runs)
    print("\n" + "="*100)
    print("3. CALIBRATION PARAMETERS - ALL RUNS")
    print("   Shows every simulation run (even incomplete ones without validation)")
    print("-"*100)
    cursor.execute("""
        SELECT DISTINCT scenario_id, timestamp
        FROM calibration_params
        ORDER BY timestamp DESC
    """)

    calibration = cursor.fetchall()
    if calibration:
        print(f"{'Row':<5} {'Scenario ID':<50} {'Date'}")
        print("-"*100)
        for i, row in enumerate(calibration, 1):
            print(f"{i:<5} {row['scenario_id']:<50} {row['timestamp'][:19]}")
        print(f"\n>> Total: {len(calibration)} simulation runs (includes runs without validation)")
    else:
        print("No calibration parameters found.")

    # 4. Summary statistics
    print("\n" + "="*100)
    print("DATABASE SUMMARY - TOTAL RECORDS vs UNIQUE SCENARIOS")
    print("="*100)

    cursor.execute("SELECT COUNT(*) FROM validation_metrics")
    vm_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT scenario_id) FROM validation_metrics")
    vm_unique = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM simulation_results")
    sr_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT scenario_id) FROM simulation_results")
    sr_unique = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM calibration_params")
    cp_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT scenario_id) FROM calibration_params")
    cp_unique = cursor.fetchone()[0]

    print(f"\n{'Table':<25} {'Total Records':<20} {'Unique Scenarios'}")
    print("-"*100)
    print(f"{'Validation Metrics':<25} {vm_count:>15} {vm_unique:>20}")
    print(f"{'Simulation Results':<25} {sr_count:>15} {sr_unique:>20}")
    print(f"{'Calibration Parameters':<25} {cp_count:>15} {cp_unique:>20}")
    print("-"*100)
    print(f"\n>> The GUI shows ALL {vm_count} validation records (not just {vm_unique} unique scenarios)")

    # 5. Best performing scenarios
    print("\n" + "="*100)
    print("TOP 10 BEST PERFORMING SCENARIOS (Lowest MAPE)")
    print("="*100)
    cursor.execute("""
        SELECT scenario_id, timestamp, mape, r_squared
        FROM validation_metrics
        ORDER BY mape ASC
        LIMIT 10
    """)

    best = cursor.fetchall()
    if best:
        print(f"{'Rank':<6} {'Scenario ID':<40} {'MAPE':<12} {'R²':<10} {'Status'}")
        print("-"*100)
        for i, row in enumerate(best, 1):
            r2_val = f"{row['r_squared']:.4f}" if row['r_squared'] else "N/A"
            if row['mape'] < 15:
                status = "Excellent"
            elif row['mape'] < 25:
                status = "Good"
            else:
                status = "Fair"
            print(f"{i:<6} {row['scenario_id']:<40} {row['mape']:>8.2f}% {r2_val:>10} {status}")

    conn.close()
    print("\n" + "="*100)

if __name__ == "__main__":
    try:
        view_all_scenarios()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
