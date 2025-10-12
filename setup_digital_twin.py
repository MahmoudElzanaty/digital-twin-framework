"""
Setup and Initialize Digital Twin System
Creates probe routes for Cairo and tests data collection
"""
import os
import sys
from modules.database import get_db
from modules.data_collector import TrafficDataCollector, TrafficDataAnalyzer

# Get API key from environment variable or user input
def get_api_key():
    """Get Google Maps API key"""
    api_key = os.environ.get('GOOGLE_MAPS_API_KEY')
    
    if not api_key:
        print("=" * 60)
        print("GOOGLE MAPS API KEY REQUIRED")
        print("=" * 60)
        print()
        print("You need a Google Maps API key to collect real traffic data.")
        print("Get one from: https://console.cloud.google.com/")
        print()
        print("You can either:")
        print("1. Set environment variable: GOOGLE_MAPS_API_KEY")
        print("2. Enter it now (it will be saved to .env file)")
        print()
        
        api_key = input("Enter your Google Maps API key: ").strip()
        
        if api_key:
            # Save to .env file
            with open('.env', 'w') as f:
                f.write(f"GOOGLE_MAPS_API_KEY={api_key}\n")
            print("✓ API key saved to .env file")
        else:
            print("❌ No API key provided. Exiting.")
            sys.exit(1)
    
    return api_key

def setup_cairo_probe_routes():
    """
    Set up probe routes in Cairo for monitoring
    These are major routes that will be monitored for real traffic
    """
    db = get_db()
    
    print("\n" + "=" * 60)
    print("SETTING UP CAIRO PROBE ROUTES")
    print("=" * 60)
    
    # Define 5 key routes in Cairo
    cairo_routes = [
        {
            'route_id': 'cairo_tahrir_citystars',
            'name': 'Tahrir Square → City Stars',
            'origin_lat': 30.0444,
            'origin_lon': 31.2357,
            'dest_lat': 30.0727,
            'dest_lon': 31.3497,
            'description': 'Major route from downtown to Nasr City mall'
        },
        {
            'route_id': 'cairo_maadi_zamalek',
            'name': 'Maadi → Zamalek',
            'origin_lat': 29.9602,
            'origin_lon': 31.2569,
            'dest_lat': 30.0618,
            'dest_lon': 31.2197,
            'description': 'Cross-Nile route from Maadi to Zamalek'
        },
        {
            'route_id': 'cairo_airport_tahrir',
            'name': 'Cairo Airport → Tahrir Square',
            'origin_lat': 30.1219,
            'origin_lon': 31.4056,
            'dest_lat': 30.0444,
            'dest_lon': 31.2357,
            'description': 'Airport to city center'
        },
        {
            'route_id': 'cairo_giza_downtown',
            'name': 'Giza Pyramids → Downtown Cairo',
            'origin_lat': 29.9792,
            'origin_lon': 31.1342,
            'dest_lat': 30.0444,
            'dest_lon': 31.2357,
            'description': 'Tourist route from pyramids to downtown'
        },
        {
            'route_id': 'cairo_ring_road_segment',
            'name': 'Ring Road: Nasr City → 6th October',
            'origin_lat': 30.0444,
            'origin_lon': 31.3369,
            'dest_lat': 30.0131,
            'dest_lon': 31.2089,
            'description': 'Major highway segment'
        }
    ]
    
    for route in cairo_routes:
        db.add_probe_route(
            route_id=route['route_id'],
            name=route['name'],
            origin_lat=route['origin_lat'],
            origin_lon=route['origin_lon'],
            dest_lat=route['dest_lat'],
            dest_lon=route['dest_lon'],
            description=route['description']
        )
        print(f"✓ Added: {route['name']}")
    
    print(f"\n✅ Created {len(cairo_routes)} probe routes")
    return cairo_routes

def test_single_collection(api_key):
    """Test collecting data for all routes once"""
    print("\n" + "=" * 60)
    print("TESTING DATA COLLECTION")
    print("=" * 60)
    
    collector = TrafficDataCollector(api_key)
    
    print("\nCollecting current traffic data...")
    results = collector.collect_all_probe_routes()
    
    print(f"\n✅ Successfully collected data for {len(results)} routes")
    
    # Show summary
    analyzer = TrafficDataAnalyzer()
    analyzer.print_collection_summary()
    
    return results

def show_database_stats():
    """Display database statistics"""
    db = get_db()
    stats = db.get_summary_stats()
    
    print("\n" + "=" * 60)
    print("DATABASE STATISTICS")
    print("=" * 60)
    print(f"Active probe routes: {stats['active_routes']}")
    print(f"Real data points collected: {stats['real_data_points']}")
    print(f"Simulation results: {stats['simulation_results']}")
    print(f"Scenarios created: {stats['scenarios']}")
    print("=" * 60)

def main_menu(api_key):
    """Interactive menu"""
    while True:
        print("\n" + "=" * 60)
        print("DIGITAL TWIN SETUP & TESTING")
        print("=" * 60)
        print("1. Setup Cairo probe routes")
        print("2. Test single data collection")
        print("3. Start continuous collection (15 min intervals)")
        print("4. View database statistics")
        print("5. View collection summary")
        print("6. Exit")
        print("=" * 60)
        
        choice = input("\nChoose an option (1-6): ").strip()
        
        if choice == '1':
            setup_cairo_probe_routes()
        
        elif choice == '2':
            test_single_collection(api_key)
        
        elif choice == '3':
            print("\nHow long to collect? (hours, 0 = infinite)")
            try:
                hours = float(input("Duration (hours): ").strip() or "2")
                collector = TrafficDataCollector(api_key)
                collector.start_continuous_collection(
                    interval_minutes=15,
                    duration_hours=hours
                )
            except ValueError:
                print("❌ Invalid duration")
            except KeyboardInterrupt:
                print("\n⚠️  Collection stopped by user")
        
        elif choice == '4':
            show_database_stats()
        
        elif choice == '5':
            analyzer = TrafficDataAnalyzer()
            analyzer.print_collection_summary()
        
        elif choice == '6':
            print("\n👋 Goodbye!")
            break
        
        else:
            print("❌ Invalid choice")

def quick_start():
    """Quick start: setup and do one test collection"""
    print("\n" + "=" * 60)
    print("🚀 DIGITAL TWIN QUICK START")
    print("=" * 60)
    
    # Get API key
    api_key = get_api_key()
    
    # Setup database and routes
    setup_cairo_probe_routes()
    
    # Do one test collection
    test_single_collection(api_key)
    
    # Show stats
    show_database_stats()
    
    print("\n✅ Quick start complete!")
    print("\nNext steps:")
    print("1. Review the collected data")
    print("2. Start continuous collection to gather more data")
    print("3. Integrate with your simulation for comparison")
    
    # Ask if they want to continue with menu
    response = input("\nOpen interactive menu? (y/n): ").strip().lower()
    if response == 'y':
        main_menu(api_key)

if __name__ == "__main__":
    try:
        # Try to load .env file if it exists
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass  # dotenv not installed, that's okay
        
        # Check command line arguments
        if len(sys.argv) > 1 and sys.argv[1] == '--quick':
            quick_start()
        else:
            api_key = get_api_key()
            main_menu(api_key)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)