import os
import osmnx as ox
import subprocess
import hashlib
import json
import glob


def get_cached_networks(output_dir):
    """
    Get list of all cached networks

    Returns:
        List of dicts with cache information
    """
    cached_networks = []
    meta_files = glob.glob(os.path.join(output_dir, "cached_*.json"))

    for meta_file in meta_files:
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                bbox_hash = os.path.basename(meta_file).replace('cached_', '').replace('.json', '')
                net_file = os.path.join(output_dir, f"cached_{bbox_hash}.net.xml")

                if os.path.exists(net_file):
                    file_size_mb = os.path.getsize(net_file) / (1024 * 1024)
                    cached_networks.append({
                        'hash': bbox_hash,
                        'location': meta.get('location_name', 'Unknown'),
                        'bbox': meta.get('bbox'),
                        'nodes': meta.get('nodes'),
                        'edges': meta.get('edges'),
                        'net_file': net_file,
                        'size_mb': file_size_mb
                    })
        except:
            continue

    return cached_networks


def clear_all_cache(output_dir):
    """Delete all cached network files"""
    cache_files = glob.glob(os.path.join(output_dir, "cached_*"))
    count = 0
    for cache_file in cache_files:
        try:
            os.remove(cache_file)
            count += 1
        except:
            pass
    return count


def get_bbox_hash(bbox):
    """Generate a unique hash for a bounding box (for caching)"""
    # Round to 4 decimal places (~11m precision) to avoid cache misses from tiny differences
    bbox_str = f"{bbox['north']:.4f}_{bbox['south']:.4f}_{bbox['east']:.4f}_{bbox['west']:.4f}"
    return hashlib.md5(bbox_str.encode()).hexdigest()[:8]


def check_cached_network(bbox, output_dir):
    """
    Check if a network already exists for this bounding box

    Returns:
        Path to cached network file if it exists, None otherwise
    """
    bbox_hash = get_bbox_hash(bbox)
    net_path = os.path.join(output_dir, f"cached_{bbox_hash}.net.xml")
    meta_path = os.path.join(output_dir, f"cached_{bbox_hash}.json")

    if os.path.exists(net_path):
        print(f"[INFO] ✅ Found cached network: {os.path.basename(net_path)}")

        # Load and display cache info if available
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    print(f"[INFO] Cached network: {meta.get('nodes', '?')} nodes, {meta.get('edges', '?')} edges")
            except:
                pass

        print(f"[INFO] Skipping download - using existing network file")
        return net_path

    return None


def generate_network(location_name, output_dir):
    """
    Download OSM map for given location and convert it to SUMO network.
    Automatically retries with a coordinate-based fallback if place lookup fails.
    """
    ox.settings.all_oneway = True
    osm_safe = location_name.replace(",", "").replace(" ", "_")
    osm_path = os.path.join(output_dir, f"{osm_safe}.osm.xml")
    net_path = os.path.join(output_dir, f"{osm_safe}.net.xml")

    print(f"[INFO] Downloading map for {location_name} ...")

    try:
        # First try normal name-based geocode
        graph = ox.graph_from_place(location_name, network_type="drive", simplify=False)
    except Exception as e:
        print(f"[WARN] Could not find drivable roads for '{location_name}'.")
        print("[INFO] Falling back to coordinate-based bounding box...")
        # fallback to 1km radius around a coordinate (Rome in this case)
        # you can later make this dynamic via Google Geocoding API
        fallback_coords = (41.9029, 12.4534)  # Vatican / Rome area
        graph = ox.graph_from_point(fallback_coords, dist=1500, network_type="drive", simplify=False)

    ox.save_graph_xml(graph, filepath=osm_path)
    print("[INFO] Map downloaded successfully.")

    print("[INFO] Converting OSM → SUMO network ...")
    subprocess.run([
        "netconvert",
        "--osm-files", osm_path,
        "-o", net_path
    ], check=True)

    print(f"[SUCCESS] Network generated: {net_path}")
    return net_path


def generate_network_from_bbox(bbox, location_name, output_dir, use_cache=True):
    """
    Download OSM map for a specific bounding box and convert it to SUMO network.
    This version captures ALL road types including residential streets.

    Args:
        bbox: Dictionary with keys 'north', 'south', 'east', 'west'
        location_name: Name for the output files
        output_dir: Directory to save the generated files
        use_cache: If True, check for and use cached network files (default: True)

    Returns:
        Path to the generated .net.xml file
    """
    # Check for cached network first
    if use_cache:
        cached_net = check_cached_network(bbox, output_dir)
        if cached_net:
            return cached_net

    print(f"[INFO] No cached network found - downloading fresh data...")

    # Configure OSMnx to get ALL roads, not just major ones
    ox.settings.all_oneway = True
    ox.settings.useful_tags_way += ['surface', 'lanes', 'name', 'highway', 'maxspeed', 'service', 'access', 'area', 'landuse', 'width', 'est_width']

    # Use hash-based filename for caching
    bbox_hash = get_bbox_hash(bbox)
    osm_path = os.path.join(output_dir, f"cached_{bbox_hash}.osm.xml")
    net_path = os.path.join(output_dir, f"cached_{bbox_hash}.net.xml")

    print(f"[INFO] Downloading map for bounding box:")
    print(f"       North: {bbox['north']:.6f}, South: {bbox['south']:.6f}")
    print(f"       East: {bbox['east']:.6f}, West: {bbox['west']:.6f}")

    try:
        # Download graph using bounding box
        # Note: osmnx 2.x uses bbox as tuple (west, south, east, north)
        bbox_tuple = (bbox['west'], bbox['south'], bbox['east'], bbox['north'])

        # Download drivable roads EXCLUDING service roads, parking, driveways, private roads
        # Includes: motorway, trunk, primary, secondary, tertiary, residential, unclassified, etc.
        # Excludes: service roads, parking, driveways, private roads, emergency access
        custom_filter = (
            '["highway"]["area"!~"yes"]'
            '["highway"!~"abandoned|bridleway|bus_guideway|construction|corridor|cycleway|'
            'elevator|escalator|footway|path|pedestrian|planned|platform|proposed|raceway|steps|track|service"]'
            '["motor_vehicle"!~"no"]["motorcar"!~"no"]'
            '["access"!~"private|no"]'
        )

        print(f"[INFO] Downloading roads (excluding service roads, parking, driveways, private roads)...")

        graph = ox.graph_from_bbox(
            bbox_tuple,
            custom_filter=custom_filter,
            simplify=False,
            retain_all=True  # Keep all disconnected road segments
        )

        if len(graph.nodes) == 0:
            raise ValueError("No drivable roads found in the selected area. Please select a different area with roads.")

        print(f"[INFO] Downloaded {len(graph.nodes)} nodes and {len(graph.edges)} edges")

    except Exception as e:
        raise Exception(f"Failed to download map data: {str(e)}")

    ox.save_graph_xml(graph, filepath=osm_path)
    print("[INFO] Map downloaded successfully.")

    print("[INFO] Converting OSM → SUMO network ...")
    print("[INFO] Using comprehensive conversion settings to preserve all roads...")

    try:
        subprocess.run([
            "netconvert",
            "--osm-files", osm_path,
            "-o", net_path,
            # Keep road geometry and details
            "--geometry.remove", "false",
            "--keep-edges.by-vclass", "passenger",
            # Remove problematic edges - CRITICAL FIX!
            "--remove-edges.isolated", "true",  # Remove disconnected edges that trap vehicles
            "--keep-edges.components", "1",  # Only keep largest connected component
            # Junction settings - simplified to avoid deadlocks
            "--junctions.join", "true",
            "--junctions.corner-detail", "5",
            "--junctions.join-dist", "15",  # Join nearby junctions to reduce complexity
            # Roundabouts - more conservative settings
            "--roundabouts.guess", "true",
            "--roundabouts.visibility-distance", "100",  # Better roundabout handling
            # Ramps
            "--ramps.guess", "true",
            "--ramps.set", "200",  # Mark ramps explicitly
            # Traffic lights - simplified
            "--tls.guess-signals", "true",
            "--tls.discard-simple", "true",  # Remove unnecessary traffic lights
            "--tls.join", "true",
            "--tls.guess.threshold", "69",  # Default threshold for TLS
            # Edge types - preserve all road types
            "--remove-edges.by-type", "",
            # Output details
            "--output.street-names", "true",
            "--output.original-names", "true",
            # Verbose output
            "--verbose", "true"
        ], check=True, capture_output=True, text=True)

        print("[INFO] Network conversion completed successfully")

    except subprocess.CalledProcessError as e:
        print(f"[WARN] Conversion stderr: {e.stderr[:500]}")  # Show first 500 chars of error
        raise Exception(f"Network conversion failed: {e.stderr}")

    # Save cache metadata for reference
    cache_meta = {
        'bbox': bbox,
        'location_name': location_name,
        'nodes': len(graph.nodes),
        'edges': len(graph.edges)
    }
    meta_path = os.path.join(output_dir, f"cached_{bbox_hash}.json")
    with open(meta_path, 'w') as f:
        json.dump(cache_meta, f, indent=2)

    print(f"[SUCCESS] Network generated: {net_path}")
    print(f"[INFO] Network includes: highways, main roads, and residential streets")
    print(f"[INFO] Excluded: service roads, parking, driveways, private roads")
    print(f"[INFO] 💾 Network cached for future use")
    return net_path