#!/usr/bin/env python3
"""
Initialize SystemSettings table with default values
Run this once on the server to ensure proper configuration
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app import models

def init_system_settings():
    print("Initializing SystemSettings...")

    # Create engine
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Check if SystemSettings table exists and has data
        existing = db.query(models.SystemSettings).first()

        if existing:
            print(f"✅ SystemSettings already exists:")
            print(f"   - Model: {existing.llm_model_name}")
            print(f"   - Input cost: ${existing.input_cost_per_million}/M tokens")
            print(f"   - Output cost: ${existing.output_cost_per_million}/M tokens")

            # Update model if it's an old value
            if existing.llm_model_name != 'gemini-3-flash-preview':
                print(f"⚠️  Updating model '{existing.llm_model_name}' to 'gemini-3-flash-preview'")
                existing.llm_model_name = 'gemini-3-flash-preview'
                existing.input_cost_per_million = '0.50'
                existing.output_cost_per_million = '3.00'
                db.commit()
                print("✅ Model and pricing updated successfully")
        else:
            print("Creating new SystemSettings record...")
            system_settings = models.SystemSettings(
                llm_model_name='gemini-3-flash-preview',
                input_cost_per_million='0.50',
                output_cost_per_million='3.00'
            )
            db.add(system_settings)
            db.commit()
            print("✅ SystemSettings created with default values:")
            print(f"   - Model: gemini-3-flash-preview")
            print(f"   - Input cost: $0.50/M tokens")
            print(f"   - Output cost: $3.00/M tokens")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()
        print("\nDone.")

if __name__ == "__main__":
    init_system_settings()
