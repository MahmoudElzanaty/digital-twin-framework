import os
import osmnx as ox
import subprocess

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


def generate_network_from_bbox(bbox, location_name, output_dir):
    """
    Download OSM map for a specific bounding box and convert it to SUMO network.
    This version captures ALL road types including residential streets.

    Args:
        bbox: Dictionary with keys 'north', 'south', 'east', 'west'
        location_name: Name for the output files
        output_dir: Directory to save the generated files

    Returns:
        Path to the generated .net.xml file
    """
    # Configure OSMnx to get ALL roads, not just major ones
    ox.settings.all_oneway = True
    ox.settings.useful_tags_way += ['surface', 'lanes', 'name', 'highway', 'maxspeed', 'service', 'access', 'area', 'landuse', 'width', 'est_width']

    osm_safe = location_name.replace(",", "").replace(" ", "_")
    osm_path = os.path.join(output_dir, f"{osm_safe}.osm.xml")
    net_path = os.path.join(output_dir, f"{osm_safe}.net.xml")

    print(f"[INFO] Downloading map for bounding box:")
    print(f"       North: {bbox['north']:.6f}, South: {bbox['south']:.6f}")
    print(f"       East: {bbox['east']:.6f}, West: {bbox['west']:.6f}")

    try:
        # Download graph using bounding box
        # Note: osmnx 2.x uses bbox as tuple (west, south, east, north)
        bbox_tuple = (bbox['west'], bbox['south'], bbox['east'], bbox['north'])

        # Use custom_filter to get ALL drivable roads including residential, service roads, etc.
        # This includes: motorway, trunk, primary, secondary, tertiary, residential, service, etc.
        custom_filter = (
            '["highway"]["area"!~"yes"]["highway"!~"abandoned|bridleway|bus_guideway|'
            'construction|corridor|cycleway|elevator|escalator|footway|path|pedestrian|'
            'planned|platform|proposed|raceway|steps|track"]'
            '["motor_vehicle"!~"no"]["motorcar"!~"no"]["service"!~"parking|parking_aisle|driveway|private|emergency_access"]'
        )

        print(f"[INFO] Downloading ALL road types (including residential streets)...")

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
            "--keep-edges.by-vclass", "passenger,pedestrian,bicycle",
            # Don't remove edges
            "--remove-edges.isolated", "false",
            "--keep-edges.components", "1",
            # Junction settings
            "--junctions.join", "true",
            "--junctions.corner-detail", "5",
            # Roundabouts
            "--roundabouts.guess", "true",
            "--roundabouts.guess.max-length", "3500",
            # Ramps
            "--ramps.guess", "true",
            # Traffic lights
            "--tls.guess-signals", "true",
            "--tls.discard-simple", "false",
            "--tls.join", "true",
            # Edge types - preserve all road types
            "--remove-edges.by-type", "",
            # Output details
            "--output.street-names", "true",
            "--output.original-names", "true",
            # Don't simplify too much
            "--junctions.join-dist", "10",
            # Verbose output
            "--verbose", "true"
        ], check=True, capture_output=True, text=True)

        print("[INFO] Network conversion completed successfully")

    except subprocess.CalledProcessError as e:
        print(f"[WARN] Conversion stderr: {e.stderr[:500]}")  # Show first 500 chars of error
        raise Exception(f"Network conversion failed: {e.stderr}")

    print(f"[SUCCESS] Network generated: {net_path}")
    print(f"[INFO] The network includes all road types (highways, residential, service roads)")
    return net_path