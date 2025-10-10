import csv
import os
import traci

class TrafficLogger:
    """Logs edge-level traffic statistics from SUMO via TraCI."""

    def __init__(self, log_dir="data/logs", interval=10):
        os.makedirs(log_dir, exist_ok=True)
        self.file_path = os.path.join(log_dir, "edge_state.csv")
        self.interval = interval   # seconds between logs
        self._last_step = 0

        self.file = open(self.file_path, "w", newline="")
        self.writer = csv.writer(self.file)
        self.writer.writerow(
            ["time", "edge_id", "meanSpeed", "occupancy", "numVeh", "travelTime"]
        )
        print(f"[LOGGER] Logging to {self.file_path}")

    def log_step(self, step):
        """Collect stats every N steps."""
        if step - self._last_step < self.interval:
            return
        self._last_step = step

        for edge_id in traci.edge.getIDList():
            # skip internal junction edges
            if edge_id.startswith(":"):
                continue

            mean_speed = traci.edge.getLastStepMeanSpeed(edge_id)
            occupancy = traci.edge.getLastStepOccupancy(edge_id)
            num_veh = traci.edge.getLastStepVehicleNumber(edge_id)
            travel_time = traci.edge.getTraveltime(edge_id)

            self.writer.writerow(
                [step, edge_id, mean_speed, occupancy, num_veh, travel_time]
            )

    def close(self):
        self.file.close()
        print("[LOGGER] Logging stopped and file saved.")
