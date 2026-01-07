import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./insurance_analyzer.db")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme")
    SESSION_TIMEOUT_HOURS: int = int(os.getenv("SESSION_TIMEOUT_HOURS", 8))
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", 100)) # Increased limit
    DEFAULT_USERS: str = os.getenv("DEFAULT_USERS", "admin:changeme123")
    
    # App URL for password reset links
    APP_URL: str = os.getenv("APP_URL", "http://localhost:5173")
    
    # Email settings (for password reset)
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@insurance-lab.ai")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "Insurance Lab AI")
    
    # Stripe settings
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_MONTHLY: str = os.getenv("STRIPE_PRICE_MONTHLY", "")
    STRIPE_PRICE_ANNUAL: str = os.getenv("STRIPE_PRICE_ANNUAL", "")

    class Config:
        case_sensitive = True

settings = Settings()

# 🔒 CRITICAL SECURITY: Validate SECRET_KEY
# Prevents CVE-2021-32677 style default secret vulnerability
if not settings.SECRET_KEY or settings.SECRET_KEY == "changeme":
    raise ValueError(
        "❌ SECURITY ERROR: SECRET_KEY must be set in environment variables!\n"
        "   Generate a secure key with: openssl rand -hex 32\n"
        "   Then add to .env: SECRET_KEY=<generated_key>"
    )

if len(settings.SECRET_KEY) < 32:
    raise ValueError(
        "❌ SECURITY ERROR: SECRET_KEY must be at least 32 characters long!\n"
        f"   Current length: {len(settings.SECRET_KEY)} chars\n"
        "   Generate with: openssl rand -hex 32"
    )

print(f"✅ SECRET_KEY validated (length: {len(settings.SECRET_KEY)} chars)")


