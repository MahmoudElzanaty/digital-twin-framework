"""
Area Manager Module
Manages monitored areas for digital twin training and prediction
Bridges map selection → SUMO network → data collection → prediction
"""
import os
from datetime import datetime
from typing import Dict, List, Optional
from modules.database import get_db
from modules.network_builder import generate_network_from_bbox


class AreaManager:
    """
    Central manager for monitored areas

    Workflow:
    1. Create area from map selection (bbox)
    2. Build SUMO network
    3. Track training status
    4. Validate routes within area
    5. Manage area lifecycle
    """

    def __init__(self):
        self.db = get_db()

    def create_area_from_bbox(
        self,
        area_name: str,
        bbox: Dict[str, float],
        build_network: bool = True
    ) -> Dict:
        """
        Create a monitored area from map bounding box

        Args:
            area_name: Human-readable name (e.g., "Downtown Cairo")
            bbox: Dict with keys: north, south, east, west
            build_network: Whether to build SUMO network immediately

        Returns:
            Dict with area details including area_id, network_file, status
        """
        print("\n" + "="*70)
        print(f"CREATING MONITORED AREA: {area_name}")
        print("="*70)

        # Generate unique area ID
        area_id = f"area_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"[AREA MANAGER] Area ID: {area_id}")
        print(f"[AREA MANAGER] Bounding Box:")
        print(f"  North: {bbox['north']:.6f}")
        print(f"  South: {bbox['south']:.6f}")
        print(f"  East:  {bbox['east']:.6f}")
        print(f"  West:  {bbox['west']:.6f}")

        # Calculate area dimensions
        lat_diff = bbox['north'] - bbox['south']
        lon_diff = bbox['east'] - bbox['west']
        approx_size_km = lat_diff * 111  # Rough km conversion

        print(f"[AREA MANAGER] Approximate size: {approx_size_km:.2f} km x {approx_size_km:.2f} km")

        network_file = None

        if build_network:
            print(f"\n[AREA MANAGER] Building SUMO network...")
            try:
                # Use existing network_builder to download OSM and convert to SUMO
                network_file = generate_network_from_bbox(
                    bbox=bbox,
                    location_name=area_name.replace(" ", "_"),
                    output_dir=f"data/networks/{area_id}"
                )

                print(f"[AREA MANAGER] SUMO network created: {network_file}")

                # Analyze network
                network_stats = self._analyze_network(network_file)
                print(f"[AREA MANAGER] Network analysis:")
                print(f"  Edges: {network_stats['num_edges']}")
                print(f"  Junctions: {network_stats['num_junctions']}")
                print(f"  Total length: {network_stats['total_length_km']:.2f} km")

            except Exception as e:
                print(f"[AREA MANAGER] ⚠️ Network build failed: {e}")
                print(f"[AREA MANAGER] Area created without network (can be built later)")

        # Store in database
        self.db.create_monitored_area(
            area_id=area_id,
            name=area_name,
            bbox=bbox,
            sumo_network_file=network_file
        )

        print(f"\n[AREA MANAGER] Area created successfully!")
        print("="*70 + "\n")

        return {
            'area_id': area_id,
            'name': area_name,
            'bbox': bbox,
            'network_file': network_file,
            'status': 'created',
            'network_stats': network_stats if network_file else None
        }

    def _analyze_network(self, network_file: str) -> Dict:
        """Analyze SUMO network structure"""
        try:
            import sumolib

            net = sumolib.net.readNet(network_file)
            edges = net.getEdges()
            junctions = net.getNodes()

            # Calculate statistics
            total_length = sum(e.getLength() for e in edges)
            avg_speed = sum(e.getSpeed() for e in edges) / len(edges) if edges else 0

            # Count by road type
            edge_types = {}
            for edge in edges:
                edge_type = edge.getType() or 'unknown'
                edge_types[edge_type] = edge_types.get(edge_type, 0) + 1

            return {
                'num_edges': len(edges),
                'num_junctions': len(junctions),
                'total_length_km': total_length / 1000,
                'avg_speed_limit': avg_speed * 3.6,  # m/s to km/h
                'edge_types': edge_types
            }

        except Exception as e:
            print(f"[AREA MANAGER] Could not analyze network: {e}")
            return {
                'num_edges': 0,
                'num_junctions': 0,
                'total_length_km': 0,
                'avg_speed_limit': 0,
                'edge_types': {}
            }

    def get_area(self, area_id: str) -> Optional[Dict]:
        """Get area details"""
        return self.db.get_monitored_area(area_id)

    def list_all_areas(self) -> List[Dict]:
        """List all monitored areas"""
        return self.db.get_all_monitored_areas()

    def start_area_training(
        self,
        area_id: str,
        duration_weeks: int,
        interval_minutes: int = 15
    ) -> Dict:
        """
        Start training data collection for area

        Args:
            area_id: Area to train
            duration_weeks: How many weeks to collect data
            interval_minutes: Collection interval (default 15 min)

        Returns:
            Training configuration dict
        """
        area = self.db.get_monitored_area(area_id)

        if not area:
            raise ValueError(f"Area {area_id} not found")

        if area['status'] == 'training':
            raise ValueError(f"Area {area_id} is already training")

        if area['status'] == 'trained':
            print(f"[AREA MANAGER] Warning: Area {area_id} is already trained. Re-training...")

        # Calculate collection parameters
        duration_days = duration_weeks * 7
        collections_per_day = (24 * 60) // interval_minutes
        total_collections = duration_days * collections_per_day

        print(f"\n[AREA MANAGER] Starting training for: {area['name']}")
        print(f"  Duration: {duration_weeks} weeks ({duration_days} days)")
        print(f"  Interval: {interval_minutes} minutes")
        print(f"  Total collections: {total_collections}")

        # Update database
        self.db.update_area_status(
            area_id=area_id,
            status='training',
            training_start_date=datetime.now().isoformat(),
            training_duration_days=duration_days,
            collections_target=total_collections
        )

        print(f"[AREA MANAGER] Training started")

        return {
            'area_id': area_id,
            'area_name': area['name'],
            'duration_days': duration_days,
            'duration_weeks': duration_weeks,
            'interval_minutes': interval_minutes,
            'collections_per_day': collections_per_day,
            'total_collections': total_collections,
            'training_start': datetime.now().isoformat()
        }

    def update_training_progress(self, area_id: str, collections_completed: int):
        """Update training progress"""
        self.db.update_area_training_progress(area_id, collections_completed)

        area = self.db.get_monitored_area(area_id)
        if area['collections_target']:
            progress = (collections_completed / area['collections_target']) * 100
            print(f"[AREA MANAGER] Training progress: {progress:.1f}% ({collections_completed}/{area['collections_target']})")

    def complete_area_training(
        self,
        area_id: str,
        accuracy_metrics: Dict[str, float]
    ):
        """
        Mark area training as complete

        Args:
            area_id: Area that completed training
            accuracy_metrics: Dict with 'rmse', 'mae', 'mape' keys
        """
        self.db.mark_area_training_complete(
            area_id=area_id,
            accuracy_rmse=accuracy_metrics['rmse'],
            accuracy_mae=accuracy_metrics['mae'],
            accuracy_mape=accuracy_metrics['mape']
        )

        print(f"\n[AREA MANAGER] Training complete for area: {area_id}")
        print(f"  RMSE: {accuracy_metrics['rmse']:.2f}")
        print(f"  MAE: {accuracy_metrics['mae']:.2f}")
        print(f"  MAPE: {accuracy_metrics['mape']:.2f}%")

    def is_point_in_area(
        self,
        lat: float,
        lon: float,
        area_id: str
    ) -> bool:
        """Check if a point (lat, lon) is within area bounds"""
        area = self.db.get_monitored_area(area_id)

        if not area:
            return False

        bbox = area['bbox']

        return (
            bbox['south'] <= lat <= bbox['north'] and
            bbox['west'] <= lon <= bbox['east']
        )

    def is_route_in_area(
        self,
        route: Dict,
        area_id: str
    ) -> bool:
        """
        Check if a route (origin and destination) is within area

        Args:
            route: Dict with origin_lat, origin_lon, dest_lat, dest_lon
            area_id: Area to check

        Returns:
            True if both origin and destination are in area
        """
        origin_in = self.is_point_in_area(
            route['origin_lat'],
            route['origin_lon'],
            area_id
        )

        dest_in = self.is_point_in_area(
            route['dest_lat'],
            route['dest_lon'],
            area_id
        )

        return origin_in and dest_in

    def validate_routes_for_area(
        self,
        route_ids: List[str],
        area_id: str
    ) -> Dict:
        """
        Validate that all routes are within area bounds

        Args:
            route_ids: List of route IDs to validate
            area_id: Area to validate against

        Returns:
            Dict with validation results
        """
        area = self.db.get_monitored_area(area_id)

        if not area:
            raise ValueError(f"Area {area_id} not found")

        results = {
            'valid': True,
            'total_routes': len(route_ids),
            'valid_routes': [],
            'invalid_routes': []
        }

        for route_id in route_ids:
            routes = self.db.get_probe_routes()
            route = next((r for r in routes if r['route_id'] == route_id), None)

            if not route:
                results['valid'] = False
                results['invalid_routes'].append({
                    'route_id': route_id,
                    'reason': 'Route not found'
                })
                continue

            if self.is_route_in_area(route, area_id):
                results['valid_routes'].append(route_id)
                # Link route to area
                self.db.link_route_to_area(route_id, area_id)
            else:
                results['valid'] = False
                results['invalid_routes'].append({
                    'route_id': route_id,
                    'route_name': route['name'],
                    'reason': f'Route is outside area bounds'
                })

        if results['valid']:
            print(f"[AREA MANAGER] All {len(route_ids)} routes validated for area {area['name']}")
        else:
            print(f"[AREA MANAGER] ⚠️ {len(results['invalid_routes'])} routes outside area bounds")
            for invalid in results['invalid_routes']:
                print(f"  - {invalid.get('route_name', invalid['route_id'])}: {invalid['reason']}")

        return results

    def get_training_status(self, area_id: str) -> Dict:
        """Get detailed training status for area"""
        area = self.db.get_monitored_area(area_id)

        if not area:
            return None

        status = {
            'area_id': area_id,
            'area_name': area['name'],
            'status': area['status'],
            'training_start_date': area.get('training_start_date'),
            'training_end_date': area.get('training_end_date'),
            'duration_days': area.get('training_duration_days'),
            'collections_completed': area.get('collections_completed', 0),
            'collections_target': area.get('collections_target'),
            'progress_percent': 0,
            'accuracy': None
        }

        if area['collections_target'] and area['collections_target'] > 0:
            status['progress_percent'] = (
                area['collections_completed'] / area['collections_target']
            ) * 100

        if area['status'] == 'trained':
            status['accuracy'] = {
                'rmse': area.get('accuracy_rmse'),
                'mae': area.get('accuracy_mae'),
                'mape': area.get('accuracy_mape')
            }

        return status

    def delete_area(self, area_id: str):
        """Delete an area and all associated data"""
        # This is a dangerous operation - implement with caution
        # For now, just mark as inactive
        area = self.db.get_monitored_area(area_id)
        if area:
            self.db.update_area_status(area_id, 'deleted')
            print(f"[AREA MANAGER] Area {area['name']} marked as deleted")

    def build_network_for_area(self, area_id: str) -> str:
        """
        Build SUMO network for area (if not already built)

        Returns:
            Path to network file
        """
        area = self.db.get_monitored_area(area_id)

        if not area:
            raise ValueError(f"Area {area_id} not found")

        if area['sumo_network_file']:
            print(f"[AREA MANAGER] Network already exists: {area['sumo_network_file']}")
            return area['sumo_network_file']

        print(f"[AREA MANAGER] Building network for: {area['name']}")

        bbox = area['bbox']
        network_file = generate_network_from_bbox(
            north=bbox['north'],
            south=bbox['south'],
            east=bbox['east'],
            west=bbox['west'],
            location_name=area['name'].replace(" ", "_"),
            output_dir=f"data/networks/{area_id}"
        )

        # Update database
        cursor = self.db.conn.cursor()
        cursor.execute("""
            UPDATE monitored_areas
            SET sumo_network_file = ?
            WHERE area_id = ?
        """, (network_file, area_id))
        self.db.conn.commit()

        print(f"[AREA MANAGER] Network built: {network_file}")

        return network_file
