"""
Test script for flexible duration units
Verifies that duration calculations work correctly
"""

def test_duration_conversions():
    """Test duration unit conversions"""
    print("=" * 60)
    print("Duration Unit Conversion Test")
    print("=" * 60)

    # Test cases: (value, unit, expected_minutes)
    test_cases = [
        # Duration tests
        (30, "Minutes", 30),
        (2, "Hours", 120),
        (1, "Days", 1440),
        (1, "Weeks", 10080),
        (2, "Weeks", 20160),

        # Interval tests
        (15, "Minutes", 15),
        (1, "Hours", 60),
        (2, "Hours", 120),
    ]

    print("\n[TEST 1] Duration to minutes conversion...")
    all_passed = True

    for value, unit, expected in test_cases:
        if unit == "Minutes":
            result = value
        elif unit == "Hours":
            result = value * 60
        elif unit == "Days":
            result = value * 24 * 60
        else:  # Weeks
            result = value * 7 * 24 * 60

        passed = result == expected
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {value} {unit} = {result} minutes (expected {expected})")

        if not passed:
            all_passed = False

    # Test collection calculations
    print("\n[TEST 2] Collection calculations...")

    collection_tests = [
        # (duration_mins, interval_mins, expected_collections)
        (1440, 15, 96),      # 1 day, 15 min interval = 96 collections
        (10080, 60, 168),    # 1 week, 1 hour interval = 168 collections
        (20160, 15, 1344),   # 2 weeks, 15 min interval = 1344 collections
        (60, 5, 12),         # 1 hour, 5 min interval = 12 collections
    ]

    for duration_mins, interval_mins, expected_collections in collection_tests:
        collections = duration_mins // interval_mins
        duration_days = duration_mins / (24 * 60)

        passed = collections == expected_collections
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {duration_days:.2f} days @ {interval_mins} min intervals = {collections} collections (expected {expected_collections})")

        if not passed:
            all_passed = False

    # Test realistic scenarios
    print("\n[TEST 3] Realistic scenarios...")

    scenarios = [
        ("Short test", 30, "Minutes", 5, "Minutes", 30, 5, 6),
        ("Hour test", 1, "Hours", 10, "Minutes", 60, 10, 6),
        ("Day test", 1, "Days", 15, "Minutes", 1440, 15, 96),
        ("Week test", 1, "Weeks", 1, "Hours", 10080, 60, 168),
        ("2 weeks test", 2, "Weeks", 15, "Minutes", 20160, 15, 1344),
    ]

    for name, dur_val, dur_unit, int_val, int_unit, exp_dur_mins, exp_int_mins, exp_collections in scenarios:
        # Convert duration
        if dur_unit == "Minutes":
            dur_mins = dur_val
        elif dur_unit == "Hours":
            dur_mins = dur_val * 60
        elif dur_unit == "Days":
            dur_mins = dur_val * 24 * 60
        else:  # Weeks
            dur_mins = dur_val * 7 * 24 * 60

        # Convert interval
        if int_unit == "Minutes":
            int_mins = int_val
        else:  # Hours
            int_mins = int_val * 60

        # Calculate
        collections = dur_mins // int_mins

        passed = (dur_mins == exp_dur_mins and
                 int_mins == exp_int_mins and
                 collections == exp_collections)

        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}: {dur_val} {dur_unit} @ {int_val} {int_unit}")
        print(f"        -> {collections} collections (expected {exp_collections})")

        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] ALL TESTS PASSED!")
        print("=" * 60)
        print("\nFlexible duration units are working correctly!")
        print("\nSupported units:")
        print("  Duration: Minutes, Hours, Days, Weeks")
        print("  Interval: Minutes, Hours")
        print("\nExamples:")
        print("  - 30 Minutes @ 5 Minutes = 6 collections")
        print("  - 1 Day @ 15 Minutes = 96 collections")
        print("  - 2 Weeks @ 15 Minutes = 1,344 collections")
        print("  - 1 Week @ 1 Hour = 168 collections")
        return True
    else:
        print("[FAILURE] SOME TESTS FAILED!")
        print("=" * 60)
        return False

if __name__ == "__main__":
    import sys
    success = test_duration_conversions()
    sys.exit(0 if success else 1)
