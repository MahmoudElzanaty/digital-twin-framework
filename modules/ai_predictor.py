"""
AI Traffic Predictor
Uses machine learning to predict traffic conditions
Combines historical patterns with current conditions
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from modules.database import get_db

class SimpleTrafficPredictor:
    """
    Simple but effective traffic predictor using statistical methods
    Good baseline before implementing deep learning
    """
    
    def __init__(self, db=None):
        self.db = db or get_db()
        self.historical_patterns = {}
        self.trained = False
    
    def extract_time_features(self, timestamp: str) -> Dict:
        """Extract time-based features from timestamp"""
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        return {
            'hour': dt.hour,
            'day_of_week': dt.weekday(),  # 0=Monday, 6=Sunday
            'is_weekend': 1 if dt.weekday() >= 5 else 0,
            'is_peak_morning': 1 if 7 <= dt.hour <= 9 else 0,
            'is_peak_evening': 1 if 17 <= dt.hour <= 19 else 0,
            'is_working_hours': 1 if 8 <= dt.hour <= 18 else 0
        }
    
    def train_from_historical_data(self, min_samples: int = 10):
        """
        Train predictor using historical real-world data
        Builds patterns for each route by time of day
        """
        print("[AI_PREDICTOR] Training on historical data...")
        
        routes = self.db.get_probe_routes(active_only=True)
        
        for route in routes:
            route_id = route['route_id']
            data = self.db.get_real_traffic_data(route_id=route_id)
            
            if len(data) < min_samples:
                print(f"[AI_PREDICTOR] Insufficient data for {route['name']} ({len(data)} samples)")
                continue
            
            # Group by hour of day
            hourly_patterns = {}
            
            for record in data:
                features = self.extract_time_features(record['timestamp'])
                hour = features['hour']
                
                if hour not in hourly_patterns:
                    hourly_patterns[hour] = []
                
                hourly_patterns[hour].append({
                    'travel_time': record['travel_time_seconds'],
                    'speed': record['speed_kmh'],
                    'is_weekend': features['is_weekend']
                })
            
            # Calculate statistics for each hour
            self.historical_patterns[route_id] = {}
            
            for hour, records in hourly_patterns.items():
                travel_times = [r['travel_time'] for r in records]
                speeds = [r['speed'] for r in records if r['speed']]
                
                self.historical_patterns[route_id][hour] = {
                    'avg_travel_time': np.mean(travel_times),
                    'std_travel_time': np.std(travel_times) if len(travel_times) > 1 else 0,
                    'avg_speed': np.mean(speeds) if speeds else 0,
                    'sample_count': len(records)
                }
            
            print(f"[AI_PREDICTOR] Trained on {route['name']}: {len(hourly_patterns)} hourly patterns")
        
        self.trained = True
        print(f"[AI_PREDICTOR] Training complete for {len(self.historical_patterns)} routes")
    
    def predict_travel_time(
        self,
        route_id: str,
        prediction_time: datetime = None
    ) -> Optional[Dict]:
        """
        Predict travel time for a route at a specific time
        Returns prediction with confidence interval
        """
        if not self.trained:
            print("[AI_PREDICTOR] Model not trained! Call train_from_historical_data() first")
            return None
        
        if prediction_time is None:
            prediction_time = datetime.now()
        
        if route_id not in self.historical_patterns:
            print(f"[AI_PREDICTOR] No pattern data for route {route_id}")
            return None
        
        # Get pattern for this hour
        hour = prediction_time.hour
        route_patterns = self.historical_patterns[route_id]
        
        # Exact match
        if hour in route_patterns:
            pattern = route_patterns[hour]
        # Fallback to nearest hour
        elif len(route_patterns) > 0:
            nearest_hour = min(route_patterns.keys(), key=lambda h: abs(h - hour))
            pattern = route_patterns[nearest_hour]
            print(f"[AI_PREDICTOR] Using pattern from hour {nearest_hour} (requested: {hour})")
        else:
            return None
        
        # Calculate confidence interval (95%)
        margin = 1.96 * pattern['std_travel_time']
        
        return {
            'route_id': route_id,
            'prediction_time': prediction_time.isoformat(),
            'predicted_travel_time': pattern['avg_travel_time'],
            'confidence_lower': pattern['avg_travel_time'] - margin,
            'confidence_upper': pattern['avg_travel_time'] + margin,
            'predicted_speed': pattern['avg_speed'],
            'confidence_level': 0.95,
            'based_on_samples': pattern['sample_count']
        }
    
    def predict_all_routes(self, prediction_time: datetime = None) -> Dict[str, Dict]:
        """Predict travel times for all routes"""
        predictions = {}
        
        for route_id in self.historical_patterns.keys():
            pred = self.predict_travel_time(route_id, prediction_time)
            if pred:
                predictions[route_id] = pred
        
        return predictions
    
    def validate_predictions(self, test_period_hours: int = 24) -> Dict:
        """
        Validate predictor accuracy using recent data
        Simulates: predict → wait → compare with actual
        """
        print(f"\n[AI_PREDICTOR] Validating predictions over last {test_period_hours} hours...")
        
        results = []
        routes = self.db.get_probe_routes(active_only=True)
        
        # Get recent data for validation
        cutoff_time = datetime.now() - timedelta(hours=test_period_hours)
        
        for route in routes:
            route_id = route['route_id']
            recent_data = self.db.get_real_traffic_data(
                route_id=route_id,
                start_time=cutoff_time.isoformat()
            )
            
            if len(recent_data) < 2:
                continue
            
            # Use first half for "prediction", second half for "actual"
            split = len(recent_data) // 2
            
            for actual_record in recent_data[split:]:
                pred_time = datetime.fromisoformat(actual_record['timestamp'].replace('Z', '+00:00'))
                
                prediction = self.predict_travel_time(route_id, pred_time)
                
                if prediction:
                    actual_tt = actual_record['travel_time_seconds']
                    predicted_tt = prediction['predicted_travel_time']
                    error = abs(actual_tt - predicted_tt)
                    error_pct = (error / actual_tt * 100) if actual_tt > 0 else 0
                    
                    results.append({
                        'route_id': route_id,
                        'route_name': route['name'],
                        'predicted': predicted_tt,
                        'actual': actual_tt,
                        'error_seconds': error,
                        'error_percent': error_pct
                    })
        
        if not results:
            print("[AI_PREDICTOR] Not enough data for validation")
            return {}
        
        # Calculate aggregate metrics
        errors = [r['error_seconds'] for r in results]
        error_pcts = [r['error_percent'] for r in results]
        
        metrics = {
            'num_predictions': len(results),
            'mae_seconds': np.mean(errors),
            'rmse_seconds': np.sqrt(np.mean([e**2 for e in errors])),
            'mape_percent': np.mean(error_pcts),
            'max_error_seconds': np.max(errors),
            'predictions': results
        }
        
        # Print report
        print("\n" + "="*70)
        print("PREDICTION VALIDATION RESULTS")
        print("="*70)
        print(f"Number of predictions tested: {metrics['num_predictions']}")
        print(f"Mean Absolute Error (MAE):    {metrics['mae_seconds']:.1f} seconds ({metrics['mae_seconds']/60:.1f} min)")
        print(f"Root Mean Squared Error:      {metrics['rmse_seconds']:.1f} seconds")
        print(f"Mean Abs Percentage Error:    {metrics['mape_percent']:.2f}%")
        print(f"Maximum error:                {metrics['max_error_seconds']:.1f} seconds")
        print()
        
        if metrics['mape_percent'] < 15:
            print("✅ Excellent prediction accuracy (<15%)")
        elif metrics['mape_percent'] < 25:
            print("✓ Good prediction accuracy (15-25%)")
        else:
            print("⚠ Moderate prediction accuracy (>25%) - need more training data")
        
        print("="*70)
        
        return metrics
    
    def compare_with_simulation(self, scenario_id: str) -> Dict:
        """
        Compare ML predictions with simulation results
        Shows: Real → ML Prediction → Simulation
        Three-way comparison
        """
        print("\n" + "="*70)
        print("THREE-WAY COMPARISON: Real vs ML vs Simulation")
        print("="*70)
        
        routes = self.db.get_probe_routes(active_only=True)
        comparisons = []
        
        for route in routes:
            route_id = route['route_id']
            
            # Get real data (most recent)
            real_data = self.db.get_real_traffic_data(route_id=route_id, limit=1)
            if not real_data:
                continue
            
            # Get ML prediction
            pred_time = datetime.now()
            ml_pred = self.predict_travel_time(route_id, pred_time)
            
            # Get simulation result
            sim_data = self.db.get_simulation_results(scenario_id, route_id)
            
            if ml_pred and sim_data:
                real_tt = real_data[0]['travel_time_seconds']
                ml_tt = ml_pred['predicted_travel_time']
                sim_tt = sim_data[0]['travel_time_seconds']
                
                comparisons.append({
                    'route': route['name'],
                    'real': real_tt,
                    'ml_predicted': ml_tt,
                    'simulated': sim_tt,
                    'ml_error': abs(real_tt - ml_tt) / real_tt * 100,
                    'sim_error': abs(real_tt - sim_tt) / real_tt * 100
                })
        
        # Print comparison
        if comparisons:
            print(f"\n{'Route':<30} {'Real':<12} {'ML Pred':<12} {'Simulated':<12}")
            print("-"*70)
            for c in comparisons:
                print(f"{c['route'][:29]:<30} {c['real']/60:>10.1f}m {c['ml_predicted']/60:>10.1f}m {c['simulated']/60:>10.1f}m")
            
            avg_ml_error = np.mean([c['ml_error'] for c in comparisons])
            avg_sim_error = np.mean([c['sim_error'] for c in comparisons])
            
            print()
            print(f"Average ML prediction error:    {avg_ml_error:.2f}%")
            print(f"Average simulation error:       {avg_sim_error:.2f}%")
            print()
            
            if avg_ml_error < avg_sim_error:
                print("🎯 ML predictions are more accurate than simulation!")
            else:
                print("🎯 Simulation is more accurate than ML predictions")
        
        print("="*70)
        
        return {'comparisons': comparisons}


class AdaptivePredictor:
    """
    Adaptive predictor that combines simulation and ML
    Uses simulation physics + ML learned patterns
    """
    
    def __init__(self, db=None):
        self.db = db or get_db()
        self.ml_predictor = SimpleTrafficPredictor(db)
        self.ml_weight = 0.5  # Balance between ML and simulation
    
    def train(self):
        """Train the ML component"""
        self.ml_predictor.train_from_historical_data()
    
    def hybrid_prediction(
        self,
        route_id: str,
        simulation_result: float,
        prediction_time: datetime = None
    ) -> Dict:
        """
        Combine simulation and ML prediction
        Weighted average gives more robust prediction
        """
        ml_pred = self.ml_predictor.predict_travel_time(route_id, prediction_time)
        
        if ml_pred is None:
            # Fall back to simulation only
            return {
                'predicted_travel_time': simulation_result,
                'method': 'simulation_only',
                'confidence': 'medium'
            }
        
        # Weighted combination
        ml_tt = ml_pred['predicted_travel_time']
        hybrid_tt = self.ml_weight * ml_tt + (1 - self.ml_weight) * simulation_result
        
        return {
            'predicted_travel_time': hybrid_tt,
            'ml_component': ml_tt,
            'simulation_component': simulation_result,
            'ml_weight': self.ml_weight,
            'method': 'hybrid',
            'confidence': 'high'
        }