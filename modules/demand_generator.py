import os
import subprocess

def generate_routes(net_file, output_dir, sim_time=3600, trip_rate=1.0):
    """Generate random trips based on the network."""
    route_file = os.path.join(output_dir, "routes.rou.xml")
    print("[INFO] Generating random trips ...")
    subprocess.run([
        "python", os.path.join(os.environ["SUMO_HOME"], "tools", "randomTrips.py"),
        "-n", net_file,
        "-o", route_file,
        "-e", str(sim_time),
        "--period", str(trip_rate),
        "--binomial", "2"
    ], check=True)
    print(f"[SUCCESS] Routes generated: {route_file}")
    return route_file
