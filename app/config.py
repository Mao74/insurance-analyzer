import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./insurance_analyzer.db")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme")
    SESSION_TIMEOUT_HOURS: int = int(os.getenv("SESSION_TIMEOUT_HOURS", 8))
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", 100)) # Increased limit
    DEFAULT_USERS: str = os.getenv("DEFAULT_USERS", "admin:changeme123")
    
    # App URL for password reset links
    APP_URL: str = os.getenv("APP_URL", "http://localhost:5173")
    
    # Email settings (for password reset)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@insurance-lab.ai")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "Insurance Lab AI")

    class Config:
        case_sensitive = True

settings = Settings()

