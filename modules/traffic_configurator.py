"""
Traffic Configurator
Sets up simulation conditions based on real-world data
Makes simulation match real Cairo traffic from the start
"""
import xml.etree.ElementTree as ET
from typing import Dict, Optional, List
from modules.database import get_db


class TrafficConfigurator:
    """Configure simulation to match real-world traffic conditions"""

    def __init__(self):
        self.db = get_db()

    def get_real_world_metrics(self, scenario_id: str) -> Optional[Dict]:
        """Get real-world traffic metrics for this area"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT speed_kmh, travel_time_seconds, distance_meters
                FROM real_traffic_data
                WHERE area_id = ? AND speed_kmh IS NOT NULL
            """, (scenario_id,))
            results = cursor.fetchall()

            if not results:
                print("[TRAFFIC_CONFIG] No real-world data found for this area")
                return None

            speeds = [r['speed_kmh'] for r in results]
            avg_speed = sum(speeds) / len(speeds)

            # Calculate congestion level (Cairo-specific based on observed speeds)
            # Heavy: <35 km/h, Moderate: 35-55 km/h, Light: >55 km/h
            # REDUCED factors to prevent gridlock
            if avg_speed > 55:
                congestion = "light"
                congestion_factor = 0.6  # Light traffic - fewer vehicles
            elif avg_speed > 45:
                congestion = "moderate_light"
                congestion_factor = 0.8  # Moderate-light congestion
            elif avg_speed > 35:
                congestion = "moderate"
                congestion_factor = 1.0  # Moderate congestion - normal density
            else:
                congestion = "heavy"
                congestion_factor = 1.3  # Heavy congestion - slightly more vehicles

            print(f"[TRAFFIC_CONFIG] Real-world data: {avg_speed:.1f} km/h → {congestion.upper()} congestion")

            return {
                'avg_speed_kmh': avg_speed,
                'congestion_level': congestion,
                'congestion_factor': congestion_factor,
                'num_samples': len(speeds)
            }

        except Exception as e:
            print(f"[TRAFFIC_CONFIG] Error getting real metrics: {e}")
            return None

    def configure_cairo_parameters(self, avg_speed_kmh: float) -> Dict[str, float]:
        """
        Configure vehicle parameters for Cairo-style traffic
        Based on real observed speeds
        """
        # Cairo drivers are more aggressive than European default
        # Adjust parameters based on observed speed

        if avg_speed_kmh < 35:
            # Heavy congestion - tight following, slow speeds
            params = {
                'tau': 0.7,           # Close following
                'accel': 2.0,          # Slow acceleration in congestion
                'decel': 5.5,          # Hard braking
                'sigma': 0.70,         # High imperfection
                'speedFactor': 0.65,   # Way below speed limits
                'speedDev': 0.25,      # High variation
                'lcStrategic': 2.5,    # Aggressive lane changes
                'lcCooperative': 0.6   # Less cooperation
            }
        elif avg_speed_kmh < 45:
            # Moderate congestion (35-45 km/h - typical congested Cairo streets)
            params = {
                'tau': 0.75,          # Close following
                'accel': 2.2,          # Slower acceleration
                'decel': 5.3,          # Good braking
                'sigma': 0.65,         # Higher imperfection
                'speedFactor': 0.70,   # Well below speed limits (KEY FIX!)
                'speedDev': 0.22,      # Higher variation
                'lcStrategic': 2.3,    # More aggressive
                'lcCooperative': 0.65  # Less cooperation
            }
        elif avg_speed_kmh < 55:
            # Moderate-light flow (45-55 km/h - typical Cairo main roads)
            params = {
                'tau': 0.85,          # Fairly close following
                'accel': 2.6,          # Standard acceleration
                'decel': 5.0,          # Standard braking
                'sigma': 0.55,         # Some imperfection
                'speedFactor': 0.85,   # Below speed limits
                'speedDev': 0.18,      # Moderate variation
                'lcStrategic': 2.0,    # Moderately aggressive
                'lcCooperative': 0.7   # Some cooperation
            }
        else:
            # Light traffic (>55 km/h - smooth flow)
            params = {
                'tau': 1.0,           # Normal following distance
                'accel': 3.0,          # Good acceleration
                'decel': 4.5,          # Standard braking
                'sigma': 0.45,         # Low imperfection
                'speedFactor': 1.05,   # At or slightly above limits
                'speedDev': 0.15,      # Low variation
                'lcStrategic': 1.5,    # Normal lane changing
                'lcCooperative': 0.8   # Good cooperation
            }

        print(f"[TRAFFIC_CONFIG] Cairo parameters for {avg_speed_kmh:.1f} km/h:")
        print(f"[TRAFFIC_CONFIG]   Speed factor: {params['speedFactor']:.2f}")
        print(f"[TRAFFIC_CONFIG]   Following distance (tau): {params['tau']:.2f}s")
        print(f"[TRAFFIC_CONFIG]   Driver imperfection: {params['sigma']:.2f}")

        return params

    def modify_route_file_with_params(self, route_file: str, params: Dict[str, float],
                                       congestion_factor: float) -> bool:
        """
        Modify route file to:
        1. Set Cairo-style vehicle parameters
        2. Increase vehicle count to match congestion
        """
        try:
            tree = ET.parse(route_file)
            root = tree.getroot()

            # Remove existing vType
            for vtype in root.findall('vType'):
                root.remove(vtype)

            # Create Cairo-style vehicle type
            cairo_vtype = ET.Element('vType', {
                'id': 'cairo_car',
                'vClass': 'passenger',
                'tau': str(params['tau']),
                'accel': str(params['accel']),
                'decel': str(params['decel']),
                'sigma': str(params['sigma']),
                'speedFactor': str(params['speedFactor']),
                'speedDev': str(params['speedDev']),
                'lcStrategic': str(params['lcStrategic']),
                'lcCooperative': str(params['lcCooperative']),
                'color': '1,0.8,0'  # Cairo taxi yellow!
            })
            root.insert(0, cairo_vtype)

            # Update all vehicles/trips to use Cairo type
            vehicle_count = 0

            # Handle <vehicle> tags
            for vehicle in root.findall('.//vehicle'):
                vehicle.set('type', 'cairo_car')
                vehicle_count += 1

            # Handle <trip> tags (more common from randomTrips.py)
            for trip in root.findall('.//trip'):
                trip.set('type', 'cairo_car')
                vehicle_count += 1

            # Modify flows to increase vehicle count based on congestion
            for flow in root.findall('.//flow'):
                flow.set('type', 'cairo_car')

                # Increase flow rate for congestion
                if 'vehsPerHour' in flow.attrib:
                    current = float(flow.get('vehsPerHour'))
                    new_rate = int(current * congestion_factor)
                    flow.set('vehsPerHour', str(new_rate))
                    print(f"[TRAFFIC_CONFIG] Adjusted flow: {current:.0f} → {new_rate} veh/hour")

                elif 'period' in flow.attrib:
                    current = float(flow.get('period'))
                    new_period = current / congestion_factor  # Shorter period = more vehicles
                    flow.set('period', str(new_period))
                    print(f"[TRAFFIC_CONFIG] Adjusted period: {current:.1f}s → {new_period:.1f}s")

            # Save modified file
            tree.write(route_file)

            print(f"[TRAFFIC_CONFIG] ✅ Modified route file:")
            print(f"[TRAFFIC_CONFIG]   - {vehicle_count} vehicles set to Cairo style")
            print(f"[TRAFFIC_CONFIG]   - Traffic density: {congestion_factor:.1f}x")

            return True

        except Exception as e:
            print(f"[TRAFFIC_CONFIG] ⚠️ Could not modify route file: {e}")
            return False

    def configure_simulation(self, scenario_id: str, route_file: str) -> Dict:
        """
        Main function: Configure simulation based on real-world data

        Returns: Dict with 'success' (bool) and 'params' (Dict) if successful
        """
        print("\n" + "="*70)
        print("🔧 CONFIGURING SIMULATION TO MATCH REAL CAIRO TRAFFIC")
        print("="*70)

        # Get real-world metrics
        metrics = self.get_real_world_metrics(scenario_id)

        if not metrics:
            print("[TRAFFIC_CONFIG] ⚠️ No real-world data - using Cairo defaults")
            # Use typical Cairo moderate flow (main roads)
            metrics = {
                'avg_speed_kmh': 45.0,  # Typical Cairo main road speed
                'congestion_level': 'moderate',
                'congestion_factor': 0.8,  # Reduced to prevent gridlock
                'num_samples': 0
            }

        # Get Cairo-specific parameters
        params = self.configure_cairo_parameters(metrics['avg_speed_kmh'])

        # Apply to route file
        success = self.modify_route_file_with_params(
            route_file,
            params,
            metrics['congestion_factor']
        )

        if success:
            print("="*70)
            print(f"✅ SIMULATION CONFIGURED FOR CAIRO TRAFFIC")
            print(f"   Target speed: {metrics['avg_speed_kmh']:.1f} km/h")
            print(f"   Congestion: {metrics['congestion_level'].upper()}")
            print(f"   Vehicle density: {metrics['congestion_factor']:.1f}x normal")
            print("="*70 + "\n")

            # Return success and the Cairo parameters for dynamic calibrator
            return {
                'success': True,
                'params': {
                    'tau': params['tau'],
                    'accel': params['accel'],
                    'decel': params['decel'],
                    'sigma': params['sigma'],
                    'speedFactor': params['speedFactor']
                },
                'metrics': metrics
            }

        return {'success': False}
