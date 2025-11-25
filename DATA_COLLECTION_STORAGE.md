# Data Collection Storage System

## Overview

The network-based traffic data collection system stores all collected data in the SQLite database at `data/digital_twin.db`, making it fully compatible with other framework systems.

## Database Storage Details

### Table: `real_traffic_data`

All collected traffic data (both typical and real-time) is stored in the `real_traffic_data` table with the following schema:

```sql
CREATE TABLE real_traffic_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id TEXT,                    -- NULL for network-based collection
    area_id TEXT,                     -- Network area identifier (optional)
    timestamp TEXT NOT NULL,          -- ISO format timestamp
    travel_time_seconds INTEGER NOT NULL,
    distance_meters INTEGER NOT NULL,
    traffic_delay_seconds INTEGER,
    speed_kmh REAL,
    data_source TEXT NOT NULL,        -- e.g., 'google_typical_monday_0800', 'google_realtime'
    raw_data TEXT,                    -- Full JSON response from Google Maps API
    origin_lat REAL,                  -- Route origin latitude
    origin_lon REAL,                  -- Route origin longitude
    dest_lat REAL,                    -- Route destination latitude
    dest_lon REAL                     -- Route destination longitude
)
```

### Storage Method

Updated method signature in `modules/database.py`:

```python
def store_real_traffic_data(
    self,
    route_id: str = None,              # Optional - NULL for network collections
    travel_time_seconds: int = None,
    distance_meters: int = None,
    traffic_delay_seconds: int = None,
    speed_kmh: float = None,
    data_source: str = "google_maps",
    raw_data: Dict = None,
    timestamp: datetime = None,
    origin_lat: float = None,          # NEW: Origin coordinates
    origin_lon: float = None,
    dest_lat: float = None,            # NEW: Destination coordinates
    dest_lon: float = None,
    area_id: str = None                # NEW: Area identifier
)
```

## Data Source Identifiers

The `data_source` field helps distinguish different collection types:

### Typical Traffic Collection
- Format: `google_typical_{day}_{time}`
- Examples:
  - `google_typical_monday_0800` - Monday 8:00 AM
  - `google_typical_saturday_1700` - Saturday 5:00 PM
  - `google_typical_wednesday_1200` - Wednesday 12:00 PM

### Real-Time Traffic Collection
- Format: `google_realtime`
- All real-time collections use this identifier
- Timestamp field contains actual collection time

## How Other Systems Can Use This Data

### 1. Route Estimator (`modules/route_estimator.py`)

The route estimator can query collected data by:

```python
# Get all traffic data for analysis
all_data = db.get_real_traffic_data()

# Filter by time range
data = db.get_real_traffic_data(
    start_time='2025-01-01T00:00:00',
    end_time='2025-01-31T23:59:59'
)

# Spatial queries using coordinates
for record in data:
    if is_near_route(record['origin_lat'], record['origin_lon'],
                    record['dest_lat'], record['dest_lon'],
                    my_route):
        # Use this data point for estimation
        speed = record['speed_kmh']
```

### 2. Simulator Calibration

Collected data provides real-world benchmarks:

```python
# Get typical traffic patterns for calibration
typical_data = [r for r in db.get_real_traffic_data()
                if 'typical' in r['data_source']]

# Calculate average speeds by time of day
speeds_by_hour = {}
for record in typical_data:
    hour = datetime.fromisoformat(record['timestamp']).hour
    speeds_by_hour[hour] = speeds_by_hour.get(hour, []) + [record['speed_kmh']]

# Use these benchmarks to calibrate SUMO parameters
target_speed = statistics.mean(speeds_by_hour[17])  # Rush hour
```

### 3. Validation and Comparison

```python
# Query data for specific time periods
monday_morning = db.get_real_traffic_data(
    start_time='2025-01-06T08:00:00',
    end_time='2025-01-06T09:00:00'
)

# Compare simulation results with real data
simulation_avg_speed = 45.2  # km/h from simulation
real_avg_speed = statistics.mean([r['speed_kmh'] for r in monday_morning])
accuracy = 100 - abs(simulation_avg_speed - real_avg_speed) / real_avg_speed * 100
```

### 4. Area-Wide Analysis

```python
# Analyze network-wide patterns
all_network_data = db.get_real_traffic_data()

# Calculate network statistics
speeds = [r['speed_kmh'] for r in all_network_data]
network_avg_speed = statistics.mean(speeds)
network_min_speed = min(speeds)
network_max_speed = max(speeds)

# Identify congestion patterns by time
congestion_times = []
for record in all_network_data:
    if record['speed_kmh'] < 20:  # Congested threshold
        hour = datetime.fromisoformat(record['timestamp']).hour
        congestion_times.append(hour)
```

### 5. Machine Learning Features

The stored data provides rich features for ML models:

```python
# Extract training features
features = []
for record in db.get_real_traffic_data():
    dt = datetime.fromisoformat(record['timestamp'])
    features.append({
        'hour': dt.hour,
        'day_of_week': dt.weekday(),
        'distance_km': record['distance_meters'] / 1000,
        'speed_kmh': record['speed_kmh'],
        'travel_time_min': record['travel_time_seconds'] / 60,
        'is_rush_hour': dt.hour in [8, 9, 17, 18],
        'is_weekend': dt.weekday() >= 5
    })
```

## Query Examples

### Get All Typical Traffic Data
```python
from modules.database import get_db

db = get_db()
typical_data = [r for r in db.get_real_traffic_data()
                if 'typical' in r['data_source']]
print(f"Total typical traffic samples: {len(typical_data)}")
```

### Get Real-Time Traffic Data
```python
realtime_data = [r for r in db.get_real_traffic_data()
                 if r['data_source'] == 'google_realtime']
print(f"Total real-time samples: {len(realtime_data)}")
```

### Get Data by Time Range
```python
import sqlite3

conn = sqlite3.connect('data/digital_twin.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT * FROM real_traffic_data
    WHERE timestamp >= ? AND timestamp <= ?
    ORDER BY timestamp ASC
""", ('2025-01-01T00:00:00', '2025-01-31T23:59:59'))

data = cursor.fetchall()
```

### Spatial Queries (Find Data Near a Location)
```python
def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km"""
    # Implementation here
    pass

# Find all data points within 1km of a location
target_lat, target_lon = 30.0444, 31.2357
radius_km = 1.0

nearby_data = []
for record in db.get_real_traffic_data():
    dist = haversine_distance(
        target_lat, target_lon,
        record['origin_lat'], record['origin_lon']
    )
    if dist <= radius_km:
        nearby_data.append(record)
```

## Data Compatibility Benefits

### ✅ Works With All Framework Systems

1. **Route Estimator**: Can use speed data for travel time predictions
2. **Simulator**: Provides calibration benchmarks
3. **Validator**: Enables accuracy comparisons
4. **Visualizer**: Can plot speed distributions and patterns
5. **Machine Learning**: Rich dataset for training models

### ✅ Flexible Queries

- No dependency on `route_id` (it's NULL for network collections)
- Coordinates enable spatial queries
- Timestamps enable temporal queries
- Data source enables filtering by collection type

### ✅ Full API Response Stored

The `raw_data` field contains the complete JSON response from Google Maps, including:
- Detailed route geometry
- Turn-by-turn directions
- Alternative routes
- Traffic conditions
- Warnings and restrictions

This can be used for advanced analysis or debugging.

## Best Practices

### 1. Query Efficiently

Use database indexes:
```python
# Indexed queries (fast)
db.get_real_traffic_data(start_time='...', end_time='...')

# Filter results in Python (slower for large datasets)
all_data = db.get_real_traffic_data()
filtered = [r for r in all_data if some_condition]
```

### 2. Handle NULL route_id

```python
for record in db.get_real_traffic_data():
    if record['route_id']:
        # Probe route data
        print(f"Route: {record['route_id']}")
    else:
        # Network-based collection data
        print(f"Network sample: {record['origin_lat']},{record['origin_lon']}")
```

### 3. Parse Raw Data When Needed

```python
import json

for record in db.get_real_traffic_data():
    if record['raw_data']:
        full_response = json.loads(record['raw_data'])
        # Access detailed route information
        polyline = full_response['routes'][0]['overview_polyline']['points']
        # Use for visualization or detailed analysis
```

## Summary

The collected traffic data is:

✅ **Properly Stored**: In the standard `real_traffic_data` table
✅ **Fully Compatible**: Works with all framework systems
✅ **Richly Detailed**: Includes coordinates, speeds, timestamps, and raw API data
✅ **Flexibly Queryable**: By time, location, or data source
✅ **Production Ready**: Uses industry-standard SQLite database

All data collection (typical and real-time) feeds into the same unified system that other framework components already use, ensuring seamless integration and analysis.

---

**Last Updated**: 2025-11-12
**Related Files**:
- `modules/database.py` - Database methods
- `app_desktop.py` - Data collection workers
- `modules/route_estimator.py` - Uses collected data
- `modules/simulator.py` - Calibrates using collected data
