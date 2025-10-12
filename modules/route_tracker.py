"""
Route Tracker for SUMO Simulation
Tracks vehicles on specific routes to measure travel times
This allows comparison with real-world data
"""
import traci
import time
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from modules.database import get_db

class VehicleTracker:
    """Track individual vehicles through the network"""
    
    def __init__(self):
        self.vehicles = {}  # veh_id -> {start_time, start_pos, route_edges, ...}
        self.completed_trips = []
        
    def add_vehicle(self, veh_id: str, route_edges: List[str], start_time: float):
        """Start tracking a vehicle"""
        self.vehicles[veh_id] = {
            'route_edges': route_edges,
            'start_time': start_time,
            'start_edge': route_edges[0] if route_edges else None,
            'end_edge': route_edges[-1] if route_edges else None,
            'completed': False
        }
    
    def update(self, current_time: float):
        """Update vehicle tracking"""
        completed = []
        
        for veh_id, data in self.vehicles.items():
            if data['completed']:
                continue
            
            try:
                # Check if vehicle still exists
                if veh_id not in traci.vehicle.getIDList():
                    # Vehicle has arrived or left simulation
                    data['end_time'] = current_time
                    data['travel_time'] = current_time - data['start_time']
                    data['completed'] = True
                    completed.append(veh_id)
                    self.completed_trips.append(data.copy())
            except traci.exceptions.TraCIException:
                # Vehicle doesn't exist anymore
                data['end_time'] = current_time
                data['travel_time'] = current_time - data['start_time']
                data['completed'] = True
                completed.append(veh_id)
                self.completed_trips.append(data.copy())
        
        return completed
    
    def get_completed_trips(self) -> List[Dict]:
        """Get all completed trips"""
        return self.completed_trips.copy()
    
    def clear_completed(self):
        """Clear completed trips from memory"""
        self.completed_trips.clear()

class RouteMonitor:
    """
    Monitor specific routes in SUMO simulation
    Maps to probe routes for comparison with real data
    """
    
    def __init__(self, db=None):
        self.db = db or get_db()
        self.probe_routes = {}  # route_id -> route definition
        self.route_vehicles = defaultdict(list)  # route_id -> [vehicle_ids]
        self.route_measurements = defaultdict(list)  # route_id -> [travel_times]
        self.tracker = VehicleTracker()
        
    def load_probe_routes_from_db(self):
        """Load probe routes from database"""
        routes = self.db.get_probe_routes(active_only=True)
        
        for route in routes:
            self.probe_routes[route['route_id']] = {
                'name': route['name'],
                'origin': (route['origin_lat'], route['origin_lon']),
                'destination': (route['dest_lat'], route['dest_lon']),
                'description': route['description']
            }
        
        print(f"[ROUTE_MONITOR] Loaded {len(self.probe_routes)} probe routes")
    
    def find_matching_edges(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        tolerance: float = 0.005  # ~500 meters
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Find SUMO edges closest to given coordinates
        Returns (origin_edge_id, dest_edge_id)
        """
        try:
            # Get all edges in network
            all_edges = traci.edge.getIDList()
            
            # Find closest edge to origin
            origin_edge = None
            min_origin_dist = float('inf')
            
            for edge_id in all_edges:
                if edge_id.startswith(':'):  # Skip internal edges
                    continue
                
                # Get edge position (approximate center)
                try:
                    # This is simplified - in reality you'd need proper coordinate conversion
                    # For now, we'll use edge IDs or positions if available
                    pass
                except:
                    continue
            
            # For now, return None - this requires network coordinates
            # In practice, you'd define routes by edge IDs directly
            return None, None
            
        except Exception as e:
            print(f"[ROUTE_MONITOR] Error finding edges: {e}")
            return None, None
    
    def define_route_by_edges(
        self,
        route_id: str,
        edge_ids: List[str],
        name: str = None
    ):
        """
        Manually define a route by SUMO edge IDs
        This is the practical way to define routes in SUMO
        """
        self.probe_routes[route_id] = {
            'name': name or route_id,
            'edge_ids': edge_ids,
            'origin_edge': edge_ids[0],
            'dest_edge': edge_ids[-1]
        }
        print(f"[ROUTE_MONITOR] Defined route: {name or route_id}")
    
    def check_vehicle_on_route(self, veh_id: str, route_id: str) -> bool:
        """Check if a vehicle is traveling on a specific route"""
        try:
            if route_id not in self.probe_routes:
                return False
            
            route_def = self.probe_routes[route_id]
            if 'edge_ids' not in route_def:
                return False
            
            # Get vehicle's current route
            veh_route = traci.vehicle.getRoute(veh_id)
            
            # Check if vehicle's route includes our probe route edges
            origin_edge = route_def['origin_edge']
            dest_edge = route_def['dest_edge']
            
            if origin_edge in veh_route and dest_edge in veh_route:
                # Check if edges are in correct order
                origin_idx = veh_route.index(origin_edge)
                dest_idx = veh_route.index(dest_edge)
                if dest_idx > origin_idx:
                    return True
            
            return False
            
        except Exception as e:
            return False
    
    def update(self, current_sim_time: float):
        """
        Update monitoring - check for vehicles on probe routes
        Call this every simulation step
        """
        try:
            # Get all current vehicles
            current_vehicles = traci.vehicle.getIDList()
            
            # Check each vehicle against probe routes
            for veh_id in current_vehicles:
                # Skip if already tracking
                if veh_id in self.tracker.vehicles:
                    continue
                
                # Check against each probe route
                for route_id in self.probe_routes:
                    if self.check_vehicle_on_route(veh_id, route_id):
                        # Start tracking this vehicle
                        route_edges = self.probe_routes[route_id].get('edge_ids', [])
                        self.tracker.add_vehicle(veh_id, route_edges, current_sim_time)
                        self.route_vehicles[route_id].append(veh_id)
                        print(f"[ROUTE_MONITOR] Tracking vehicle {veh_id} on route {route_id}")
                        break
            
            # Update tracker
            completed = self.tracker.update(current_sim_time)
            
            # Process completed trips
            for veh_id in completed:
                trip = self.tracker.vehicles[veh_id]
                travel_time = trip.get('travel_time', 0)
                
                # Find which route this vehicle was on
                for route_id, veh_list in self.route_vehicles.items():
                    if veh_id in veh_list:
                        self.route_measurements[route_id].append(travel_time)
                        print(f"[ROUTE_MONITOR] Vehicle {veh_id} completed {route_id}: {travel_time:.1f}s")
                        break
        
        except Exception as e:
            print(f"[ROUTE_MONITOR] Error in update: {e}")
    
    def get_route_statistics(self, route_id: str) -> Optional[Dict]:
        """Get statistics for a monitored route"""
        measurements = self.route_measurements.get(route_id, [])
        
        if not measurements:
            return None
        
        import statistics
        
        return {
            'route_id': route_id,
            'name': self.probe_routes[route_id].get('name', route_id),
            'sample_count': len(measurements),
            'avg_travel_time': statistics.mean(measurements),
            'min_travel_time': min(measurements),
            'max_travel_time': max(measurements),
            'std_dev': statistics.stdev(measurements) if len(measurements) > 1 else 0
        }
    
    def get_all_statistics(self) -> Dict[str, Dict]:
        """Get statistics for all monitored routes"""
        stats = {}
        for route_id in self.probe_routes:
            route_stats = self.get_route_statistics(route_id)
            if route_stats:
                stats[route_id] = route_stats
        return stats
    
    def save_results_to_db(self, scenario_id: str):
        """Save simulation results to database for comparison"""
        for route_id, measurements in self.route_measurements.items():
            if not measurements:
                continue
            
            import statistics
            avg_travel_time = statistics.mean(measurements)
            
            # Estimate distance (you'd need to calculate this from edges)
            # For now, use 0 as placeholder
            distance_meters = 0
            
            # Estimate speed
            avg_speed_kmh = 0  # Would calculate from distance/time
            
            self.db.store_simulation_result(
                scenario_id=scenario_id,
                route_id=route_id,
                travel_time_seconds=avg_travel_time,
                distance_meters=distance_meters,
                avg_speed_kmh=avg_speed_kmh,
                num_vehicles=len(measurements)
            )
        
        print(f"[ROUTE_MONITOR] Saved results for {len(self.route_measurements)} routes")
    
    def print_summary(self):
        """Print monitoring summary"""
        print("\n" + "="*60)
        print("ROUTE MONITORING SUMMARY")
        print("="*60)
        
        stats = self.get_all_statistics()
        
        if not stats:
            print("No route data collected yet")
        else:
            for route_id, route_stats in stats.items():
                print(f"\n📍 {route_stats['name']}")
                print(f"   Vehicles tracked: {route_stats['sample_count']}")
                print(f"   Avg travel time: {route_stats['avg_travel_time']:.1f}s ({route_stats['avg_travel_time']/60:.1f} min)")
                print(f"   Range: {route_stats['min_travel_time']:.1f}s - {route_stats['max_travel_time']:.1f}s")
        
        print("="*60)