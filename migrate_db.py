import sqlite3
import os

db_path = 'insurance_analyzer.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Check if column exists
    cursor.execute("PRAGMA table_info(analyses)")
    columns = [info[1] for info in cursor.fetchall()]
    
    if 'policy_type' not in columns:
        print("Adding policy_type column...")
        cursor.execute("ALTER TABLE analyses ADD COLUMN policy_type TEXT DEFAULT 'rc_generale'")
        conn.commit()
        print("Column policy_type added successfully.")
    else:
        print("Column policy_type already exists.")
        
    conn.close()
except Exception as e:
    print(f"Migration failed: {e}")
    exit(1)
