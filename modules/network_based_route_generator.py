"""
Network-Based Route Generator
Generates probe routes using ACTUAL SUMO network edges
This ensures routes will always map correctly during simulation
"""
import traci
import random
from typing import Dict, List, Optional, Tuple
from modules.database import get_db

class NetworkBasedRouteGenerator:
    """
    Generate probe routes based on actual SUMO network topology
    Routes are guaranteed to exist since they use real edges
    """

    def __init__(self):
        self.db = get_db()
        self.network_edges = []
        self.edge_positions = {}

    def initialize_from_network(self) -> bool:
        """
        Initialize by scanning the current SUMO network
        Must be called AFTER traci.start()
        """
        try:
            print("[NETWORK_ROUTE_GEN] Scanning SUMO network for available edges...")

            # Get all edges (exclude internal junctions)
            all_edges = [e for e in traci.edge.getIDList() if not e.startswith(':')]

            if not all_edges:
                print("[NETWORK_ROUTE_GEN] No edges found in network!")
                return False

            print(f"[NETWORK_ROUTE_GEN] Processing {len(all_edges)} potential edges...")

            # Get edge positions and filter for valid ones
            valid_edges = []
            errors = 0
            for i, edge_id in enumerate(all_edges):
                try:
                    # Lane IDs are formatted as: edgeID_laneIndex
                    lane_id = f"{edge_id}_0"  # Use first lane (index 0)

                    # Get lane shape
                    shape = traci.lane.getShape(lane_id)

                    if shape and len(shape) > 0:
                        # Get start and end positions
                        start_x, start_y = shape[0]
                        end_x, end_y = shape[-1]

                        # Convert to GPS
                        start_lon, start_lat = traci.simulation.convertGeo(start_x, start_y)
                        end_lon, end_lat = traci.simulation.convertGeo(end_x, end_y)

                        self.edge_positions[edge_id] = {
                            'start': (start_lat, start_lon),
                            'end': (end_lat, end_lon),
                            'length': traci.edge.getLength(edge_id)
                        }

                        valid_edges.append(edge_id)

                        # Progress indicator for large networks
                        if (i + 1) % 500 == 0:
                            print(f"[NETWORK_ROUTE_GEN] Processed {i+1}/{len(all_edges)}...")

                except Exception as e:
                    errors += 1
                    if errors <= 3:  # Show first 3 errors
                        print(f"[NETWORK_ROUTE_GEN] Error on edge '{edge_id}': {e}")
                    continue

            self.network_edges = valid_edges

            print(f"[NETWORK_ROUTE_GEN] Found {len(self.network_edges)} valid edges ({errors} failed)")

            if len(self.network_edges) == 0:
                print("[NETWORK_ROUTE_GEN] ERROR: No valid edges found!")
                print(f"[NETWORK_ROUTE_GEN] Total edges: {len(all_edges)}, All failed: {errors}")
                return False

            print(f"[NETWORK_ROUTE_GEN] Network ready for route generation")
            return True

        except Exception as e:
            print(f"[NETWORK_ROUTE_GEN] Error initializing network: {e}")
            import traceback
            traceback.print_exc()
            return False

    def find_route_in_network(self, origin_edge: str, dest_edge: str) -> Optional[List[str]]:
        """Find a valid route between two edges using SUMO's routing"""
        try:
            route_result = traci.simulation.findRoute(origin_edge, dest_edge)

            if route_result and route_result.edges and len(route_result.edges) > 0:
                return list(route_result.edges)

            return None

        except Exception:
            return None

    def generate_network_based_routes(
        self,
        location_name: str,
        num_routes: int = 8,
        min_route_length: float = 500.0  # meters
    ) -> List[Dict]:
        """
        Generate probe routes using actual network edges

        Returns list of route dicts with REAL GPS coordinates from network
        """
        if not self.network_edges:
            print("[NETWORK_ROUTE_GEN] Network not initialized! Call initialize_from_network() first")
            return []

        print(f"\n[NETWORK_ROUTE_GEN] Generating {num_routes} network-based routes...")

        created_routes = []
        attempts = 0
        max_attempts = num_routes * 10

        while len(created_routes) < num_routes and attempts < max_attempts:
            attempts += 1

            # Pick random origin and destination edges
            origin_edge = random.choice(self.network_edges)
            dest_edge = random.choice(self.network_edges)

            if origin_edge == dest_edge:
                continue

            # Check if route exists
            edge_list = self.find_route_in_network(origin_edge, dest_edge)

            if not edge_list or len(edge_list) < 2:
                continue

            # Calculate route length
            route_length = sum(
                traci.edge.getLength(edge)
                for edge in edge_list
            )

            if route_length < min_route_length:
                continue

            # Get GPS coordinates from actual edges
            origin_pos = self.edge_positions[origin_edge]['start']
            dest_pos = self.edge_positions[dest_edge]['end']

            route_id = f"{location_name}_network_{len(created_routes)+1}"
            route_name = f"{location_name}: Network Route {len(created_routes)+1}"

            route_dict = {
                'route_id': route_id,
                'name': route_name,
                'origin_lat': origin_pos[0],
                'origin_lon': origin_pos[1],
                'dest_lat': dest_pos[0],
                'dest_lon': dest_pos[1],
                'origin_edge': origin_edge,
                'dest_edge': dest_edge,
                'edge_list': edge_list,
                'length_meters': route_length,
                'num_edges': len(edge_list)
            }

            # Add to database
            self.db.add_probe_route(
                route_id=route_id,
                name=route_name,
                origin_lat=origin_pos[0],
                origin_lon=origin_pos[1],
                dest_lat=dest_pos[0],
                dest_lon=dest_pos[1],
                description=f"Network-based route: {len(edge_list)} edges, {route_length:.0f}m"
            )

            created_routes.append(route_dict)

            print(f"[NETWORK_ROUTE_GEN] Created route {len(created_routes)}/{num_routes}")
            print(f"  Length: {route_length:.0f}m, Edges: {len(edge_list)}")

        print(f"\n[NETWORK_ROUTE_GEN] ✅ Created {len(created_routes)} routes from network")

        return created_routes

    def generate_strategic_routes(
        self,
        location_name: str,
        strategy: str = 'mixed'  # 'long', 'short', 'mixed'
    ) -> List[Dict]:
        """
        Generate routes with specific strategies
        """
        if strategy == 'long':
            # Generate longer routes (>1km)
            return self.generate_network_based_routes(location_name, num_routes=6, min_route_length=1000)

        elif strategy == 'short':
            # Generate shorter routes (>200m)
            return self.generate_network_based_routes(location_name, num_routes=10, min_route_length=200)

        else:  # mixed
            # Mix of short and long
            short_routes = self.generate_network_based_routes(location_name, num_routes=4, min_route_length=200)
            long_routes = self.generate_network_based_routes(location_name, num_routes=4, min_route_length=800)
            return short_routes + long_routes


def generate_routes_from_running_network(location_name: str, num_routes: int = 8) -> List[Dict]:
    """
    Convenience function to generate routes from running SUMO network
    Call this DURING simulation (after traci.start())
    """
    generator = NetworkBasedRouteGenerator()

    if not generator.initialize_from_network():
        print("[ERROR] Could not initialize from network")
        return []

    return generator.generate_network_based_routes(location_name, num_routes)
