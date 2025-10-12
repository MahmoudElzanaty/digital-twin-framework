"""
Real Traffic Data Collector
Fetches current traffic conditions from Google Maps API
"""
import requests
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
from modules.database import get_db

class TrafficDataCollector:
    """Collects real-world traffic data via Google Maps API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api/directions/json"
        self.db = get_db()
        self.last_request_time = 0
        self.min_request_interval = 1.0  # Rate limiting: 1 request per second
    
    def _rate_limit(self):
        """Ensure we don't exceed API rate limits"""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()
    
    def fetch_route_traffic(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        route_id: str = None
    ) -> Optional[Dict]:
        """
        Fetch current traffic conditions for a route
        
        Returns dict with:
        - travel_time_seconds: current travel time
        - distance_meters: route distance
        - traffic_delay_seconds: delay due to traffic (vs free-flow)
        - speed_kmh: average speed
        """
        self._rate_limit()
        
        origin = f"{origin_lat},{origin_lon}"
        destination = f"{dest_lat},{dest_lon}"
        
        params = {
            'origin': origin,
            'destination': destination,
            'mode': 'driving',
            'departure_time': 'now',  # Get current traffic
            'key': self.api_key
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data['status'] != 'OK':
                print(f"[COLLECTOR] API Error: {data['status']}")
                return None
            
            route = data['routes'][0]['legs'][0]
            
            # Extract data
            distance_meters = route['distance']['value']
            duration_seconds = route['duration']['value']
            
            # Duration in traffic (with current conditions)
            if 'duration_in_traffic' in route:
                traffic_duration = route['duration_in_traffic']['value']
                traffic_delay = traffic_duration - duration_seconds
            else:
                traffic_duration = duration_seconds
                traffic_delay = 0
            
            # Calculate average speed
            speed_kmh = (distance_meters / 1000) / (traffic_duration / 3600) if traffic_duration > 0 else 0
            
            result = {
                'travel_time_seconds': traffic_duration,
                'distance_meters': distance_meters,
                'traffic_delay_seconds': traffic_delay,
                'speed_kmh': round(speed_kmh, 2),
                'timestamp': datetime.now().isoformat(),
                'raw_response': data
            }
            
            # Store in database if route_id provided
            if route_id:
                self.db.store_real_traffic_data(
                    route_id=route_id,
                    travel_time_seconds=traffic_duration,
                    distance_meters=distance_meters,
                    traffic_delay_seconds=traffic_delay,
                    speed_kmh=speed_kmh,
                    data_source='google_maps',
                    raw_data=data
                )
                print(f"[COLLECTOR] Stored data for route: {route_id}")
            
            return result
            
        except requests.RequestException as e:
            print(f"[COLLECTOR] Network error: {e}")
            return None
        except Exception as e:
            print(f"[COLLECTOR] Error: {e}")
            return None
    
    def collect_all_probe_routes(self) -> Dict[str, Dict]:
        """
        Collect traffic data for all active probe routes
        Returns dict mapping route_id to traffic data
        """
        routes = self.db.get_probe_routes(active_only=True)
        
        if not routes:
            print("[COLLECTOR] No probe routes defined!")
            return {}
        
        print(f"[COLLECTOR] Collecting data for {len(routes)} routes...")
        results = {}
        
        for route in routes:
            print(f"[COLLECTOR] Fetching: {route['name']}")
            
            data = self.fetch_route_traffic(
                origin_lat=route['origin_lat'],
                origin_lon=route['origin_lon'],
                dest_lat=route['dest_lat'],
                dest_lon=route['dest_lon'],
                route_id=route['route_id']
            )
            
            if data:
                results[route['route_id']] = data
                print(f"  ✓ {data['travel_time_seconds']}s, {data['speed_kmh']} km/h")
            else:
                print(f"  ✗ Failed to fetch data")
        
        return results
    
    def start_continuous_collection(
        self,
        interval_minutes: int = 15,
        duration_hours: int = 2
    ):
        """
        Continuously collect traffic data at regular intervals
        
        Args:
            interval_minutes: Time between collections
            duration_hours: How long to collect (0 = infinite)
        """
        print(f"[COLLECTOR] Starting continuous collection")
        print(f"  Interval: {interval_minutes} minutes")
        print(f"  Duration: {duration_hours} hours {'(infinite)' if duration_hours == 0 else ''}")
        
        start_time = time.time()
        collection_count = 0
        
        try:
            while True:
                collection_count += 1
                print(f"\n[COLLECTOR] Collection #{collection_count} at {datetime.now().strftime('%H:%M:%S')}")
                
                self.collect_all_probe_routes()
                
                # Check if we should stop
                if duration_hours > 0:
                    elapsed_hours = (time.time() - start_time) / 3600
                    if elapsed_hours >= duration_hours:
                        print(f"\n[COLLECTOR] Completed {duration_hours} hours of collection")
                        break
                
                # Wait for next collection
                print(f"[COLLECTOR] Waiting {interval_minutes} minutes until next collection...")
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            print(f"\n[COLLECTOR] Stopped by user after {collection_count} collections")

class TrafficDataAnalyzer:
    """Analyze collected traffic data"""
    
    def __init__(self):
        self.db = get_db()
    
    def get_route_statistics(
        self,
        route_id: str,
        start_time: str = None,
        end_time: str = None
    ) -> Dict:
        """Calculate statistics for a route"""
        data = self.db.get_real_traffic_data(
            route_id=route_id,
            start_time=start_time,
            end_time=end_time
        )
        
        if not data:
            return {}
        
        travel_times = [d['travel_time_seconds'] for d in data]
        speeds = [d['speed_kmh'] for d in data if d['speed_kmh']]
        
        import statistics
        
        stats = {
            'count': len(data),
            'avg_travel_time': statistics.mean(travel_times),
            'min_travel_time': min(travel_times),
            'max_travel_time': max(travel_times),
            'std_travel_time': statistics.stdev(travel_times) if len(travel_times) > 1 else 0,
        }
        
        if speeds:
            stats['avg_speed'] = statistics.mean(speeds)
            stats['min_speed'] = min(speeds)
            stats['max_speed'] = max(speeds)
        
        return stats
    
    def print_collection_summary(self):
        """Print summary of collected data"""
        routes = self.db.get_probe_routes()
        
        print("\n" + "="*60)
        print("TRAFFIC DATA COLLECTION SUMMARY")
        print("="*60)
        
        for route in routes:
            print(f"\n📍 {route['name']}")
            print(f"   ID: {route['route_id']}")
            
            stats = self.get_route_statistics(route['route_id'])
            
            if stats:
                print(f"   Samples: {stats['count']}")
                print(f"   Avg travel time: {stats['avg_travel_time']:.1f}s ({stats['avg_travel_time']/60:.1f} min)")
                print(f"   Range: {stats['min_travel_time']}s - {stats['max_travel_time']}s")
                if 'avg_speed' in stats:
                    print(f"   Avg speed: {stats['avg_speed']:.1f} km/h")
            else:
                print(f"   ⚠️  No data collected yet")
        
        print("\n" + "="*60)