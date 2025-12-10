from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import settings
from .auth import get_password_hash

# Create engine
# check_same_thread=False is needed only for SQLite
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_engine(
    settings.DATABASE_URL, connect_args=connect_args
)

# Enable Write-Ahead Logging for SQLite
if "sqlite" in settings.DATABASE_URL:
    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL;"))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # Import models to ensure they are registered
    from . import models
    Base.metadata.create_all(bind=engine)
    
    # Create default users if they don't exist
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            print("Creating default users...")
            default_users = settings.DEFAULT_USERS.split(',')
            for user_pair in default_users:
                if ':' in user_pair:
                    username, password = user_pair.split(':')
                    # Hash password here
                    pwd_hash = get_password_hash(password)
                    user = models.User(username=username, password_hash=pwd_hash)
                    db.add(user)
            db.commit()
            print("Default users created.")
    except Exception as e:
        print(f"Error initializing DB: {e}")
    finally:
        db.close()
