"""
End-to-End Digital Twin Test
Tests the complete workflow: collect real data → run simulation → compare
"""
import os
import sys
import time
from datetime import datetime
from modules.database import get_db
from modules.data_collector import TrafficDataCollector
from modules.comparison_engine import ComparisonEngine

def test_digital_twin_workflow():
    """
    Complete workflow test
    This demonstrates the digital twin concept
    """
    print("\n" + "="*70)
    print("DIGITAL TWIN END-TO-END TEST")
    print("="*70)
    print()
    
    # Get API key
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not api_key:
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('GOOGLE_MAPS_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        break
        except:
            pass
    
    if not api_key:
        print("❌ API key not found. Run setup_digital_twin.py first!")
        return False
    
    db = get_db()
    collector = TrafficDataCollector(api_key)
    comparison = ComparisonEngine(db)
    
    # Step 1: Check if we have probe routes
    print("STEP 1: Checking probe routes...")
    routes = db.get_probe_routes()
    if not routes:
        print("❌ No probe routes! Run setup_digital_twin.py option 1 first")
        return False
    print(f"✅ Found {len(routes)} probe routes")
    print()
    
    # Step 2: Check if we have real data
    print("STEP 2: Checking real traffic data...")
    stats = db.get_summary_stats()
    if stats['real_data_points'] == 0:
        print("⚠️  No real data yet. Collecting now...")
        collector.collect_all_probe_routes()
        stats = db.get_summary_stats()
    
    print(f"✅ Have {stats['real_data_points']} real data points")
    print()
    
    # Step 3: Check simulation results
    print("STEP 3: Checking simulation results...")
    if stats['simulation_results'] == 0:
        print("⚠️  No simulation data yet.")
        print()
        print("TO COMPLETE THE TEST:")
        print("1. Run your simulation using app_desktop.py")
        print("2. The simulation should track vehicles on probe routes")
        print("3. Re-run this test script")
        print()
        print("For now, we'll create MOCK simulation data for demonstration...")
        print()
        
        # Create mock simulation data
        create_mock_simulation_data(db, routes)
        stats = db.get_summary_stats()
    
    print(f"✅ Have {stats['simulation_results']} simulation results")
    print()
    
    # Step 4: Compare and validate
    print("STEP 4: Comparing simulation vs real data...")
    print()
    
    scenario_id = "test_scenario"
    comparison.print_comparison_report(scenario_id)
    
    return True

def create_mock_simulation_data(db, routes):
    """
    Create mock simulation data for testing
    In reality, this comes from running SUMO simulation
    """
    print("Creating mock simulation data...")
    scenario_id = "test_scenario"
    
    # Get real data to create realistic mock sim data
    for route in routes[:5]:  # Just first 5 routes
        route_id = route['route_id']
        
        # Get real data
        real_data = db.get_real_traffic_data(route_id=route_id, limit=1)
        if not real_data:
            continue
        
        real_tt = real_data[0]['travel_time_seconds']
        
        # Create simulation result that's within 10-30% of real data
        # This simulates an uncalibrated but reasonable simulation
        import random
        sim_tt = real_tt * random.uniform(0.85, 1.25)
        
        db.store_simulation_result(
            scenario_id=scenario_id,
            route_id=route_id,
            travel_time_seconds=sim_tt,
            distance_meters=real_data[0]['distance_meters'],
            avg_speed_kmh=(real_data[0]['distance_meters'] / 1000) / (sim_tt / 3600),
            num_vehicles=10
        )
    
    print(f"✅ Created mock simulation data for {len(routes[:5])} routes")

def continuous_data_collection_test(hours=1):
    """
    Test continuous data collection
    Useful for gathering baseline data for your thesis
    """
    print("\n" + "="*70)
    print(f"CONTINUOUS DATA COLLECTION TEST ({hours} hour{'s' if hours != 1 else ''})")
    print("="*70)
    print()
    
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    if not api_key:
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('GOOGLE_MAPS_API_KEY='):
                        api_key = line.split('=', 1)[1].strip()
                        break
        except:
            pass
    
    if not api_key:
        print("❌ API key not found")
        return
    
    collector = TrafficDataCollector(api_key)
    
    print(f"Starting continuous collection for {hours} hour(s)...")
    print("Collecting data every 15 minutes")
    print("Press Ctrl+C to stop early")
    print()
    
    try:
        collector.start_continuous_collection(
            interval_minutes=15,
            duration_hours=hours
        )
    except KeyboardInterrupt:
        print("\n⚠️  Collection stopped by user")
    
    # Show summary
    from modules.data_collector import TrafficDataAnalyzer
    analyzer = TrafficDataAnalyzer()
    analyzer.print_collection_summary()

def quick_comparison_test():
    """Quick test - just show current comparison status"""
    print("\n" + "="*70)
    print("QUICK COMPARISON STATUS")
    print("="*70)
    
    db = get_db()
    stats = db.get_summary_stats()
    
    print(f"\nCurrent Status:")
    print(f"  Probe routes: {stats['active_routes']}")
    print(f"  Real data points: {stats['real_data_points']}")
    print(f"  Simulation results: {stats['simulation_results']}")
    print()
    
    if stats['real_data_points'] > 0 and stats['simulation_results'] > 0:
        comparison = ComparisonEngine(db)
        comparison.print_comparison_report("test_scenario")
    else:
        print("⚠️  Need both real data AND simulation results to compare")
        if stats['real_data_points'] == 0:
            print("   Run: python setup_digital_twin.py (option 2)")
        if stats['simulation_results'] == 0:
            print("   Run your simulation with app_desktop.py")

def main_menu():
    """Interactive menu for testing"""
    while True:
        print("\n" + "="*70)
        print("DIGITAL TWIN TESTING MENU")
        print("="*70)
        print("1. Quick comparison status")
        print("2. Full end-to-end test")
        print("3. Collect real data (1 hour continuous)")
        print("4. Collect real data (custom duration)")
        print("5. Export comparison to CSV")
        print("6. Exit")
        print("="*70)
        
        choice = input("\nChoose an option (1-6): ").strip()
        
        if choice == '1':
            quick_comparison_test()
        
        elif choice == '2':
            test_digital_twin_workflow()
        
        elif choice == '3':
            continuous_data_collection_test(hours=1)
        
        elif choice == '4':
            try:
                hours = float(input("How many hours? ").strip())
                continuous_data_collection_test(hours=hours)
            except ValueError:
                print("❌ Invalid duration")
        
        elif choice == '5':
            output = input("Output file path (default: comparison.csv): ").strip()
            if not output:
                output = "comparison.csv"
            comparison = ComparisonEngine()
            try:
                comparison.export_comparison_csv("test_scenario", output)
                print(f"✅ Exported to {output}")
            except Exception as e:
                print(f"❌ Error: {e}")
        
        elif choice == '6':
            print("\n👋 Goodbye!")
            break
        
        else:
            print("❌ Invalid choice")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--quick':
            quick_comparison_test()
        elif sys.argv[1] == '--full':
            test_digital_twin_workflow()
        elif sys.argv[1] == '--collect':
            hours = float(sys.argv[2]) if len(sys.argv) > 2 else 1
            continuous_data_collection_test(hours)
        else:
            print("Usage:")
            print("  python test_digital_twin_comparison.py           # Interactive menu")
            print("  python test_digital_twin_comparison.py --quick   # Quick status")
            print("  python test_digital_twin_comparison.py --full    # Full test")
            print("  python test_digital_twin_comparison.py --collect [hours]")
    else:
        main_menu()