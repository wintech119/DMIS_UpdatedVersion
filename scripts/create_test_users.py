#!/usr/bin/env python3
"""
Create Test Users for Dashboard Testing

This script creates dedicated test users with single specific roles
to enable proper testing of role-based dashboard routing.

Test Accounts Created (all with password 'test123'):
- test.logistics@odpem.gov.jm - LOGISTICS_MANAGER only
- test.agency@gmail.com - AGENCY_SHELTER only
- test.director@odpem.gov.jm - ODPEM_DG only
- test.inventory@odpem.gov.jm - INVENTORY_CLERK only

Usage:
    python scripts/create_test_users.py
"""

import os
import sys
import psycopg2
from werkzeug.security import generate_password_hash

def create_test_users():
    """Create test users with single roles for dashboard testing"""
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    print("=" * 70)
    print("DRIMS Test User Creation")
    print("Creating dedicated test users with single roles for dashboard testing")
    print("=" * 70)
    
    try:
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()
        
        # Password hash for 'test123'
        password_hash = generate_password_hash('test123')
        
        test_users = [
            {
                'email': 'test.logistics@odpem.gov.jm',
                'first_name': 'Test',
                'last_name': 'Logistics',
                'full_name': 'TEST LOGISTICS MANAGER',
                'role_code': 'LOGISTICS_MANAGER',
                'agency_id': None
            },
            {
                'email': 'test.agency@gmail.com',
                'first_name': 'Test',
                'last_name': 'Agency',
                'full_name': 'TEST AGENCY USER',
                'role_code': 'AGENCY_SHELTER',
                'agency_id': 'SELECT_FIRST_AGENCY'  # Will be replaced with actual agency_id
            },
            {
                'email': 'test.director@odpem.gov.jm',
                'first_name': 'Test',
                'last_name': 'Director',
                'full_name': 'TEST DIRECTOR GENERAL',
                'role_code': 'ODPEM_DG',
                'agency_id': None
            },
            {
                'email': 'test.inventory@odpem.gov.jm',
                'first_name': 'Test',
                'last_name': 'Inventory',
                'full_name': 'TEST INVENTORY CLERK',
                'role_code': 'INVENTORY_CLERK',
                'agency_id': None
            }
        ]
        
        # Get first agency for agency user
        cursor.execute('SELECT agency_id FROM agency LIMIT 1')
        agency_result = cursor.fetchone()
        first_agency_id = agency_result[0] if agency_result else None
        
        for user_data in test_users:
            email = user_data['email']
            role_code = user_data['role_code']
            
            # Set agency_id if needed
            agency_id = first_agency_id if user_data['agency_id'] == 'SELECT_FIRST_AGENCY' else user_data['agency_id']
            
            print(f"\nProcessing {email}...")
            
            # Insert or update user
            if agency_id:
                cursor.execute("""
                    INSERT INTO "user" (email, password_hash, first_name, last_name, full_name, is_active, agency_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE 
                    SET password_hash = EXCLUDED.password_hash,
                        agency_id = EXCLUDED.agency_id
                    RETURNING user_id
                """, (email, password_hash, user_data['first_name'], user_data['last_name'], 
                      user_data['full_name'], True, agency_id))
            else:
                cursor.execute("""
                    INSERT INTO "user" (email, password_hash, first_name, last_name, full_name, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE 
                    SET password_hash = EXCLUDED.password_hash
                    RETURNING user_id
                """, (email, password_hash, user_data['first_name'], user_data['last_name'], 
                      user_data['full_name'], True))
            
            result = cursor.fetchone()
            if result:
                user_id = result[0]
                print(f"  ✓ User created/updated (ID: {user_id})")
            else:
                # User already exists, get ID
                cursor.execute('SELECT user_id FROM "user" WHERE email = %s', (email,))
                user_id = cursor.fetchone()[0]
                print(f"  ℹ User already exists (ID: {user_id})")
            
            # Remove all existing roles for this user to ensure single role
            cursor.execute('DELETE FROM user_role WHERE user_id = %s', (user_id,))
            print(f"  ✓ Cleared existing roles")
            
            # Get role ID
            cursor.execute('SELECT id FROM role WHERE code = %s', (role_code,))
            role_result = cursor.fetchone()
            if not role_result:
                print(f"  ✗ ERROR: Role {role_code} not found in database")
                continue
            
            role_id = role_result[0]
            
            # Assign single role
            cursor.execute("""
                INSERT INTO user_role (user_id, role_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (user_id, role_id))
            print(f"  ✓ Assigned role: {role_code}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 70)
        print("✓ Test users created successfully!")
        print("=" * 70)
        print("\nTest Account Credentials:")
        print("  test.logistics@odpem.gov.jm  - Password: test123 - Role: LOGISTICS_MANAGER")
        print("  test.agency@gmail.com        - Password: test123 - Role: AGENCY_SHELTER")
        print("  test.director@odpem.gov.jm   - Password: test123 - Role: ODPEM_DG")
        print("  test.inventory@odpem.gov.jm  - Password: test123 - Role: INVENTORY_CLERK")
        print("\nUse these accounts to test role-based dashboard routing.")
        print("Each user has ONLY ONE role to ensure clean dashboard testing.")
        print("=" * 70)
        
        return True
        
    except psycopg2.Error as e:
        print(f"\n✗ Database error: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False

if __name__ == '__main__':
    success = create_test_users()
    sys.exit(0 if success else 1)
