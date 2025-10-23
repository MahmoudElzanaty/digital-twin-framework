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
        self.migrate_schema()  # Handle schema updates
        self.create_tables()
    
    def connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return dict-like rows
        print(f"[DB] Connected to {self.db_path}")

    def migrate_schema(self):
        """Migrate existing database to new schema"""
        cursor = self.conn.cursor()

        try:
            # Check if real_traffic_data table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='real_traffic_data'")
            table_exists = cursor.fetchone()

            if table_exists:
                # Get table info including NOT NULL constraints
                cursor.execute("PRAGMA table_info(real_traffic_data)")
                table_info = cursor.fetchall()
                columns = {col[1]: {'notnull': col[3]} for col in table_info}

                # Check if route_id has NOT NULL constraint (old schema bug)
                if 'route_id' in columns and columns['route_id']['notnull'] == 1:
                    print("[DB] ⚠️ Fixing old schema: route_id should be nullable")
                    print("[DB] Recreating real_traffic_data table...")

                    # Create new table with correct schema
                    cursor.execute("""
                        CREATE TABLE real_traffic_data_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            route_id TEXT,
                            area_id TEXT,
                            timestamp TEXT NOT NULL,
                            travel_time_seconds INTEGER NOT NULL,
                            distance_meters INTEGER NOT NULL,
                            traffic_delay_seconds INTEGER,
                            speed_kmh REAL,
                            data_source TEXT NOT NULL,
                            raw_data TEXT,
                            origin_lat REAL,
                            origin_lon REAL,
                            dest_lat REAL,
                            dest_lon REAL
                        )
                    """)

                    # Copy existing data
                    try:
                        cursor.execute("""
                            INSERT INTO real_traffic_data_new
                            SELECT * FROM real_traffic_data
                        """)
                    except:
                        # If columns don't match, skip data migration
                        pass

                    # Drop old table and rename
                    cursor.execute("DROP TABLE real_traffic_data")
                    cursor.execute("ALTER TABLE real_traffic_data_new RENAME TO real_traffic_data")
                    print("[DB] ✅ Fixed: route_id is now nullable")

                else:
                    # Add missing columns if needed
                    column_names = [col[1] for col in table_info]

                    if 'area_id' not in column_names:
                        print("[DB] Adding area_id column...")
                        cursor.execute("ALTER TABLE real_traffic_data ADD COLUMN area_id TEXT")

                    if 'origin_lat' not in column_names:
                        print("[DB] Adding coordinate columns...")
                        cursor.execute("ALTER TABLE real_traffic_data ADD COLUMN origin_lat REAL")
                        cursor.execute("ALTER TABLE real_traffic_data ADD COLUMN origin_lon REAL")
                        cursor.execute("ALTER TABLE real_traffic_data ADD COLUMN dest_lat REAL")
                        cursor.execute("ALTER TABLE real_traffic_data ADD COLUMN dest_lon REAL")

            # Check if probe_routes has area_id column
            cursor.execute("PRAGMA table_info(probe_routes)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'area_id' not in columns:
                cursor.execute("ALTER TABLE probe_routes ADD COLUMN area_id TEXT")
                print("[DB] Added area_id to probe_routes")

            if 'is_primary' not in columns:
                cursor.execute("ALTER TABLE probe_routes ADD COLUMN is_primary INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE probe_routes ADD COLUMN priority INTEGER DEFAULT 0")
                print("[DB] Added is_primary and priority to probe_routes")

            self.conn.commit()
            print("[DB] Schema migration complete")

        except Exception as e:
            # Table doesn't exist yet, that's fine
            print(f"[DB] Migration skipped: {e}")
            pass

    def create_tables(self):
        """Create all necessary tables"""
        cursor = self.conn.cursor()

        # NEW TABLE: Monitored Areas (fixed geographic areas for training)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitored_areas (
                area_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                bbox_north REAL NOT NULL,
                bbox_south REAL NOT NULL,
                bbox_east REAL NOT NULL,
                bbox_west REAL NOT NULL,
                sumo_network_file TEXT,
                status TEXT DEFAULT 'created',
                training_start_date TEXT,
                training_end_date TEXT,
                training_duration_days INTEGER,
                collections_completed INTEGER DEFAULT 0,
                collections_target INTEGER,
                accuracy_rmse REAL,
                accuracy_mae REAL,
                accuracy_mape REAL,
                created_at TEXT NOT NULL
            )
        """)

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
                active INTEGER DEFAULT 1,
                is_primary INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                area_id TEXT,
                FOREIGN KEY (area_id) REFERENCES monitored_areas(area_id)
            )
        """)
        
        # Table 2: Real Traffic Data (from APIs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS real_traffic_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id TEXT,
                area_id TEXT,
                timestamp TEXT NOT NULL,
                travel_time_seconds INTEGER NOT NULL,
                distance_meters INTEGER NOT NULL,
                traffic_delay_seconds INTEGER,
                speed_kmh REAL,
                data_source TEXT NOT NULL,
                raw_data TEXT,
                origin_lat REAL,
                origin_lon REAL,
                dest_lat REAL,
                dest_lon REAL,
                FOREIGN KEY (route_id) REFERENCES probe_routes (route_id),
                FOREIGN KEY (area_id) REFERENCES monitored_areas (area_id)
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
        
        # NEW TABLE: Area Traffic Snapshots (aggregated area-wide data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS area_traffic_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                snapshot_timestamp TEXT NOT NULL,
                num_samples INTEGER,
                avg_speed_kmh REAL,
                min_speed_kmh REAL,
                max_speed_kmh REAL,
                FOREIGN KEY (area_id) REFERENCES monitored_areas(area_id)
            )
        """)

        # NEW TABLE: Calibration History (tracks calibration improvements)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calibration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area_id TEXT NOT NULL,
                calibration_date TEXT NOT NULL,
                sumo_params TEXT NOT NULL,
                accuracy_mae REAL,
                accuracy_rmse REAL,
                accuracy_mape REAL,
                num_validation_samples INTEGER,
                notes TEXT,
                FOREIGN KEY (area_id) REFERENCES monitored_areas(area_id)
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
            CREATE INDEX IF NOT EXISTS idx_real_traffic_area
            ON real_traffic_data(area_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sim_results_scenario
            ON simulation_results(scenario_id, route_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_area_snapshots
            ON area_traffic_snapshots(area_id, snapshot_timestamp)
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
        description: str = "",
        is_primary: bool = False,
        priority: int = 0
    ):
        """Add a probe route to monitor"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO probe_routes
            (route_id, name, origin_lat, origin_lon, dest_lat, dest_lon,
             description, created_at, is_primary, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (route_id, name, origin_lat, origin_lon, dest_lat, dest_lon,
              description, datetime.now().isoformat(), 1 if is_primary else 0, priority))
        self.conn.commit()
        print(f"[DB] Added probe route: {name}")
    
    def get_probe_routes(self, active_only: bool = True, primary_only: bool = False) -> List[Dict]:
        """Get all probe routes"""
        cursor = self.conn.cursor()
        query = "SELECT * FROM probe_routes WHERE 1=1"
        if active_only:
            query += " AND active = 1"
        if primary_only:
            query += " AND is_primary = 1 ORDER BY priority ASC"
        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    def get_primary_routes(self) -> List[Dict]:
        """Get the 5 primary routes for congestion prediction"""
        return self.get_probe_routes(active_only=True, primary_only=True)
    
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
    
    # ========== MONITORED AREAS (NEW) ==========

    def create_monitored_area(
        self,
        area_id: str,
        name: str,
        bbox: Dict[str, float],
        sumo_network_file: str = None
    ):
        """Create a new monitored area for training"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO monitored_areas
            (area_id, name, bbox_north, bbox_south, bbox_east, bbox_west,
             sumo_network_file, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?)
        """, (
            area_id,
            name,
            bbox['north'],
            bbox['south'],
            bbox['east'],
            bbox['west'],
            sumo_network_file,
            datetime.now().isoformat()
        ))
        self.conn.commit()
        print(f"[DB] Created monitored area: {name} ({area_id})")

    def get_monitored_area(self, area_id: str) -> Dict:
        """Get area details"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM monitored_areas WHERE area_id = ?", (area_id,))
        row = cursor.fetchone()
        if row:
            area = dict(row)
            # Reconstruct bbox dict
            area['bbox'] = {
                'north': area['bbox_north'],
                'south': area['bbox_south'],
                'east': area['bbox_east'],
                'west': area['bbox_west']
            }
            return area
        return None

    def get_all_monitored_areas(self) -> List[Dict]:
        """Get all monitored areas"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM monitored_areas ORDER BY created_at DESC")
        areas = []
        for row in cursor.fetchall():
            area = dict(row)
            area['bbox'] = {
                'north': area['bbox_north'],
                'south': area['bbox_south'],
                'east': area['bbox_east'],
                'west': area['bbox_west']
            }
            areas.append(area)
        return areas

    def update_area_status(
        self,
        area_id: str,
        status: str,
        training_start_date: str = None,
        training_duration_days: int = None,
        collections_target: int = None
    ):
        """Update area training status"""
        cursor = self.conn.cursor()

        updates = ["status = ?"]
        params = [status]

        if training_start_date:
            updates.append("training_start_date = ?")
            params.append(training_start_date)
        if training_duration_days:
            updates.append("training_duration_days = ?")
            params.append(training_duration_days)
        if collections_target:
            updates.append("collections_target = ?")
            params.append(collections_target)

        params.append(area_id)

        query = f"UPDATE monitored_areas SET {', '.join(updates)} WHERE area_id = ?"
        cursor.execute(query, params)
        self.conn.commit()
        print(f"[DB] Updated area status: {area_id} -> {status}")

    def update_area_training_progress(self, area_id: str, collections_completed: int):
        """Update training progress"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE monitored_areas
            SET collections_completed = ?
            WHERE area_id = ?
        """, (collections_completed, area_id))
        self.conn.commit()

    def mark_area_training_complete(
        self,
        area_id: str,
        accuracy_rmse: float,
        accuracy_mae: float,
        accuracy_mape: float
    ):
        """Mark training as complete with accuracy metrics"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE monitored_areas
            SET status = 'trained',
                training_end_date = ?,
                accuracy_rmse = ?,
                accuracy_mae = ?,
                accuracy_mape = ?
            WHERE area_id = ?
        """, (
            datetime.now().isoformat(),
            accuracy_rmse,
            accuracy_mae,
            accuracy_mape,
            area_id
        ))
        self.conn.commit()
        print(f"[DB] Area training complete: {area_id}")

    def link_route_to_area(self, route_id: str, area_id: str):
        """Link a route to its parent area"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE probe_routes
            SET area_id = ?
            WHERE route_id = ?
        """, (area_id, route_id))
        self.conn.commit()

    def get_routes_in_area(self, area_id: str) -> List[Dict]:
        """Get all routes within an area"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM probe_routes
            WHERE area_id = ? AND active = 1
            ORDER BY priority ASC
        """, (area_id,))
        return [dict(row) for row in cursor.fetchall()]

    # ========== AREA TRAFFIC DATA (NEW) ==========

    def store_area_traffic_sample(
        self,
        area_id: str,
        snapshot_id: str,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        travel_time_seconds: int,
        distance_meters: int,
        speed_kmh: float,
        data_source: str = "google_maps"
    ):
        """Store area-wide traffic sample (not tied to specific route)"""
        cursor = self.conn.cursor()
        # Use snapshot_id as pseudo route_id for area-wide samples
        cursor.execute("""
            INSERT INTO real_traffic_data
            (route_id, area_id, timestamp, travel_time_seconds, distance_meters,
             speed_kmh, data_source, origin_lat, origin_lon, dest_lat, dest_lon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,  # Use snapshot_id as route_id for area-wide data
            area_id,
            datetime.now().isoformat(),
            travel_time_seconds,
            distance_meters,
            speed_kmh,
            data_source,
            origin_lat,
            origin_lon,
            dest_lat,
            dest_lon
        ))
        self.conn.commit()

    def store_area_snapshot(
        self,
        area_id: str,
        snapshot_id: str,
        num_samples: int,
        avg_speed_kmh: float,
        min_speed_kmh: float = None,
        max_speed_kmh: float = None
    ):
        """Store aggregated snapshot of area traffic"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO area_traffic_snapshots
            (area_id, snapshot_id, snapshot_timestamp, num_samples,
             avg_speed_kmh, min_speed_kmh, max_speed_kmh)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            area_id,
            snapshot_id,
            datetime.now().isoformat(),
            num_samples,
            avg_speed_kmh,
            min_speed_kmh,
            max_speed_kmh
        ))
        self.conn.commit()

    def get_area_traffic_data(
        self,
        area_id: str,
        start_time: str = None,
        end_time: str = None,
        limit: int = None
    ) -> List[Dict]:
        """Get all training data for an area"""
        cursor = self.conn.cursor()

        query = "SELECT * FROM real_traffic_data WHERE area_id = ?"
        params = [area_id]

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

    def get_area_snapshots(self, area_id: str, limit: int = None) -> List[Dict]:
        """Get area traffic snapshots"""
        cursor = self.conn.cursor()

        query = """
            SELECT * FROM area_traffic_snapshots
            WHERE area_id = ?
            ORDER BY snapshot_timestamp DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, (area_id,))
        return [dict(row) for row in cursor.fetchall()]

    # ========== CALIBRATION HISTORY (NEW) ==========

    def store_area_calibration(
        self,
        area_id: str,
        sumo_params: Dict[str, float],
        accuracy_mae: float,
        accuracy_rmse: float,
        accuracy_mape: float,
        num_samples: int,
        notes: str = None
    ):
        """Store calibration attempt for area"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO calibration_history
            (area_id, calibration_date, sumo_params, accuracy_mae,
             accuracy_rmse, accuracy_mape, num_validation_samples, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            area_id,
            datetime.now().isoformat(),
            json.dumps(sumo_params),
            accuracy_mae,
            accuracy_rmse,
            accuracy_mape,
            num_samples,
            notes
        ))
        self.conn.commit()

    def get_best_area_calibration(self, area_id: str) -> Dict:
        """Get best calibration for area (lowest RMSE)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM calibration_history
            WHERE area_id = ?
            ORDER BY accuracy_rmse ASC
            LIMIT 1
        """, (area_id,))

        row = cursor.fetchone()
        if row:
            result = dict(row)
            result['sumo_params'] = json.loads(result['sumo_params'])
            return result
        return None

    # ========== UTILITY ==========

    def get_summary_stats(self) -> Dict:
        """Get database summary statistics"""
        cursor = self.conn.cursor()

        stats = {}

        # Count monitored areas
        cursor.execute("SELECT COUNT(*) as count FROM monitored_areas")
        stats['monitored_areas'] = cursor.fetchone()['count']

        # Count areas by status
        cursor.execute("SELECT COUNT(*) as count FROM monitored_areas WHERE status = 'trained'")
        stats['trained_areas'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM monitored_areas WHERE status = 'training'")
        stats['training_areas'] = cursor.fetchone()['count']

        # Count probe routes
        cursor.execute("SELECT COUNT(*) as count FROM probe_routes WHERE active = 1")
        stats['active_routes'] = cursor.fetchone()['count']

        # Count primary routes
        cursor.execute("SELECT COUNT(*) as count FROM probe_routes WHERE is_primary = 1")
        stats['primary_routes'] = cursor.fetchone()['count']

        # Count real data points
        cursor.execute("SELECT COUNT(*) as count FROM real_traffic_data")
        stats['real_data_points'] = cursor.fetchone()['count']

        # Count area snapshots
        cursor.execute("SELECT COUNT(*) as count FROM area_traffic_snapshots")
        stats['area_snapshots'] = cursor.fetchone()['count']

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