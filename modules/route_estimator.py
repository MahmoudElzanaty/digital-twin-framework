"""
Route Estimator
Estimates travel time between two points using simulation data
"""
import os
import csv
import subprocess
import tempfile
from typing import Dict, List, Tuple, Optional
from modules.database import get_db
from modules.advanced_visualizer import AdvancedVisualizer
from modules.results_logger import get_results_logger


class RouteEstimator:
    """Estimate travel times using simulation results"""

    def __init__(self, net_file: str, scenario_id: str):
        """
        Initialize route estimator

        Args:
            net_file: Path to SUMO network file (.net.xml)
            scenario_id: ID of the simulation scenario to use for data
        """
        self.net_file = net_file
        self.scenario_id = scenario_id
        self.edge_speeds = {}  # edge_id -> average speed in m/s
        self.db = get_db()
        self.visualizer = AdvancedVisualizer()
        self.logger = get_results_logger()

        # Load simulation edge data
        self._load_simulation_data()

    def _load_simulation_data(self):
        """Load edge speeds from simulation logs"""
        log_file = "data/logs/edge_state.csv"

        if not os.path.exists(log_file):
            print(f"[ROUTE_ESTIMATOR] Warning: No simulation log found at {log_file}")
            print(f"[ROUTE_ESTIMATOR] Will use default speeds (50 km/h = 13.89 m/s)")
            return

        # Read edge states and calculate average speeds
        edge_data = {}  # edge_id -> list of speeds

        try:
            with open(log_file, 'r') as f:
                reader = csv.DictReader(f)

                # Get column names for debugging
                fieldnames = reader.fieldnames
                print(f"[ROUTE_ESTIMATOR] CSV columns: {fieldnames}")

                for row in reader:
                    # Try different possible column names
                    edge_id = row.get('edge_id') or row.get('edgeID') or row.get('edge')
                    mean_speed = row.get('mean_speed') or row.get('meanSpeed') or row.get('speed')

                    if edge_id and mean_speed:
                        try:
                            speed = float(mean_speed)
                            # Only use positive speeds
                            if speed > 0:
                                if edge_id not in edge_data:
                                    edge_data[edge_id] = []
                                edge_data[edge_id].append(speed)
                        except (ValueError, TypeError):
                            continue

            # Calculate average speed for each edge
            for edge_id, speeds in edge_data.items():
                if speeds:
                    self.edge_speeds[edge_id] = sum(speeds) / len(speeds)

            if len(self.edge_speeds) > 0:
                print(f"[ROUTE_ESTIMATOR] Loaded speed data for {len(self.edge_speeds)} edges")
            else:
                print(f"[ROUTE_ESTIMATOR] Warning: No valid edge speeds found in CSV")
                print(f"[ROUTE_ESTIMATOR] Will use default speeds (50 km/h = 13.89 m/s)")

        except Exception as e:
            print(f"[ROUTE_ESTIMATOR] Error loading simulation data: {e}")
            import traceback
            traceback.print_exc()

    def _find_nearest_edge(self, lat: float, lon: float, max_distance: float = 500.0) -> Optional[str]:
        """Find the nearest edge to given coordinates using network XML"""
        import xml.etree.ElementTree as ET
        import math

        try:
            tree = ET.parse(self.net_file)
            root = tree.getroot()

            # Check network location to understand coordinate system
            location = root.find('location')
            if location is None:
                print(f"[ROUTE_ESTIMATOR] No location info in network - assuming lat/lon")
                use_projection = False
                target_x, target_y = lon, lat
            else:
                print(f"[ROUTE_ESTIMATOR] Network location info: {location.attrib}")

                # Extract projection info
                proj_param = location.get('projParameter', '')
                net_offset_str = location.get('netOffset', '0.0,0.0')

                if 'proj=utm' in proj_param or 'proj=merc' in proj_param:
                    # Network uses projection - need to convert lat/lon
                    use_projection = True

                    # Parse netOffset
                    offset_x, offset_y = map(float, net_offset_str.split(','))

                    # Convert lat/lon to projected coordinates using pyproj
                    try:
                        from pyproj import Proj, transform, Transformer

                        # Create transformer from WGS84 to the network's projection
                        transformer = Transformer.from_crs("EPSG:4326", proj_param, always_xy=True)
                        utm_x, utm_y = transformer.transform(lon, lat)

                        # Apply netOffset to get network coordinates
                        target_x = utm_x + offset_x
                        target_y = utm_y + offset_y

                        print(f"[ROUTE_ESTIMATOR] Converted {lat},{lon} to network coords {target_x:.2f},{target_y:.2f}")

                    except ImportError:
                        print("[ROUTE_ESTIMATOR] ERROR: pyproj not installed. Install with: pip install pyproj")
                        return None
                    except Exception as e:
                        print(f"[ROUTE_ESTIMATOR] Coordinate conversion failed: {e}")
                        return None
                else:
                    # No projection
                    use_projection = False
                    target_x, target_y = lon, lat

            nearest_edge = None
            min_distance = float('inf')
            sample_coords = []

            # Iterate through all edges
            for edge in root.findall('.//edge'):
                edge_id = edge.get('id')

                # Skip internal edges
                if edge_id and ':' in edge_id:
                    continue

                # Get edge shape (series of x,y coordinates)
                for lane in edge.findall('lane'):
                    shape = lane.get('shape')
                    if not shape:
                        continue

                    # Parse shape coordinates
                    points = shape.split()
                    for point in points:
                        try:
                            x, y = point.split(',')
                            point_x, point_y = float(x), float(y)

                            # Store sample coords for debugging
                            if len(sample_coords) < 3:
                                sample_coords.append((point_x, point_y))

                            # Calculate distance in meters (both coordinates are now in same system)
                            # target_x, target_y are already converted to network coordinates
                            # point_x, point_y are network edge coordinates
                            # Both are in UTM meters, so use simple Euclidean distance
                            dx = target_x - point_x
                            dy = target_y - point_y
                            distance = math.sqrt(dx*dx + dy*dy)

                            if distance < min_distance:
                                min_distance = distance
                                nearest_edge = edge_id
                        except Exception as e:
                            continue

            if len(sample_coords) > 0:
                print(f"[ROUTE_ESTIMATOR] Sample network coordinates: {sample_coords[:3]}")
                print(f"[ROUTE_ESTIMATOR] Looking for: lat={lat}, lon={lon} → network coords ({target_x:.2f}, {target_y:.2f})")

            if nearest_edge and min_distance <= max_distance:
                print(f"[ROUTE_ESTIMATOR] Found edge {nearest_edge} at {min_distance:.1f}m from {lat},{lon}")
                return nearest_edge
            else:
                print(f"[ROUTE_ESTIMATOR] No edge found within {max_distance}m of {lat},{lon} (nearest was {min_distance:.1f}m)")
                return None

        except Exception as e:
            print(f"[ROUTE_ESTIMATOR] Error finding nearest edge: {e}")
            import traceback
            traceback.print_exc()
            return None

    def find_route(self, from_lat: float, from_lon: float,
                   to_lat: float, to_lon: float) -> Optional[Dict]:
        """
        Find route between two points and estimate travel time

        Args:
            from_lat, from_lon: Origin coordinates
            to_lat, to_lon: Destination coordinates

        Returns:
            Dictionary with route information or None if route not found
        """
        try:
            # Find nearest edges to the clicked coordinates
            print(f"[ROUTE_ESTIMATOR] Finding nearest edges to coordinates...")
            from_edge = self._find_nearest_edge(from_lat, from_lon)
            to_edge = self._find_nearest_edge(to_lat, to_lon)

            if not from_edge:
                print(f"[ROUTE_ESTIMATOR] Could not find origin edge near {from_lat},{from_lon}")
                return None

            if not to_edge:
                print(f"[ROUTE_ESTIMATOR] Could not find destination edge near {to_lat},{to_lon}")
                return None

            # Use SUMO's duarouter to find the route
            # Create a trip file with edge IDs instead of coordinates
            trip_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<routes>
    <vType id="estimator_car" vClass="passenger"/>
    <trip id="estimate" type="estimator_car" depart="0" from="{from_edge}" to="{to_edge}"/>
</routes>"""

            # Create temporary files
            with tempfile.NamedTemporaryFile(mode='w', suffix='.trips.xml', delete=False) as trip_file:
                trip_file.write(trip_content)
                trip_path = trip_file.name

            print(f"[ROUTE_ESTIMATOR] Trip file created: {trip_path}")
            print(f"[ROUTE_ESTIMATOR] Trip content:")
            print(trip_content)

            route_path = trip_path.replace('.trips.xml', '.rou.xml')

            # Run duarouter to find the route
            print(f"[ROUTE_ESTIMATOR] Running duarouter...")
            print(f"[ROUTE_ESTIMATOR]   Network: {self.net_file}")
            print(f"[ROUTE_ESTIMATOR]   From: {from_lat}, {from_lon}")
            print(f"[ROUTE_ESTIMATOR]   To: {to_lat}, {to_lon}")

            result = subprocess.run([
                'duarouter',
                '-n', self.net_file,
                '--route-files', trip_path,
                '-o', route_path,
                '--repair',
                '--repair.from',
                '--repair.to',
                '--mapmatch.distance', '500',  # Search within 500m for nearest edge
                '--mapmatch.junctions',  # Allow routing from junctions
                '--routing-algorithm', 'astar',  # Use A* for better routing
                '--verbose',
                '--error-log', route_path + '.errors.txt'
            ], capture_output=True, text=True)

            # Check for errors even if return code is 0 (duarouter sometimes succeeds with warnings)
            error_log_path = route_path + '.errors.txt'
            if os.path.exists(error_log_path):
                with open(error_log_path, 'r') as f:
                    errors = f.read()
                    if errors.strip():
                        print(f"[ROUTE_ESTIMATOR] duarouter errors/warnings:")
                        print(errors)
                try:
                    os.unlink(error_log_path)
                except:
                    pass

            if result.returncode != 0:
                print(f"[ROUTE_ESTIMATOR] duarouter failed with return code {result.returncode}")
                print(f"[ROUTE_ESTIMATOR] STDERR: {result.stderr}")
                print(f"[ROUTE_ESTIMATOR] STDOUT: {result.stdout}")
                print(f"[ROUTE_ESTIMATOR] Trip file: {trip_path}")
                print(f"[ROUTE_ESTIMATOR] Network file: {self.net_file}")
                try:
                    os.unlink(trip_path)
                except:
                    pass
                return None

            # Check if route file was created
            if not os.path.exists(route_path):
                print(f"[ROUTE_ESTIMATOR] Route file not created: {route_path}")
                try:
                    os.unlink(trip_path)
                except:
                    pass
                return None

            # Parse the route file to get edges
            import xml.etree.ElementTree as ET
            try:
                tree = ET.parse(route_path)
                root = tree.getroot()
            except Exception as e:
                print(f"[ROUTE_ESTIMATOR] Failed to parse route file: {e}")
                try:
                    os.unlink(trip_path)
                    os.unlink(route_path)
                except:
                    pass
                return None

            route_elem = root.find('.//route')
            if route_elem is None or 'edges' not in route_elem.attrib:
                print("[ROUTE_ESTIMATOR] No route found between points")
                print(f"[ROUTE_ESTIMATOR] Route XML content:")
                # Print route file content for debugging
                try:
                    with open(route_path, 'r') as f:
                        print(f.read())
                except:
                    pass
                try:
                    os.unlink(trip_path)
                    os.unlink(route_path)
                except:
                    pass
                return None

            edges = route_elem.get('edges').split()
            print(f"[ROUTE_ESTIMATOR] Found route with {len(edges)} edges")

            # Clean up temp files
            try:
                os.unlink(trip_path)
                os.unlink(route_path)
            except:
                pass

            # Calculate travel time using simulation data
            result = self._estimate_travel_time(edges, from_lat, from_lon, to_lat, to_lon)

            # Log the estimation
            if result and result.get('success'):
                self.logger.log_route_estimation(result)

                # Generate visualization
                try:
                    viz_path = self.visualizer.plot_route_estimation(result)
                    result['visualization_path'] = viz_path
                    print(f"[ROUTE_ESTIMATOR] ✅ Visualization saved: {viz_path}")
                except Exception as viz_error:
                    print(f"[ROUTE_ESTIMATOR] ⚠️ Could not generate visualization: {viz_error}")

            return result

        except Exception as e:
            print(f"[ROUTE_ESTIMATOR] Error finding route: {e}")
            self.logger.log_error("Route estimation", e)
            import traceback
            traceback.print_exc()
            return None

    def _estimate_travel_time(self, edges: List[str], from_lat: float, from_lon: float,
                              to_lat: float, to_lon: float) -> Dict:
        """
        Calculate estimated travel time based on simulation edge speeds

        Args:
            edges: List of edge IDs in the route
            from_lat, from_lon: Origin coordinates
            to_lat, to_lon: Destination coordinates

        Returns:
            Dictionary with route estimation results
        """
        # Get edge lengths from network
        import xml.etree.ElementTree as ET
        tree = ET.parse(self.net_file)
        root = tree.getroot()

        edge_lengths = {}
        for edge in root.findall('.//edge'):
            edge_id = edge.get('id')
            if edge_id and ':' not in edge_id:  # Skip internal edges
                # Calculate length from lanes
                lane = edge.find('lane')
                if lane is not None and 'length' in lane.attrib:
                    edge_lengths[edge_id] = float(lane.get('length'))

        # Calculate total distance and time
        total_distance = 0.0
        total_time = 0.0
        edges_used = 0
        edges_with_data = 0

        edge_details = []

        for edge_id in edges:
            if edge_id in edge_lengths:
                length = edge_lengths[edge_id]
                total_distance += length
                edges_used += 1

                # Get speed from simulation data
                if edge_id in self.edge_speeds:
                    speed = self.edge_speeds[edge_id]  # m/s
                    edges_with_data += 1
                else:
                    # Use default speed if no simulation data
                    speed = 13.89  # 50 km/h default

                time = length / speed if speed > 0 else length / 13.89
                total_time += time

                edge_details.append({
                    'edge_id': edge_id,
                    'length': length,
                    'speed_ms': speed,
                    'speed_kmh': speed * 3.6,
                    'time': time,
                    'has_sim_data': edge_id in self.edge_speeds
                })

        # Calculate straight-line distance for reference
        import math
        lat_diff = (to_lat - from_lat) * 111000  # meters
        lon_diff = (to_lon - from_lon) * 111000 * math.cos(math.radians(from_lat))
        straight_line_distance = math.sqrt(lat_diff**2 + lon_diff**2)

        return {
            'success': True,
            'distance_meters': total_distance,
            'distance_km': total_distance / 1000,
            'travel_time_seconds': total_time,
            'travel_time_minutes': total_time / 60,
            'average_speed_kmh': (total_distance / total_time * 3.6) if total_time > 0 else 0,
            'num_edges': edges_used,
            'edges_with_sim_data': edges_with_data,
            'data_coverage': (edges_with_data / edges_used * 100) if edges_used > 0 else 0,
            'straight_line_distance': straight_line_distance,
            'route_factor': total_distance / straight_line_distance if straight_line_distance > 0 else 1.0,
            'edge_details': edge_details,
            'origin': {'lat': from_lat, 'lon': from_lon},
            'destination': {'lat': to_lat, 'lon': to_lon}
        }

    def compare_with_google_maps(self, from_lat: float, from_lon: float,
                                  to_lat: float, to_lon: float,
                                  api_key: str) -> Optional[Dict]:
        """
        Compare simulation estimate with Google Maps real-time data

        Returns:
            Dictionary with comparison results
        """
        # Get simulation estimate
        sim_result = self.find_route(from_lat, from_lon, to_lat, to_lon)

        if not sim_result or not sim_result.get('success'):
            return None

        # Get Google Maps estimate
        try:
            from modules.data_collector import TrafficDataCollector
            collector = TrafficDataCollector(api_key)

            real_data = collector.fetch_route_traffic(
                origin_lat=from_lat,
                origin_lon=from_lon,
                dest_lat=to_lat,
                dest_lon=to_lon,
                route_id=None
            )

            if not real_data:
                print("[ROUTE_ESTIMATOR] Could not fetch Google Maps data")
                return sim_result

            # Add comparison
            sim_result['google_maps'] = {
                'travel_time_seconds': real_data['travel_time_seconds'],
                'travel_time_minutes': real_data['travel_time_seconds'] / 60,
                'distance_meters': real_data['distance_meters'],
                'speed_kmh': real_data['speed_kmh'],
                'traffic_delay_seconds': real_data.get('traffic_delay_seconds', 0)
            }

            # Calculate accuracy
            time_error = abs(sim_result['travel_time_seconds'] - real_data['travel_time_seconds'])
            time_error_pct = (time_error / real_data['travel_time_seconds'] * 100) if real_data['travel_time_seconds'] > 0 else 0

            speed_error = abs(sim_result['average_speed_kmh'] - real_data['speed_kmh'])
            speed_error_pct = (speed_error / real_data['speed_kmh'] * 100) if real_data['speed_kmh'] > 0 else 0

            sim_result['comparison'] = {
                'time_error_seconds': time_error,
                'time_error_percent': time_error_pct,
                'speed_error_kmh': speed_error,
                'speed_error_percent': speed_error_pct,
                'distance_error_meters': abs(sim_result['distance_meters'] - real_data['distance_meters'])
            }

            # Log the comparison
            self.logger.log_route_estimation(sim_result)

            # Generate comparison visualization
            try:
                viz_path = self.visualizer.plot_route_estimation(sim_result)
                sim_result['visualization_path'] = viz_path
                print(f"[ROUTE_ESTIMATOR] ✅ Comparison visualization saved: {viz_path}")
            except Exception as viz_error:
                print(f"[ROUTE_ESTIMATOR] ⚠️ Could not generate visualization: {viz_error}")

            return sim_result

        except Exception as e:
            print(f"[ROUTE_ESTIMATOR] Error comparing with Google Maps: {e}")
            self.logger.log_error("Google Maps comparison", e)
            import traceback
            traceback.print_exc()
            return sim_result
