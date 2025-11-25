# Database Access Guide

## Your Database Location
```
C:\Users\mondy\OneDrive\Desktop\Bachelors\digital_twin_framework\data\digital_twin.db
```

## Current Database Contents

Based on the latest scan:

| Table | Total Records | Unique Scenarios |
|-------|--------------|------------------|
| **validation_metrics** | 25 | 13 |
| **simulation_results** | 5 | 1 |
| **calibration_params** | 135 | 27 |

---

## 5 Ways to Access Your Database

### 🚀 Method 1: Quick View Script (Recommended for Quick Checks)

**Run this anytime:**
```bash
python view_database.py
```

**What it shows:**
- ✅ All validation metrics (completed simulations)
- ✅ All simulation results (raw outputs)
- ✅ All calibration runs
- ✅ Database statistics
- ✅ Top 10 best performing scenarios

---

### 🎯 Method 2: Custom Query Tool (Recommended for Filtering)

**Run this for custom queries:**
```bash
python query_database.py
```

**Pre-defined queries:**
1. All validation metrics
2. Best scenarios (MAPE < 30%)
3. Scenarios by date
4. All unique scenarios
5. Simulation statistics
6. Custom SQL query (write your own!)

---

### 🖥️ Method 3: DB Browser for SQLite (Best Visual Tool)

**Download:** https://sqlitebrowser.org/dl/

**Steps:**
1. Download and install DB Browser for SQLite
2. Open the application
3. Click **"Open Database"**
4. Select: `data/digital_twin.db`
5. Use the **"Browse Data"** tab to view tables
6. Use the **"Execute SQL"** tab to run custom queries

**Features:**
- ✅ Visual table browsing
- ✅ Export to CSV/Excel
- ✅ Edit data directly
- ✅ Run SQL queries with autocomplete
- ✅ View table schemas

---

### 💻 Method 4: SQLite Command Line

**Open Command Prompt in project folder:**

```bash
# Open database
sqlite3 data/digital_twin.db

# Useful commands:
.tables                                    # List all tables
.schema validation_metrics                 # See table structure
.mode column                               # Format output in columns
.headers on                                # Show column names

# Sample queries:
SELECT COUNT(*) FROM validation_metrics;
SELECT * FROM validation_metrics ORDER BY timestamp DESC LIMIT 10;
SELECT scenario_id, mape FROM validation_metrics WHERE mape < 30;

# Exit:
.quit
```

---

### 🐍 Method 5: Python Script (Custom Analysis)

**Create your own script:**

```python
import sqlite3

conn = sqlite3.connect('data/digital_twin.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Your custom query
cursor.execute("""
    SELECT scenario_id, mape, r_squared
    FROM validation_metrics
    WHERE mape < 30
    ORDER BY mape ASC
""")

for row in cursor.fetchall():
    print(f"Scenario: {row['scenario_id']}, MAPE: {row['mape']:.2f}%")

conn.close()
```

---

## Important Database Tables

### 1. `validation_metrics` (Main Results Table)
Contains completed simulation results with validation metrics.

**Columns:**
- `scenario_id` - Unique identifier for the simulation run
- `timestamp` - When the simulation was run
- `mape` - Mean Absolute Percentage Error (lower is better)
- `r_squared` - R² correlation coefficient (higher is better)
- `num_samples` - Number of data points used
- `mae`, `rmse` - Other error metrics

**Use this table for:** Viewing completed simulation performance

---

### 2. `simulation_results` (Raw Simulation Outputs)
Contains detailed route-level simulation results.

**Columns:**
- `scenario_id` - Links to validation_metrics
- `route_id` - Specific route simulated
- `travel_time_seconds` - Simulated travel time
- `avg_speed_kmh` - Average speed
- `num_vehicles` - Number of vehicles in simulation

**Use this table for:** Detailed route-level analysis

---

### 3. `calibration_params` (All Simulation Runs)
Contains calibration parameters for every simulation (even incomplete ones).

**Columns:**
- `scenario_id` - Simulation identifier
- `param_name` - Parameter being calibrated (tau, accel, decel, etc.)
- `param_value` - Parameter value
- `timestamp` - When calibration was done

**Use this table for:** Seeing all simulation attempts (including incomplete)

---

## Common SQL Queries

### Get all scenarios with good performance (MAPE < 25%)
```sql
SELECT scenario_id, mape, r_squared, timestamp
FROM validation_metrics
WHERE mape < 25
ORDER BY mape ASC;
```

### Count simulations per day
```sql
SELECT DATE(timestamp) as date, COUNT(*) as simulations
FROM validation_metrics
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

### Find best and worst performance
```sql
SELECT
    MIN(mape) as best_mape,
    MAX(mape) as worst_mape,
    AVG(mape) as avg_mape
FROM validation_metrics;
```

### Get latest simulation for each unique scenario
```sql
SELECT scenario_id, MAX(timestamp) as latest_run, mape
FROM validation_metrics
GROUP BY scenario_id
ORDER BY latest_run DESC;
```

---

## Export Data

### Export to CSV using Python:
```python
import sqlite3
import csv

conn = sqlite3.connect('data/digital_twin.db')
cursor = conn.cursor()

cursor.execute("SELECT * FROM validation_metrics")

with open('validation_metrics.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow([desc[0] for desc in cursor.description])  # Headers
    writer.writerows(cursor.fetchall())

conn.close()
print("Exported to validation_metrics.csv")
```

### Export using DB Browser:
1. Open table in "Browse Data"
2. Click **"Export to CSV"** button
3. Choose filename and save

---

## Your Current Best Scenarios

From latest analysis:

| Rank | Scenario | MAPE | R² | Status |
|------|----------|------|----|--------|
| 1 | test_scenario | 6.65% | 0.878 | ✅ Excellent |
| 2 | custom_area_20251022_201322 | 26.62% | 0.797 | ✓ Good |
| 3 | custom_area_20251014_231534 | 29.66% | 0.795 | ⚠️ Fair |

---

## Troubleshooting

**Problem:** "unable to open database file"
- Check the path is correct
- Make sure you're in the project directory

**Problem:** "database is locked"
- Close the application (app_desktop.py)
- Close DB Browser if open
- Try again

**Problem:** "no such table"
- Make sure database file exists
- Check table name spelling (case-sensitive)

---

**Last Updated:** 2025-11-13
