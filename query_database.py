"""
Custom Database Query Tool
Run any SQL query on the digital twin database
"""
import sqlite3
import sys

def run_query(query):
    """Execute a custom SQL query"""
    conn = sqlite3.connect('data/digital_twin.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(query)
        results = cursor.fetchall()

        if results:
            # Print column headers
            print("\n" + "-"*100)
            columns = results[0].keys()
            header = " | ".join(f"{col:20}" for col in columns)
            print(header)
            print("-"*100)

            # Print rows
            for row in results:
                values = " | ".join(f"{str(row[col])[:20]:20}" for col in columns)
                print(values)

            print("-"*100)
            print(f"Total rows: {len(results)}\n")
        else:
            print("No results found.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    print("\n" + "="*100)
    print("DIGITAL TWIN DATABASE - CUSTOM QUERY TOOL")
    print("="*100)

    # Example queries
    examples = {
        "1": ("All validation metrics",
              "SELECT scenario_id, timestamp, mape, r_squared FROM validation_metrics ORDER BY timestamp DESC"),
        "2": ("Best scenarios (MAPE < 30%)",
              "SELECT scenario_id, mape, r_squared FROM validation_metrics WHERE mape < 30 ORDER BY mape"),
        "3": ("Scenarios by date",
              "SELECT scenario_id, DATE(timestamp) as date, COUNT(*) as runs FROM validation_metrics GROUP BY DATE(timestamp) ORDER BY date DESC"),
        "4": ("All unique scenarios",
              "SELECT DISTINCT scenario_id FROM validation_metrics ORDER BY scenario_id"),
        "5": ("Simulation statistics",
              "SELECT scenario_id, AVG(mape) as avg_mape, MIN(mape) as best_mape, MAX(mape) as worst_mape FROM validation_metrics GROUP BY scenario_id"),
    }

    print("\nPre-defined queries:")
    for key, (name, _) in examples.items():
        print(f"  {key}. {name}")
    print("  6. Custom query")
    print("  0. Exit")

    choice = input("\nSelect option (0-6): ").strip()

    if choice == "0":
        sys.exit(0)
    elif choice in examples:
        name, query = examples[choice]
        print(f"\nRunning: {name}")
        print(f"Query: {query}\n")
        run_query(query)
    elif choice == "6":
        print("\nEnter your SQL query (press Enter twice to execute):")
        lines = []
        while True:
            line = input()
            if line == "" and lines:
                break
            lines.append(line)
        query = " ".join(lines)
        run_query(query)
    else:
        print("Invalid choice!")
