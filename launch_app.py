"""
Launcher script for Digital Twin Traffic Simulator
Includes diagnostics and helpful error messages
"""
import sys
import os

# Fix Unicode output on Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    if sys.stderr:
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def check_dependencies():
    """Check if all required packages are installed"""
    print("🔍 Checking dependencies...")

    missing = []
    required = {
        'PyQt6': 'PyQt6',
        'folium': 'folium',
        'geopy': 'geopy',
        'osmnx': 'osmnx'
    }

    for package_name, import_name in required.items():
        try:
            __import__(import_name)
            print(f"  ✓ {package_name}")
        except ImportError:
            print(f"  ✗ {package_name} - NOT INSTALLED")
            missing.append(package_name)

    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print(f"\n📦 Install them with:")
        print(f"   pip install {' '.join(missing)}")
        return False

    print("✅ All dependencies installed!\n")
    return True

def check_environment():
    """Check environment"""
    print("🔍 Checking environment...")
    print(f"  Python version: {sys.version.split()[0]}")
    print(f"  Working directory: {os.getcwd()}")
    print(f"  Platform: {sys.platform}")
    print()

def main():
    """Main launcher"""
    print("=" * 60)
    print("🚦 Digital Twin Traffic Simulator")
    print("=" * 60)
    print()

    check_environment()

    if not check_dependencies():
        print("\n⚠️  Cannot start application - missing dependencies")
        input("Press Enter to exit...")
        return 1

    print("🚀 Launching application...")
    print()
    print("📋 USAGE INSTRUCTIONS:")
    print("  1. Search for a location (e.g., 'Berlin, Germany')")
    print("  2. Use the rectangle tool (□) on the map to select an area")
    print("  3. Configure simulation parameters")
    print("  4. Click 'Run Simulation'")
    print()
    print("💡 See USAGE_GUIDE.md for detailed instructions")
    print("=" * 60)
    print()

    try:
        from app_desktop import run_app
        run_app()
    except Exception as e:
        print(f"\n❌ Error launching application:")
        print(f"   {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
