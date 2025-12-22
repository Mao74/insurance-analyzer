"""
Migration script to add user management fields and create admin user.
SQLite-compatible version that recreates the table.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine, SessionLocal
from app import models
from app.auth import get_password_hash

def run_migration():
    print("Starting user management migration...")
    print("=" * 50)
    
    with engine.connect() as conn:
        # Check if email column exists
        try:
            result = conn.execute(text("PRAGMA table_info(users)"))
            columns = [row[1] for row in result.fetchall()]
            print(f"Current columns: {columns}")
            
            if 'email' in columns:
                print("Email column already exists. Skipping schema migration.")
            else:
                print("Adding new columns to users table...")
                
                # SQLite approach: add columns without UNIQUE first
                new_columns = [
                    ("email", "VARCHAR(255)"),
                    ("is_admin", "BOOLEAN DEFAULT 0"),
                    ("is_active", "BOOLEAN DEFAULT 1"),
                    ("access_expires_at", "DATETIME"),
                    ("last_login", "DATETIME"),
                    ("total_tokens_used", "BIGINT DEFAULT 0"),
                ]
                
                for col_name, col_type in new_columns:
                    if col_name not in columns:
                        try:
                            stmt = f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
                            conn.execute(text(stmt))
                            print(f"  Added column: {col_name}")
                        except Exception as e:
                            if "duplicate" in str(e).lower():
                                print(f"  Column {col_name} already exists")
                            else:
                                print(f"  Error adding {col_name}: {e}")
                
                conn.commit()
                
                # Copy username to email for existing users
                print("Copying username to email for existing users...")
                conn.execute(text("UPDATE users SET email = username WHERE email IS NULL"))
                conn.commit()
                
        except Exception as e:
            print(f"Error during schema migration: {e}")
            raise
    
    print("\n" + "=" * 50)
    print("Creating/updating admin user...")
    
    db = SessionLocal()
    try:
        # Check if admin already exists (use username since email might not be set)
        admin = db.query(models.User).filter(models.User.username == "admin").first()
        
        admin_email = "molinari.maurizio@gmail.com"
        admin_password = "MonteRosa74"
        
        if admin:
            # Update existing admin
            admin.email = admin_email
            admin.is_admin = True
            admin.is_active = True
            admin.access_expires_at = None  # Never expires
            admin.password_hash = get_password_hash(admin_password)
            print(f"  Updated existing admin user: {admin_email}")
        else:
            # Create new admin
            admin = models.User(
                email=admin_email,
                username="admin",
                password_hash=get_password_hash(admin_password),
                is_admin=True,
                is_active=True,
                access_expires_at=None
            )
            db.add(admin)
            print(f"  Created new admin user: {admin_email}")
        
        db.commit()
        
        # Verify
        admin = db.query(models.User).filter(models.User.email == admin_email).first()
        if admin:
            print(f"\n  Admin verified:")
            print(f"    ID: {admin.id}")
            print(f"    Email: {admin.email}")
            print(f"    is_admin: {admin.is_admin}")
            print(f"    is_active: {admin.is_active}")
        
        print("\n" + "=" * 50)
        print("Migration completed successfully!")
        
    except Exception as e:
        print(f"\nError during migration: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
