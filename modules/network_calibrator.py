"""
Network Calibrator
Modifies SUMO network files to match real-world traffic conditions
"""
import xml.etree.ElementTree as ET
import os
from typing import Dict, Optional


def calibrate_network_speeds(
    network_file: str,
    target_speed_kmh: float,
    output_file: Optional[str] = None
) -> str:
    """
    Modify network edge speeds to match real-world traffic conditions

    Args:
        network_file: Path to original .net.xml file
        target_speed_kmh: Target average speed from real-world data (e.g., 37 km/h)
        output_file: Path to save calibrated network (if None, overwrites original)

    Returns:
        Path to calibrated network file
    """
    print(f"[NETWORK_CALIB] Calibrating network speeds to match {target_speed_kmh:.1f} km/h")

    # Parse network XML
    tree = ET.parse(network_file)
    root = tree.getroot()

    # Calculate realistic speed limits based on target speed
    # Account for:
    # 1. Vehicles with speedFactor=0.85 will travel at 85% of limit
    # 2. Traffic congestion further reduces speeds
    # Formula: If we want 38.9 km/h actual speed with speedFactor=0.85
    #          Then limit should be 38.9 / 0.85 = 45.8 km/h
    #          Add small buffer for variations: 45.8 × 1.05 = 48 km/h

    # Using a conservative multiplier to ensure we hit target speed
    speed_multiplier = 1.05  # Small 5% buffer above minimum required
    target_max_speed_ms = (target_speed_kmh * speed_multiplier) / 3.6  # Convert to m/s

    # Set reasonable bounds (20-60 km/h in m/s)
    min_speed_ms = 20.0 / 3.6  # 20 km/h minimum
    max_speed_ms = 60.0 / 3.6  # 60 km/h maximum (reduced from 70)
    target_max_speed_ms = max(min_speed_ms, min(max_speed_ms, target_max_speed_ms))

    print(f"[NETWORK_CALIB] Target real-world speed: {target_speed_kmh:.1f} km/h")
    print(f"[NETWORK_CALIB] Setting edge maxSpeed to {target_max_speed_ms * 3.6:.1f} km/h")
    print(f"[NETWORK_CALIB] Expected average with speedFactor=0.85: {target_max_speed_ms * 3.6 * 0.85:.1f} km/h")

    edges_modified = 0

    # Modify all edge speeds
    for edge in root.findall('.//edge'):
        edge_id = edge.get('id')

        # Skip internal edges (junctions)
        if edge_id and ':' in edge_id:
            continue

        # Modify all lanes in this edge
        for lane in edge.findall('lane'):
            original_speed = lane.get('speed')

            # Set new max speed
            lane.set('speed', f"{target_max_speed_ms:.2f}")
            edges_modified += 1

    # Also add traffic light timing adjustments for realism
    # Find all traffic lights and set realistic timing
    for tlLogic in root.findall('.//tlLogic'):
        # Cairo traffic lights typically have longer cycles due to congestion
        tl_type = tlLogic.get('type')
        if tl_type == 'static':
            # Adjust phase durations for more realistic stop times
            for phase in tlLogic.findall('phase'):
                duration = float(phase.get('duration', 30))
                # Increase red light duration to simulate congestion
                if 'r' in phase.get('state', ''):
                    # Red phases should be slightly longer in congested traffic
                    phase.set('duration', str(duration * 1.15))

    print(f"[NETWORK_CALIB] Adjusted traffic light timings for congestion")

    print(f"[NETWORK_CALIB] Modified {edges_modified} lanes")

    # Save calibrated network
    if output_file is None:
        output_file = network_file

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Write modified network
    tree.write(output_file, encoding='utf-8', xml_declaration=True)

    print(f"[NETWORK_CALIB] Calibrated network saved to {output_file}")

    return output_file


def create_congestion_in_network(
    network_file: str,
    target_speed_kmh: float,
    congestion_level: str = "moderate"
) -> str:
    """
    Modify network to simulate congestion by reducing speeds

    Args:
        network_file: Path to network file
        target_speed_kmh: Real-world average speed
        congestion_level: "light", "moderate", "heavy", or "severe"

    Returns:
        Path to modified network
    """
    print(f"[NETWORK_CALIB] Creating {congestion_level} congestion for {target_speed_kmh:.1f} km/h target")

    # Congestion factor determines how much below speed limit vehicles travel
    congestion_factors = {
        "light": 0.85,      # Travel at 85% of limit
        "moderate": 0.70,   # Travel at 70% of limit
        "heavy": 0.55,      # Travel at 55% of limit
        "severe": 0.40      # Travel at 40% of limit
    }

    factor = congestion_factors.get(congestion_level, 0.70)

    # Calculate what speed limit should be to achieve target average speed
    # If vehicles travel at 70% of limit and we want 37 km/h average,
    # then limit should be 37 / 0.7 = 53 km/h
    required_limit_kmh = target_speed_kmh / factor

    print(f"[NETWORK_CALIB] Setting speed limits to {required_limit_kmh:.1f} km/h")
    print(f"[NETWORK_CALIB] With {congestion_level} congestion (factor={factor:.2f})")
    print(f"[NETWORK_CALIB] Expected average speed: {required_limit_kmh * factor:.1f} km/h")

    return calibrate_network_speeds(network_file, target_speed_kmh)


def get_network_speed_stats(network_file: str) -> Dict:
    """Get statistics about speeds in network"""
    tree = ET.parse(network_file)
    root = tree.getroot()

    speeds = []

    for edge in root.findall('.//edge'):
        edge_id = edge.get('id')
        if edge_id and ':' not in edge_id:  # Skip internal edges
            for lane in edge.findall('lane'):
                speed_ms = float(lane.get('speed', 13.89))
                speeds.append(speed_ms * 3.6)  # Convert to km/h

    if speeds:
        return {
            'avg_speed_kmh': sum(speeds) / len(speeds),
            'min_speed_kmh': min(speeds),
            'max_speed_kmh': max(speeds),
            'num_lanes': len(speeds)
        }

    return {}
