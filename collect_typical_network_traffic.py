"""
Collect Typical Traffic Data for Cached Networks
Reads bounding boxes from cached network files and collects typical traffic patterns
"""
import os
import json
import time
import requests
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List
from modules.database import get_db


class NetworkTrafficCollector:
    """Collects typical traffic patterns for a cached network's area"""

    def __init__(self, api_key: str, network_json_path: str, grid_size: int = 5):
        """
        Initialize collector for a cached network

        Args:
            api_key: Google Maps API key
            network_json_path: Path to network .json file with bbox
            grid_size: Grid density (default 5x5)
        """
        self.api_key = api_key
        self.grid_size = grid_size
        self.db = get_db()

        # Load network metadata
        with open(network_json_path, 'r') as f:
            self.network_info = json.load(f)

        self.network_name = self.network_info.get('location_name', 'unknown')
        self.bbox = self.network_info['bbox']
        self.network_id = os.path.basename(network_json_path).replace('.json', '')

        # Generate sampling grid
        self.sampling_routes = self._generate_sampling_grid()

        print(f"[NETWORK COLLECTOR] Network: {self.network_name}")
        print(f"[NETWORK COLLECTOR] Nodes: {self.network_info.get('nodes', 'N/A')}")
        print(f"[NETWORK COLLECTOR] Edges: {self.network_info.get('edges', 'N/A')}")
        print(f"[NETWORK COLLECTOR] Grid: {grid_size}x{grid_size}")
        print(f"[NETWORK COLLECTOR] Sample routes: {len(self.sampling_routes)}")

    def _generate_sampling_grid(self) -> List[Dict]:
        """Generate grid of sampling routes across network area"""
        bbox = self.bbox

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

        # Create OD pairs (adjacent connections)
        sampling_routes = []

        for point in grid_points:
            i, j = point['grid_i'], point['grid_j']

            # Horizontal connection (to right neighbor)
            if j < self.grid_size - 1:
                neighbor = grid_points[i * self.grid_size + (j + 1)]
                sampling_routes.append({
                    'route_id': f"{self.network_id}_grid_{i}_{j}_H",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'horizontal'
                })

            # Vertical connection (to bottom neighbor)
            if i < self.grid_size - 1:
                neighbor = grid_points[(i + 1) * self.grid_size + j]
                sampling_routes.append({
                    'route_id': f"{self.network_id}_grid_{i}_{j}_V",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'vertical'
                })

        return sampling_routes

    def collect_snapshot(self, sample_time: datetime, description: str = "") -> Dict:
        """
        Collect typical traffic snapshot for all grid routes

        Args:
            sample_time: DateTime to query typical traffic for
            description: Human-readable description

        Returns:
            Collection statistics
        """
        print(f"\n{'='*70}")
        print(f"COLLECTING: {description}")
        print(f"Time: {sample_time.strftime('%A, %B %d at %I:%M %p')}")
        print(f"Network: {self.network_name}")
        print(f"Routes: {len(self.sampling_routes)}")
        print(f"{'='*70}\n")

        departure_timestamp = int(sample_time.timestamp())

        collected = 0
        failed = 0
        speeds = []
        travel_times = []

        for i, route in enumerate(self.sampling_routes):
            route_id = route['route_id']

            # Progress
            if (i + 1) % 10 == 0:
                print(f"Progress: {i + 1}/{len(self.sampling_routes)} routes ({collected} successful)", end="\r")

            try:
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

                    # Prefer duration_in_traffic for typical patterns
                    if 'duration_in_traffic' in route_data:
                        travel_time = route_data['duration_in_traffic']['value']
                    else:
                        travel_time = route_data['duration']['value']

                    speed_kmh = (distance_meters / 1000) / (travel_time / 3600) if travel_time > 0 else 0
                    speeds.append(speed_kmh)
                    travel_times.append(travel_time)

                    # Store in database
                    self.db.store_real_traffic_data(
                        route_id=route_id,
                        travel_time_seconds=travel_time,
                        distance_meters=distance_meters,
                        traffic_delay_seconds=0,
                        speed_kmh=round(speed_kmh, 2),
                        data_source=f'google_typical_{self.network_name}',
                        raw_data=data,
                        timestamp=sample_time
                    )

                    collected += 1

                elif data['status'] == 'ZERO_RESULTS':
                    # No route found between these points (might be disconnected)
                    failed += 1
                else:
                    failed += 1
                    if failed <= 3:
                        print(f"\nAPI Status: {data['status']}")

            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"\nError: {str(e)[:50]}")

        # Statistics
        avg_speed = np.mean(speeds) if speeds else 0
        avg_time = np.mean(travel_times) if travel_times else 0

        print(f"\n\n{'='*70}")
        print(f"SNAPSHOT COMPLETE")
        print(f"{'='*70}")
        print(f"✅ Collected: {collected}/{len(self.sampling_routes)} routes")
        print(f"❌ Failed: {failed}")
        print(f"📊 Average speed: {avg_speed:.1f} km/h")
        print(f"📊 Average travel time: {avg_time:.0f} seconds")
        print(f"💾 Stored with timestamp: {sample_time.strftime('%Y-%m-%d %H:%M:%S')}")

        return {
            'collected': collected,
            'failed': failed,
            'avg_speed': avg_speed,
            'avg_travel_time': avg_time,
            'timestamp': sample_time
        }


def find_cached_networks():
    """Find all cached network JSON files"""
    networks_dir = "data/networks"

    if not os.path.exists(networks_dir):
        return []

    networks = []
    for filename in os.listdir(networks_dir):
        if filename.endswith('.json'):
            path = os.path.join(networks_dir, filename)
            try:
                with open(path, 'r') as f:
                    info = json.load(f)
                    if 'bbox' in info:  # Valid network file
                        networks.append({
                            'path': path,
                            'name': info.get('location_name', filename.replace('.json', '')),
                            'nodes': info.get('nodes', 'N/A'),
                            'edges': info.get('edges', 'N/A'),
                            'bbox': info['bbox']
                        })
            except:
                continue

    return networks


def collect_peak_hours(network_path: str, api_key: str, grid_size: int = 5):
    """Quick collection - just peak hours"""
    collector = NetworkTrafficCollector(api_key, network_path, grid_size)

    total_routes = len(collector.sampling_routes)
    total_calls = total_routes * 4

    print(f"\n{'='*70}")
    print(f"PEAK HOURS COLLECTION")
    print(f"{'='*70}")
    print(f"Network: {collector.network_name}")
    print(f"Grid: {grid_size}x{grid_size} ({total_routes} routes)")
    print(f"Samples: Monday/Saturday at 8 AM & 5 PM")
    print(f"Total API calls: {total_calls}")
    print(f"Estimated time: {total_calls / 60:.0f} minutes")
    print(f"Estimated cost: ${total_calls * 0.005:.2f}")
    print(f"{'='*70}\n")

    proceed = input("Continue? (y/n): ").strip().lower()
    if proceed != 'y':
        print("Cancelled.")
        return

    # Calculate sample times
    now = datetime.now()

    # Next Monday
    days_until_monday = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_until_monday)).replace(hour=8, minute=0, second=0, microsecond=0)

    # Next Saturday
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
        result = collector.collect_snapshot(sample_time, description)
        results.append(result)

    total_collected = sum(r['collected'] for r in results)
    total_failed = sum(r['failed'] for r in results)

    print(f"\n{'='*70}")
    print(f"PEAK HOURS COMPLETE!")
    print(f"{'='*70}")
    print(f"✅ Total collected: {total_collected} data points")
    print(f"❌ Total failed: {total_failed}")
    print(f"💾 Stored in: data/digital_twin.db")
    print(f"\nYou can now run simulations using this stored data!")


def collect_full_week(network_path: str, api_key: str, grid_size: int = 5, samples_per_day: int = 4):
    """Collect full week of typical traffic"""
    collector = NetworkTrafficCollector(api_key, network_path, grid_size)

    total_routes = len(collector.sampling_routes)
    total_calls = total_routes * 7 * samples_per_day

    print(f"\n{'='*70}")
    print(f"FULL WEEK COLLECTION")
    print(f"{'='*70}")
    print(f"Network: {collector.network_name}")
    print(f"Grid: {grid_size}x{grid_size} ({total_routes} routes)")
    print(f"Days: 7")
    print(f"Samples/day: {samples_per_day}")
    print(f"Total API calls: {total_calls}")
    print(f"Estimated time: {total_calls / 60:.0f} minutes")
    print(f"Estimated cost: ${total_calls * 0.005:.2f}")
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

    # Sample hours
    if samples_per_day == 4:
        hours = [8, 12, 17, 20]
    elif samples_per_day == 8:
        hours = [0, 3, 6, 8, 12, 15, 17, 20]
    else:
        hours = [int(24 * i / samples_per_day) for i in range(samples_per_day)]

    all_results = []

    for day in range(7):
        current_date = start_date + timedelta(days=day)
        day_name = current_date.strftime('%A')

        print(f"\n{'#'*70}")
        print(f"DAY {day + 1}/7: {day_name}")
        print(f"{'#'*70}")

        for hour in hours:
            sample_time = current_date.replace(hour=hour, minute=0)
            description = f"{day_name} {sample_time.strftime('%I:%M %p')}"

            result = collector.collect_snapshot(sample_time, description)
            all_results.append(result)

    total_collected = sum(r['collected'] for r in all_results)
    total_failed = sum(r['failed'] for r in all_results)

    print(f"\n{'='*70}")
    print(f"FULL WEEK COMPLETE!")
    print(f"{'='*70}")
    print(f"✅ Total collected: {total_collected} data points")
    print(f"❌ Total failed: {total_failed}")
    print(f"📊 Success rate: {total_collected / (total_collected + total_failed) * 100:.1f}%")
    print(f"💾 Stored in: data/digital_twin.db")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("❌ No API key found in .env file")
        exit(1)

    # Find cached networks
    networks = find_cached_networks()

    if not networks:
        print("❌ No cached networks found!")
        print("Please build a network first using the GUI.")
        exit(1)

    print("\n" + "="*70)
    print("CACHED NETWORKS")
    print("="*70)
    for i, net in enumerate(networks, 1):
        print(f"{i}. {net['name']}")
        print(f"   Nodes: {net['nodes']}, Edges: {net['edges']}")
        print(f"   Bbox: ({net['bbox']['south']:.4f}, {net['bbox']['west']:.4f}) to ({net['bbox']['north']:.4f}, {net['bbox']['east']:.4f})")
        print()

    print("="*70)
    print("SELECT NETWORK TO COLLECT DATA FOR")
    print("="*70)

    choice = input(f"\nChoose network (1-{len(networks)}): ").strip()
    try:
        network_index = int(choice) - 1
        selected_network = networks[network_index]
        network_path = selected_network['path']
    except:
        print("Invalid choice!")
        exit(1)

    print("\n" + "="*70)
    print("COLLECTION MODE")
    print("="*70)
    print("1. Peak Hours Only (4 samples) - RECOMMENDED for testing")
    print("2. Full Week (7 days x 4 samples/day = 28 samples)")
    print("3. Full Week Dense (7 days x 8 samples/day = 56 samples)")

    mode = input("\nChoose mode (1-3): ").strip()

    grid = int(input("Grid size (3-10, default 5): ").strip() or "5")

    if mode == '1':
        collect_peak_hours(network_path, api_key, grid_size=grid)
    elif mode == '2':
        collect_full_week(network_path, api_key, grid_size=grid, samples_per_day=4)
    elif mode == '3':
        collect_full_week(network_path, api_key, grid_size=grid, samples_per_day=8)
    else:
        print("Invalid choice!")
