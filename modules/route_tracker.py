import traci
from collections import defaultdict
from typing import Dict, List, Optional
from modules.database import get_db
from modules.spatial_route_matcher import SpatialRouteMatcher

class VehicleTracker:
    """Track individual vehicles through the network"""
    
    def __init__(self):
        self.vehicles = {}  # veh_id -> vehicle data
        self.completed_trips = []
        
    def add_vehicle(
        self,
        veh_id: str,
        route_id: str,
        start_time: float,
        edge_list: List[str]
    ):
        """Start tracking a vehicle"""
        self.vehicles[veh_id] = {
            'route_id': route_id,
            'start_time': start_time,
            'edge_list': edge_list,
            'start_edge': edge_list[0] if edge_list else None,
            'end_edge': edge_list[-1] if edge_list else None,
            'completed': False,
            'current_edge': None
        }
        
        print(f"[TRACKER] Started tracking vehicle {veh_id} on route {route_id}")
    
    def update(self, current_time: float):
        """Update vehicle tracking"""
        completed = []
        
        for veh_id, data in self.vehicles.items():
            if data['completed']:
                continue
            
            try:
                # Check if vehicle still exists
                if veh_id not in traci.vehicle.getIDList():
                    # Vehicle has left simulation
                    data['end_time'] = current_time
                    data['travel_time'] = current_time - data['start_time']
                    data['completed'] = True
                    completed.append(veh_id)
                    
                    self.completed_trips.append({
                        'vehicle_id': veh_id,
                        'route_id': data['route_id'],
                        'start_time': data['start_time'],
                        'end_time': data['end_time'],
                        'travel_time': data['travel_time']
                    })
                    
                    print(f"[TRACKER] ✅ Vehicle {veh_id} completed route {data['route_id']}: {data['travel_time']:.1f}s")
                else:
                    # Update current position
                    try:
                        current_edge = traci.vehicle.getRoadID(veh_id)
                        data['current_edge'] = current_edge
                    except:
                        pass
                        
            except traci.exceptions.TraCIException:
                # Vehicle no longer exists
                data['completed'] = True
                completed.append(veh_id)
        
        return completed
    
    def get_completed_trips(self) -> List[Dict]:
        """Get all completed trips"""
        return self.completed_trips.copy()
    
    def get_stats(self) -> Dict:
        """Get tracking statistics"""
        return {
            'active_vehicles': sum(1 for v in self.vehicles.values() if not v['completed']),
            'completed_vehicles': len(self.completed_trips),
            'total_tracked': len(self.vehicles)
        }


class RouteMonitor:
    """
    FIXED VERSION: Monitor specific routes using spatial matching
    This ACTUALLY WORKS unlike the original!
    """
    
    def __init__(self, db=None):
        self.db = db or get_db()
        self.spatial_matcher = SpatialRouteMatcher()
        self.tracker = VehicleTracker()
        
        self.route_mappings = {}  # route_id -> SUMO edge mapping
        self.route_measurements = defaultdict(list)  # route_id -> [travel_times]
        self.tracked_vehicles = set()  # vehicles we're already tracking
        
        print("[ROUTE_MONITOR] Fixed route monitor initialized")
    
    def initialize_routes(self):
        """
        Initialize route mappings at simulation start
        MUST BE CALLED after SUMO is running!
        """
        print("\n[ROUTE_MONITOR] Initializing probe route mappings...")
        
        try:
            # Map all GPS routes to SUMO edges
            self.route_mappings = self.spatial_matcher.map_all_probe_routes()
            
            if not self.route_mappings:
                print("[ROUTE_MONITOR] ⚠️ No routes could be mapped!")
                print("[ROUTE_MONITOR] Make sure:")
                print("  1. Probe routes are defined in database")
                print("  2. Routes overlap with simulated area")
                return False
            
            print(f"[ROUTE_MONITOR] ✅ Mapped {len(self.route_mappings)} routes")
            
            # Export for debugging
            self.spatial_matcher.export_mappings()
            
            return True
            
        except Exception as e:
            print(f"[ROUTE_MONITOR] ❌ Error initializing routes: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_new_vehicles(self, current_time: float):
        """
        Check for new vehicles that match our probe routes
        Call this every simulation step
        """
        try:
            # Get all current vehicles
            current_vehicles = traci.vehicle.getIDList()
            
            # Check new vehicles (not yet tracked)
            new_vehicles = [v for v in current_vehicles if v not in self.tracked_vehicles]
            
            for veh_id in new_vehicles:
                # Check against each probe route
                for route_id, mapping in self.route_mappings.items():
                    # Use spatial matcher to check if vehicle matches route
                    if self.spatial_matcher.vehicle_matches_route(veh_id, route_id):
                        # Start tracking this vehicle
                        self.tracker.add_vehicle(
                            veh_id=veh_id,
                            route_id=route_id,
                            start_time=current_time,
                            edge_list=mapping['edge_list']
                        )
                        
                        self.tracked_vehicles.add(veh_id)
                        break  # One route per vehicle
                        
        except Exception as e:
            print(f"[ROUTE_MONITOR] Error checking vehicles: {e}")
    
    def update(self, current_time: float):
        """
        Main update function - call every simulation step
        """
        # Check for new vehicles
        self.check_new_vehicles(current_time)
        
        # Update tracker
        completed = self.tracker.update(current_time)
        
        # Process completed trips
        for trip in self.tracker.get_completed_trips():
            if trip['vehicle_id'] in completed:
                route_id = trip['route_id']
                travel_time = trip['travel_time']
                
                self.route_measurements[route_id].append(travel_time)
                
                print(f"[ROUTE_MONITOR] Route {route_id}: {len(self.route_measurements[route_id])} samples")
    
    def get_route_statistics(self, route_id: str) -> Optional[Dict]:
        """Get statistics for a monitored route"""
        measurements = self.route_measurements.get(route_id, [])
        
        if not measurements:
            return None
        
        import statistics
        
        # Get route info
        mapping = self.route_mappings.get(route_id, {})
        
        return {
            'route_id': route_id,
            'sample_count': len(measurements),
            'avg_travel_time': statistics.mean(measurements),
            'min_travel_time': min(measurements),
            'max_travel_time': max(measurements),
            'std_dev': statistics.stdev(measurements) if len(measurements) > 1 else 0,
            'estimated_distance': mapping.get('estimated_length', 0)
        }
    
    def get_all_statistics(self) -> Dict[str, Dict]:
        """Get statistics for all monitored routes"""
        stats = {}
        for route_id in self.route_mappings.keys():
            route_stats = self.get_route_statistics(route_id)
            if route_stats:
                stats[route_id] = route_stats
        return stats
    
    def save_results_to_db(self, scenario_id: str):
        """Save simulation results to database"""
        print(f"\n[ROUTE_MONITOR] Saving results for scenario: {scenario_id}")
        
        saved_count = 0
        
        for route_id, measurements in self.route_measurements.items():
            if not measurements:
                continue
            
            import statistics
            avg_travel_time = statistics.mean(measurements)
            
            # Get distance from mapping
            mapping = self.route_mappings.get(route_id, {})
            distance_meters = mapping.get('estimated_length', 0)
            
            # Calculate speed
            if avg_travel_time > 0 and distance_meters > 0:
                avg_speed_kmh = (distance_meters / 1000) / (avg_travel_time / 3600)
            else:
                avg_speed_kmh = 0
            
            # Save to database
            self.db.store_simulation_result(
                scenario_id=scenario_id,
                route_id=route_id,
                travel_time_seconds=avg_travel_time,
                distance_meters=distance_meters,
                avg_speed_kmh=avg_speed_kmh,
                num_vehicles=len(measurements)
            )
            
            saved_count += 1
            print(f"[ROUTE_MONITOR]   ✅ {route_id}: {len(measurements)} samples, {avg_travel_time:.1f}s avg")
        
        if saved_count > 0:
            print(f"[ROUTE_MONITOR] ✅ Saved {saved_count} route results to database")
        else:
            print(f"[ROUTE_MONITOR] ⚠️ No route data to save - vehicles may not have matched probe routes")
            print(f"[ROUTE_MONITOR]    This is normal if simulated area doesn't overlap with probe routes")
    
    def print_summary(self):
        """Print monitoring summary"""
        print("\n" + "="*70)
        print("ROUTE MONITORING SUMMARY")
        print("="*70)
        
        tracker_stats = self.tracker.get_stats()
        
        print(f"\nVehicle Tracking:")
        print(f"  Total tracked: {tracker_stats['total_tracked']}")
        print(f"  Completed: {tracker_stats['completed_vehicles']}")
        print(f"  Active: {tracker_stats['active_vehicles']}")
        
        stats = self.get_all_statistics()
        
        if stats:
            print(f"\nRoute Statistics:")
            print(f"{'Route':<40} {'Samples':<10} {'Avg Time':<15} {'Avg Speed':<15}")
            print("-"*70)
            
            for route_id, route_stats in stats.items():
                # Get route name from database
                routes = self.db.get_probe_routes()
                route_name = next((r['name'] for r in routes if r['route_id'] == route_id), route_id)
                
                avg_time_min = route_stats['avg_travel_time'] / 60
                
                # Calculate speed
                if route_stats['estimated_distance'] > 0 and route_stats['avg_travel_time'] > 0:
                    avg_speed = (route_stats['estimated_distance'] / 1000) / (route_stats['avg_travel_time'] / 3600)
                else:
                    avg_speed = 0
                
                print(f"{route_name[:39]:<40} {route_stats['sample_count']:<10} "
                      f"{avg_time_min:<14.1f}m {avg_speed:<14.1f} km/h")
        else:
            print("\n⚠️ No route data collected")
            print("   Possible reasons:")
            print("   1. Simulated area doesn't overlap with probe routes")
            print("   2. Not enough vehicles generated")
            print("   3. Routes couldn't be mapped (check route_mappings.json)")
        
        print("="*70)
    
    def get_coverage_report(self) -> Dict:
        """
        Generate coverage report showing which routes have data
        Useful for debugging
        """
        report = {
            'total_routes': len(self.route_mappings),
            'routes_with_data': len([r for r in self.route_measurements if self.route_measurements[r]]),
            'routes_without_data': [],
            'mapped_routes': list(self.route_mappings.keys())
        }
        
        for route_id in self.route_mappings:
            if not self.route_measurements[route_id]:
                report['routes_without_data'].append(route_id)
        
        return report