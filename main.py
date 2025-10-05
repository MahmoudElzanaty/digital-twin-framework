from modules.network_builder import generate_network
from modules.demand_generator import generate_routes
from modules.simulator import create_config, run_simulation
import os

def main():
    location = input("Enter location (e.g., 'Berlin, Germany'): ")
    out_dir = os.path.join("data", "networks")
    os.makedirs(out_dir, exist_ok=True)

    net = generate_network(location, out_dir)
    route = generate_routes(net, os.path.join("data", "routes"), sim_time=1800)
    cfg = create_config(net, route, os.path.join("data", "configs", "simulation.sumocfg"))
    run_simulation(cfg, gui=True)

if __name__ == "__main__":
    main()
