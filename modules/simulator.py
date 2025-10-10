import os
import traci
from modules.logger import TrafficLogger

def create_config(net_file, route_file, cfg_path):
    net_rel = os.path.relpath(net_file, start=os.path.dirname(cfg_path))
    route_rel = os.path.relpath(route_file, start=os.path.dirname(cfg_path))

    cfg_content = f"""<configuration>
    <input>
        <net-file value="{net_rel}"/>
        <route-files value="{route_rel}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
    </time>
</configuration>"""
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    return cfg_path


def run_simulation(cfg_file, gui=True):
    sumo_binary = "sumo-gui" if gui else "sumo"
    traci.start([sumo_binary, "-c", cfg_file])
    step = 0

    logger = TrafficLogger(log_dir="data/logs", interval=10)

    print("[SIM] Simulation started ...")
    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1
            logger.log_step(step)
            if step % 100 == 0:
                print(f"[SIM] Step {step}")
    finally:
        logger.close()
        traci.close()
        print("[SIM] Simulation ended.")
