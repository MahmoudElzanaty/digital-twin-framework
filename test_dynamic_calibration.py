"""
Test Dynamic Calibration Integration
Quick test to verify dynamic calibrator is properly integrated
"""
import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')

from modules.dynamic_calibrator import DynamicCalibrator

def test_dynamic_calibrator_initialization():
    """Test that dynamic calibrator can be initialized"""
    print("=" * 60)
    print("TESTING DYNAMIC CALIBRATION INTEGRATION")
    print("=" * 60)
    print()

    try:
        print("1. Testing DynamicCalibrator initialization...")
        calibrator = DynamicCalibrator(
            update_interval=300,
            learning_rate=0.1,
            window_size=10
        )
        print("   [OK] DynamicCalibrator initialized successfully")
        print()

        print("2. Testing parameter bounds...")
        for param, bounds in calibrator.param_bounds.items():
            print(f"   {param}: {bounds[0]} - {bounds[1]}")
        print("   [OK] Parameter bounds configured")
        print()

        print("3. Testing initial parameters...")
        for param, value in calibrator.current_params.items():
            print(f"   {param}: {value}")
        print("   [OK] Initial parameters set")
        print()

        print("4. Testing gradient computation...")
        # Simulate some error history
        calibrator.error_history.append(25.0)
        calibrator.error_history.append(23.0)
        calibrator.last_sim_speed = 45.0
        calibrator.last_real_speed = 50.0

        gradients = calibrator.compute_parameter_gradients(23.0)
        print(f"   Computed gradients for {len(gradients)} parameters")
        print("   [OK] Gradient computation works")
        print()

        print("5. Testing parameter update...")
        new_params = calibrator.update_parameters(gradients)
        print(f"   Updated {len(new_params)} parameters")
        for param, value in new_params.items():
            old_value = calibrator.current_params[param]
            if abs(value - old_value) > 0.001:
                print(f"   {param}: {old_value:.3f} -> {value:.3f}")
        print("   [OK] Parameter updates work")
        print()

        print("=" * 60)
        print("[SUCCESS] ALL TESTS PASSED")
        print("=" * 60)
        print()
        print("Dynamic Calibration is ready to use!")
        print()
        print("When you run a simulation in the GUI:")
        print("  • Dynamic calibration will automatically start")
        print("  • Parameters adjust every 300 simulation steps (5 min)")
        print("  • Watch the console for calibration updates")
        print("  • Final report shows improvement statistics")
        print()

        return True

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_dynamic_calibrator_initialization()
    sys.exit(0 if success else 1)
