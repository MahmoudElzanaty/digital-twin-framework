"""
Quick test to verify database.py works
"""
from modules.database import get_db

print("Testing database module...")

# This will create the database and tables
db = get_db()

print("✅ Database created successfully!")
print(f"   Location: {db.db_path}")

# Show summary
stats = db.get_summary_stats()
print("\nDatabase stats:")
print(f"  Active routes: {stats['active_routes']}")
print(f"  Data points: {stats['real_data_points']}")
print(f"  Simulations: {stats['simulation_results']}")

print("\n✅ Test complete! Database is working.")