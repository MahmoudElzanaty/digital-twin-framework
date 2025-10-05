import os
import osmnx as ox
import subprocess

def generate_network(location_name, output_dir):
    """Download OSM map for given location and convert to SUMO network."""
    ox.settings.all_oneway = True  # ensures export compatibility
    osm_path = os.path.join(output_dir, f"{location_name.replace(',', '').replace(' ', '_')}.osm.xml")
    net_path = os.path.join(output_dir, f"{location_name.replace(',', '').replace(' ', '_')}.net.xml")

    # Check if network already exists
    if os.path.exists(net_path):
        print(f"[INFO] Map already exists: {net_path}")
        print("[INFO] Loading existing network...")
        return net_path

    print(f"[INFO] Downloading map for {location_name} ...")
    graph = ox.graph_from_place(location_name, network_type='drive', simplify=False)
    ox.save_graph_xml(graph, filepath=osm_path)
    print("[INFO] Map downloaded.")

    print("[INFO] Converting OSM → SUMO network ...")
    subprocess.run([
        "netconvert",
        "--osm-files", osm_path,
        "-o", net_path
    ], check=True)

    print(f"[SUCCESS] Network generated: {net_path}")
    return net_path
