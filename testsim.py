"""
Test Area-Based Comparison
Use this to test the digital twin comparison on your last simulation
"""
import sys
from modules.area_comparison import AreaBasedComparison
from modules.database import get_db

def find_latest_scenario():
    """Find the most recent scenario in database"""
    db = get_db()
    
    # Get all validation metrics ordered by timestamp
    import sqlite3
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT DISTINCT scenario_id, timestamp 
        FROM validation_metrics 
        ORDER BY timestamp DESC 
        LIMIT 1
    """)
    result = cursor.fetchone()
    
    if result:
        return result['scenario_id']
    
    # If no validation metrics, try simulation results
    cursor.execute("""
        SELECT DISTINCT scenario_id, timestamp 
        FROM simulation_results 
        ORDER BY timestamp DESC 
        LIMIT 1
    """)
    result = cursor.fetchone()
    
    if result:
        return result['scenario_id']
    
    return None

def test_last_simulation():
    """Test comparison on the last simulation"""
    print("="*70)
    print("TESTING AREA-BASED COMPARISON")
    print("="*70)
    print()
    
    # Find latest scenario
    scenario_id = find_latest_scenario()
    
    if not scenario_id:
        print("❌ No simulation scenarios found in database")
        print()
        print("To test:")
        print("1. Run a simulation using app_desktop.py")
        print("2. Then run this test script again")
        return
    
    print(f"Testing scenario: {scenario_id}")
    print()
    
    # Run comparison
    comp = AreaBasedComparison()
    results = comp.compare_area_metrics(
        scenario_id=scenario_id,
        log_file="data/logs/edge_state.csv"
    )
    
    if results:
        print("\n✅ Area-based comparison successful!")
        print(f"\nKey Results:")
        print(f"  Speed Error: {results['comparison']['speed_error_pct']:.2f}%")
        print(f"  Congestion Similarity: {results['comparison']['congestion_similarity']:.1f}%")
        
        # Export report
        comp.export_comparison_report(scenario_id, f"report_{scenario_id}.txt")
    else:
        print("\n❌ Comparison failed - check if you have both:")
        print("   1. Simulation logs (data/logs/edge_state.csv)")
        print("   2. Real-world data (run: python setup_digital_twin.py)")

def test_specific_scenario(scenario_id: str):
    """Test comparison on a specific scenario"""
    comp = AreaBasedComparison()
    results = comp.compare_area_metrics(scenario_id, "data/logs/edge_state.csv")
    
    if results:
        comp.export_comparison_report(scenario_id)

def show_all_scenarios():
    """List all available scenarios"""
    db = get_db()
    
    print("="*70)
    print("ALL SCENARIOS IN DATABASE")
    print("="*70)
    print()
    
    import sqlite3
    cursor = db.conn.cursor()
    
    # Get unique scenarios from validation metrics
    cursor.execute("""
        SELECT scenario_id, timestamp, mae, mape
        FROM validation_metrics
        ORDER BY timestamp DESC
    """)
    
    results = cursor.fetchall()
    
    if results:
        print(f"{'Scenario ID':<40} {'Timestamp':<20} {'Speed Error %':<15}")
        print("-"*70)
        for row in results:
            print(f"{row['scenario_id']:<40} {row['timestamp'][:19]:<20} {row['mape']:<15.2f}")
    else:
        print("No scenarios with validation metrics found")
    
    print()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            show_all_scenarios()
        else:
            test_specific_scenario(sys.argv[1])
    else:
        test_last_simulation()