"""
Simple Route Generator
Generates representative routes within a bounding box for Google Maps sampling
"""
import random
from typing import List, Dict, Tuple


class SimpleRouteGenerator:
    """Generate simple representative routes within a bbox"""

    def generate_routes_for_bbox(self, bbox: Dict, num_routes: int = 5) -> List[Dict]:
        """
        Generate representative routes within a bounding box
        Creates routes that sample different parts of the area

        Args:
            bbox: Dict with 'north', 'south', 'east', 'west' keys
            num_routes: Number of routes to generate (default 5)

        Returns:
            List of route dicts with origin/dest coordinates
        """
        north = bbox['north']
        south = bbox['south']
        east = bbox['east']
        west = bbox['west']

        # Calculate center and dimensions
        center_lat = (north + south) / 2
        center_lon = (east + west) / 2
        lat_range = north - south
        lon_range = east - west

        routes = []

        # Strategy: Create LONGER routes to capture highway/main road speeds
        # Short routes (1-4 km) give artificially low speeds due to stops/turns
        # Longer routes (8-15 km) better represent actual traffic flow speeds
        route_patterns = [
            # 1. Extended North-South (cross entire area + beyond)
            {
                'name': 'South → North Extended',
                'origin': (south - lat_range * 0.5, center_lon),  # Start below bbox
                'dest': (north + lat_range * 0.5, center_lon)     # End above bbox
            },
            # 2. Extended West-East (cross entire area + beyond)
            {
                'name': 'West → East Extended',
                'origin': (center_lat, west - lon_range * 0.5),   # Start left of bbox
                'dest': (center_lat, east + lon_range * 0.5)      # End right of bbox
            },
            # 3. Long diagonal SW-NE
            {
                'name': 'SW → NE Diagonal',
                'origin': (south - lat_range * 0.3, west - lon_range * 0.3),
                'dest': (north + lat_range * 0.3, east + lon_range * 0.3)
            },
            # 4. Long diagonal NW-SE
            {
                'name': 'NW → SE Diagonal',
                'origin': (north + lat_range * 0.3, west - lon_range * 0.3),
                'dest': (south - lat_range * 0.3, east + lon_range * 0.3)
            },
            # 5. North edge extended route
            {
                'name': 'North Edge Extended',
                'origin': (north, west - lon_range * 0.4),
                'dest': (north, east + lon_range * 0.4)
            },
            # 6. South edge extended route
            {
                'name': 'South Edge Extended',
                'origin': (south, west - lon_range * 0.4),
                'dest': (south, east + lon_range * 0.4)
            },
            # 7. Extended radial from center
            {
                'name': 'Center → Far North',
                'origin': (center_lat, center_lon),
                'dest': (north + lat_range * 0.8, center_lon)
            },
            # 8. Cross-bbox diagonal
            {
                'name': 'Corner to Corner',
                'origin': (south - lat_range * 0.2, west - lon_range * 0.2),
                'dest': (north + lat_range * 0.2, east + lon_range * 0.2)
            }
        ]

        # Select requested number of routes
        for i, pattern in enumerate(route_patterns[:num_routes]):
            origin_lat, origin_lon = pattern['origin']
            dest_lat, dest_lon = pattern['dest']

            # Don't clamp coordinates - we WANT routes to extend beyond bbox
            # for longer, more representative routes that capture highway speeds

            routes.append({
                'route_id': f'area_sample_{i+1}',
                'name': pattern['name'],
                'origin_lat': origin_lat,
                'origin_lon': origin_lon,
                'dest_lat': dest_lat,
                'dest_lon': dest_lon
            })

        return routes

    def get_area_info(self, bbox: Dict) -> Dict:
        """Get info about the selected area"""
        lat_range = bbox['north'] - bbox['south']
        lon_range = bbox['east'] - bbox['west']

        # Approximate area in km² (rough calculation)
        lat_km = lat_range * 111  # 1 degree latitude ≈ 111 km
        lon_km = lon_range * 111 * abs(((bbox['north'] + bbox['south'])/2))  # Adjusted for latitude
        area_km2 = lat_km * lon_km

        return {
            'area_km2': area_km2,
            'center_lat': (bbox['north'] + bbox['south']) / 2,
            'center_lon': (bbox['east'] + bbox['west']) / 2,
            'lat_range': lat_range,
            'lon_range': lon_range
        }
