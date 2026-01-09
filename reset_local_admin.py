from app.database import SessionLocal
from app.models import User
from app.auth import get_password_hash
import sys

def reset_admin_password():
    db = SessionLocal()
    try:
        print("🔍 Searching for Admin user...")
        user = db.query(User).filter(User.email == "admin@insurance-lab.ai").first()
        
        if not user:
            print("⚠️ Admin user not found. Creating one...")
            user = User(
                email="admin@insurance-lab.ai",
                is_admin=True,
                is_active=True,
                password_hash="" # Will be set below
            )
            db.add(user)
        else:
            print("✅ Admin user found.")
        
        new_password = "admin123"
        hashed_pw = get_password_hash(new_password)
        
        user.password_hash = hashed_pw
        db.commit()
        
        print(f"\n✅ PASSWORD RESET SUCCESSFUL")
        print(f"📧 Email: admin@insurance-lab.ai")
        print(f"🔑 Password: {new_password}")
        
    except Exception as e:
        print(f"\n❌ Error resetting password: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    reset_admin_password()
