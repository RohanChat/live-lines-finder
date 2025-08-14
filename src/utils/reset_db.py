#!/usr/bin/env python3
"""
Database reset script to update schema from INTEGER primary keys to UUID
and VARCHAR fields to TEXT fields.
"""
import sys
import os

# Add src directory to path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.database import engine, Base
from sqlalchemy import text
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_database():
    """Drop and recreate all tables with new schema"""
    logger.info("🗑️  Dropping existing tables...")
    
    try:
        # Drop the existing table manually
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
            conn.commit()
            logger.info("✅ Dropped 'users' table")
        
        logger.info("🔨 Creating new tables with UUID primary keys and TEXT fields...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database reset complete!")
        
        # Show the new table structure
        logger.info("📋 New table structure:")
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'users' 
                ORDER BY ordinal_position
            """))
            
            for row in result:
                logger.info(f"  {row[0]}: {row[1]} (nullable: {row[2]}, default: {row[3]})")
                
    except Exception as e:
        logger.error(f"❌ Error resetting database: {e}")
        raise

if __name__ == "__main__":
    print("🚀 Starting database reset...")
    print("⚠️  WARNING: This will delete all existing user data!")
    
    confirm = input("Continue? (y/N): ").lower().strip()
    if confirm in ['y', 'yes']:
        reset_database()
        print("✅ Database reset completed successfully!")
    else:
        print("❌ Database reset cancelled.")
