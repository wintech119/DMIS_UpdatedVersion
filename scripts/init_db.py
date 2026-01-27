#!/usr/bin/env python3
"""
DRIMS Database Initialization Script
Executes DRIMS_Complete_Schema.sql against PostgreSQL database
"""
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys

def init_database():
    """Initialize database by executing the complete schema SQL file"""
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    schema_file = os.path.join(os.path.dirname(__file__), '..', 'attached_assets', 'DRIMS_Complete_Schema_1762917808553.sql')
    
    if not os.path.exists(schema_file):
        print(f"ERROR: Schema file not found at {schema_file}")
        sys.exit(1)
    
    print("=" * 70)
    print("DRIMS Database Initialization")
    print("=" * 70)
    print(f"Database: {database_url.split('@')[-1] if '@' in database_url else 'configured'}")
    print(f"Schema file: {schema_file}")
    print("-" * 70)
    
    try:
        conn = psycopg2.connect(database_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        print("Reading schema file...")
        with open(schema_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        print("Executing schema (this may take a moment)...")
        cursor.execute(sql_content)
        
        print("\nVerifying tables...")
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        
        tables = cursor.fetchall()
        print(f"\n✓ Successfully created {len(tables)} tables:")
        
        for table in tables:
            print(f"  - {table[0]}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 70)
        print("✓ Database initialization completed successfully!")
        print("=" * 70)
        
        return True
        
    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        if 'already exists' in str(e):
            print("\nNote: Some objects already exist. This is safe if re-running the script.")
            return True
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False

if __name__ == '__main__':
    success = init_database()
    sys.exit(0 if success else 1)
