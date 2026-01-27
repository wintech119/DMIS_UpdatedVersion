#!/usr/bin/env python3
"""
DRIMS Demo Data Seeding Script
Populates database with minimal working dataset for testing
"""
import os
import sys
from datetime import datetime, date
import psycopg2
from werkzeug.security import generate_password_hash

def seed_demo_data():
    """Seed database with demo data"""
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    print("=" * 70)
    print("DRIMS Demo Data Seeding")
    print("=" * 70)
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        now = datetime.now()
        today = date.today()
        
        print("Seeding demo data...")
        
        print("  - Creating admin user...")
        password_hash = generate_password_hash('admin123')
        cursor.execute("""
            INSERT INTO "user" (email, password_hash, full_name, first_name, last_name, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            RETURNING id
        """, ('admin@odpem.gov.jm', password_hash, 'SYSTEM ADMINISTRATOR', 'SYSTEM', 'ADMINISTRATOR', True, now))
        
        result = cursor.fetchone()
        if result:
            admin_user_id = result[0]
            print(f"    ✓ Admin user created (ID: {admin_user_id})")
        else:
            cursor.execute('SELECT id FROM "user" WHERE email = %s', ('admin@odpem.gov.jm',))
            admin_user_id = cursor.fetchone()[0]
            print(f"    ℹ Admin user already exists (ID: {admin_user_id})")
        
        print("  - Creating System Administrator role...")
        cursor.execute("""
            INSERT INTO role (code, name, description, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO NOTHING
            RETURNING id
        """, ('SYS_ADMIN', 'System Administrator', 'Full system access', now))
        
        result = cursor.fetchone()
        if result:
            admin_role_id = result[0]
        else:
            cursor.execute('SELECT id FROM role WHERE code = %s', ('SYS_ADMIN',))
            admin_role_id = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO user_role (user_id, role_id, assigned_at)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (admin_user_id, admin_role_id, now))
        
        print("  - Creating test event...")
        cursor.execute("""
            INSERT INTO event (event_type, start_date, event_name, event_desc, impact_desc,
                             status_code, create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, ('STORM', today, 'TROPICAL STORM BETA', 'Test storm event', 
              'Moderate flooding in western parishes', 'A', 'admin', now, 'admin', now, 1))
        
        print("  - Creating test warehouse...")
        cursor.execute("""
            INSERT INTO warehouse (warehouse_name, warehouse_type, address1_text, parish_code,
                                 contact_name, phone_no, custodian_id, status_code,
                                 create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
            SELECT %s, %s, %s, %s, %s, %s, c.custodian_id, %s, %s, %s, %s, %s, %s
            FROM custodian c LIMIT 1
            ON CONFLICT DO NOTHING
        """, ('KINGSTON CENTRAL DEPOT', 'MAIN', '123 Main Street, Kingston', '01',
              'JOHN BROWN', '876-555-1234', 'A', 'admin', now, 'admin', now, 1))
        
        print("  - Creating test agency...")
        cursor.execute("""
            INSERT INTO agency (agency_name, address1_text, parish_code, contact_name, phone_no,
                              create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, ('PORTMORE COMMUNITY CENTER', '45 Community Lane, Portmore', '12',
              'MARY JOHNSON', '876-555-5678', 'admin', now, 'admin', now, 1))
        
        print("  - Creating test item...")
        cursor.execute("""
            INSERT INTO item (item_name, sku_code, category_code, item_desc, reorder_qty,
                            default_uom_code, expiration_apply_flag, status_code,
                            create_by_id, create_dtime, update_by_id, update_dtime, version_nbr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, ('BOTTLED WATER 500ML', 'WATER-500ML', 'WATER', 'Drinking water 500ml bottles',
              1000.00, 'UNIT', False, 'A', 'admin', now, 'admin', now, 1))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 70)
        print("✓ Demo data seeding completed successfully!")
        print("=" * 70)
        print("\nTest Credentials:")
        print("  Email: admin@odpem.gov.jm")
        print("  Password: admin123")
        print("=" * 70)
        
        return True
        
    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        conn.rollback()
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False

if __name__ == '__main__':
    success = seed_demo_data()
    sys.exit(0 if success else 1)
