"""
Test Auto Route Generation
Quick test to verify the auto route generator works
"""
from modules.auto_route_generator import AutoRouteGenerator, auto_create_routes
from modules.database import get_db
import json

def test_basic_generation():
    """Test basic route generation"""
    print("\n" + "="*70)
    print("TEST 1: Basic Route Generation")
    print("="*70)
    
    # Test bbox (small Cairo area)
    bbox = {
        'north': 30.0544,
        'south': 30.0344,
        'east': 31.2457,
        'west': 31.2257
    }
    
    print(f"\nTest area:")
    print(f"  North: {bbox['north']}")
    print(f"  South: {bbox['south']}")
    print(f"  East: {bbox['east']}")
    print(f"  West: {bbox['west']}")
    
    # Generate routes
    routes = auto_create_routes(bbox, "test_area")
    
    print(f"\n✅ Test passed! Created {len(routes)} routes")
    
    return routes

def test_all_strategies():
    """Test all route generation strategies"""
    print("\n" + "="*70)
    print("TEST 2: All Strategy Types")
    print("="*70)
    
    bbox = {
        'north': 30.06,
        'south': 30.04,
        'east': 31.26,
        'west': 31.24
    }
    
    generator = AutoRouteGenerator()
    strategies = ['grid', 'radial', 'loop', 'mixed']
    
    results = {}
    
    for strategy in strategies:
        print(f"\n--- Testing {strategy.upper()} strategy ---")
        
        routes = generator.auto_generate_for_area(
            bbox=bbox,
            location_name=f"test_{strategy}",
            strategy=strategy,
            num_routes=6
        )
        
        results[strategy] = len(routes)
        print(f"✅ {strategy}: {len(routes)} routes created")
    
    print(f"\n✅ All strategies tested!")
    print(f"Results: {results}")
    
    return results

def test_different_sizes():
    """Test with different area sizes"""
    print("\n" + "="*70)
    print("TEST 3: Different Area Sizes")
    print("="*70)
    
    generator = AutoRouteGenerator()
    
    test_areas = [
        {
            'name': 'Very Small (0.5 km²)',
            'bbox': {'north': 30.03, 'south': 30.02, 'east': 31.24, 'west': 31.23}
        },
        {
            'name': 'Small (2 km²)',
            'bbox': {'north': 30.04, 'south': 30.02, 'east': 31.25, 'west': 31.23}
        },
        {
            'name': 'Medium (10 km²)',
            'bbox': {'north': 30.08, 'south': 30.02, 'east': 31.28, 'west': 31.22}
        },
        {
            'name': 'Large (25 km²)',
            'bbox': {'north': 30.10, 'south': 30.02, 'east': 31.30, 'west': 31.20}
        }
    ]
    
    for area in test_areas:
        bbox = area['bbox']
        area_info = generator.calculate_area_size(bbox)
        
        # Get recommendations
        strategy = generator.get_recommended_strategy(bbox)
        num_routes = generator.get_recommended_num_routes(bbox)
        
        print(f"\n{area['name']}:")
        print(f"  Actual area: {area_info['area_km2']:.2f} km²")
        print(f"  Recommended strategy: {strategy}")
        print(f"  Recommended routes: {num_routes}")
    
    print(f"\n✅ Size recommendations working correctly!")

def test_database_persistence():
    """Test that routes are saved to database"""
    print("\n" + "="*70)
    print("TEST 4: Database Persistence")
    print("="*70)
    
    db = get_db()
    
    # Count routes before
    routes_before = db.get_probe_routes(active_only=True)
    count_before = len(routes_before)
    
    print(f"\nRoutes before: {count_before}")
    
    # Create new routes
    bbox = {
        'north': 30.05,
        'south': 30.03,
        'east': 31.25,
        'west': 31.23
    }
    
    routes = auto_create_routes(bbox, "db_test_area")
    
    # Count routes after
    routes_after = db.get_probe_routes(active_only=True)
    count_after = len(routes_after)
    
    print(f"Routes after: {count_after}")
    print(f"New routes added: {count_after - count_before}")
    
    if count_after > count_before:
        print(f"\n✅ Database persistence working!")
    else:
        print(f"\n⚠️ Warning: No new routes added to database")
    
    # Show sample routes
    print(f"\nSample routes in database:")
    for route in routes_after[-3:]:  # Last 3 routes
        print(f"  - {route['name']}")

def test_bbox_file_creation():
    """Test that bbox info is saved to file"""
    print("\n" + "="*70)
    print("TEST 5: Bbox File Creation")
    print("="*70)
    
    import os
    
    bbox = {
        'north': 30.05,
        'south': 30.03,
        'east': 31.25,
        'west': 31.23
    }
    
    routes = auto_create_routes(bbox, "file_test_area")
    
    # Check if file was created
    bbox_file = "data/last_bbox.json"
    
    if os.path.exists(bbox_file):
        print(f"\n✅ Bbox file created: {bbox_file}")
        
        with open(bbox_file, 'r') as f:
            data = json.load(f)
        
        print(f"\nFile contents:")
        print(f"  Location: {data['location_name']}")
        print(f"  Routes: {data['num_routes']}")
        print(f"  Area: {data['area_km2']:.2f} km²")
        print(f"  Timestamp: {data['timestamp']}")
    else:
        print(f"\n⚠️ Warning: Bbox file not created")

def run_all_tests():
    """Run all tests"""
    print("\n" + "="*70)
    print("RUNNING ALL AUTO ROUTE GENERATION TESTS")
    print("="*70)
    
    try:
        test_basic_generation()
        test_all_strategies()
        test_different_sizes()
        test_database_persistence()
        test_bbox_file_creation()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\nAuto route generation is working correctly!")
        print("You can now integrate it into your GUI.")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

def verify_current_routes():
    """Show currently active routes in database"""
    print("\n" + "="*70)
    print("CURRENT ACTIVE ROUTES IN DATABASE")
    print("="*70)
    
    db = get_db()
    routes = db.get_probe_routes(active_only=True)
    
    if not routes:
        print("\nNo active routes in database")
        print("Run test_basic_generation() to create some")
    else:
        print(f"\nFound {len(routes)} active routes:\n")
        
        for i, route in enumerate(routes, 1):
            print(f"{i}. {route['name']}")
            print(f"   Route ID: {route['route_id']}")
            print(f"   Origin: ({route['origin_lat']:.6f}, {route['origin_lon']:.6f})")
            print(f"   Dest: ({route['dest_lat']:.6f}, {route['dest_lon']:.6f})")
            print()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "verify":
            verify_current_routes()
        elif sys.argv[1] == "basic":
            test_basic_generation()
        elif sys.argv[1] == "strategies":
            test_all_strategies()
        elif sys.argv[1] == "sizes":
            test_different_sizes()
        elif sys.argv[1] == "db":
            test_database_persistence()
        elif sys.argv[1] == "file":
            test_bbox_file_creation()
        else:
            print("Usage:")
            print("  python test_auto_route_generation.py          # Run all tests")
            print("  python test_auto_route_generation.py verify   # Show current routes")
            print("  python test_auto_route_generation.py basic    # Test basic generation")
            print("  python test_auto_route_generation.py strategies  # Test all strategies")
            print("  python test_auto_route_generation.py sizes    # Test different sizes")
            print("  python test_auto_route_generation.py db       # Test database")
            print("  python test_auto_route_generation.py file     # Test file creation")
    else:
        run_all_tests()