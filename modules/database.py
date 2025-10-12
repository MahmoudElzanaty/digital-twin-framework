"""
Database Schema and Manager for Digital Twin
Stores real traffic data, simulation results, and comparison metrics
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

class DigitalTwinDatabase:
    """Manages all database operations for the digital twin"""
    
    def __init__(self, db_path: str = "data/digital_twin.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return dict-like rows
        print(f"[DB] Connected to {self.db_path}")
    
    def create_tables(self):
        """Create all necessary tables"""
        cursor = self.conn.cursor()
        
        # Table 1: Probe Routes (routes we monitor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS probe_routes (
                route_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                origin_lat REAL NOT NULL,
                origin_lon REAL NOT NULL,
                dest_lat REAL NOT NULL,
                dest_lon REAL NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)
        
        # Table 2: Real Traffic Data (from APIs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS real_traffic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                travel_time_seconds INTEGER NOT NULL,
                distance_meters INTEGER NOT NULL,
                traffic_delay_seconds INTEGER,
                speed_kmh REAL,
                data_source TEXT NOT NULL,
                raw_data TEXT,
                FOREIGN KEY (route_id) REFERENCES probe_routes (route_id)
            )
        """)
        
        # Table 3: Simulation Results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS simulation_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT NOT NULL,
                route_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                travel_time_seconds REAL NOT NULL,
                distance_meters REAL NOT NULL,
                avg_speed_kmh REAL,
                num_vehicles INTEGER,
                simulation_params TEXT,
                FOREIGN KEY (route_id) REFERENCES probe_routes (route_id)
            )
        """)
        
        # Table 4: Calibration Parameters
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calibration_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT NOT NULL,
                param_name TEXT NOT NULL,
                param_value REAL NOT NULL,
                timestamp TEXT NOT NULL,
                rmse REAL,
                mae REAL,
                notes TEXT
            )
        """)
        
        # Table 5: Validation Metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS validation_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                mae REAL NOT NULL,
                rmse REAL NOT NULL,
                mape REAL NOT NULL,
                r_squared REAL,
                num_samples INTEGER NOT NULL,
                time_period_start TEXT,
                time_period_end TEXT,
                notes TEXT
            )
        """)
        
        # Table 6: Predictions (for tracking accuracy)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT NOT NULL,
                prediction_time TEXT NOT NULL,
                target_time TEXT NOT NULL,
                predicted_travel_time REAL NOT NULL,
                actual_travel_time REAL,
                error_seconds REAL,
                error_percentage REAL,
                FOREIGN KEY (route_id) REFERENCES probe_routes (route_id)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_real_traffic_timestamp 
            ON real_traffic_data(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_real_traffic_route 
            ON real_traffic_data(route_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sim_results_scenario 
            ON simulation_results(scenario_id, route_id)
        """)
        
        self.conn.commit()
        print("[DB] Database schema created/verified")
    
    # ========== PROBE ROUTES ==========
    
    def add_probe_route(
        self,
        route_id: str,
        name: str,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        description: str = ""
    ):
        """Add a probe route to monitor"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO probe_routes 
            (route_id, name, origin_lat, origin_lon, dest_lat, dest_lon, 
             description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (route_id, name, origin_lat, origin_lon, dest_lat, dest_lon,
              description, datetime.now().isoformat()))
        self.conn.commit()
        print(f"[DB] Added probe route: {name}")
    
    def get_probe_routes(self, active_only: bool = True) -> List[Dict]:
        """Get all probe routes"""
        cursor = self.conn.cursor()
        if active_only:
            cursor.execute("SELECT * FROM probe_routes WHERE active = 1")
        else:
            cursor.execute("SELECT * FROM probe_routes")
        return [dict(row) for row in cursor.fetchall()]
    
    # ========== REAL TRAFFIC DATA ==========
    
    def store_real_traffic_data(
        self,
        route_id: str,
        travel_time_seconds: int,
        distance_meters: int,
        traffic_delay_seconds: int = None,
        speed_kmh: float = None,
        data_source: str = "google_maps",
        raw_data: Dict = None
    ):
        """Store real-world traffic measurement"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO real_traffic_data
            (route_id, timestamp, travel_time_seconds, distance_meters,
             traffic_delay_seconds, speed_kmh, data_source, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (route_id, datetime.now().isoformat(), travel_time_seconds,
              distance_meters, traffic_delay_seconds, speed_kmh, data_source,
              json.dumps(raw_data) if raw_data else None))
        self.conn.commit()
    
    def get_real_traffic_data(
        self,
        route_id: str = None,
        start_time: str = None,
        end_time: str = None,
        limit: int = None
    ) -> List[Dict]:
        """Query real traffic data"""
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM real_traffic_data WHERE 1=1"
        params = []
        
        if route_id:
            query += " AND route_id = ?"
            params.append(route_id)
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        
        query += " ORDER BY timestamp DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    # ========== SIMULATION RESULTS ==========
    
    def store_simulation_result(
        self,
        scenario_id: str,
        route_id: str,
        travel_time_seconds: float,
        distance_meters: float,
        avg_speed_kmh: float = None,
        num_vehicles: int = None,
        simulation_params: Dict = None
    ):
        """Store simulation result for a route"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO simulation_results
            (scenario_id, route_id, timestamp, travel_time_seconds,
             distance_meters, avg_speed_kmh, num_vehicles, simulation_params)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (scenario_id, route_id, datetime.now().isoformat(),
              travel_time_seconds, distance_meters, avg_speed_kmh,
              num_vehicles, json.dumps(simulation_params) if simulation_params else None))
        self.conn.commit()
    
    def get_simulation_results(
        self,
        scenario_id: str,
        route_id: str = None
    ) -> List[Dict]:
        """Get simulation results"""
        cursor = self.conn.cursor()
        if route_id:
            cursor.execute("""
                SELECT * FROM simulation_results 
                WHERE scenario_id = ? AND route_id = ?
                ORDER BY timestamp DESC
            """, (scenario_id, route_id))
        else:
            cursor.execute("""
                SELECT * FROM simulation_results 
                WHERE scenario_id = ?
                ORDER BY timestamp DESC
            """, (scenario_id,))
        return [dict(row) for row in cursor.fetchall()]
    
    # ========== CALIBRATION ==========
    
    def store_calibration_params(
        self,
        scenario_id: str,
        params: Dict[str, float],
        rmse: float = None,
        mae: float = None,
        notes: str = None
    ):
        """Store calibration parameters"""
        cursor = self.conn.cursor()
        timestamp = datetime.now().isoformat()
        
        for param_name, param_value in params.items():
            cursor.execute("""
                INSERT INTO calibration_params
                (scenario_id, param_name, param_value, timestamp, rmse, mae, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (scenario_id, param_name, param_value, timestamp, rmse, mae, notes))
        
        self.conn.commit()
    
    def get_best_calibration(self, scenario_id: str) -> Dict[str, float]:
        """Get best calibration parameters (lowest RMSE)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT param_name, param_value 
            FROM calibration_params
            WHERE scenario_id = ?
            AND rmse = (
                SELECT MIN(rmse) FROM calibration_params 
                WHERE scenario_id = ?
            )
        """, (scenario_id, scenario_id))
        
        return {row['param_name']: row['param_value'] for row in cursor.fetchall()}
    
    # ========== VALIDATION METRICS ==========
    
    def store_validation_metrics(
        self,
        scenario_id: str,
        mae: float,
        rmse: float,
        mape: float,
        r_squared: float = None,
        num_samples: int = 0,
        time_period_start: str = None,
        time_period_end: str = None,
        notes: str = None
    ):
        """Store validation metrics"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO validation_metrics
            (scenario_id, timestamp, mae, rmse, mape, r_squared,
             num_samples, time_period_start, time_period_end, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (scenario_id, datetime.now().isoformat(), mae, rmse, mape,
              r_squared, num_samples, time_period_start, time_period_end, notes))
        self.conn.commit()
    
    def get_validation_metrics(self, scenario_id: str) -> List[Dict]:
        """Get all validation metrics for a scenario"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM validation_metrics 
            WHERE scenario_id = ?
            ORDER BY timestamp DESC
        """, (scenario_id,))
        return [dict(row) for row in cursor.fetchall()]
    
    # ========== UTILITY ==========
    
    def get_summary_stats(self) -> Dict:
        """Get database summary statistics"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # Count probe routes
        cursor.execute("SELECT COUNT(*) as count FROM probe_routes WHERE active = 1")
        stats['active_routes'] = cursor.fetchone()['count']
        
        # Count real data points
        cursor.execute("SELECT COUNT(*) as count FROM real_traffic_data")
        stats['real_data_points'] = cursor.fetchone()['count']
        
        # Count simulation results
        cursor.execute("SELECT COUNT(*) as count FROM simulation_results")
        stats['simulation_results'] = cursor.fetchone()['count']
        
        # Count scenarios
        cursor.execute("SELECT COUNT(DISTINCT scenario_id) as count FROM simulation_results")
        stats['scenarios'] = cursor.fetchone()['count']
        
        return stats
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print("[DB] Database connection closed")

# Global database instance
_db = None

def get_db() -> DigitalTwinDatabase:
    """Get global database instance"""
    global _db
    if _db is None:
        _db = DigitalTwinDatabase()
    return _db