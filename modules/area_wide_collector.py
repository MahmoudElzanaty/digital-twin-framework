"""
Area-Wide Data Collector
Extends TrafficDataCollector to collect traffic data across entire geographic area
Uses grid-based sampling to capture area-wide traffic patterns
"""
import time
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional
from modules.database import get_db
from modules.data_collector import TrafficDataCollector


class AreaWideCollector:
    """
    Collects traffic data for an entire geographic area
    Uses grid sampling instead of specific routes

    Workflow:
    1. Generate grid of sampling points across area
    2. Create origin-destination pairs from grid
    3. Collect traffic data for each OD pair
    4. Store as area snapshot
    """

    def __init__(self, api_key: str, area_id: str, grid_size: int = 5):
        """
        Initialize area-wide collector

        Args:
            api_key: Google Maps API key
            area_id: Area to collect data for
            grid_size: NxN grid (default 5x5 = 25 points)
        """
        self.api_key = api_key
        self.area_id = area_id
        self.grid_size = grid_size
        self.db = get_db()

        # Reuse existing TrafficDataCollector
        self.collector = TrafficDataCollector(api_key)

        # Load area
        self.area = self.db.get_monitored_area(area_id)
        if not self.area:
            raise ValueError(f"Area {area_id} not found")

        # Generate sampling grid
        self.sampling_routes = self._generate_sampling_grid()

        print(f"[AREA COLLECTOR] Initialized for: {self.area['name']}")
        print(f"[AREA COLLECTOR] Grid size: {grid_size}x{grid_size}")
        print(f"[AREA COLLECTOR] Sampling routes: {len(self.sampling_routes)}")

    def _generate_sampling_grid(self) -> List[Dict]:
        """
        Generate grid of sampling points across area
        Creates OD pairs for data collection

        Strategy:
        1. Divide area into grid_size x grid_size cells
        2. Place a point in center of each cell
        3. Create routes between adjacent points (horizontal + vertical)

        Returns:
            List of sampling routes (origin -> destination pairs)
        """
        bbox = self.area['bbox']

        # Calculate grid spacing
        lat_step = (bbox['north'] - bbox['south']) / self.grid_size
        lon_step = (bbox['east'] - bbox['west']) / self.grid_size

        # Generate grid points (center of each cell)
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

        # Create OD pairs (routes between adjacent points)
        sampling_routes = []
        route_id = 0

        for point in grid_points:
            i, j = point['grid_i'], point['grid_j']

            # Connect to right neighbor (horizontal)
            if j < self.grid_size - 1:
                neighbor = grid_points[i * self.grid_size + (j + 1)]
                sampling_routes.append({
                    'route_id': f"area_sample_{route_id}",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'horizontal',
                    'grid_from': (i, j),
                    'grid_to': (i, j+1)
                })
                route_id += 1

            # Connect to bottom neighbor (vertical)
            if i < self.grid_size - 1:
                neighbor = grid_points[(i + 1) * self.grid_size + j]
                sampling_routes.append({
                    'route_id': f"area_sample_{route_id}",
                    'origin': {'lat': point['lat'], 'lon': point['lon']},
                    'destination': {'lat': neighbor['lat'], 'lon': neighbor['lon']},
                    'direction': 'vertical',
                    'grid_from': (i, j),
                    'grid_to': (i+1, j)
                })
                route_id += 1

        return sampling_routes

    def collect_area_snapshot(self) -> Dict:
        """
        Collect one complete snapshot of area traffic
        Samples all grid routes

        Returns:
            Dict with snapshot data and statistics
        """
        snapshot_id = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        timestamp = datetime.now()

        print(f"\n[AREA COLLECTOR] Collecting snapshot: {snapshot_id}")
        print(f"[AREA COLLECTOR] Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[AREA COLLECTOR] Sampling {len(self.sampling_routes)} routes...")

        samples = []
        speeds = []
        travel_times = []

        for i, route in enumerate(self.sampling_routes):
            # Rate limiting
            if i > 0 and i % 10 == 0:
                print(f"[AREA COLLECTOR] Progress: {i}/{len(self.sampling_routes)} routes sampled")
                time.sleep(1)  # Small delay every 10 requests

            # Collect traffic data using existing collector
            try:
                data = self.collector.fetch_route_traffic(
                    origin_lat=route['origin']['lat'],
                    origin_lon=route['origin']['lon'],
                    dest_lat=route['destination']['lat'],
                    dest_lon=route['destination']['lon'],
                    route_id=None  # Not tied to specific route
                )

                if data:
                    # Store in database with area_id
                    self.db.store_area_traffic_sample(
                        area_id=self.area_id,
                        snapshot_id=snapshot_id,
                        origin_lat=route['origin']['lat'],
                        origin_lon=route['origin']['lon'],
                        dest_lat=route['destination']['lat'],
                        dest_lon=route['destination']['lon'],
                        travel_time_seconds=data['travel_time_seconds'],
                        distance_meters=data['distance_meters'],
                        speed_kmh=data['speed_kmh']
                    )

                    samples.append(data)
                    speeds.append(data['speed_kmh'])
                    travel_times.append(data['travel_time_seconds'])

            except Exception as e:
                print(f"[AREA COLLECTOR] Error sampling route {i}: {e}")
                continue

        # Calculate statistics
        if samples:
            avg_speed = np.mean(speeds)
            min_speed = np.min(speeds)
            max_speed = np.max(speeds)
            std_speed = np.std(speeds)

            # Store aggregated snapshot
            self.db.store_area_snapshot(
                area_id=self.area_id,
                snapshot_id=snapshot_id,
                num_samples=len(samples),
                avg_speed_kmh=avg_speed,
                min_speed_kmh=min_speed,
                max_speed_kmh=max_speed
            )

            print(f"\n[AREA COLLECTOR] Snapshot complete!")
            print(f"  Samples collected: {len(samples)}/{len(self.sampling_routes)}")
            print(f"  Avg speed: {avg_speed:.1f} km/h")
            print(f"  Speed range: {min_speed:.1f} - {max_speed:.1f} km/h")
            print(f"  Std dev: {std_speed:.1f} km/h")

            return {
                'snapshot_id': snapshot_id,
                'timestamp': timestamp.isoformat(),
                'num_samples': len(samples),
                'success_rate': len(samples) / len(self.sampling_routes) * 100,
                'statistics': {
                    'avg_speed_kmh': avg_speed,
                    'min_speed_kmh': min_speed,
                    'max_speed_kmh': max_speed,
                    'std_speed_kmh': std_speed,
                    'avg_travel_time_seconds': np.mean(travel_times)
                },
                'samples': samples
            }
        else:
            print(f"[AREA COLLECTOR] Warning: No samples collected!")
            return {
                'snapshot_id': snapshot_id,
                'timestamp': timestamp.isoformat(),
                'num_samples': 0,
                'success_rate': 0,
                'statistics': {},
                'samples': []
            }

    def collect_training_data(
        self,
        duration_days: int,
        interval_minutes: int = 15,
        progress_callback=None
    ):
        """
        Collect training data for specified duration

        Args:
            duration_days: How many days to collect
            interval_minutes: Time between collections (default 15 min)
            progress_callback: Optional callback function(current, total, snapshot_data)
        """
        print(f"\n{'='*70}")
        print(f"STARTING AREA TRAINING DATA COLLECTION")
        print(f"{'='*70}")
        print(f"Area: {self.area['name']}")
        print(f"Duration: {duration_days} days")
        print(f"Interval: {interval_minutes} minutes")
        print(f"Grid size: {self.grid_size}x{self.grid_size}")
        print(f"Samples per collection: {len(self.sampling_routes)}")

        # Calculate total collections
        collections_per_day = (24 * 60) // interval_minutes
        total_collections = duration_days * collections_per_day

        print(f"Total collections: {total_collections}")
        print(f"{'='*70}\n")

        start_time = time.time()
        collection_count = 0

        try:
            while collection_count < total_collections:
                collection_count += 1

                print(f"\n[COLLECTION #{collection_count}/{total_collections}]")
                print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

                # Collect snapshot
                snapshot = self.collect_area_snapshot()

                # Update progress in database
                self.db.update_area_training_progress(self.area_id, collection_count)

                # Call progress callback if provided
                if progress_callback:
                    progress_callback(collection_count, total_collections, snapshot)

                # Check if training should stop
                elapsed_days = (time.time() - start_time) / 86400
                if elapsed_days >= duration_days:
                    print(f"\n[AREA COLLECTOR] Training duration complete!")
                    break

                # Wait for next collection
                if collection_count < total_collections:
                    print(f"[AREA COLLECTOR] Waiting {interval_minutes} minutes...")
                    time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            print(f"\n[AREA COLLECTOR] Training interrupted by user")
            print(f"Collected {collection_count}/{total_collections} snapshots")

        except Exception as e:
            print(f"\n[AREA COLLECTOR] Error during training: {e}")

        finally:
            # Calculate training summary
            elapsed_hours = (time.time() - start_time) / 3600
            total_samples = collection_count * len(self.sampling_routes)

            print(f"\n{'='*70}")
            print(f"TRAINING DATA COLLECTION SUMMARY")
            print(f"{'='*70}")
            print(f"Area: {self.area['name']}")
            print(f"Collections completed: {collection_count}/{total_collections}")
            print(f"Duration: {elapsed_hours:.1f} hours")
            print(f"Total samples: {total_samples}")
            print(f"{'='*70}\n")

    def get_collection_statistics(self, days: int = 7) -> Dict:
        """
        Get statistics for recent collections

        Args:
            days: Number of days to analyze

        Returns:
            Dict with statistics
        """
        from datetime import timedelta

        start_time = (datetime.now() - timedelta(days=days)).isoformat()
        snapshots = self.db.get_area_snapshots(self.area_id, limit=None)

        # Filter by time
        recent_snapshots = [
            s for s in snapshots
            if s['snapshot_timestamp'] >= start_time
        ]

        if not recent_snapshots:
            return {
                'num_snapshots': 0,
                'time_range_days': days,
                'statistics': None
            }

        speeds = [s['avg_speed_kmh'] for s in recent_snapshots if s['avg_speed_kmh']]

        return {
            'num_snapshots': len(recent_snapshots),
            'time_range_days': days,
            'statistics': {
                'avg_speed_kmh': np.mean(speeds) if speeds else 0,
                'min_speed_kmh': np.min(speeds) if speeds else 0,
                'max_speed_kmh': np.max(speeds) if speeds else 0,
                'std_speed_kmh': np.std(speeds) if speeds else 0
            },
            'snapshots': recent_snapshots
        }

    def get_grid_visualization_data(self) -> Dict:
        """
        Get data for visualizing the sampling grid
        Useful for debugging and UI display

        Returns:
            Dict with grid points and routes for visualization
        """
        bbox = self.area['bbox']

        # Extract unique points
        points = []
        seen_points = set()

        for route in self.sampling_routes:
            origin = (route['origin']['lat'], route['origin']['lon'])
            dest = (route['destination']['lat'], route['destination']['lon'])

            if origin not in seen_points:
                points.append({'lat': origin[0], 'lon': origin[1]})
                seen_points.add(origin)

            if dest not in seen_points:
                points.append({'lat': dest[0], 'lon': dest[1]})
                seen_points.add(dest)

        return {
            'area_name': self.area['name'],
            'bbox': bbox,
            'grid_size': self.grid_size,
            'grid_points': points,
            'sampling_routes': [
                {
                    'origin': r['origin'],
                    'destination': r['destination'],
                    'direction': r['direction']
                }
                for r in self.sampling_routes
            ],
            'num_points': len(points),
            'num_routes': len(self.sampling_routes)
        }


class ScheduledAreaCollector:
    """
    Wrapper for running area-wide collection in background
    Compatible with existing ScheduledCollectionWorker pattern
    """

    def __init__(self, api_key: str, area_id: str, duration_hours: int, interval_minutes: int = 15):
        self.api_key = api_key
        self.area_id = area_id
        self.duration_hours = duration_hours
        self.interval_minutes = interval_minutes
        self.running = False
        self.collector = None

    def start(self, progress_callback=None):
        """Start scheduled collection"""
        self.running = True
        self.collector = AreaWideCollector(self.api_key, self.area_id)

        duration_days = self.duration_hours / 24

        self.collector.collect_training_data(
            duration_days=duration_days,
            interval_minutes=self.interval_minutes,
            progress_callback=progress_callback
        )

    def stop(self):
        """Stop scheduled collection"""
        self.running = False
        print("[SCHEDULED COLLECTOR] Stopping...")
