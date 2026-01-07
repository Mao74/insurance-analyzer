import sqlite3
import os

DB_FILE = 'insurance_analyzer.db'

if not os.path.exists(DB_FILE):
    print(f"Database file {DB_FILE} not found!")
    exit(1)

print(f"Connecting to {DB_FILE}...")
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# 1. analyses table
try:
    cursor.execute("ALTER TABLE analyses ADD COLUMN input_tokens INTEGER DEFAULT 0")
    print("SUCCESS: Added 'input_tokens' to 'analyses'")
except sqlite3.OperationalError as e:
    print(f"INFO: 'input_tokens' on 'analyses' - {e}")

try:
    cursor.execute("ALTER TABLE analyses ADD COLUMN output_tokens INTEGER DEFAULT 0")
    print("SUCCESS: Added 'output_tokens' to 'analyses'")
except sqlite3.OperationalError as e:
    print(f"INFO: 'output_tokens' on 'analyses' - {e}")

# 2. users table (just in case, based on previous code reading)
# models.py: user.total_input_tokens = (user.total_input_tokens or 0)
# Let's check if User needs them too
try:
    cursor.execute("ALTER TABLE users ADD COLUMN total_input_tokens INTEGER DEFAULT 0")
    print("SUCCESS: Added 'total_input_tokens' to 'users'")
except sqlite3.OperationalError as e:
    print(f"INFO: 'total_input_tokens' on 'users' - {e}")

try:
    cursor.execute("ALTER TABLE users ADD COLUMN total_output_tokens INTEGER DEFAULT 0")
    print("SUCCESS: Added 'total_output_tokens' to 'users'")
except sqlite3.OperationalError as e:
    print(f"INFO: 'total_output_tokens' on 'users' - {e}")

conn.commit()
conn.close()
print("Database schema update complete.")
