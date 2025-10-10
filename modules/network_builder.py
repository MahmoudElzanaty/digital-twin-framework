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