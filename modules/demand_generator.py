import os
import subprocess
import xml.etree.ElementTree as ET
from typing import List, Tuple, Optional

def generate_routes(net_file, output_dir, sim_time=3600, trip_rate=3.0):
    """Generate random trips based on the network with validation."""
    route_file = os.path.join(output_dir, "routes.rou.xml")
    print(f"[INFO] Generating random trips with validation (1 vehicle every {trip_rate}s)...")

    # Use SUMO's randomTrips.py with validation to avoid stuck vehicles
    subprocess.run([
        "python", os.path.join(os.environ["SUMO_HOME"], "tools", "randomTrips.py"),
        "-n", net_file,
        "-o", route_file,
        "-e", str(sim_time),
        "--period", str(trip_rate),
        "--binomial", "2",
        "--validate",  # Validate routes - ensures destinations are reachable
        "--remove-loops",  # Remove looping routes
        "--min-distance", "500",  # Minimum route distance (500m) - longer routes avoid issues
        "--max-distance", "5000",  # Maximum distance to avoid extremely long routes
        "--fringe-factor", "10",  # Strongly prefer edge nodes as start/end (better connectivity)
        "--trip-attributes", 'departLane="best" departSpeed="max" departPos="random"',  # Better insertion
        "--random-depart",  # Randomize departure times to avoid congestion spikes
    ], check=True)
    print(f"[SUCCESS] Routes generated and validated: {route_file}")
    return route_file


def find_edges_near_point(net_file: str, lat: float, lon: float, max_distance: float = 1000.0) -> List[str]:
    """Find all edges within max_distance meters of a lat/lon point"""
    import math

    try:
        tree = ET.parse(net_file)
        root = tree.getroot()

        # Get network projection info
        location = root.find('location')
        target_x, target_y = lon, lat

        if location is not None:
            proj_param = location.get('projParameter', '')
            net_offset_str = location.get('netOffset', '0.0,0.0')

            if 'proj=utm' in proj_param or 'proj=merc' in proj_param:
                # Convert lat/lon to network coordinates
                try:
                    from pyproj import Transformer
                    offset_x, offset_y = map(float, net_offset_str.split(','))
                    transformer = Transformer.from_crs("EPSG:4326", proj_param, always_xy=True)
                    utm_x, utm_y = transformer.transform(lon, lat)
                    target_x = utm_x + offset_x
                    target_y = utm_y + offset_y
                    print(f"[DEMAND_GEN] Converted {lat},{lon} to network coords {target_x:.2f},{target_y:.2f}")
                except Exception as e:
                    print(f"[DEMAND_GEN] Coordinate conversion failed: {e}")
                    return []

        # Find all edges within distance
        nearby_edges = []

        for edge in root.findall('.//edge'):
            edge_id = edge.get('id')

            # Skip internal edges
            if edge_id and ':' in edge_id:
                continue

            # Get edge shape
            for lane in edge.findall('lane'):
                shape = lane.get('shape')
                if not shape:
                    continue

                # Check if any point on the edge is within distance
                points = shape.split()
                for point in points:
                    try:
                        x, y = point.split(',')
                        point_x, point_y = float(x), float(y)

                        # Calculate distance
                        dx = target_x - point_x
                        dy = target_y - point_y
                        distance = math.sqrt(dx*dx + dy*dy)

                        if distance <= max_distance:
                            if edge_id not in nearby_edges:
                                nearby_edges.append(edge_id)
                            break
                    except:
                        continue
                break  # Only need to check first lane

        print(f"[DEMAND_GEN] Found {len(nearby_edges)} edges within {max_distance}m of {lat},{lon}")
        return nearby_edges

    except Exception as e:
        print(f"[DEMAND_GEN] Error finding nearby edges: {e}")
        import traceback
        traceback.print_exc()
        return []


def generate_targeted_routes(net_file: str, output_dir: str,
                            origin_lat: float, origin_lon: float,
                            dest_lat: float, dest_lon: float,
                            sim_time: int = 1800, num_vehicles: int = 50,
                            calibration_params: dict = None) -> Optional[str]:
    """Generate routes targeting specific origin/destination area for data collection with calibration"""

    print(f"[DEMAND_GEN] Generating targeted routes from {origin_lat},{origin_lon} to {dest_lat},{dest_lon}")

    # Find edges near origin and destination
    origin_edges = find_edges_near_point(net_file, origin_lat, origin_lon, max_distance=500.0)
    dest_edges = find_edges_near_point(net_file, dest_lat, dest_lon, max_distance=500.0)

    if not origin_edges:
        print(f"[DEMAND_GEN] ERROR: No edges found near origin {origin_lat},{origin_lon}")
        return None

    if not dest_edges:
        print(f"[DEMAND_GEN] ERROR: No edges found near destination {dest_lat},{dest_lon}")
        return None

    print(f"[DEMAND_GEN] Origin area: {len(origin_edges)} edges, Destination area: {len(dest_edges)} edges")

    # Use calibration parameters or defaults
    if calibration_params:
        speed_factor = calibration_params.get('speedFactor', 1.0)
        speed_dev = calibration_params.get('speedDev', 0.1)
        sigma = calibration_params.get('sigma', 0.5)
        tau = calibration_params.get('tau', 1.0)
        print(f"[DEMAND_GEN] Using calibrated parameters: speedFactor={speed_factor:.2f}, sigma={sigma:.2f}")
    else:
        speed_factor = 1.0
        speed_dev = 0.1
        sigma = 0.5
        tau = 1.0
        print(f"[DEMAND_GEN] Warning: No calibration params provided, using defaults")

    # Create trips file
    trips_file = os.path.join(output_dir, "targeted_trips.trips.xml")
    route_file = os.path.join(output_dir, "targeted_routes.rou.xml")

    # Generate trip combinations with calibrated vType
    import random
    trips_content = ['<trips>']

    # Add calibrated vehicle type definition
    trips_content.append(
        f'    <vType id="calibrated_car" '
        f'speedFactor="{speed_factor:.3f}" '
        f'speedDev="{speed_dev:.3f}" '
        f'sigma="{sigma:.3f}" '
        f'tau="{tau:.3f}" '
        f'vClass="passenger" '
        f'carFollowModel="Krauss"/>'
    )

    depart_time = 0
    time_increment = sim_time / num_vehicles  # Spread vehicles over simulation time

    for i in range(num_vehicles):
        # Randomly select origin and destination edges
        from_edge = random.choice(origin_edges)
        to_edge = random.choice(dest_edges)

        trips_content.append(
            f'    <trip id="targeted_{i}" type="calibrated_car" depart="{depart_time:.1f}" '
            f'from="{from_edge}" to="{to_edge}" '
            f'departLane="best" departSpeed="max"/>'
        )

        depart_time += time_increment

    trips_content.append('</trips>')

    # Write trips file
    os.makedirs(output_dir, exist_ok=True)
    with open(trips_file, 'w') as f:
        f.write('\n'.join(trips_content))

    print(f"[DEMAND_GEN] Created {num_vehicles} targeted trips in {trips_file}")

    # Convert trips to routes using duarouter
    print(f"[DEMAND_GEN] Converting trips to routes with duarouter...")
    try:
        subprocess.run([
            "duarouter",
            "--net-file", net_file,
            "--trip-files", trips_file,
            "--output-file", route_file,
            "--ignore-errors",
            "--repair",
            "--remove-loops",
            "--max-alternatives", "3",
            "--routing-algorithm", "dijkstra"
        ], check=True, capture_output=True, text=True)

        print(f"[SUCCESS] Targeted routes generated: {route_file}")
        return route_file

    except subprocess.CalledProcessError as e:
        print(f"[DEMAND_GEN] ERROR: duarouter failed: {e.stderr}")
        return None
