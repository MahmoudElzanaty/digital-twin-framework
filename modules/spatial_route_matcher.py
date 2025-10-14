"""
Spatial Route Matcher
Maps GPS coordinates to SUMO edges for route tracking
SOLVES THE ROUTE TRACKING PROBLEM
"""
import traci
import math
from typing import Tuple, Optional, List, Dict
from modules.database import get_db

class SpatialRouteMatcher:
    """
    Maps real-world GPS routes to SUMO network edges
    This is the MISSING LINK in your route tracking!
    """
    
    def __init__(self):
        self.db = get_db()
        self.edge_cache = {}  # Cache edge positions
        self.route_mappings = {}  # Stored GPS → Edge mappings
    
    def haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two GPS points (meters)"""
        R = 6371000  # Earth radius in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def get_edge_position(self, edge_id: str) -> Optional[Tuple[float, float]]:
        """
        Get approximate GPS position of a SUMO edge
        Uses edge midpoint
        """
        if edge_id in self.edge_cache:
            return self.edge_cache[edge_id]
        
        try:
            # Get edge shape (list of x,y coordinates in SUMO projection)
            shape = traci.edge.getShape(edge_id)
            
            if not shape:
                return None
            
            # Get midpoint of edge
            mid_idx = len(shape) // 2
            x, y = shape[mid_idx]
            
            # Convert SUMO coordinates to GPS
            # IMPORTANT: This requires knowing the network's projection!
            # For now, we'll use SUMO's built-in conversion
            lon, lat = traci.simulation.convertGeo(x, y)
            
            self.edge_cache[edge_id] = (lat, lon)
            return (lat, lon)
            
        except Exception as e:
            print(f"[SPATIAL] Error getting edge position for {edge_id}: {e}")
            return None
    
    def find_nearest_edge(
        self, 
        target_lat: float, 
        target_lon: float,
        max_distance: float = 500.0  # meters
    ) -> Optional[str]:
        """
        Find the nearest SUMO edge to a GPS coordinate
        This is THE KEY FUNCTION!
        """
        all_edges = traci.edge.getIDList()
        
        best_edge = None
        best_distance = float('inf')
        
        for edge_id in all_edges:
            # Skip internal edges
            if edge_id.startswith(':'):
                continue
            
            edge_pos = self.get_edge_position(edge_id)
            if not edge_pos:
                continue
            
            edge_lat, edge_lon = edge_pos
            
            distance = self.haversine_distance(
                target_lat, target_lon,
                edge_lat, edge_lon
            )
            
            if distance < best_distance:
                best_distance = distance
                best_edge = edge_id
        
        # Only return if within max_distance
        if best_distance <= max_distance:
            print(f"[SPATIAL] Matched GPS ({target_lat:.4f}, {target_lon:.4f}) to edge {best_edge} ({best_distance:.1f}m away)")
            return best_edge
        else:
            print(f"[SPATIAL] No edge found within {max_distance}m of GPS ({target_lat:.4f}, {target_lon:.4f})")
            return None
    
    def map_gps_route_to_sumo(
        self,
        route_id: str,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float
    ) -> Optional[Dict]:
        """
        Map a GPS route (from database) to SUMO edges
        This creates the route_id → edge_list mapping
        """
        print(f"\n[SPATIAL] Mapping GPS route to SUMO: {route_id}")
        print(f"[SPATIAL] Origin: ({origin_lat:.4f}, {origin_lon:.4f})")
        print(f"[SPATIAL] Dest: ({dest_lat:.4f}, {dest_lon:.4f})")
        
        # Find nearest edges
        origin_edge = self.find_nearest_edge(origin_lat, origin_lon)
        dest_edge = self.find_nearest_edge(dest_lat, dest_lon)
        
        if not origin_edge or not dest_edge:
            print(f"[SPATIAL] ❌ Failed to map route {route_id}")
            return None
        
        # Use SUMO's routing to find path
        try:
            # Get route from origin to destination
            route_edges = traci.simulation.findRoute(origin_edge, dest_edge)
            
            if not route_edges or not route_edges.edges:
                print(f"[SPATIAL] ❌ No route found between edges")
                return None
            
            edge_list = list(route_edges.edges)
            
            mapping = {
                'route_id': route_id,
                'origin_edge': origin_edge,
                'dest_edge': dest_edge,
                'edge_list': edge_list,
                'num_edges': len(edge_list),
                'estimated_length': route_edges.length
            }
            
            self.route_mappings[route_id] = mapping
            
            print(f"[SPATIAL] ✅ Mapped route: {len(edge_list)} edges, {route_edges.length:.0f}m")
            
            return mapping
            
        except Exception as e:
            print(f"[SPATIAL] ❌ Error finding route: {e}")
            return None
    
    def map_all_probe_routes(self):
        """
        Map all probe routes from database to SUMO edges
        Call this at simulation start!
        """
        routes = self.db.get_probe_routes(active_only=True)
        
        print(f"\n[SPATIAL] Mapping {len(routes)} probe routes to SUMO network...")
        
        success_count = 0
        
        for route in routes:
            mapping = self.map_gps_route_to_sumo(
                route_id=route['route_id'],
                origin_lat=route['origin_lat'],
                origin_lon=route['origin_lon'],
                dest_lat=route['dest_lat'],
                dest_lon=route['dest_lon']
            )
            
            if mapping:
                success_count += 1
        
        print(f"\n[SPATIAL] Successfully mapped {success_count}/{len(routes)} routes")
        
        return self.route_mappings
    
    def vehicle_matches_route(
        self,
        vehicle_id: str,
        route_id: str,
        threshold: float = 0.7  # 70% of edges must match
    ) -> bool:
        """
        Check if a vehicle's route matches a probe route
        More robust than exact matching
        """
        if route_id not in self.route_mappings:
            return False
        
        probe_route = self.route_mappings[route_id]
        probe_edges = set(probe_route['edge_list'])
        
        try:
            vehicle_route = traci.vehicle.getRoute(vehicle_id)
            vehicle_edges = set(vehicle_route)
            
            # Calculate overlap
            overlap = len(probe_edges & vehicle_edges)
            overlap_ratio = overlap / len(probe_edges) if probe_edges else 0
            
            matches = overlap_ratio >= threshold
            
            if matches:
                print(f"[SPATIAL] ✅ Vehicle {vehicle_id} matches route {route_id} ({overlap_ratio*100:.0f}% overlap)")
            
            return matches
            
        except Exception as e:
            return False
    
    def get_route_mapping(self, route_id: str) -> Optional[Dict]:
        """Get the SUMO edge mapping for a route"""
        return self.route_mappings.get(route_id)
    
    def export_mappings(self, filename: str = "data/route_mappings.json"):
        """Export mappings for inspection"""
        import json
        
        # Convert to serializable format
        export_data = {}
        for route_id, mapping in self.route_mappings.items():
            export_data[route_id] = {
                'origin_edge': mapping['origin_edge'],
                'dest_edge': mapping['dest_edge'],
                'num_edges': mapping['num_edges'],
                'edge_list': mapping['edge_list']
            }
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"[SPATIAL] Exported mappings to {filename}")