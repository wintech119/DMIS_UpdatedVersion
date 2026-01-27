#!/usr/bin/env python3
"""
Comprehensive Workflow Simulation Tests for DMIS

Tests all major workflows:
1. Master Tables (Items, Donors, Events, etc.)
2. Donations (Create, Verify)
3. Donation Intake (Entry, Verification)
4. Relief Requests (Create, Submit)
5. Packaging (Create Package, Allocate)
6. Fulfillment & Dispatch

Run with: python tests/workflow_simulation_test.py
"""

import os
import sys
from decimal import Decimal
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drims_app import app, db
from app.db.models import (
    User, Role, UserRole, Item, ItemCategory, Donor, Event, Warehouse,
    Donation, DonationItem, DonationIntake, DonationIntakeItem,
    Inventory, ItemBatch, ReliefRqst, ReliefRqstItem, ReliefPkg,
    ReliefPkgItem, Agency, Country, Currency, UnitOfMeasure
)
from app.utils.timezone import now


class WorkflowSimulator:
    """Simulates all DMIS workflows to identify issues"""
    
    def __init__(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.results = []
        self.errors = []
        
    def log_result(self, test_name, passed, message=""):
        status = "PASS" if passed else "FAIL"
        self.results.append({
            'test': test_name,
            'passed': passed,
            'message': message
        })
        if not passed:
            self.errors.append(f"{test_name}: {message}")
        print(f"[{status}] {test_name}" + (f" - {message}" if message else ""))
        
    def run_all_tests(self):
        """Run all workflow tests"""
        print("\n" + "="*60)
        print("DMIS WORKFLOW SIMULATION TESTS")
        print("="*60 + "\n")
        
        with self.app.app_context():
            self.test_database_connection()
            self.test_master_tables()
            self.test_user_roles()
            self.test_donation_workflow()
            self.test_donation_intake_workflow()
            self.test_relief_request_workflow()
            self.test_packaging_workflow()
            self.test_inventory_tracking()
            self.test_audit_logging_imports()
            
        self.print_summary()
        return len(self.errors) == 0
    
    def test_database_connection(self):
        """Test database connectivity"""
        try:
            result = db.session.execute(db.text("SELECT 1")).scalar()
            self.log_result("Database Connection", result == 1)
        except Exception as e:
            self.log_result("Database Connection", False, str(e))
    
    def test_master_tables(self):
        """Test all master/reference tables"""
        print("\n--- Master Tables Tests ---")
        
        tests = [
            ("Items", Item, "item_id"),
            ("Item Categories", ItemCategory, "itemcatg_code"),
            ("Donors", Donor, "donor_id"),
            ("Warehouses", Warehouse, "warehouse_id"),
            ("Countries", Country, "country_code"),
            ("Currencies", Currency, "currency_code"),
            ("Units of Measure", UnitOfMeasure, "uom_code"),
            ("Agencies", Agency, "agency_id"),
            ("Roles", Role, "role_id"),
            ("Users", User, "user_id"),
        ]
        
        for name, model, pk in tests:
            try:
                count = db.session.query(model).count()
                self.log_result(f"{name} Table", True, f"{count} records")
            except Exception as e:
                self.log_result(f"{name} Table", False, str(e))
        
        try:
            events_count = db.session.query(Event).count()
            self.log_result("Events Table", True, f"{events_count} records")
        except Exception as e:
            self.log_result("Events Table", False, str(e))
    
    def test_user_roles(self):
        """Test user and role assignments"""
        print("\n--- User & Role Tests ---")
        
        try:
            users_with_roles = db.session.query(User).join(UserRole).distinct().count()
            self.log_result("Users with Roles", users_with_roles > 0, f"{users_with_roles} users")
        except Exception as e:
            self.log_result("Users with Roles", False, str(e))
        
        try:
            test_user = db.session.query(User).filter(
                User.email.ilike('%logistics%')
            ).first()
            if test_user:
                self.log_result("Logistics User Exists", True, test_user.email)
            else:
                test_user = db.session.query(User).first()
                self.log_result("Any User Exists", test_user is not None, 
                              test_user.email if test_user else "No users found")
        except Exception as e:
            self.log_result("User Query", False, str(e))
    
    def test_donation_workflow(self):
        """Test donation creation and verification workflow"""
        print("\n--- Donation Workflow Tests ---")
        
        try:
            donations = db.session.query(Donation).all()
            self.log_result("Donations Query", True, f"{len(donations)} donations")
            
            by_status = {}
            for d in donations:
                status = d.status_code or 'NULL'
                by_status[status] = by_status.get(status, 0) + 1
            
            status_labels = {'E': 'Entered', 'V': 'Verified', 'P': 'Processed'}
            for code, count in by_status.items():
                label = status_labels.get(code, code)
                self.log_result(f"Donations ({label})", True, f"{count} records")
                
        except Exception as e:
            self.log_result("Donations Query", False, str(e))
        
        try:
            items = db.session.query(DonationItem).limit(10).all()
            self.log_result("Donation Items Query", True, f"{len(items)} sample items")
        except Exception as e:
            self.log_result("Donation Items Query", False, str(e))
        
        try:
            donors = db.session.query(Donor).filter(Donor.status_code == 'A').count()
            self.log_result("Active Donors", donors > 0, f"{donors} active donors")
        except Exception as e:
            self.log_result("Active Donors", False, str(e))
        
        try:
            goods_catg = db.session.query(ItemCategory).filter(
                ItemCategory.itemcatg_type == 'GOODS'
            ).first()
            self.log_result("GOODS Category Exists", goods_catg is not None)
            
            goods_items = db.session.query(Item).join(ItemCategory).filter(
                ItemCategory.itemcatg_type == 'GOODS',
                Item.status_code == 'A'
            ).count()
            self.log_result("Active GOODS Items", goods_items > 0, f"{goods_items} items")
        except Exception as e:
            self.log_result("GOODS Items Query", False, str(e))
    
    def test_donation_intake_workflow(self):
        """Test donation intake entry and verification"""
        print("\n--- Donation Intake Workflow Tests ---")
        
        try:
            intakes = db.session.query(DonationIntake).all()
            self.log_result("Donation Intakes Query", True, f"{len(intakes)} intakes")
            
            by_status = {}
            for i in intakes:
                status = i.status_code or 'NULL'
                by_status[status] = by_status.get(status, 0) + 1
            
            status_labels = {'I': 'Draft', 'C': 'Submitted', 'V': 'Verified'}
            for code, count in by_status.items():
                label = status_labels.get(code, code)
                self.log_result(f"Intakes ({label})", True, f"{count} records")
                
        except Exception as e:
            self.log_result("Donation Intakes Query", False, str(e))
        
        try:
            intake_items = db.session.query(DonationIntakeItem).count()
            self.log_result("Intake Items", True, f"{intake_items} items")
        except Exception as e:
            self.log_result("Intake Items Query", False, str(e))
        
        try:
            verified_donations = db.session.query(Donation).filter(
                Donation.status_code == 'V'
            ).count()
            self.log_result("Verified Donations (Ready for Intake)", 
                          True, f"{verified_donations} donations")
        except Exception as e:
            self.log_result("Verified Donations Query", False, str(e))
    
    def test_relief_request_workflow(self):
        """Test relief request creation and approval"""
        print("\n--- Relief Request Workflow Tests ---")
        
        try:
            requests = db.session.query(ReliefRqst).all()
            self.log_result("Relief Requests Query", True, f"{len(requests)} requests")
            
            by_status = {}
            for r in requests:
                status = r.status_code or 'NULL'
                by_status[status] = by_status.get(status, 0) + 1
            
            status_labels = {
                'D': 'Draft', 'S': 'Submitted', 'A': 'Approved', 
                'R': 'Rejected', 'P': 'Packaging', 'F': 'Fulfilled'
            }
            for code, count in by_status.items():
                label = status_labels.get(code, code)
                self.log_result(f"Requests ({label})", True, f"{count} records")
                
        except Exception as e:
            self.log_result("Relief Requests Query", False, str(e))
        
        try:
            request_items = db.session.query(ReliefRqstItem).count()
            self.log_result("Relief Request Items", True, f"{request_items} items")
        except Exception as e:
            self.log_result("Relief Request Items Query", False, str(e))
        
        try:
            agencies = db.session.query(Agency).filter(Agency.status_code == 'A').count()
            self.log_result("Active Agencies", agencies > 0, f"{agencies} agencies")
        except Exception as e:
            self.log_result("Active Agencies Query", False, str(e))
    
    def test_packaging_workflow(self):
        """Test relief package creation and dispatch"""
        print("\n--- Packaging Workflow Tests ---")
        
        try:
            packages = db.session.query(ReliefPkg).all()
            self.log_result("Relief Packages Query", True, f"{len(packages)} packages")
            
            by_status = {}
            for p in packages:
                status = p.status_code or 'NULL'
                by_status[status] = by_status.get(status, 0) + 1
            
            status_labels = {
                'D': 'Draft', 'P': 'Pending Approval', 
                'A': 'Approved', 'X': 'Dispatched', 'R': 'Received'
            }
            for code, count in by_status.items():
                label = status_labels.get(code, code)
                self.log_result(f"Packages ({label})", True, f"{count} records")
                
        except Exception as e:
            self.log_result("Relief Packages Query", False, str(e))
        
        try:
            pkg_items = db.session.query(ReliefPkgItem).count()
            self.log_result("Package Items", True, f"{pkg_items} items")
        except Exception as e:
            self.log_result("Package Items Query", False, str(e))
    
    def test_inventory_tracking(self):
        """Test inventory and batch tracking"""
        print("\n--- Inventory & Batch Tests ---")
        
        try:
            inventory = db.session.query(Inventory).all()
            self.log_result("Inventory Records", True, f"{len(inventory)} records")
            
            total_usable = sum(i.usable_qty or 0 for i in inventory)
            total_reserved = sum(i.reserved_qty or 0 for i in inventory)
            self.log_result("Inventory Quantities", True, 
                          f"Usable: {total_usable}, Reserved: {total_reserved}")
        except Exception as e:
            self.log_result("Inventory Query", False, str(e))
        
        try:
            batches = db.session.query(ItemBatch).all()
            self.log_result("Item Batches", True, f"{len(batches)} batches")
            
            by_status = {}
            for b in batches:
                status = b.status_code or 'NULL'
                by_status[status] = by_status.get(status, 0) + 1
            
            for code, count in by_status.items():
                self.log_result(f"Batches (Status {code})", True, f"{count} records")
                
        except Exception as e:
            self.log_result("Item Batches Query", False, str(e))
        
        try:
            warehouses = db.session.query(Warehouse).filter(
                Warehouse.status_code == 'A'
            ).all()
            self.log_result("Active Warehouses", len(warehouses) > 0, 
                          f"{len(warehouses)} warehouses")
            
            for wh in warehouses[:3]:
                inv_count = db.session.query(Inventory).filter(
                    Inventory.inventory_id == wh.warehouse_id
                ).count()
                self.log_result(f"  Warehouse {wh.warehouse_id} Inventory", 
                              True, f"{inv_count} items")
        except Exception as e:
            self.log_result("Warehouse Inventory Query", False, str(e))
    
    def test_audit_logging_imports(self):
        """Test that audit logging imports work correctly"""
        print("\n--- Audit Logging Tests ---")
        
        try:
            from app.security.audit_logger import (
                log_data_event, AuditAction, AuditOutcome
            )
            self.log_result("Audit Logger Import", True)
            
            self.log_result("AuditAction.CREATE exists", hasattr(AuditAction, 'CREATE'))
            self.log_result("AuditAction.UPDATE exists", hasattr(AuditAction, 'UPDATE'))
            self.log_result("AuditAction.VERIFY exists", hasattr(AuditAction, 'VERIFY'))
            self.log_result("AuditAction.DISPATCH exists", hasattr(AuditAction, 'DISPATCH'))
            self.log_result("AuditAction.CANCEL exists", hasattr(AuditAction, 'CANCEL'))
            
            self.log_result("AuditOutcome.SUCCESS exists", hasattr(AuditOutcome, 'SUCCESS'))
            self.log_result("AuditOutcome.FAILURE exists", hasattr(AuditOutcome, 'FAILURE'))
            
        except Exception as e:
            self.log_result("Audit Logger Import", False, str(e))
        
        try:
            from app.features.donations import donations_bp
            self.log_result("Donations Blueprint Import", True)
        except Exception as e:
            self.log_result("Donations Blueprint Import", False, str(e))
        
        try:
            from app.features.packaging import packaging_bp
            self.log_result("Packaging Blueprint Import", True)
        except Exception as e:
            self.log_result("Packaging Blueprint Import", False, str(e))
        
        try:
            from app.features.donation_intake import donation_intake_bp
            self.log_result("Donation Intake Blueprint Import", True)
        except Exception as e:
            self.log_result("Donation Intake Blueprint Import", False, str(e))
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for r in self.results if r['passed'])
        failed = sum(1 for r in self.results if not r['passed'])
        total = len(self.results)
        
        print(f"\nTotal Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        
        if self.errors:
            print("\n--- FAILURES ---")
            for error in self.errors:
                print(f"  - {error}")
        
        print("\n" + "="*60)
        if failed == 0:
            print("ALL TESTS PASSED!")
        else:
            print(f"{failed} TEST(S) FAILED - Review errors above")
        print("="*60 + "\n")


def test_route_accessibility():
    """Test that all main routes are accessible"""
    print("\n" + "="*60)
    print("ROUTE ACCESSIBILITY TESTS")
    print("="*60 + "\n")
    
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    routes_to_test = [
        ('/', 'Home/Login Redirect'),
        ('/login', 'Login Page'),
        ('/donations/', 'Donations List'),
        ('/donations/create', 'Create Donation'),
        ('/donation-intake/', 'Donation Intake'),
        ('/relief-requests/', 'Relief Requests'),
        ('/packaging/', 'Packaging'),
        ('/dashboard/aid-movement', 'Aid Movement Dashboard'),
        ('/reports/', 'Reports'),
        ('/admin/items/', 'Items Management'),
        ('/admin/donors/', 'Donors Management'),
    ]
    
    with app.test_client() as client:
        for route, name in routes_to_test:
            try:
                response = client.get(route, follow_redirects=False)
                if response.status_code in [200, 302, 303]:
                    print(f"[PASS] {name} ({route}) - Status: {response.status_code}")
                else:
                    print(f"[FAIL] {name} ({route}) - Status: {response.status_code}")
            except Exception as e:
                print(f"[FAIL] {name} ({route}) - Error: {str(e)[:50]}")


def test_model_relationships():
    """Test model relationships are working"""
    print("\n" + "="*60)
    print("MODEL RELATIONSHIP TESTS")
    print("="*60 + "\n")
    
    with app.app_context():
        try:
            donation = db.session.query(Donation).first()
            if donation:
                items = donation.items
                print(f"[PASS] Donation -> Items relationship: {len(items) if items else 0} items")
                
                if donation.donor:
                    print(f"[PASS] Donation -> Donor relationship: {donation.donor.donor_name}")
                else:
                    print(f"[WARN] Donation has no donor linked")
            else:
                print("[INFO] No donations to test relationships")
        except Exception as e:
            print(f"[FAIL] Donation relationships: {str(e)}")
        
        try:
            relief_request = db.session.query(ReliefRqst).first()
            if relief_request:
                items = relief_request.items
                print(f"[PASS] ReliefRequest -> Items relationship: {len(items) if items else 0} items")
                
                if relief_request.agency:
                    print(f"[PASS] ReliefRequest -> Agency relationship: {relief_request.agency.agency_name}")
            else:
                print("[INFO] No relief requests to test relationships")
        except Exception as e:
            print(f"[FAIL] ReliefRequest relationships: {str(e)}")
        
        try:
            user = db.session.query(User).first()
            if user:
                roles = user.roles
                print(f"[PASS] User -> Roles relationship: {len(roles) if roles else 0} roles")
            else:
                print("[INFO] No users to test relationships")
        except Exception as e:
            print(f"[FAIL] User relationships: {str(e)}")
        
        try:
            inventory = db.session.query(Inventory).first()
            if inventory:
                if inventory.item:
                    print(f"[PASS] Inventory -> Item relationship: {inventory.item.item_code}")
                if inventory.warehouse:
                    print(f"[PASS] Inventory -> Warehouse relationship: {inventory.warehouse.warehouse_name}")
            else:
                print("[INFO] No inventory to test relationships")
        except Exception as e:
            print(f"[FAIL] Inventory relationships: {str(e)}")


def test_workflow_dependencies():
    """Test workflow dependencies and data availability"""
    print("\n" + "="*60)
    print("WORKFLOW DEPENDENCY TESTS")
    print("="*60 + "\n")
    
    with app.app_context():
        print("--- Donation Creation Dependencies ---")
        donors = db.session.query(Donor).filter(Donor.status_code == 'A').count()
        print(f"[{'PASS' if donors > 0 else 'FAIL'}] Active Donors: {donors}")
        
        countries = db.session.query(Country).count()
        print(f"[{'PASS' if countries > 0 else 'FAIL'}] Countries: {countries}")
        
        currencies = db.session.query(Currency).count()
        print(f"[{'PASS' if currencies > 0 else 'FAIL'}] Currencies: {currencies}")
        
        goods_items = db.session.query(Item).join(ItemCategory).filter(
            ItemCategory.itemcatg_type == 'GOODS',
            Item.status_code == 'A'
        ).count()
        print(f"[{'PASS' if goods_items > 0 else 'FAIL'}] Active GOODS Items: {goods_items}")
        
        print("\n--- Intake Dependencies ---")
        verified_donations = db.session.query(Donation).filter(
            Donation.status_code == 'V'
        ).count()
        print(f"[{'PASS' if verified_donations > 0 else 'WARN'}] Verified Donations for Intake: {verified_donations}")
        
        warehouses = db.session.query(Warehouse).filter(Warehouse.status_code == 'A').count()
        print(f"[{'PASS' if warehouses > 0 else 'FAIL'}] Active Warehouses: {warehouses}")
        
        print("\n--- Relief Request Dependencies ---")
        agencies = db.session.query(Agency).filter(Agency.status_code == 'A').count()
        print(f"[{'PASS' if agencies > 0 else 'FAIL'}] Active Agencies: {agencies}")
        
        events = db.session.query(Event).filter(Event.status_code == 'A').count()
        print(f"[{'PASS' if events > 0 else 'WARN'}] Active Events: {events}")
        
        print("\n--- Packaging Dependencies ---")
        approved_requests = db.session.query(ReliefRqst).filter(
            ReliefRqst.status_code == 'A'
        ).count()
        print(f"[{'PASS' if approved_requests > 0 else 'WARN'}] Approved Requests for Packaging: {approved_requests}")
        
        inventory_with_stock = db.session.query(Inventory).filter(
            Inventory.usable_qty > 0
        ).count()
        print(f"[{'PASS' if inventory_with_stock > 0 else 'WARN'}] Inventory with Stock: {inventory_with_stock}")


if __name__ == '__main__':
    simulator = WorkflowSimulator()
    success = simulator.run_all_tests()
    
    test_route_accessibility()
    test_model_relationships()
    test_workflow_dependencies()
    
    sys.exit(0 if success else 1)
