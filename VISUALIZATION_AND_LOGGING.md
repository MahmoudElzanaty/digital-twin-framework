# Advanced Visualization and Logging System

## Overview

The Digital Twin Framework has been enhanced with comprehensive visualization and logging capabilities to provide deep insights into simulation results and route estimations.

## New Features

### 1. Advanced Visualizations (`modules/advanced_visualizer.py`)

#### Simulation Overview Dashboard
- **9-panel comprehensive visualization** for each simulation scenario
- **Real-time metrics tracking** with beautiful graphs

**Panels include:**
1. **Speed Distribution** - Histogram showing speed patterns across the network
2. **Traffic Flow Over Time** - Time-series plot of vehicle counts
3. **Speed Accuracy** - Pie chart comparing simulation vs real-world accuracy
4. **Congestion Levels** - Bar chart categorizing traffic congestion
5. **Edge Speed Comparison** - Scatter plot of simulated vs real speeds
6. **Vehicle Count** - Network-wide vehicle count timeline
7. **Travel Time Distribution** - Statistical analysis of travel times
8. **Calibration Progress** - Dynamic calibration improvements over time
9. **Performance Metrics** - Overall accuracy scores

**Usage:**
```python
from modules.advanced_visualizer import AdvancedVisualizer

visualizer = AdvancedVisualizer()
viz_path = visualizer.plot_simulation_overview("scenario_id")
# Creates: data/visualizations/scenario_id_overview.png
```

#### Route Estimation Visualization
- **6-panel detailed route analysis**
- **Google Maps comparison graphics**

**Panels include:**
1. **Route Overview** - Summary box with key metrics
2. **Speed Profile** - Speed variation along the route
3. **Edge Details** - Length distribution of route segments
4. **Estimation Comparison** - Simulation vs Google Maps bar chart
5. **Data Coverage** - Pie chart showing simulation data availability

**Usage:**
```python
route_data = route_estimator.find_route(lat1, lon1, lat2, lon2)
viz_path = visualizer.plot_route_estimation(route_data)
# Creates: data/visualizations/route_estimation_timestamp.png
```

#### Multi-Scenario Comparison
- **Compare multiple simulations** side-by-side
- **Timeline analysis** of accuracy improvements

**Usage:**
```python
scenario_ids = ["sim_001", "sim_002", "sim_003"]
viz_path = visualizer.plot_comparison_timeline(scenario_ids)
# Creates: data/visualizations/comparison_timeline_timestamp.png
```

### 2. Comprehensive Logging (`modules/results_logger.py`)

#### Structured Logging System
- **Multi-level logging** (DEBUG, INFO, WARNING, ERROR)
- **File and console output**
- **Automatic log rotation** by date

**Log File Locations:**
- Detailed logs: `data/results_logs/detailed_log_YYYYMMDD.log`
- Configuration: `data/results_logs/scenario_id_config.json`
- Progress: `data/results_logs/scenario_id_progress.csv`
- Results: `data/results_logs/scenario_id_results.json`
- Calibration: `data/results_logs/scenario_id_calibration.csv`

#### Key Logging Methods

**Simulation Logging:**
```python
from modules.results_logger import get_results_logger

logger = get_results_logger()

# Start of simulation
logger.log_simulation_start(scenario_id, config_dict)

# During simulation (progress tracking)
logger.log_simulation_progress(scenario_id, step, metrics_dict)

# Calibration updates
logger.log_calibration_update(scenario_id, step, parameters_dict)

# End of simulation
logger.log_simulation_complete(scenario_id, results_dict)
```

**Route Estimation Logging:**
```python
# Log route estimation with full details
logger.log_route_estimation(route_data)
```

**Comparison Logging:**
```python
# Log digital twin comparison
logger.log_comparison(comparison_data)
```

**Error Logging:**
```python
# Log errors with context and traceback
logger.log_error("Context description", exception)
```

#### Summary Reports
Generate comprehensive reports for multiple scenarios:

```python
report_path = logger.generate_summary_report(["sim_001", "sim_002", "sim_003"])
# Creates: data/results_logs/summary_report_timestamp.txt
```

**Report includes:**
- Individual scenario summaries
- Comparison metrics
- Calibration results
- Overall statistics
- Best/worst performers

#### Export Capabilities
Export scenario data to CSV:

```python
csv_path = logger.export_to_csv(scenario_id)
# Creates: data/results_logs/scenario_id_export.csv
```

### 3. Enhanced Simulator (`modules/simulator.py`)

The simulator now automatically:
- ✅ Logs all simulation events
- ✅ Tracks progress metrics every 100 steps
- ✅ Generates visualizations after completion
- ✅ Creates comprehensive result reports

**New output includes:**
```
Results saved:
  - Traffic logs: data/logs/edge_state.csv
  - Dynamic calibration: Database
  - Comparison report: data/reports/report_scenario_id.txt
  - Detailed logs: data/results_logs/
  - Visualizations: data/visualizations/scenario_id_overview.png
```

### 4. Enhanced Route Estimator (`modules/route_estimator.py`)

Route estimations now automatically:
- ✅ Log all route estimation details
- ✅ Generate visualizations for each estimation
- ✅ Include comparison visualizations when using Google Maps

**Enhanced output:**
```python
result = route_estimator.find_route(lat1, lon1, lat2, lon2)
# Returns dictionary with:
#   - All route metrics
#   - 'visualization_path': Path to generated PNG

result = route_estimator.compare_with_google_maps(lat1, lon1, lat2, lon2, api_key)
# Returns enhanced dictionary with:
#   - Simulation data
#   - Google Maps data
#   - Comparison metrics
#   - 'visualization_path': Comparison visualization PNG
```

### 5. GUI Integration (`app_desktop.py`)

#### Results Tab Enhancements

**New Buttons:**
1. **📊 Generate Visualization** - Create visualizations for selected scenario
2. **📝 Generate Summary Report** - Create report for all recent scenarios

**Enhanced Workflow:**
1. Select scenario from table
2. Click "View Details"
3. System automatically offers to:
   - Open existing visualization (if available)
   - Generate new visualization (if needed)
4. Visualizations open in system default image viewer

**New Methods:**
```python
# Open visualization in default viewer
app.open_visualization(viz_path)

# Generate visualization for scenario
app.generate_visualization(scenario_id)

# Generate summary report
app.generate_summary_report()
```

## File Structure

```
digital_twin_framework/
├── modules/
│   ├── advanced_visualizer.py      # NEW: Visualization generation
│   ├── results_logger.py           # NEW: Advanced logging system
│   ├── simulator.py                # ENHANCED: Auto-logging & visualization
│   └── route_estimator.py          # ENHANCED: Auto-logging & visualization
├── data/
│   ├── visualizations/             # NEW: Generated visualizations
│   │   ├── scenario_id_overview.png
│   │   ├── route_estimation_timestamp.png
│   │   └── comparison_timeline_timestamp.png
│   └── results_logs/               # NEW: Detailed logging
│       ├── detailed_log_YYYYMMDD.log
│       ├── scenario_id_config.json
│       ├── scenario_id_progress.csv
│       ├── scenario_id_results.json
│       ├── scenario_id_calibration.csv
│       └── summary_report_timestamp.txt
└── VISUALIZATION_AND_LOGGING.md    # This file
```

## Usage Examples

### Example 1: Run Simulation with Full Logging and Visualization

```python
from modules.simulator import run_simulation

# Run simulation (automatically logs and visualizes)
scenario_id = run_simulation(
    "data/sim/config.sumocfg",
    gui=False,
    scenario_id="my_test_scenario",
    enable_digital_twin=True,
    enable_dynamic_calibration=True
)

# Output:
# - Console logs with progress
# - Detailed log file in data/results_logs/
# - Visualization in data/visualizations/
# - Results JSON in data/results_logs/
```

### Example 2: Estimate Route with Visualization

```python
from modules.route_estimator import RouteEstimator

estimator = RouteEstimator("data/network.net.xml", "my_scenario")

# Estimate route (automatically logs and visualizes)
result = estimator.find_route(30.0444, 31.2357, 30.0622, 31.2494)

print(f"Travel time: {result['travel_time_minutes']:.1f} minutes")
print(f"Visualization: {result['visualization_path']}")

# Compare with Google Maps (generates comparison visualization)
comparison = estimator.compare_with_google_maps(
    30.0444, 31.2357, 30.0622, 31.2494,
    api_key="YOUR_API_KEY"
)

print(f"Accuracy: {100 - comparison['comparison']['time_error_percent']:.1f}%")
print(f"Comparison viz: {comparison['visualization_path']}")
```

### Example 3: Generate Summary Report

```python
from modules.results_logger import get_results_logger

logger = get_results_logger()

# Generate report for multiple scenarios
scenarios = ["sim_001", "sim_002", "sim_003"]
report_path = logger.generate_summary_report(scenarios)

print(f"Report saved to: {report_path}")
```

### Example 4: Custom Visualization

```python
from modules.advanced_visualizer import AdvancedVisualizer

visualizer = AdvancedVisualizer()

# Visualize specific scenario
viz_path = visualizer.plot_simulation_overview("sim_20250110_123456")

# Compare multiple scenarios
comparison_path = visualizer.plot_comparison_timeline([
    "sim_20250110_123456",
    "sim_20250110_134567",
    "sim_20250110_145678"
])
```

## Performance Metrics Tracked

### Simulation Metrics
- **Speed Accuracy**: Percentage match with real-world speeds
- **Congestion Similarity**: How well congestion patterns match reality
- **RMSE**: Root Mean Square Error for speed predictions
- **Data Coverage**: Percentage of edges with simulation data

### Route Estimation Metrics
- **Travel Time Error**: Accuracy of time predictions
- **Speed Error**: Accuracy of speed predictions
- **Distance Error**: Route distance accuracy
- **Data Coverage**: Percentage of route with simulation data

### Calibration Metrics
- **Initial Speed**: Starting average speed
- **Final Speed**: Optimized average speed
- **Improvement**: Percentage improvement from calibration
- **Updates Applied**: Number of parameter adjustments

## Quality Assessment Thresholds

The system automatically assesses quality:

### Speed Accuracy
- ✅ **Excellent**: < 10% error
- 👍 **Good**: 10-20% error
- ⚠️ **Fair**: 20-30% error
- ❌ **Poor**: > 30% error

### Congestion Similarity
- ✅ **High**: > 80% similarity
- 👍 **Moderate**: 60-80% similarity
- ⚠️ **Low**: 40-60% similarity
- ❌ **Very Low**: < 40% similarity

## Dependencies

New requirements added to `requirements.txt`:
- `scipy>=1.11.0` - For statistical analysis in visualizations

All visualization dependencies already included:
- `matplotlib==3.8.2`
- `seaborn==0.13.1`
- `pandas==2.1.4`
- `numpy==1.26.3`

## Best Practices

### 1. Regular Visualization Generation
- Generate visualizations after each significant simulation
- Compare visualizations across scenarios to track improvements
- Use summary reports for stakeholder presentations

### 2. Log Analysis
- Review detailed logs for troubleshooting
- Monitor progress CSV files for trends
- Use calibration logs to understand parameter evolution

### 3. Performance Monitoring
- Track speed accuracy over multiple scenarios
- Identify scenarios with low performance for re-calibration
- Use comparison timelines to demonstrate improvements

### 4. Data Organization
- Keep visualization directories clean (archive old files)
- Regularly backup log files
- Use meaningful scenario IDs for easy identification

## Troubleshooting

### Visualization not generating?
1. Check if matplotlib backend is properly configured
2. Ensure database has data for the scenario
3. Verify sufficient disk space in data/visualizations/

### Logs not appearing?
1. Check write permissions on data/results_logs/
2. Verify logger initialization in your code
3. Check log level settings

### GUI buttons not working?
1. Ensure scenario is selected in table
2. Check console for error messages
3. Verify all dependencies are installed

## Future Enhancements

Potential additions:
- Interactive web-based visualizations (Plotly/Dash)
- Real-time visualization during simulation
- 3D traffic flow visualizations
- Animated route comparison videos
- Machine learning-based anomaly detection in logs
- Automatic performance regression detection

## Credits

Enhanced visualization and logging system for Digital Twin Framework.
Designed for comprehensive traffic simulation analysis and reporting.

---

**Last Updated**: 2025-11-10
**Version**: 1.0
**Author**: Digital Twin Framework Development Team
