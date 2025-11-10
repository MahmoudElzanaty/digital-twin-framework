"""
Collect Typical Traffic Patterns from Google Maps
Uses departure_time to get typical traffic for different days/times
Creates a synthetic week of data without waiting
"""
import os
from datetime import datetime, timedelta
from modules.data_collector import TrafficDataCollector
from modules.database import get_db
import time

def collect_typical_week(api_key, days=7, samples_per_day=8):
    """
    Collect typical traffic patterns for a full week

    Args:
        api_key: Google Maps API key
        days: Number of days to simulate (default 7)
        samples_per_day: How many time samples per day (default 8 = every 3 hours)
    """

    collector = TrafficDataCollector(api_key)
    db = get_db()

    # Get all probe routes
    routes = db.get_probe_routes(active_only=True)

    if not routes:
        print("❌ No probe routes found!")
        print("Please create routes first using the GUI or setup_digital_twin.py")
        return

    print("\n" + "="*70)
    print(f"COLLECTING TYPICAL TRAFFIC PATTERNS")
    print("="*70)
    print(f"Routes: {len(routes)}")
    print(f"Days: {days}")
    print(f"Samples per day: {samples_per_day}")
    print(f"Total API calls: {len(routes) * days * samples_per_day}")
    print("="*70 + "\n")

    # Start from next Monday to get clean weekly patterns
    now = datetime.now()
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7  # If today is Monday, start next Monday
    start_date = now + timedelta(days=days_until_monday)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"📅 Simulating typical traffic patterns starting from: {start_date.strftime('%A, %B %d, %Y')}\n")

    total_collected = 0
    total_failed = 0

    # Loop through each day
    for day in range(days):
        current_date = start_date + timedelta(days=day)
        day_name = current_date.strftime('%A')

        print(f"\n{'='*70}")
        print(f"DAY {day + 1}/{days}: {day_name}, {current_date.strftime('%B %d, %Y')}")
        print(f"{'='*70}")

        # Sample different times throughout the day
        hours_to_sample = [
            0,   # Midnight
            3,   # Early morning
            6,   # Dawn
            8,   # Morning rush
            12,  # Noon
            17,  # Evening rush
            20,  # Evening
            23   # Night
        ][:samples_per_day]

        for hour in hours_to_sample:
            sample_time = current_date.replace(hour=hour, minute=0)

            print(f"\n⏰ Time: {sample_time.strftime('%I:%M %p')} ({hour:02d}:00)")
            print("-" * 70)

            # Collect for each route
            for i, route in enumerate(routes, 1):
                route_name = route['name']
                route_id = route['route_id']

                print(f"  [{i}/{len(routes)}] {route_name[:50]:<50}", end=" ... ")

                try:
                    # Fetch typical traffic for this specific time
                    # We'll modify the collector to use departure_time
                    import requests

                    origin = f"{route['origin_lat']},{route['origin_lon']}"
                    destination = f"{route['dest_lat']},{route['dest_lon']}"

                    # Convert to Unix timestamp for API
                    departure_timestamp = int(sample_time.timestamp())

                    params = {
                        'origin': origin,
                        'destination': destination,
                        'mode': 'driving',
                        'departure_time': departure_timestamp,  # Request typical traffic for this time
                        'key': api_key
                    }

                    # Rate limiting
                    time.sleep(1.0)

                    response = requests.get(
                        "https://maps.googleapis.com/maps/api/directions/json",
                        params=params,
                        timeout=10
                    )
                    response.raise_for_status()
                    data = response.json()

                    if data['status'] == 'OK':
                        route_data = data['routes'][0]['legs'][0]

                        distance_meters = route_data['distance']['value']

                        # Use duration_in_traffic if available (typical for this time)
                        if 'duration_in_traffic' in route_data:
                            travel_time = route_data['duration_in_traffic']['value']
                            data_type = "typical_traffic"
                        else:
                            travel_time = route_data['duration']['value']
                            data_type = "no_traffic"

                        speed_kmh = (distance_meters / 1000) / (travel_time / 3600) if travel_time > 0 else 0

                        # Store in database with simulated timestamp
                        db.store_real_traffic_data(
                            route_id=route_id,
                            travel_time_seconds=travel_time,
                            distance_meters=distance_meters,
                            traffic_delay_seconds=0,  # Not available for typical traffic
                            speed_kmh=round(speed_kmh, 2),
                            data_source=f'google_typical_{day_name.lower()}_{hour:02d}00',
                            raw_data=data,
                            timestamp=sample_time  # Use the simulated time
                        )

                        print(f"✅ {speed_kmh:.1f} km/h ({travel_time/60:.1f} min)")
                        total_collected += 1

                    else:
                        print(f"❌ API Error: {data['status']}")
                        total_failed += 1

                except Exception as e:
                    print(f"❌ Error: {str(e)[:30]}")
                    total_failed += 1

            # Progress summary after each time slot
            print(f"\n  Progress: {total_collected} collected, {total_failed} failed")

    # Final summary
    print("\n" + "="*70)
    print("COLLECTION COMPLETE!")
    print("="*70)
    print(f"✅ Successfully collected: {total_collected} data points")
    print(f"❌ Failed: {total_failed}")
    print(f"📊 Success rate: {total_collected / (total_collected + total_failed) * 100:.1f}%")
    print(f"💾 Data stored in: data/digital_twin.db")
    print("\n" + "="*70)
    print("NEXT STEPS:")
    print("="*70)
    print("1. View your data in the GUI (Data Collection tab)")
    print("2. Run simulations using this typical traffic data")
    print("3. Compare simulation results with typical patterns")
    print("4. Use for thesis validation!")
    print()


def collect_typical_peak_hours(api_key):
    """
    Quick collection - just peak hours for a few days
    Minimal API calls but still useful data
    """
    collector = TrafficDataCollector(api_key)
    db = get_db()

    routes = db.get_probe_routes(active_only=True)

    if not routes:
        print("❌ No probe routes found!")
        return

    print("\n" + "="*70)
    print("COLLECTING TYPICAL PEAK HOUR TRAFFIC")
    print("="*70)
    print(f"Routes: {len(routes)}")
    print(f"Focus: Morning rush (8 AM) and Evening rush (5 PM)")
    print(f"Days: Weekday + Weekend comparison")
    print("="*70 + "\n")

    # Sample times: Monday & Saturday, morning & evening
    now = datetime.now()

    # Next Monday
    days_until_monday = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_until_monday)).replace(hour=8, minute=0, second=0, microsecond=0)

    # Next Saturday
    days_until_saturday = (5 - now.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = (now + timedelta(days=days_until_saturday)).replace(hour=8, minute=0, second=0, microsecond=0)

    sample_times = [
        (monday.replace(hour=8), "Monday Morning Rush"),
        (monday.replace(hour=17), "Monday Evening Rush"),
        (saturday.replace(hour=8), "Saturday Morning"),
        (saturday.replace(hour=17), "Saturday Evening"),
    ]

    total_collected = 0

    for sample_time, description in sample_times:
        print(f"\n{'='*70}")
        print(f"{description}: {sample_time.strftime('%A %I:%M %p')}")
        print("="*70)

        for route in routes:
            print(f"  {route['name'][:50]:<50}", end=" ... ")

            try:
                import requests
                origin = f"{route['origin_lat']},{route['origin_lon']}"
                destination = f"{route['dest_lat']},{route['dest_lon']}"
                departure_timestamp = int(sample_time.timestamp())

                params = {
                    'origin': origin,
                    'destination': destination,
                    'mode': 'driving',
                    'departure_time': departure_timestamp,
                    'key': api_key
                }

                time.sleep(1.0)
                response = requests.get(
                    "https://maps.googleapis.com/maps/api/directions/json",
                    params=params,
                    timeout=10
                )
                data = response.json()

                if data['status'] == 'OK':
                    route_data = data['routes'][0]['legs'][0]
                    distance_meters = route_data['distance']['value']
                    travel_time = route_data.get('duration_in_traffic', route_data['duration'])['value']
                    speed_kmh = (distance_meters / 1000) / (travel_time / 3600) if travel_time > 0 else 0

                    db.store_real_traffic_data(
                        route_id=route['route_id'],
                        travel_time_seconds=travel_time,
                        distance_meters=distance_meters,
                        traffic_delay_seconds=0,
                        speed_kmh=round(speed_kmh, 2),
                        data_source=f'google_typical_{description.lower().replace(" ", "_")}',
                        raw_data=data,
                        timestamp=sample_time
                    )

                    print(f"✅ {speed_kmh:.1f} km/h")
                    total_collected += 1
                else:
                    print(f"❌ {data['status']}")

            except Exception as e:
                print(f"❌ {str(e)[:30]}")

    print(f"\n✅ Collected {total_collected} typical peak hour data points!")


if __name__ == "__main__":
    # Get API key
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv('GOOGLE_MAPS_API_KEY')

    if not api_key:
        print("❌ No API key found!")
        print("Please set GOOGLE_MAPS_API_KEY in your .env file")
        exit(1)

    print("\n" + "="*70)
    print("TYPICAL TRAFFIC DATA COLLECTION")
    print("="*70)
    print("\nChoose collection mode:")
    print("1. Full Week (7 days x 8 samples/day) - Comprehensive but more API calls")
    print("2. Peak Hours Only (4 samples) - Quick and minimal API calls")
    print("3. Custom (specify days and samples)")

    choice = input("\nYour choice (1-3): ").strip()

    if choice == '1':
        collect_typical_week(api_key, days=7, samples_per_day=8)
    elif choice == '2':
        collect_typical_peak_hours(api_key)
    elif choice == '3':
        days = int(input("Number of days (1-7): ").strip() or "3")
        samples = int(input("Samples per day (1-24): ").strip() or "4")
        collect_typical_week(api_key, days=days, samples_per_day=samples)
    else:
        print("Invalid choice!")
