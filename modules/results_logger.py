"""
Advanced Results Logger for Digital Twin Framework
Provides comprehensive logging for simulations and route estimations
"""
import os
import json
import csv
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import sqlite3


class ResultsLogger:
    """Advanced logging system for simulation and estimation results"""

    def __init__(self, output_dir: str = "data/results_logs"):
        """
        Initialize results logger

        Args:
            output_dir: Directory to save log files
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Set up Python logging
        self.logger = logging.getLogger("DigitalTwinResults")
        self.logger.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # File handler for detailed logs
        log_file = os.path.join(output_dir, f"detailed_log_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Console handler for important messages
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        self.logger.info("="*80)
        self.logger.info("Results Logger Initialized")
        self.logger.info("="*80)

    def log_simulation_start(self, scenario_id: str, config: Dict[str, Any]):
        """
        Log simulation start with configuration

        Args:
            scenario_id: Unique simulation scenario ID
            config: Simulation configuration dictionary
        """
        self.logger.info("="*80)
        self.logger.info(f"SIMULATION START: {scenario_id}")
        self.logger.info("="*80)

        self.logger.info("Configuration:")
        for key, value in config.items():
            self.logger.info(f"  {key}: {value}")

        # Save configuration to JSON
        config_file = os.path.join(self.output_dir, f"{scenario_id}_config.json")
        with open(config_file, 'w') as f:
            json.dump({
                'scenario_id': scenario_id,
                'timestamp': datetime.now().isoformat(),
                'config': config
            }, f, indent=2)

        self.logger.debug(f"Configuration saved to: {config_file}")

    def log_simulation_progress(self, scenario_id: str, step: int, metrics: Dict[str, float]):
        """
        Log simulation progress metrics

        Args:
            scenario_id: Scenario ID
            step: Current simulation step
            metrics: Dictionary of metrics (avg_speed, vehicle_count, etc.)
        """
        metrics_str = " | ".join([f"{k}={v:.2f}" for k, v in metrics.items()])
        self.logger.debug(f"[{scenario_id}] Step {step:>6d} | {metrics_str}")

        # Append to CSV
        csv_file = os.path.join(self.output_dir, f"{scenario_id}_progress.csv")
        file_exists = os.path.exists(csv_file)

        with open(csv_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['step', 'timestamp'] + list(metrics.keys()))

            if not file_exists:
                writer.writeheader()

            row = {'step': step, 'timestamp': datetime.now().isoformat()}
            row.update(metrics)
            writer.writerow(row)

    def log_simulation_complete(self, scenario_id: str, results: Dict[str, Any]):
        """
        Log simulation completion with final results

        Args:
            scenario_id: Scenario ID
            results: Final results dictionary
        """
        self.logger.info("="*80)
        self.logger.info(f"SIMULATION COMPLETE: {scenario_id}")
        self.logger.info("="*80)

        # Log key results
        if 'comparison' in results:
            comp = results['comparison']
            self.logger.info("Digital Twin Comparison Results:")
            self.logger.info(f"  Speed Error:        {comp.get('speed_error_pct', 0):.2f}%")
            self.logger.info(f"  Speed Accuracy:     {100 - comp.get('speed_error_pct', 0):.2f}%")
            self.logger.info(f"  Congestion Match:   {comp.get('congestion_similarity', 0):.2f}%")

        if 'calibration' in results:
            cal = results['calibration']
            self.logger.info("Dynamic Calibration Results:")
            self.logger.info(f"  Initial Avg Speed:  {cal.get('initial_speed', 0):.2f} m/s")
            self.logger.info(f"  Final Avg Speed:    {cal.get('final_speed', 0):.2f} m/s")
            self.logger.info(f"  Improvement:        {cal.get('improvement_pct', 0):.2f}%")
            self.logger.info(f"  Updates Applied:    {cal.get('num_updates', 0)}")

        if 'statistics' in results:
            stats = results['statistics']
            self.logger.info("Traffic Statistics:")
            for key, value in stats.items():
                if isinstance(value, float):
                    self.logger.info(f"  {key:<20s}: {value:.2f}")
                else:
                    self.logger.info(f"  {key:<20s}: {value}")

        # Save complete results to JSON
        results_file = os.path.join(self.output_dir, f"{scenario_id}_results.json")
        with open(results_file, 'w') as f:
            json.dump({
                'scenario_id': scenario_id,
                'completion_time': datetime.now().isoformat(),
                'results': results
            }, f, indent=2)

        self.logger.info(f"Results saved to: {results_file}")
        self.logger.info("="*80)

    def log_route_estimation(self, route_data: Dict[str, Any]):
        """
        Log route estimation results

        Args:
            route_data: Route estimation data dictionary
        """
        origin = route_data.get('origin', {})
        dest = route_data.get('destination', {})

        self.logger.info("="*80)
        self.logger.info("ROUTE ESTIMATION")
        self.logger.info("="*80)
        self.logger.info(f"Origin:      ({origin.get('lat', 0):.6f}, {origin.get('lon', 0):.6f})")
        self.logger.info(f"Destination: ({dest.get('lat', 0):.6f}, {dest.get('lon', 0):.6f})")
        self.logger.info("-"*80)

        # Simulation results
        self.logger.info("Simulation Estimation:")
        self.logger.info(f"  Distance:           {route_data.get('distance_km', 0):.2f} km")
        self.logger.info(f"  Travel Time:        {route_data.get('travel_time_minutes', 0):.1f} min")
        self.logger.info(f"  Average Speed:      {route_data.get('average_speed_kmh', 0):.1f} km/h")
        self.logger.info(f"  Number of Edges:    {route_data.get('num_edges', 0)}")
        self.logger.info(f"  Data Coverage:      {route_data.get('data_coverage', 0):.1f}%")

        # Google Maps comparison if available
        if 'google_maps' in route_data:
            gm = route_data['google_maps']
            comp = route_data.get('comparison', {})

            self.logger.info("-"*80)
            self.logger.info("Google Maps Validation:")
            self.logger.info(f"  Real Travel Time:   {gm['travel_time_minutes']:.1f} min")
            self.logger.info(f"  Real Speed:         {gm['speed_kmh']:.1f} km/h")
            self.logger.info(f"  Traffic Delay:      {gm.get('traffic_delay_seconds', 0)/60:.1f} min")

            self.logger.info("-"*80)
            self.logger.info("Accuracy Metrics:")
            self.logger.info(f"  Time Error:         {comp.get('time_error_percent', 0):.1f}%")
            self.logger.info(f"  Speed Error:        {comp.get('speed_error_percent', 0):.1f}%")
            self.logger.info(f"  Distance Error:     {comp.get('distance_error_meters', 0):.0f} m")

            # Accuracy assessment
            time_error = comp.get('time_error_percent', 100)
            if time_error < 10:
                assessment = "EXCELLENT"
                symbol = "✅"
            elif time_error < 20:
                assessment = "GOOD"
                symbol = "👍"
            elif time_error < 30:
                assessment = "FAIR"
                symbol = "⚠️"
            else:
                assessment = "NEEDS IMPROVEMENT"
                symbol = "❌"

            self.logger.info("-"*80)
            self.logger.info(f"Overall Assessment: {symbol} {assessment}")

        # Edge details
        edge_details = route_data.get('edge_details', [])
        if len(edge_details) > 0:
            self.logger.debug(f"Route consists of {len(edge_details)} edges:")
            for i, edge in enumerate(edge_details[:10]):  # Show first 10
                self.logger.debug(
                    f"  Edge {i+1}: {edge['edge_id']:<20s} | "
                    f"Length: {edge['length']:>6.0f}m | "
                    f"Speed: {edge['speed_kmh']:>5.1f} km/h | "
                    f"Data: {'✓' if edge['has_sim_data'] else '✗'}"
                )
            if len(edge_details) > 10:
                self.logger.debug(f"  ... and {len(edge_details) - 10} more edges")

        self.logger.info("="*80)

        # Save to JSON
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        route_file = os.path.join(self.output_dir, f"route_estimation_{timestamp}.json")
        with open(route_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'route_data': route_data
            }, f, indent=2)

        self.logger.debug(f"Route estimation saved to: {route_file}")

    def log_comparison(self, comparison_data: Dict[str, Any]):
        """
        Log area-based comparison results

        Args:
            comparison_data: Comparison results dictionary
        """
        scenario_id = comparison_data.get('scenario_id', 'unknown')

        self.logger.info("="*80)
        self.logger.info(f"DIGITAL TWIN COMPARISON: {scenario_id}")
        self.logger.info("="*80)

        comp = comparison_data.get('comparison', {})

        self.logger.info("Real-World Data:")
        real = comparison_data.get('real_world', {})
        self.logger.info(f"  Average Speed:      {real.get('avg_speed_kmh', 0):.2f} km/h")
        self.logger.info(f"  Congestion Level:   {real.get('congestion_level', 'Unknown')}")
        self.logger.info(f"  Data Points:        {real.get('num_samples', 0)}")

        self.logger.info("-"*80)
        self.logger.info("Simulation Data:")
        sim = comparison_data.get('simulation', {})
        self.logger.info(f"  Average Speed:      {sim.get('avg_speed_kmh', 0):.2f} km/h")
        self.logger.info(f"  Congestion Level:   {sim.get('congestion_level', 'Unknown')}")
        self.logger.info(f"  Data Points:        {sim.get('num_samples', 0)}")

        self.logger.info("-"*80)
        self.logger.info("Comparison Metrics:")
        self.logger.info(f"  Speed Error:        {comp.get('speed_error_pct', 0):.2f}%")
        self.logger.info(f"  Speed Accuracy:     {100 - comp.get('speed_error_pct', 0):.2f}%")
        self.logger.info(f"  Congestion Match:   {comp.get('congestion_similarity', 0):.2f}%")
        self.logger.info(f"  RMSE:               {comp.get('rmse', 0):.2f}")

        # Quality assessment
        speed_error = comp.get('speed_error_pct', 100)
        if speed_error < 10:
            quality = "EXCELLENT - Simulation closely matches reality"
            symbol = "✅"
        elif speed_error < 20:
            quality = "GOOD - Simulation is reliable for most use cases"
            symbol = "👍"
        elif speed_error < 30:
            quality = "FAIR - Simulation needs calibration improvement"
            symbol = "⚠️"
        else:
            quality = "POOR - Simulation requires significant calibration"
            symbol = "❌"

        self.logger.info("-"*80)
        self.logger.info(f"Quality: {symbol} {quality}")
        self.logger.info("="*80)

        # Save to JSON
        comparison_file = os.path.join(self.output_dir, f"{scenario_id}_comparison.json")
        with open(comparison_file, 'w') as f:
            json.dump({
                'scenario_id': scenario_id,
                'timestamp': datetime.now().isoformat(),
                'comparison': comparison_data
            }, f, indent=2)

        self.logger.debug(f"Comparison saved to: {comparison_file}")

    def log_calibration_update(self, scenario_id: str, step: int, parameters: Dict[str, float]):
        """
        Log dynamic calibration parameter updates

        Args:
            scenario_id: Scenario ID
            step: Simulation step
            parameters: Updated parameters dictionary
        """
        params_str = " | ".join([f"{k}={v:.3f}" for k, v in parameters.items()])
        self.logger.info(f"[CALIBRATION] [{scenario_id}] Step {step} | Updated: {params_str}")

        # Append to CSV
        csv_file = os.path.join(self.output_dir, f"{scenario_id}_calibration.csv")
        file_exists = os.path.exists(csv_file)

        with open(csv_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['step', 'timestamp'] + list(parameters.keys()))

            if not file_exists:
                writer.writeheader()

            row = {'step': step, 'timestamp': datetime.now().isoformat()}
            row.update(parameters)
            writer.writerow(row)

    def log_error(self, context: str, error: Exception):
        """
        Log error with context

        Args:
            context: Description of what was being attempted
            error: Exception that occurred
        """
        self.logger.error("="*80)
        self.logger.error(f"ERROR: {context}")
        self.logger.error(f"Exception Type: {type(error).__name__}")
        self.logger.error(f"Exception Message: {str(error)}")
        self.logger.error("="*80)

        import traceback
        self.logger.debug("Traceback:")
        self.logger.debug(traceback.format_exc())

    def generate_summary_report(self, scenario_ids: List[str]) -> str:
        """
        Generate a summary report for multiple scenarios

        Args:
            scenario_ids: List of scenario IDs to include

        Returns:
            Path to generated report file
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(self.output_dir, f"summary_report_{timestamp}.txt")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*100 + "\n")
            f.write(" "*30 + "DIGITAL TWIN SUMMARY REPORT\n")
            f.write("="*100 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Scenarios: {len(scenario_ids)}\n")
            f.write("="*100 + "\n\n")

            for i, scenario_id in enumerate(scenario_ids, 1):
                f.write(f"\n{'─'*100}\n")
                f.write(f"SCENARIO {i}: {scenario_id}\n")
                f.write(f"{'─'*100}\n\n")

                # Load results
                results_file = os.path.join(self.output_dir, f"{scenario_id}_results.json")
                if os.path.exists(results_file):
                    with open(results_file, 'r') as rf:
                        data = json.load(rf)
                        results = data.get('results', {})

                        # Comparison results
                        if 'comparison' in results:
                            comp = results['comparison']
                            f.write("Digital Twin Comparison:\n")
                            f.write(f"  • Speed Error:        {comp.get('speed_error_pct', 0):>6.2f}%\n")
                            f.write(f"  • Speed Accuracy:     {100 - comp.get('speed_error_pct', 0):>6.2f}%\n")
                            f.write(f"  • Congestion Match:   {comp.get('congestion_similarity', 0):>6.2f}%\n\n")

                        # Calibration results
                        if 'calibration' in results:
                            cal = results['calibration']
                            f.write("Dynamic Calibration:\n")
                            f.write(f"  • Initial Speed:      {cal.get('initial_speed', 0):>6.2f} m/s\n")
                            f.write(f"  • Final Speed:        {cal.get('final_speed', 0):>6.2f} m/s\n")
                            f.write(f"  • Improvement:        {cal.get('improvement_pct', 0):>6.2f}%\n")
                            f.write(f"  • Updates Applied:    {cal.get('num_updates', 0):>6d}\n\n")

                        # Statistics
                        if 'statistics' in results:
                            stats = results['statistics']
                            f.write("Traffic Statistics:\n")
                            for key, value in stats.items():
                                if isinstance(value, float):
                                    f.write(f"  • {key:<20s}: {value:>8.2f}\n")
                                else:
                                    f.write(f"  • {key:<20s}: {value:>8}\n")
                            f.write("\n")
                else:
                    f.write("  (No results file found)\n\n")

            # Overall summary
            f.write("\n" + "="*100 + "\n")
            f.write(" "*35 + "OVERALL SUMMARY\n")
            f.write("="*100 + "\n\n")

            # Calculate aggregate statistics
            all_speed_errors = []
            all_similarities = []

            for scenario_id in scenario_ids:
                results_file = os.path.join(self.output_dir, f"{scenario_id}_results.json")
                if os.path.exists(results_file):
                    with open(results_file, 'r') as rf:
                        data = json.load(rf)
                        results = data.get('results', {})
                        if 'comparison' in results:
                            comp = results['comparison']
                            all_speed_errors.append(comp.get('speed_error_pct', 0))
                            all_similarities.append(comp.get('congestion_similarity', 0))

            if len(all_speed_errors) > 0:
                f.write(f"Average Speed Error:        {sum(all_speed_errors)/len(all_speed_errors):>6.2f}%\n")
                f.write(f"Average Speed Accuracy:     {100 - sum(all_speed_errors)/len(all_speed_errors):>6.2f}%\n")
                f.write(f"Best Speed Accuracy:        {100 - min(all_speed_errors):>6.2f}%\n")
                f.write(f"Worst Speed Accuracy:       {100 - max(all_speed_errors):>6.2f}%\n\n")

            if len(all_similarities) > 0:
                f.write(f"Average Congestion Match:   {sum(all_similarities)/len(all_similarities):>6.2f}%\n")
                f.write(f"Best Congestion Match:      {max(all_similarities):>6.2f}%\n")
                f.write(f"Worst Congestion Match:     {min(all_similarities):>6.2f}%\n\n")

            f.write("="*100 + "\n")
            f.write(" "*25 + "END OF REPORT\n")
            f.write("="*100 + "\n")

        self.logger.info(f"Summary report generated: {report_file}")
        return report_file

    def export_to_csv(self, scenario_id: str) -> str:
        """
        Export all scenario data to CSV format

        Args:
            scenario_id: Scenario ID to export

        Returns:
            Path to exported CSV file
        """
        csv_file = os.path.join(self.output_dir, f"{scenario_id}_export.csv")

        # Load all data
        results_file = os.path.join(self.output_dir, f"{scenario_id}_results.json")
        if not os.path.exists(results_file):
            self.logger.warning(f"No results file found for {scenario_id}")
            return ""

        with open(results_file, 'r') as f:
            data = json.load(f)

        # Flatten data and export to CSV
        rows = []

        results = data.get('results', {})

        # Add comparison data
        if 'comparison' in results:
            comp = results['comparison']
            rows.append({
                'metric': 'speed_error_pct',
                'value': comp.get('speed_error_pct', 0),
                'category': 'comparison'
            })
            rows.append({
                'metric': 'congestion_similarity',
                'value': comp.get('congestion_similarity', 0),
                'category': 'comparison'
            })

        # Add calibration data
        if 'calibration' in results:
            cal = results['calibration']
            for key, value in cal.items():
                rows.append({
                    'metric': key,
                    'value': value,
                    'category': 'calibration'
                })

        # Add statistics
        if 'statistics' in results:
            stats = results['statistics']
            for key, value in stats.items():
                rows.append({
                    'metric': key,
                    'value': value,
                    'category': 'statistics'
                })

        # Write to CSV
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['category', 'metric', 'value'])
            writer.writeheader()
            writer.writerows(rows)

        self.logger.info(f"Exported data to: {csv_file}")
        return csv_file


# Global logger instance
_global_logger = None


def get_results_logger() -> ResultsLogger:
    """Get or create global results logger instance"""
    global _global_logger
    if _global_logger is None:
        _global_logger = ResultsLogger()
    return _global_logger


if __name__ == "__main__":
    # Test the logger
    logger = ResultsLogger()

    # Test simulation logging
    logger.log_simulation_start("test_scenario_001", {
        'network': 'cairo_downtown.net.xml',
        'duration': 3600,
        'vehicles': 1000,
        'calibration': True
    })

    logger.log_simulation_progress("test_scenario_001", 100, {
        'avg_speed': 12.5,
        'vehicle_count': 45,
        'congestion': 0.35
    })

    logger.log_simulation_complete("test_scenario_001", {
        'comparison': {
            'speed_error_pct': 15.2,
            'congestion_similarity': 78.5
        },
        'calibration': {
            'initial_speed': 10.5,
            'final_speed': 12.8,
            'improvement_pct': 21.9,
            'num_updates': 12
        },
        'statistics': {
            'total_distance': 125000.5,
            'total_time': 95400,
            'avg_speed': 12.3
        }
    })

    print("\n✅ Logger test complete!")
