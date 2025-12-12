
import sqlite3
import os

db_path = 'insurance_analyzer.db'
if not os.path.exists(db_path):
    print(f"Database {db_path} not found.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columns = [
    ('title', 'TEXT'),
    ('is_saved', 'BOOLEAN DEFAULT 0'),
    ('last_updated', 'TIMESTAMP')
]

for col_name, col_type in columns:
    try:
        cursor.execute(f"ALTER TABLE analyses ADD COLUMN {col_name} {col_type}")
        print(f"Added column {col_name}")
    except sqlite3.OperationalError as e:
        print(f"Column {col_name} likely exists or error: {e}")

conn.commit()
conn.close()
