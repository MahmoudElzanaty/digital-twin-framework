"""
Advanced Visualization Module for Digital Twin Framework
Provides comprehensive plotting and visualization for simulation results
"""
import os
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
import seaborn as sns
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sqlite3

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 10)
plt.rcParams['font.size'] = 10


class AdvancedVisualizer:
    """Advanced visualization for simulation results and route estimation"""

    def __init__(self, db_path: str = "data/digital_twin.db"):
        """
        Initialize visualizer

        Args:
            db_path: Path to database file
        """
        self.db_path = db_path
        self.output_dir = "data/visualizations"
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)

    def plot_simulation_overview(self, scenario_id: str, save_path: Optional[str] = None) -> str:
        """
        Create comprehensive overview plot for a simulation scenario

        Args:
            scenario_id: Scenario ID to visualize
            save_path: Optional path to save figure

        Returns:
            Path to saved figure
        """
        if save_path is None:
            save_path = os.path.join(self.output_dir, f"{scenario_id}_overview.png")

        # Create figure with subplots
        fig = plt.figure(figsize=(18, 12))
        gs = GridSpec(3, 3, figure=fig, hspace=0.3, wspace=0.3)

        # Load data
        conn = self._get_connection()

        # 1. Speed Distribution (top left)
        ax1 = fig.add_subplot(gs[0, 0])
        self._plot_speed_distribution(ax1, scenario_id, conn)

        # 2. Traffic Flow Over Time (top middle)
        ax2 = fig.add_subplot(gs[0, 1])
        self._plot_traffic_flow_time(ax2, scenario_id, conn)

        # 3. Speed Accuracy (top right)
        ax3 = fig.add_subplot(gs[0, 2])
        self._plot_speed_accuracy(ax3, scenario_id, conn)

        # 4. Congestion Heatmap (middle left)
        ax4 = fig.add_subplot(gs[1, 0])
        self._plot_congestion_levels(ax4, scenario_id, conn)

        # 5. Edge Speed Comparison (middle center)
        ax5 = fig.add_subplot(gs[1, 1])
        self._plot_edge_speed_comparison(ax5, scenario_id, conn)

        # 6. Vehicle Count Over Time (middle right)
        ax6 = fig.add_subplot(gs[1, 2])
        self._plot_vehicle_count(ax6, scenario_id, conn)

        # 7. Travel Time Distribution (bottom left)
        ax7 = fig.add_subplot(gs[2, 0])
        self._plot_travel_time_distribution(ax7, scenario_id, conn)

        # 8. Calibration Progress (bottom center)
        ax8 = fig.add_subplot(gs[2, 1])
        self._plot_calibration_progress(ax8, scenario_id, conn)

        # 9. Performance Metrics (bottom right)
        ax9 = fig.add_subplot(gs[2, 2])
        self._plot_performance_metrics(ax9, scenario_id, conn)

        conn.close()

        # Add title
        fig.suptitle(f'Simulation Overview: {scenario_id}',
                    fontsize=16, fontweight='bold', y=0.995)

        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[VISUALIZER] Saved simulation overview to: {save_path}")
        return save_path

    def _plot_speed_distribution(self, ax, scenario_id: str, conn):
        """Plot speed distribution histogram"""
        try:
            query = """
                SELECT mean_speed FROM edge_states
                WHERE scenario_id = ? AND mean_speed > 0
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                # Convert m/s to km/h
                speeds_kmh = df['mean_speed'] * 3.6

                ax.hist(speeds_kmh, bins=30, color='#2196F3', alpha=0.7, edgecolor='black')
                ax.axvline(speeds_kmh.mean(), color='red', linestyle='--',
                          label=f'Mean: {speeds_kmh.mean():.1f} km/h')
                ax.axvline(speeds_kmh.median(), color='green', linestyle='--',
                          label=f'Median: {speeds_kmh.median():.1f} km/h')

                ax.set_xlabel('Speed (km/h)')
                ax.set_ylabel('Frequency')
                ax.set_title('Speed Distribution')
                ax.legend()
                ax.grid(True, alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
                ax.set_title('Speed Distribution (No Data)')
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_traffic_flow_time(self, ax, scenario_id: str, conn):
        """Plot traffic flow over time"""
        try:
            query = """
                SELECT step, AVG(vehicle_count) as avg_vehicles
                FROM edge_states
                WHERE scenario_id = ?
                GROUP BY step
                ORDER BY step
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                # Convert steps to minutes
                df['time_min'] = df['step'] / 60

                ax.plot(df['time_min'], df['avg_vehicles'],
                       color='#FF9800', linewidth=2)
                ax.fill_between(df['time_min'], 0, df['avg_vehicles'],
                               alpha=0.3, color='#FF9800')

                ax.set_xlabel('Time (minutes)')
                ax.set_ylabel('Average Vehicles per Edge')
                ax.set_title('Traffic Flow Over Time')
                ax.grid(True, alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_speed_accuracy(self, ax, scenario_id: str, conn):
        """Plot speed accuracy comparison"""
        try:
            query = """
                SELECT speed_error_pct FROM area_comparisons
                WHERE scenario_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0 and not pd.isna(df['speed_error_pct'].iloc[0]):
                error_pct = df['speed_error_pct'].iloc[0]
                accuracy = 100 - error_pct

                # Create gauge chart
                categories = ['Error', 'Accuracy']
                values = [error_pct, accuracy]
                colors = ['#F44336', '#4CAF50']

                wedges, texts, autotexts = ax.pie(values, labels=categories,
                                                   autopct='%1.1f%%',
                                                   colors=colors, startangle=90)

                for autotext in autotexts:
                    autotext.set_color('white')
                    autotext.set_fontweight('bold')
                    autotext.set_fontsize(12)

                ax.set_title(f'Speed Accuracy\n({accuracy:.1f}% accurate)')
            else:
                ax.text(0.5, 0.5, 'No comparison data', ha='center', va='center',
                       transform=ax.transAxes)
                ax.set_title('Speed Accuracy (No Data)')
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_congestion_levels(self, ax, scenario_id: str, conn):
        """Plot congestion level distribution"""
        try:
            query = """
                SELECT mean_speed FROM edge_states
                WHERE scenario_id = ? AND mean_speed > 0
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                # Categorize speeds
                speeds_kmh = df['mean_speed'] * 3.6

                def categorize_congestion(speed):
                    if speed >= 40:
                        return 'Free Flow'
                    elif speed >= 25:
                        return 'Moderate'
                    elif speed >= 15:
                        return 'Heavy'
                    else:
                        return 'Severe'

                congestion = speeds_kmh.apply(categorize_congestion)
                congestion_counts = congestion.value_counts()

                colors = {'Free Flow': '#4CAF50', 'Moderate': '#FF9800',
                         'Heavy': '#F44336', 'Severe': '#B71C1C'}

                bars = ax.bar(congestion_counts.index, congestion_counts.values,
                             color=[colors.get(x, '#777') for x in congestion_counts.index])

                ax.set_xlabel('Congestion Level')
                ax.set_ylabel('Number of Edges')
                ax.set_title('Congestion Level Distribution')
                ax.tick_params(axis='x', rotation=45)

                # Add value labels on bars
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{int(height)}',
                           ha='center', va='bottom', fontweight='bold')
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_edge_speed_comparison(self, ax, scenario_id: str, conn):
        """Plot simulated vs real speed comparison"""
        try:
            query = """
                SELECT es.mean_speed as sim_speed, rt.speed_kmh as real_speed
                FROM edge_states es
                JOIN routes r ON es.edge_id = r.route_id
                JOIN route_traffic rt ON r.route_id = rt.route_id
                WHERE es.scenario_id = ? AND es.mean_speed > 0 AND rt.speed_kmh > 0
                LIMIT 100
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                # Convert sim speed to km/h
                df['sim_speed_kmh'] = df['sim_speed'] * 3.6

                ax.scatter(df['real_speed'], df['sim_speed_kmh'],
                          alpha=0.6, s=50, c='#2196F3', edgecolors='black')

                # Add perfect prediction line
                max_val = max(df['real_speed'].max(), df['sim_speed_kmh'].max())
                ax.plot([0, max_val], [0, max_val], 'r--', label='Perfect Match', linewidth=2)

                ax.set_xlabel('Real Speed (km/h)')
                ax.set_ylabel('Simulated Speed (km/h)')
                ax.set_title('Sim vs Real Speed Comparison')
                ax.legend()
                ax.grid(True, alpha=0.3)

                # Calculate R²
                from scipy.stats import linregress
                slope, intercept, r_value, p_value, std_err = linregress(
                    df['real_speed'], df['sim_speed_kmh'])
                ax.text(0.05, 0.95, f'R² = {r_value**2:.3f}',
                       transform=ax.transAxes, fontweight='bold',
                       bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
            else:
                ax.text(0.5, 0.5, 'No comparison data', ha='center', va='center',
                       transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_vehicle_count(self, ax, scenario_id: str, conn):
        """Plot vehicle count over time"""
        try:
            query = """
                SELECT step, SUM(vehicle_count) as total_vehicles
                FROM edge_states
                WHERE scenario_id = ?
                GROUP BY step
                ORDER BY step
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                df['time_min'] = df['step'] / 60

                ax.plot(df['time_min'], df['total_vehicles'],
                       color='#9C27B0', linewidth=2, marker='o', markersize=3)

                # Add trend line
                z = np.polyfit(df['time_min'], df['total_vehicles'], 2)
                p = np.poly1d(z)
                ax.plot(df['time_min'], p(df['time_min']),
                       "r--", alpha=0.5, label='Trend')

                ax.set_xlabel('Time (minutes)')
                ax.set_ylabel('Total Vehicles in Network')
                ax.set_title('Vehicle Count Over Time')
                ax.legend()
                ax.grid(True, alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_travel_time_distribution(self, ax, scenario_id: str, conn):
        """Plot travel time distribution"""
        try:
            query = """
                SELECT travel_time_seconds FROM route_traffic
                WHERE travel_time_seconds > 0
                ORDER BY timestamp DESC
                LIMIT 1000
            """
            df = pd.read_sql_query(query, conn)

            if len(df) > 0:
                travel_times_min = df['travel_time_seconds'] / 60

                ax.hist(travel_times_min, bins=25, color='#00BCD4',
                       alpha=0.7, edgecolor='black')
                ax.axvline(travel_times_min.mean(), color='red',
                          linestyle='--', linewidth=2,
                          label=f'Mean: {travel_times_min.mean():.1f} min')

                ax.set_xlabel('Travel Time (minutes)')
                ax.set_ylabel('Frequency')
                ax.set_title('Travel Time Distribution')
                ax.legend()
                ax.grid(True, alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_calibration_progress(self, ax, scenario_id: str, conn):
        """Plot dynamic calibration progress"""
        try:
            query = """
                SELECT step, avg_speed FROM dynamic_calibrations
                WHERE scenario_id = ?
                ORDER BY step
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))

            if len(df) > 0:
                df['time_min'] = df['step'] / 60

                ax.plot(df['time_min'], df['avg_speed'],
                       color='#4CAF50', linewidth=2, marker='s', markersize=4)

                # Add moving average
                window = min(5, len(df))
                if window > 1:
                    df['ma'] = df['avg_speed'].rolling(window=window).mean()
                    ax.plot(df['time_min'], df['ma'],
                           color='red', linestyle='--', linewidth=2,
                           label=f'{window}-point MA')

                ax.set_xlabel('Time (minutes)')
                ax.set_ylabel('Average Speed (m/s)')
                ax.set_title('Dynamic Calibration Progress')
                if window > 1:
                    ax.legend()
                ax.grid(True, alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No calibration data', ha='center', va='center',
                       transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def _plot_performance_metrics(self, ax, scenario_id: str, conn):
        """Plot key performance metrics"""
        try:
            # Get various metrics
            metrics = {}

            # Speed error
            query = "SELECT speed_error_pct FROM area_comparisons WHERE scenario_id = ? ORDER BY timestamp DESC LIMIT 1"
            result = pd.read_sql_query(query, conn, params=(scenario_id,))
            if len(result) > 0 and not pd.isna(result['speed_error_pct'].iloc[0]):
                metrics['Speed\nAccuracy'] = 100 - result['speed_error_pct'].iloc[0]

            # Congestion similarity
            query = "SELECT congestion_similarity FROM area_comparisons WHERE scenario_id = ? ORDER BY timestamp DESC LIMIT 1"
            result = pd.read_sql_query(query, conn, params=(scenario_id,))
            if len(result) > 0 and not pd.isna(result['congestion_similarity'].iloc[0]):
                metrics['Congestion\nSimilarity'] = result['congestion_similarity'].iloc[0]

            # Data coverage
            query = """
                SELECT COUNT(DISTINCT edge_id) * 100.0 /
                (SELECT COUNT(DISTINCT edge_id) FROM edge_states WHERE scenario_id = ?) as coverage
                FROM edge_states WHERE scenario_id = ? AND mean_speed > 0
            """
            result = pd.read_sql_query(query, conn, params=(scenario_id, scenario_id))
            if len(result) > 0:
                metrics['Data\nCoverage'] = result['coverage'].iloc[0]

            if len(metrics) > 0:
                labels = list(metrics.keys())
                values = list(metrics.values())
                colors_list = ['#4CAF50' if v >= 70 else '#FF9800' if v >= 50 else '#F44336'
                              for v in values]

                bars = ax.barh(labels, values, color=colors_list)

                # Add value labels
                for i, (bar, val) in enumerate(zip(bars, values)):
                    ax.text(val + 2, i, f'{val:.1f}%',
                           va='center', fontweight='bold')

                ax.set_xlabel('Score (%)')
                ax.set_title('Performance Metrics')
                ax.set_xlim(0, 105)
                ax.grid(True, axis='x', alpha=0.3)
            else:
                ax.text(0.5, 0.5, 'No metrics available', ha='center', va='center',
                       transform=ax.transAxes)
        except Exception as e:
            ax.text(0.5, 0.5, f'Error: {str(e)}', ha='center', va='center', transform=ax.transAxes)

    def plot_route_estimation(self, route_data: Dict, save_path: Optional[str] = None) -> str:
        """
        Create visualization for route estimation results

        Args:
            route_data: Route estimation data dictionary
            save_path: Optional path to save figure

        Returns:
            Path to saved figure
        """
        if save_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = os.path.join(self.output_dir, f"route_estimation_{timestamp}.png")

        fig = plt.figure(figsize=(16, 10))
        gs = GridSpec(2, 3, figure=fig, hspace=0.3, wspace=0.3)

        # 1. Route Overview (top left, double width)
        ax1 = fig.add_subplot(gs[0, :2])
        self._plot_route_overview(ax1, route_data)

        # 2. Speed Profile (top right)
        ax2 = fig.add_subplot(gs[0, 2])
        self._plot_speed_profile(ax2, route_data)

        # 3. Edge Details (bottom left)
        ax3 = fig.add_subplot(gs[1, 0])
        self._plot_edge_details(ax3, route_data)

        # 4. Comparison (bottom center)
        ax4 = fig.add_subplot(gs[1, 1])
        self._plot_estimation_comparison(ax4, route_data)

        # 5. Data Coverage (bottom right)
        ax5 = fig.add_subplot(gs[1, 2])
        self._plot_data_coverage(ax5, route_data)

        origin = route_data.get('origin', {})
        dest = route_data.get('destination', {})
        title = f"Route Estimation: ({origin.get('lat', 0):.4f}, {origin.get('lon', 0):.4f}) → ({dest.get('lat', 0):.4f}, {dest.get('lon', 0):.4f})"
        fig.suptitle(title, fontsize=14, fontweight='bold', y=0.995)

        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[VISUALIZER] Saved route estimation to: {save_path}")
        return save_path

    def _plot_route_overview(self, ax, route_data: Dict):
        """Plot route overview with key metrics"""
        ax.axis('off')

        # Extract metrics
        distance_km = route_data.get('distance_km', 0)
        travel_time_min = route_data.get('travel_time_minutes', 0)
        avg_speed = route_data.get('average_speed_kmh', 0)
        num_edges = route_data.get('num_edges', 0)
        data_coverage = route_data.get('data_coverage', 0)

        # Create text summary
        summary = f"""
╔══════════════════════════════════════════════════════╗
║                  ROUTE ESTIMATION SUMMARY             ║
╠══════════════════════════════════════════════════════╣
║                                                       ║
║  📍 Distance:           {distance_km:>8.2f} km              ║
║  ⏱️  Travel Time:        {travel_time_min:>8.1f} min             ║
║  🚗 Average Speed:      {avg_speed:>8.1f} km/h            ║
║  🛣️  Number of Edges:   {num_edges:>8d}                  ║
║  📊 Data Coverage:      {data_coverage:>8.1f} %              ║
║                                                       ║
╚══════════════════════════════════════════════════════╝
"""

        # Google Maps comparison if available
        if 'google_maps' in route_data:
            gm = route_data['google_maps']
            comp = route_data.get('comparison', {})

            summary += f"""
╔══════════════════════════════════════════════════════╗
║              GOOGLE MAPS COMPARISON                   ║
╠══════════════════════════════════════════════════════╣
║                                                       ║
║  Real Travel Time:     {gm['travel_time_minutes']:>8.1f} min             ║
║  Real Speed:           {gm['speed_kmh']:>8.1f} km/h            ║
║  Time Error:           {comp.get('time_error_percent', 0):>8.1f} %              ║
║  Speed Error:          {comp.get('speed_error_percent', 0):>8.1f} %              ║
║                                                       ║
╚══════════════════════════════════════════════════════╝
"""

        ax.text(0.1, 0.5, summary, fontfamily='monospace', fontsize=11,
               verticalalignment='center', bbox=dict(boxstyle='round',
               facecolor='#E3F2FD', alpha=0.8, edgecolor='#2196F3', linewidth=2))

    def _plot_speed_profile(self, ax, route_data: Dict):
        """Plot speed profile along route"""
        edge_details = route_data.get('edge_details', [])

        if len(edge_details) > 0:
            speeds = [e['speed_kmh'] for e in edge_details]
            has_data = [e['has_sim_data'] for e in edge_details]

            colors = ['#4CAF50' if h else '#FF9800' for h in has_data]

            ax.bar(range(len(speeds)), speeds, color=colors, alpha=0.7, edgecolor='black')

            # Add average line
            avg_speed = np.mean(speeds)
            ax.axhline(avg_speed, color='red', linestyle='--', linewidth=2,
                      label=f'Average: {avg_speed:.1f} km/h')

            ax.set_xlabel('Edge Index')
            ax.set_ylabel('Speed (km/h)')
            ax.set_title('Speed Profile Along Route')
            ax.legend()
            ax.grid(True, axis='y', alpha=0.3)
        else:
            ax.text(0.5, 0.5, 'No edge data', ha='center', va='center', transform=ax.transAxes)

    def _plot_edge_details(self, ax, route_data: Dict):
        """Plot edge length distribution"""
        edge_details = route_data.get('edge_details', [])

        if len(edge_details) > 0:
            lengths = [e['length'] for e in edge_details]

            ax.hist(lengths, bins=20, color='#00BCD4', alpha=0.7, edgecolor='black')
            ax.axvline(np.mean(lengths), color='red', linestyle='--', linewidth=2,
                      label=f'Mean: {np.mean(lengths):.1f} m')

            ax.set_xlabel('Edge Length (m)')
            ax.set_ylabel('Frequency')
            ax.set_title('Edge Length Distribution')
            ax.legend()
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, 'No edge data', ha='center', va='center', transform=ax.transAxes)

    def _plot_estimation_comparison(self, ax, route_data: Dict):
        """Plot estimation vs real comparison"""
        if 'google_maps' in route_data:
            gm = route_data['google_maps']
            sim_time = route_data.get('travel_time_minutes', 0)
            real_time = gm['travel_time_minutes']

            categories = ['Simulation', 'Google Maps']
            times = [sim_time, real_time]
            colors = ['#2196F3', '#4CAF50']

            bars = ax.bar(categories, times, color=colors, alpha=0.7, edgecolor='black')

            # Add value labels
            for bar, time in zip(bars, times):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{time:.1f} min',
                       ha='center', va='bottom', fontweight='bold')

            # Add error annotation
            error_pct = route_data.get('comparison', {}).get('time_error_percent', 0)
            ax.text(0.5, 0.95, f'Error: {error_pct:.1f}%',
                   transform=ax.transAxes, ha='center',
                   fontsize=12, fontweight='bold',
                   bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.5))

            ax.set_ylabel('Travel Time (minutes)')
            ax.set_title('Estimation Comparison')
            ax.grid(True, axis='y', alpha=0.3)
        else:
            ax.text(0.5, 0.5, 'No comparison data', ha='center', va='center',
                   transform=ax.transAxes)
            ax.set_title('Estimation Comparison (No Data)')

    def _plot_data_coverage(self, ax, route_data: Dict):
        """Plot data coverage pie chart"""
        edges_with_data = route_data.get('edges_with_sim_data', 0)
        total_edges = route_data.get('num_edges', 1)
        edges_without_data = total_edges - edges_with_data

        if total_edges > 0:
            sizes = [edges_with_data, edges_without_data]
            labels = ['With Sim Data', 'Default Speed']
            colors = ['#4CAF50', '#FF9800']
            explode = (0.1, 0)

            wedges, texts, autotexts = ax.pie(sizes, explode=explode, labels=labels,
                                               autopct='%1.1f%%', colors=colors,
                                               startangle=90)

            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
                autotext.set_fontsize(11)

            ax.set_title(f'Data Coverage\n({edges_with_data}/{total_edges} edges)')
        else:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)

    def plot_comparison_timeline(self, scenario_ids: List[str], save_path: Optional[str] = None) -> str:
        """
        Create timeline comparison of multiple scenarios

        Args:
            scenario_ids: List of scenario IDs to compare
            save_path: Optional path to save figure

        Returns:
            Path to saved figure
        """
        if save_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = os.path.join(self.output_dir, f"comparison_timeline_{timestamp}.png")

        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        fig.suptitle('Multi-Scenario Comparison', fontsize=16, fontweight='bold')

        conn = self._get_connection()

        # Prepare data for all scenarios
        scenarios_data = []
        for scenario_id in scenario_ids:
            query = """
                SELECT scenario_id, speed_error_pct, congestion_similarity, timestamp
                FROM area_comparisons
                WHERE scenario_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """
            df = pd.read_sql_query(query, conn, params=(scenario_id,))
            if len(df) > 0:
                scenarios_data.append(df.iloc[0])

        conn.close()

        if len(scenarios_data) == 0:
            fig.text(0.5, 0.5, 'No comparison data available',
                    ha='center', va='center', fontsize=14)
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close()
            return save_path

        # Convert to DataFrame
        comp_df = pd.DataFrame(scenarios_data)

        # Plot 1: Speed Error Comparison
        ax = axes[0, 0]
        ax.bar(range(len(comp_df)), comp_df['speed_error_pct'],
              color='#F44336', alpha=0.7, edgecolor='black')
        ax.set_xlabel('Scenario')
        ax.set_ylabel('Speed Error (%)')
        ax.set_title('Speed Error by Scenario')
        ax.set_xticks(range(len(comp_df)))
        ax.set_xticklabels([s[:15] for s in comp_df['scenario_id']], rotation=45, ha='right')
        ax.grid(True, axis='y', alpha=0.3)

        # Plot 2: Congestion Similarity
        ax = axes[0, 1]
        ax.bar(range(len(comp_df)), comp_df['congestion_similarity'],
              color='#4CAF50', alpha=0.7, edgecolor='black')
        ax.set_xlabel('Scenario')
        ax.set_ylabel('Similarity (%)')
        ax.set_title('Congestion Similarity by Scenario')
        ax.set_xticks(range(len(comp_df)))
        ax.set_xticklabels([s[:15] for s in comp_df['scenario_id']], rotation=45, ha='right')
        ax.grid(True, axis='y', alpha=0.3)

        # Plot 3: Overall Accuracy
        ax = axes[1, 0]
        accuracy = 100 - comp_df['speed_error_pct']
        colors_list = ['#4CAF50' if a >= 70 else '#FF9800' if a >= 50 else '#F44336' for a in accuracy]
        ax.bar(range(len(comp_df)), accuracy, color=colors_list, alpha=0.7, edgecolor='black')
        ax.set_xlabel('Scenario')
        ax.set_ylabel('Accuracy (%)')
        ax.set_title('Overall Speed Accuracy')
        ax.set_xticks(range(len(comp_df)))
        ax.set_xticklabels([s[:15] for s in comp_df['scenario_id']], rotation=45, ha='right')
        ax.axhline(70, color='green', linestyle='--', alpha=0.5, label='Good (70%)')
        ax.axhline(50, color='orange', linestyle='--', alpha=0.5, label='Fair (50%)')
        ax.legend()
        ax.grid(True, axis='y', alpha=0.3)

        # Plot 4: Summary Table
        ax = axes[1, 1]
        ax.axis('off')

        # Create summary stats
        summary = f"""
╔══════════════════════════════════════════╗
║         COMPARISON SUMMARY               ║
╠══════════════════════════════════════════╣
║                                          ║
║  Total Scenarios:  {len(comp_df):>4d}                  ║
║                                          ║
║  Best Speed Accuracy:                    ║
║    {comp_df.loc[comp_df['speed_error_pct'].idxmin(), 'scenario_id'][:30]:30s}  ║
║    Error: {comp_df['speed_error_pct'].min():>5.1f}%                      ║
║                                          ║
║  Best Congestion Match:                  ║
║    {comp_df.loc[comp_df['congestion_similarity'].idxmax(), 'scenario_id'][:30]:30s}  ║
║    Similarity: {comp_df['congestion_similarity'].max():>5.1f}%               ║
║                                          ║
║  Average Metrics:                        ║
║    Speed Error:     {comp_df['speed_error_pct'].mean():>6.1f}%            ║
║    Similarity:      {comp_df['congestion_similarity'].mean():>6.1f}%            ║
║                                          ║
╚══════════════════════════════════════════╝
"""

        ax.text(0.1, 0.5, summary, fontfamily='monospace', fontsize=10,
               verticalalignment='center', bbox=dict(boxstyle='round',
               facecolor='#E8F5E9', alpha=0.8, edgecolor='#4CAF50', linewidth=2))

        plt.tight_layout()
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.close()

        print(f"[VISUALIZER] Saved comparison timeline to: {save_path}")
        return save_path


if __name__ == "__main__":
    # Test visualization
    visualizer = AdvancedVisualizer()

    # Test with a scenario
    conn = visualizer._get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT scenario_id FROM area_comparisons LIMIT 1")
    result = cursor.fetchone()

    if result:
        scenario_id = result[0]
        print(f"Testing with scenario: {scenario_id}")
        visualizer.plot_simulation_overview(scenario_id)
    else:
        print("No scenarios found in database")

    conn.close()
