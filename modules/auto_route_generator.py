"""
Automatic Route Generator for Selected Map Areas
Intelligently creates probe routes within any selected bounding box
"""
import json
from typing import Dict, List, Tuple
from modules.database import get_db
from datetime import datetime

class AutoRouteGenerator:
    """
    Automatically generates probe routes for a selected area
    Creates strategic routes that cover the area comprehensively
    """
    
    def __init__(self):
        self.db = get_db()
    
    def calculate_area_size(self, bbox: Dict) -> Dict:
        """Calculate area dimensions"""
        lat_diff = abs(bbox['north'] - bbox['south'])
        lon_diff = abs(bbox['east'] - bbox['west'])
        
        # Approximate area in km²
        area_km2 = lat_diff * lon_diff * 111 * 111
        
        return {
            'lat_diff': lat_diff,
            'lon_diff': lon_diff,
            'area_km2': area_km2,
            'center_lat': (bbox['north'] + bbox['south']) / 2,
            'center_lon': (bbox['east'] + bbox['west']) / 2
        }
    
    def generate_grid_routes(
        self, 
        bbox: Dict, 
        num_routes: int = 8
    ) -> List[Dict]:
        """
        Generate a grid of routes covering the area
        Creates horizontal, vertical, and diagonal routes
        """
        routes = []
        area_info = self.calculate_area_size(bbox)
        
        lat_diff = area_info['lat_diff']
        lon_diff = area_info['lon_diff']
        center_lat = area_info['center_lat']
        center_lon = area_info['center_lon']
        
        # Add padding (don't start exactly at edges)
        pad_lat = lat_diff * 0.15
        pad_lon = lon_diff * 0.15
        
        # 1. Main horizontal route (West → East through center)
        routes.append({
            'name': 'Main Horizontal (W→E)',
            'origin_lat': center_lat,
            'origin_lon': bbox['west'] + pad_lon,
            'dest_lat': center_lat,
            'dest_lon': bbox['east'] - pad_lon,
            'type': 'horizontal',
            'description': 'Main east-west corridor through center'
        })
        
        # 2. Main vertical route (South → North through center)
        routes.append({
            'name': 'Main Vertical (S→N)',
            'origin_lat': bbox['south'] + pad_lat,
            'origin_lon': center_lon,
            'dest_lat': bbox['north'] - pad_lat,
            'dest_lon': center_lon,
            'type': 'vertical',
            'description': 'Main north-south corridor through center'
        })
        
        # 3. Main diagonal (SW → NE)
        routes.append({
            'name': 'Main Diagonal (SW→NE)',
            'origin_lat': bbox['south'] + pad_lat,
            'origin_lon': bbox['west'] + pad_lon,
            'dest_lat': bbox['north'] - pad_lat,
            'dest_lon': bbox['east'] - pad_lon,
            'type': 'diagonal',
            'description': 'Southwest to northeast diagonal'
        })
        
        # 4. Reverse diagonal (NW → SE)
        routes.append({
            'name': 'Reverse Diagonal (NW→SE)',
            'origin_lat': bbox['north'] - pad_lat,
            'origin_lon': bbox['west'] + pad_lon,
            'dest_lat': bbox['south'] + pad_lat,
            'dest_lon': bbox['east'] - pad_lon,
            'type': 'diagonal',
            'description': 'Northwest to southeast diagonal'
        })
        
        # 5. Northern horizontal route
        routes.append({
            'name': 'Northern Route (W→E)',
            'origin_lat': bbox['north'] - pad_lat * 1.5,
            'origin_lon': bbox['west'] + pad_lon,
            'dest_lat': bbox['north'] - pad_lat * 1.5,
            'dest_lon': bbox['east'] - pad_lon,
            'type': 'horizontal',
            'description': 'Northern east-west corridor'
        })
        
        # 6. Southern horizontal route
        routes.append({
            'name': 'Southern Route (W→E)',
            'origin_lat': bbox['south'] + pad_lat * 1.5,
            'origin_lon': bbox['west'] + pad_lon,
            'dest_lat': bbox['south'] + pad_lat * 1.5,
            'dest_lon': bbox['east'] - pad_lon,
            'type': 'horizontal',
            'description': 'Southern east-west corridor'
        })
        
        # 7. Western vertical route
        routes.append({
            'name': 'Western Route (S→N)',
            'origin_lat': bbox['south'] + pad_lat,
            'origin_lon': bbox['west'] + pad_lon * 1.5,
            'dest_lat': bbox['north'] - pad_lat,
            'dest_lon': bbox['west'] + pad_lon * 1.5,
            'type': 'vertical',
            'description': 'Western north-south corridor'
        })
        
        # 8. Eastern vertical route
        routes.append({
            'name': 'Eastern Route (S→N)',
            'origin_lat': bbox['south'] + pad_lat,
            'origin_lon': bbox['east'] - pad_lon * 1.5,
            'dest_lat': bbox['north'] - pad_lat,
            'dest_lon': bbox['east'] - pad_lon * 1.5,
            'type': 'vertical',
            'description': 'Eastern north-south corridor'
        })
        
        return routes[:num_routes]
    
    def generate_radial_routes(
        self, 
        bbox: Dict, 
        num_routes: int = 8
    ) -> List[Dict]:
        """
        Generate radial routes from center to edges
        Good for city-center simulations
        """
        import math
        
        routes = []
        area_info = self.calculate_area_size(bbox)
        
        center_lat = area_info['center_lat']
        center_lon = area_info['center_lon']
        
        # Calculate radius (use smaller dimension)
        radius_lat = area_info['lat_diff'] * 0.4
        radius_lon = area_info['lon_diff'] * 0.4
        
        # Create routes radiating outward
        for i in range(num_routes):
            angle = (2 * math.pi * i) / num_routes
            
            # Destination point on circle
            dest_lat = center_lat + radius_lat * math.sin(angle)
            dest_lon = center_lon + radius_lon * math.cos(angle)
            
            # Direction name
            directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
            direction = directions[i % len(directions)]
            
            routes.append({
                'name': f'Radial to {direction}',
                'origin_lat': center_lat,
                'origin_lon': center_lon,
                'dest_lat': dest_lat,
                'dest_lon': dest_lon,
                'type': 'radial',
                'description': f'Route from center toward {direction}'
            })
        
        return routes
    
    def generate_loop_routes(
        self, 
        bbox: Dict, 
        num_loops: int = 3
    ) -> List[Dict]:
        """
        Generate circular/loop routes at different scales
        Good for traffic circulation patterns
        """
        routes = []
        area_info = self.calculate_area_size(bbox)
        
        center_lat = area_info['center_lat']
        center_lon = area_info['center_lon']
        
        # Create concentric loops
        for i in range(num_loops):
            scale = 0.2 + (i * 0.25)  # 20%, 45%, 70% of area
            
            # Create 4 points of a loop (approximate circle with square)
            offset_lat = area_info['lat_diff'] * scale
            offset_lon = area_info['lon_diff'] * scale
            
            # Loop: go around the perimeter
            routes.append({
                'name': f'Loop {i+1} ({"Small" if i==0 else "Medium" if i==1 else "Large"})',
                'origin_lat': center_lat - offset_lat,
                'origin_lon': center_lon - offset_lon,
                'dest_lat': center_lat + offset_lat,
                'dest_lon': center_lon + offset_lon,
                'type': 'loop',
                'description': f'Circular route at {scale*100:.0f}% of area'
            })
        
        return routes
    
    def auto_generate_for_area(
        self,
        bbox: Dict,
        location_name: str,
        strategy: str = 'grid',  # 'grid', 'radial', 'loop', or 'mixed'
        num_routes: int = 8
    ) -> List[Dict]:
        """
        Main function: Auto-generate routes for selected area
        
        Args:
            bbox: Bounding box dict with north, south, east, west
            location_name: Name for the location
            strategy: Route generation strategy
            num_routes: Number of routes to generate
        
        Returns:
            List of created route dictionaries
        """
        print("\n" + "="*70)
        print("AUTO-GENERATING PROBE ROUTES")
        print("="*70)
        
        area_info = self.calculate_area_size(bbox)
        
        print(f"Location: {location_name}")
        print(f"Area: {area_info['area_km2']:.2f} km²")
        print(f"Center: ({area_info['center_lat']:.6f}, {area_info['center_lon']:.6f})")
        print(f"Strategy: {strategy}")
        print(f"Routes to create: {num_routes}")
        print("="*70 + "\n")
        
        # Generate routes based on strategy
        if strategy == 'grid':
            route_templates = self.generate_grid_routes(bbox, num_routes)
        elif strategy == 'radial':
            route_templates = self.generate_radial_routes(bbox, num_routes)
        elif strategy == 'loop':
            route_templates = self.generate_loop_routes(bbox, min(num_routes, 3))
        elif strategy == 'mixed':
            # Combine strategies
            grid_routes = self.generate_grid_routes(bbox, num_routes // 2)
            radial_routes = self.generate_radial_routes(bbox, num_routes // 2)
            route_templates = grid_routes + radial_routes
        else:
            route_templates = self.generate_grid_routes(bbox, num_routes)
        
        # First, deactivate old routes for this location
        self._deactivate_old_routes(location_name)
        
        # Add routes to database
        created_routes = []
        
        for i, template in enumerate(route_templates):
            route_id = f"{location_name}_{template['type']}_{i+1}".replace(" ", "_").lower()
            
            full_name = f"{location_name}: {template['name']}"
            
            # Add to database
            self.db.add_probe_route(
                route_id=route_id,
                name=full_name,
                origin_lat=template['origin_lat'],
                origin_lon=template['origin_lon'],
                dest_lat=template['dest_lat'],
                dest_lon=template['dest_lon'],
                description=template['description']
            )
            
            route_dict = {
                'route_id': route_id,
                'name': full_name,
                'origin_lat': template['origin_lat'],
                'origin_lon': template['origin_lon'],
                'dest_lat': template['dest_lat'],
                'dest_lon': template['dest_lon'],
                'type': template['type'],
                'description': template['description']
            }
            
            created_routes.append(route_dict)
            
            print(f"✅ Created: {full_name}")
            print(f"   Origin: ({template['origin_lat']:.6f}, {template['origin_lon']:.6f})")
            print(f"   Dest:   ({template['dest_lat']:.6f}, {template['dest_lon']:.6f})")
            print(f"   Type:   {template['type']}")
            print()
        
        # Save bbox info for future reference
        self._save_bbox_info(bbox, location_name, created_routes)
        
        print("="*70)
        print(f"✅ AUTO-GENERATED {len(created_routes)} ROUTES")
        print("="*70)
        print(f"💡 These routes cover your selected simulation area")
        print(f"💡 They will be tracked during simulation")
        print(f"💡 Strategy used: {strategy}")
        print("="*70 + "\n")
        
        return created_routes
    
    def _deactivate_old_routes(self, location_name: str):
        """Deactivate old routes for this location"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            UPDATE probe_routes 
            SET active = 0 
            WHERE route_id LIKE ?
        """, (f"{location_name}%",))
        self.db.conn.commit()
    
    def _save_bbox_info(self, bbox: Dict, location_name: str, routes: List[Dict]):
        """Save bbox and route info to file"""
        import os
        
        os.makedirs("data", exist_ok=True)
        
        info = {
            'bbox': bbox,
            'location_name': location_name,
            'timestamp': datetime.now().isoformat(),
            'num_routes': len(routes),
            'routes': routes,
            'area_km2': self.calculate_area_size(bbox)['area_km2']
        }
        
        # Save current bbox
        with open("data/last_bbox.json", 'w') as f:
            json.dump(info, f, indent=2)
        
        # Also save with timestamp
        filename = f"data/bbox_{location_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(info, f, indent=2)
        
        print(f"💾 Saved bbox info to: {filename}")
    
    def get_recommended_strategy(self, bbox: Dict) -> str:
        """
        Recommend route strategy based on area size
        """
        area_info = self.calculate_area_size(bbox)
        area_km2 = area_info['area_km2']
        
        if area_km2 < 1:  # Very small area (<1 km²)
            return 'radial'
        elif area_km2 < 5:  # Small area (1-5 km²)
            return 'mixed'
        elif area_km2 < 20:  # Medium area (5-20 km²)
            return 'grid'
        else:  # Large area (>20 km²)
            return 'grid'
    
    def get_recommended_num_routes(self, bbox: Dict) -> int:
        """
        Recommend number of routes based on area size
        """
        area_info = self.calculate_area_size(bbox)
        area_km2 = area_info['area_km2']
        
        if area_km2 < 1:
            return 4
        elif area_km2 < 5:
            return 6
        elif area_km2 < 20:
            return 8
        else:
            return 10


# Convenience function for direct use
def auto_create_routes(bbox: Dict, location_name: str = "custom_area") -> List[Dict]:
    """
    Convenience function to auto-create routes
    
    Usage:
        bbox = {'north': 30.1, 'south': 30.0, 'east': 31.3, 'west': 31.2}
        routes = auto_create_routes(bbox, "my_area")
    """
    generator = AutoRouteGenerator()
    
    # Get smart recommendations
    strategy = generator.get_recommended_strategy(bbox)
    num_routes = generator.get_recommended_num_routes(bbox)
    
    print(f"📊 Recommendations based on area analysis:")
    print(f"   Strategy: {strategy}")
    print(f"   Number of routes: {num_routes}\n")
    
    return generator.auto_generate_for_area(bbox, location_name, strategy, num_routes)


if __name__ == "__main__":
    # Test with sample bbox
    test_bbox = {
        'north': 30.1,
        'south': 30.0,
        'east': 31.3,
        'west': 31.2
    }
    
    routes = auto_create_routes(test_bbox, "test_area")
    
    print(f"\nCreated {len(routes)} routes for testing")