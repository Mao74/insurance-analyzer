from app.database import engine, Base
from sqlalchemy import text

def add_show_in_dashboard_column():
    with engine.connect() as conn:
        try:
            print("Attempting to add show_in_dashboard column...")
            # Try to add column directly. SQLite will error if it exists.
            # Using DEFAULT 1 for boolean True in SQLite
            conn.execute(text("ALTER TABLE analyses ADD COLUMN show_in_dashboard BOOLEAN DEFAULT 1"))
            print("Column added successfully.")
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                print("Column show_in_dashboard already exists.")
            else:
                 print(f"Note on ADD COLUMN: {e}")

        # Always ensure data integrity
        print("Verifying data integrity...")
        conn.execute(text("UPDATE analyses SET show_in_dashboard = 1 WHERE show_in_dashboard IS NULL"))
        conn.commit()
        print("Dashboard visibility restored.")

if __name__ == "__main__":
    add_show_in_dashboard_column()
