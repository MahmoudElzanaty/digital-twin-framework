"""
Collect Typical Traffic Patterns for Entire Areas
Generates grid-based sampling routes and collects typical traffic data
"""
import os
import time
import requests
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
from modules.database import get_db
from modules.area_manager import AreaManager


class TypicalAreaCollector:
    """Collects typical traffic patterns for an entire geographic area"""

    def __init__(self, api_key: str, area_id: str, grid_size: int = 5):
        """
        Initialize collector

        Args:
            api_key: Google Maps API key
            area_id: Area to collect data for
            grid_size: NxN grid (default 5x5 = 25 points)
        """
        self.api_key = api_key
        self.area_id = area_id
        self.grid_size = grid_size
        self.db = get_db()

        # Load area
        self.area = self.db.get_monitored_area(area_id)
        if not self.area:
            raise ValueError(f"Area {area_id} not found")

        # Generate sampling grid
        self.sampling_routes = self._generate_sampling_grid()

        print(f"[TYPICAL COLLECTOR] Area: {self.area['name']}")
        print(f"[TYPICAL COLLECTOR] Grid: {grid_size}x{grid_size}")
        print(f"[TYPICAL COLLECTOR] Sample routes: {len(self.sampling_routes)}")

    def _generate_sampling_grid(self) -> List[Dict]:
        """Generate grid of sampling points across area"""
        bbox = self.area['bbox']

        # Calculate grid spacing
        lat_step = (bbox['north'] - bbox['south']) / self.grid_size
        lon_step = (bbox['east'] - bbox['west']) / self.grid_size

        # Generate grid points
        grid_points = []
        for i in range(self.grid_size):
            for j in range(self.grid_size):
                lat = bbox['south'] + (i + 0.5) * lat_step
                lon = bbox['west'] + (j + 0.5) * lon_step
                grid_points.append({
                    'lat': lat,
                    'lon': lon,
                    'grid_i': i,
                    'grid_j': j
                })

        # Create OD pairs (adjacent points)
        sampling_routes = []
        route_id = 0

        for point in grid_points:
            i, j = point['grid_i'], point['grid_j']

            # Horizontal connections
            if j < self.grid_size - 1:
                neighbor = grid_points[i * self.grid_size + (j + 1)]
                sampling_routes.append({
                    'route_id': f"{self.area_id}_grid_{i}_{j}_H",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'horizontal'
                })
                route_id += 1

            # Vertical connections
            if i < self.grid_size - 1:
                neighbor = grid_points[(i + 1) * self.grid_size + j]
                sampling_routes.append({
                    'route_id': f"{self.area_id}_grid_{i}_{j}_V",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'vertical'
                })
                route_id += 1

        return sampling_routes

    def collect_typical_snapshot(self, sample_time: datetime, description: str = "") -> Dict:
        """
        Collect typical traffic for all grid routes at a specific time

        Args:
            sample_time: The datetime to query typical traffic for
            description: Description of this time period

        Returns:
            Dict with collection statistics
        """
        print(f"\n{'='*70}")
        print(f"COLLECTING: {description}")
        print(f"Time: {sample_time.strftime('%A, %B %d at %I:%M %p')}")
        print(f"Area: {self.area['name']}")
        print(f"Routes: {len(self.sampling_routes)}")
        print(f"{'='*70}\n")

        departure_timestamp = int(sample_time.timestamp())

        collected = 0
        failed = 0
        speeds = []

        for i, route in enumerate(self.sampling_routes):
            route_id = route['route_id']

            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"Progress: {i + 1}/{len(self.sampling_routes)} routes", end="\r")

            try:
                # Query Google Maps for typical traffic
                origin = f"{route['origin']['lat']},{route['origin']['lon']}"
                destination = f"{route['destination']['lat']},{route['destination']['lon']}"

                params = {
                    'origin': origin,
                    'destination': destination,
                    'mode': 'driving',
                    'departure_time': departure_timestamp,
                    'key': self.api_key
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

                    # Use duration_in_traffic for typical traffic patterns
                    if 'duration_in_traffic' in route_data:
                        travel_time = route_data['duration_in_traffic']['value']
                    else:
                        travel_time = route_data['duration']['value']

                    speed_kmh = (distance_meters / 1000) / (travel_time / 3600) if travel_time > 0 else 0
                    speeds.append(speed_kmh)

                    # Store in database
                    self.db.store_real_traffic_data(
                        route_id=route_id,
                        travel_time_seconds=travel_time,
                        distance_meters=distance_meters,
                        traffic_delay_seconds=0,
                        speed_kmh=round(speed_kmh, 2),
                        data_source=f'google_typical_{self.area_id}',
                        raw_data=data,
                        timestamp=sample_time
                    )

                    collected += 1
                else:
                    failed += 1

            except Exception as e:
                failed += 1
                if failed <= 3:  # Only print first few errors
                    print(f"\nWarning: {str(e)[:50]}")

        # Statistics
        avg_speed = np.mean(speeds) if speeds else 0

        print(f"\n\n{'='*70}")
        print(f"SNAPSHOT COMPLETE")
        print(f"{'='*70}")
        print(f"✅ Collected: {collected}/{len(self.sampling_routes)} routes")
        print(f"❌ Failed: {failed}")
        print(f"📊 Average speed: {avg_speed:.1f} km/h")
        print(f"💾 Stored in database with timestamp: {sample_time.strftime('%Y-%m-%d %H:%M:%S')}")

        return {
            'collected': collected,
            'failed': failed,
            'avg_speed': avg_speed,
            'timestamp': sample_time
        }


def collect_typical_week(area_id: str, api_key: str, grid_size: int = 5, samples_per_day: int = 4):
    """
    Collect a full week of typical traffic patterns

    Args:
        area_id: Area to collect for
        api_key: Google Maps API key
        grid_size: Grid size (default 5x5)
        samples_per_day: Time samples per day (default 4)
    """
    collector = TypicalAreaCollector(api_key, area_id, grid_size)

    # Calculate total API calls
    total_routes = len(collector.sampling_routes)
    total_samples = 7 * samples_per_day
    total_calls = total_routes * total_samples

    print(f"\n{'='*70}")
    print(f"TYPICAL WEEK COLLECTION")
    print(f"{'='*70}")
    print(f"Area: {collector.area['name']}")
    print(f"Grid: {grid_size}x{grid_size} ({total_routes} routes)")
    print(f"Days: 7")
    print(f"Samples/day: {samples_per_day}")
    print(f"Total API calls: {total_calls}")
    print(f"Estimated time: {total_calls / 60:.0f} minutes")
    print(f"Estimated cost: ${total_calls * 0.005:.2f} (covered by free credit)")
    print(f"{'='*70}\n")

    proceed = input("Continue? (y/n): ").strip().lower()
    if proceed != 'y':
        print("Cancelled.")
        return

    # Start from next Monday
    now = datetime.now()
    days_until_monday = (7 - now.weekday()) % 7 or 7
    start_date = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\nSimulating week starting: {start_date.strftime('%A, %B %d, %Y')}\n")

    # Sample times per day
    if samples_per_day == 4:
        hours = [8, 12, 17, 20]  # Morning rush, noon, evening rush, night
    elif samples_per_day == 8:
        hours = [0, 3, 6, 8, 12, 15, 17, 20]
    else:
        # Evenly distributed
        hours = [int(24 * i / samples_per_day) for i in range(samples_per_day)]

    all_results = []

    # Collect for each day
    for day in range(7):
        current_date = start_date + timedelta(days=day)
        day_name = current_date.strftime('%A')

        print(f"\n{'#'*70}")
        print(f"DAY {day + 1}/7: {day_name}")
        print(f"{'#'*70}")

        for hour in hours:
            sample_time = current_date.replace(hour=hour, minute=0)
            description = f"{day_name} {sample_time.strftime('%I:%M %p')}"

            result = collector.collect_typical_snapshot(sample_time, description)
            all_results.append(result)

    # Final summary
    total_collected = sum(r['collected'] for r in all_results)
    total_failed = sum(r['failed'] for r in all_results)

    print(f"\n\n{'='*70}")
    print(f"WEEK COLLECTION COMPLETE!")
    print(f"{'='*70}")
    print(f"✅ Total data points: {total_collected}")
    print(f"❌ Total failed: {total_failed}")
    print(f"📊 Success rate: {total_collected / (total_collected + total_failed) * 100:.1f}%")
    print(f"💾 All data stored in: data/digital_twin.db")
    print(f"\nYou can now run simulations using this stored data!")
    print(f"{'='*70}\n")


def collect_typical_peak_hours(area_id: str, api_key: str, grid_size: int = 5):
    """Quick collection - just peak hours"""
    collector = TypicalAreaCollector(api_key, area_id, grid_size)

    total_routes = len(collector.sampling_routes)
    total_calls = total_routes * 4  # 4 samples

    print(f"\n{'='*70}")
    print(f"PEAK HOURS COLLECTION")
    print(f"{'='*70}")
    print(f"Area: {collector.area['name']}")
    print(f"Grid: {grid_size}x{grid_size} ({total_routes} routes)")
    print(f"Samples: Monday 8 AM, 5 PM + Saturday 8 AM, 5 PM")
    print(f"Total API calls: {total_calls}")
    print(f"Estimated time: {total_calls / 60:.0f} minutes")
    print(f"{'='*70}\n")

    proceed = input("Continue? (y/n): ").strip().lower()
    if proceed != 'y':
        print("Cancelled.")
        return

    # Sample times
    now = datetime.now()
    days_until_monday = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_until_monday)).replace(hour=8, minute=0, second=0, microsecond=0)

    days_until_saturday = (5 - now.weekday()) % 7 or 7
    saturday = (now + timedelta(days=days_until_saturday)).replace(hour=8, minute=0, second=0, microsecond=0)

    samples = [
        (monday.replace(hour=8), "Monday Morning Rush (8 AM)"),
        (monday.replace(hour=17), "Monday Evening Rush (5 PM)"),
        (saturday.replace(hour=8), "Saturday Morning (8 AM)"),
        (saturday.replace(hour=17), "Saturday Evening (5 PM)"),
    ]

    results = []
    for sample_time, description in samples:
        result = collector.collect_typical_snapshot(sample_time, description)
        results.append(result)

    total_collected = sum(r['collected'] for r in results)
    print(f"\n✅ Peak hours collection complete! {total_collected} data points stored.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("❌ No API key found in .env file")
        exit(1)

    # List available areas
    am = AreaManager()
    areas = am.list_all_areas()

    if not areas:
        print("❌ No areas found!")
        print("Please create an area in the GUI first.")
        exit(1)

    print("\n" + "="*70)
    print("AVAILABLE AREAS")
    print("="*70)
    for i, area in enumerate(areas, 1):
        status = area.get('status', 'unknown')
        print(f"{i}. {area['name']} (ID: {area['area_id']}) - Status: {status}")

    print("\n" + "="*70)
    print("SELECT AREA TO COLLECT DATA FOR")
    print("="*70)

    choice = input(f"\nChoose area (1-{len(areas)}): ").strip()
    try:
        area_index = int(choice) - 1
        selected_area = areas[area_index]
        area_id = selected_area['area_id']
    except:
        print("Invalid choice!")
        exit(1)

    print("\n" + "="*70)
    print("COLLECTION MODE")
    print("="*70)
    print("1. Peak Hours Only (4 samples) - Quick")
    print("2. Full Week (7 days x 4 samples/day = 28 samples)")
    print("3. Full Week Dense (7 days x 8 samples/day = 56 samples)")
    print("4. Custom")

    mode = input("\nChoose mode (1-4): ").strip()

    if mode == '1':
        grid = int(input("Grid size (3-10, default 5): ").strip() or "5")
        collect_typical_peak_hours(area_id, api_key, grid_size=grid)
    elif mode == '2':
        grid = int(input("Grid size (3-10, default 5): ").strip() or "5")
        collect_typical_week(area_id, api_key, grid_size=grid, samples_per_day=4)
    elif mode == '3':
        grid = int(input("Grid size (3-10, default 5): ").strip() or "5")
        collect_typical_week(area_id, api_key, grid_size=grid, samples_per_day=8)
    elif mode == '4':
        grid = int(input("Grid size (3-10): ").strip())
        days = 7
        samples = int(input("Samples per day (1-24): ").strip())
        collect_typical_week(area_id, api_key, grid_size=grid, samples_per_day=samples)
    else:
        print("Invalid choice!")
